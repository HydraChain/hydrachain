import time
from ethereum.config import Env
from ethereum.utils import sha3
import rlp
from rlp.utils import encode_hex
from ethereum import processblock
from ethereum.slogging import get_logger
from ethereum.processblock import validate_transaction
from ethereum.exceptions import InvalidTransaction
from ethereum.chain import Chain
from ethereum.refcount_db import RefcountDB
from ethereum.blocks import Block, VerificationFailed
from ethereum.transactions import Transaction
from devp2p.service import WiredService
from devp2p.protocol import BaseProtocol
from ethereum import config as ethereum_config
import gevent
import gevent.lock
import statistics
from collections import deque
from gevent.queue import Queue
from ethereum.utils import DEBUG
from pyethapp.eth_service import ChainService as eth_ChainService
from .consensus.protocol import HDCProtocol, HDCProtocolError
from .consensus.base import Signed, VotingInstruction, BlockProposal, Proposal, TransientBlock
from .consensus.base import Vote, VoteBlock, VoteNil, HDCBlockHeader, LockSet
from .consensus.utils import phx
from .consensus.manager import ConsensusManager, ConsensusContract

import json

log = get_logger('hdc.chainservice')


# patch to get context switches between tx replay
processblock_apply_transaction = processblock.apply_transaction


def apply_transaction(block, tx):
    # import traceback
    # print traceback.print_stack()
    log.debug('apply_transaction ctx switch', tx=tx.hash.encode('hex')[:8])
    gevent.sleep(0.001)
    return processblock_apply_transaction(block, tx)
processblock.apply_transaction = apply_transaction


rlp_hash_hex = lambda data: encode_hex(sha3(rlp.encode(data)))


class DuplicatesFilter(object):

    def __init__(self, max_items=128):
        self.max_items = max_items
        self.filter = list()

    def update(self, data):
        "returns True if unknown"
        if data not in self.filter:
            self.filter.append(data)
            if len(self.filter) > self.max_items:
                self.filter.pop(0)
            return True
        else:
            self.filter.append(self.filter.pop(0))
            return False

    def __contains__(self, v):
        return v in self.filter


def update_watcher(chainservice):
    timeout = 180
    d = dict(head=chainservice.chain.head)

    def up(b):
        log.debug('watcher head updated')
        d['head'] = b
    chainservice.on_new_head_cbs.append(lambda b: up(b))

    while True:
        last = d['head']
        gevent.sleep(timeout)
        assert last != d['head'], 'no updates for %d secs' % timeout


class ChainService(eth_ChainService):

    """
    Manages the chain and requests to it.
    """
    # required by BaseService
    name = 'chain'
    default_config = dict(eth=dict(network_id=0,
                                   genesis='',
                                   pruning=-1,
                                   block=ethereum_config.default_config),
                          hdc=dict(validators=[]),

                          )

    # required by WiredService
    wire_protocol = HDCProtocol  # create for each peer

    # initialized after configure:
    chain = None
    genesis = None
    synchronizer = None
    config = None
    block_queue_size = 1024
    transaction_queue_size = 1024
    processed_gas = 0
    processed_elapsed = 0

    def __init__(self, app):
        self.config = app.config
        sce = self.config['eth']
        if int(sce['pruning']) >= 0:
            self.db = RefcountDB(app.services.db)
            if "I am not pruning" in self.db.db:
                raise Exception("This database was initialized as non-pruning."
                                " Kinda hard to start pruning now.")
            self.db.ttl = int(sce['pruning'])
            self.db.db.put("I am pruning", "1")
        else:
            self.db = app.services.db
            if "I am pruning" in self.db:
                raise Exception("This database was initialized as pruning."
                                " Kinda hard to stop pruning now.")
            self.db.put("I am not pruning", "1")

        if 'network_id' in self.db:
            db_network_id = self.db.get('network_id')
            if db_network_id != str(sce['network_id']):
                raise Exception("This database was initialized with network_id {} "
                                "and can not be used when connecting to network_id {}".format(
                                    db_network_id, sce['network_id'])
                                )

        else:
            self.db.put('network_id', str(sce['network_id']))
            self.db.commit()

        assert self.db is not None

        WiredService.__init__(self, app)
        log.info('initializing chain')
        coinbase = app.services.accounts.coinbase
        env = Env(self.db, sce['block'])
        self.chain = Chain(env, new_head_cb=self._on_new_head, coinbase=coinbase)

        log.info('chain at', number=self.chain.head.number)
        if 'genesis_hash' in sce:
            assert sce['genesis_hash'] == self.chain.genesis.hex_hash()

#        self.synchronizer = Synchronizer(self, force_sync=None)

#        self.block_queue = Queue(maxsize=self.block_queue_size)
        self.transaction_queue = Queue(maxsize=self.transaction_queue_size)
        self.add_blocks_lock = False
        self.add_transaction_lock = gevent.lock.Semaphore()
        self.broadcast_filter = DuplicatesFilter()
        self.on_new_head_cbs = []
        self.on_new_head_candidate_cbs = []
        self.newblock_processing_times = deque(maxlen=1000)

        # Consensus
        self.consensus_contract = ConsensusContract(validators=self.config['hdc']['validators'])
        self.consensus_manager = ConsensusManager(self, self.consensus_contract,
                                                  self.consensus_privkey)

        # self.consensus_manager.process()

    # interface accessed by ConensusManager

    def log(self, msg, *args, **kargs):
        log.debug(msg, *args, **kargs)

    @property
    def consensus_privkey(self):
        return self.app.services.accounts[0].privkey

    def sign(self, obj):
        assert isinstance(obj, Signed)
        obj.sign(self.consensus_privkey)

    @property
    def now(self):
        return time.time()

    def setup_alarm(self, delay, cb, *args):
        log.DEV('setting up alarm')

        def _trigger():
            gevent.sleep(delay)
            log.DEV('alarm triggered')
            cb(*args)
        gevent.spawn(_trigger)

    def commit_block(self, blk):
        assert isinstance(blk.header, HDCBlockHeader)
        self.add_transaction_lock.acquire()
        success = self.chain.add_block(blk,  forward_pending_transactions=True)
        self.add_transaction_lock.release()
        return success

    def link_block(self, t_block):
        assert isinstance(t_block.header, HDCBlockHeader)
        self.add_transaction_lock.acquire()
        block = self._link_block(t_block)
        if not block:
            return
        assert block.get_parent() == self.chain.head, (block.get_parent(), self.chain.head)
        assert block.header.coinbase == t_block.header.coinbase
        self.add_transaction_lock.release()
        return block

    def _link_block(self, t_block):
        assert isinstance(t_block.header, HDCBlockHeader)
        if t_block.header.hash in self.chain:
            log.warn('known block', block=t_block)
            return
        if t_block.header.prevhash not in self.chain:
            log.warn('missing parent', block=t_block, head=self.chain.head,
                     prevhash=phx(t_block.header.prevhash))
            return
        if isinstance(t_block, Block):
            return True  # already deserialized
        try:  # deserialize
            st = time.time()
            block = t_block.to_block(env=self.chain.env)
            elapsed = time.time() - st
            log.debug('deserialized', elapsed='%.4fs' % elapsed, ts=time.time(),
                      gas_used=block.gas_used, gpsec=self.gpsec(block.gas_used, elapsed))
            assert block.header.check_pow()
        except processblock.InvalidTransaction as e:
            log.warn('invalid transaction', block=t_block, error=e, FIXME='ban node')
            return
        except VerificationFailed as e:
            log.warn('verification failed', error=e, FIXME='ban node')
            return
        return block

    ###############################################################################

    # @property
    # def is_syncing(self):
    #     return self.synchronizer.synctask is not None

    # @property
    # def is_mining(self):
    #     if 'pow' in self.app.services:
    #         return self.app.services.pow.active
    #     return False

    # wire protocol receivers ###########

    # transactions

    def on_receive_transactions(self, proto, transactions):
        "receives rlp.decoded serialized"
        log.debug('----------------------------------')
        log.debug('remote_transactions_received', count=len(transactions), remote_id=proto)
        for tx in transactions:
            self.add_transaction(tx, origin=proto)

    # blocks / proposals ################

    def receive_message(self, peer, m):
        self.log('receive', msg=m)
        self.messages_received.append(m)
        assert isinstance(m, Message)
        if isinstance(m, Vote):
            self.add_vote(m)
        elif isinstance(m, Proposal):
            self.add_proposal(m)
        elif isinstance(m, BlockRequest):
            self.receive_block_request(peer, m)
        elif isinstance(m, BlockReply):
            self.add_block(m.block)
        else:
            raise Exception('unhandled message')
        self.process()

    def on_receive_getblocks(self, proto, blockrequests):
        log.debug('----------------------------------')
        log.debug("on_receive_getblocks", count=len(blockrequests))
        # integers
        found = []
        blockhash = blockrequest.blockhash
        b = self.get_block(blockhash)
        if b:
            self.env.send(self, peer, BlockReply(b, id(blockrequest)))  # filter id

        for bh in blockhashes[:self.wire_protocol.max_getblocks_count]:
            try:
                found.append(self.chain.db.get(bh))
            except KeyError:
                log.debug("unknown block requested", block_hash=encode_hex(bh))
        if found:
            log.debug("found", count=len(found))
            proto.send_blocks(*found)

    def on_receive_blockproposal(self, proto, proposal):
        log.debug('----------------------------------')
        self.consensus_manager.log('receive proposal', sender=proto)
        log.debug("recv newproposal", proposal=proposal, remote_id=proto)
        # self.synchronizer.receive_newproposal(proto, proposal)
        assert isinstance(proposal, BlockProposal)
        assert isinstance(proposal.block.header, HDCBlockHeader)
        self.consensus_manager.add_proposal(proposal)
        self.consensus_manager.process()

    def on_receive_votinginstruction(self, proto, votinginstruction):
        log.debug('----------------------------------')
        log.debug("recv votinginstruction", proposal=votinginstruction, remote_id=proto)
        # self.synchronizer.receive_newproposal(proto, proposal)
        self.consensus_manager.add_proposal(votinginstruction)
        self.consensus_manager.process()

    def on_receive_vote(self, proto, vote):
        log.debug('----------------------------------')
        log.debug("recv vote", vote=vote, remote_id=proto)
        self.consensus_manager.add_vote(vote)
        self.consensus_manager.process()

    def on_receive_status(self, proto, eth_version, network_id, genesis_hash, current_lockset):
        log.debug('----------------------------------')
        log.debug('status received', proto=proto, eth_version=eth_version)
        assert eth_version == proto.version, (eth_version, proto.version)
        if network_id != self.config['eth'].get('network_id', proto.network_id):
            log.warn("invalid network id", remote_network_id=network_id,
                     expected_network_id=self.config['eth'].get('network_id', proto.network_id))
            raise HDCProtocolError('wrong network_id')

        # check genesis
        if genesis_hash != self.chain.genesis.hash:
            log.warn("invalid genesis hash", remote_id=proto, genesis=genesis_hash.encode('hex'))
            raise HDCProtocolError('wrong genesis block')

        assert isinstance(current_lockset, LockSet)
        if len(current_lockset):
            log.debug('adding received lockset', ls=current_lockset)
            for v in current_lockset.votes:
                self.consensus_manager.add_vote(v)
            self.consensus_manager.process()

        # request chain
        #self.synchronizer.receive_status(proto, chain_head_hash, chain_difficulty)

        # send last BlockProposal
        p = self.consensus_manager.last_blockproposal
        if p:
            self.consensus_manager.log('sending proposal', p=p)
            proto.send_blockproposal(p)

        # send transactions
        transactions = self.chain.get_transactions()
        if transactions:
            log.debug("sending transactions", remote_id=proto)
            proto.send_transactions(*transactions)

    def on_wire_protocol_start(self, proto):
        log.debug('----------------------------------')
        log.debug('on_wire_protocol_start', proto=proto)
        assert isinstance(proto, self.wire_protocol)
        # register callbacks
        proto.receive_status_callbacks.append(self.on_receive_status)
        proto.receive_transactions_callbacks.append(self.on_receive_transactions)
        proto.receive_blocks_callbacks.append(self.on_receive_blocks)
        proto.receive_blockproposal_callbacks.append(self.on_receive_blockproposal)
        proto.receive_votinginstruction_callbacks.append(self.on_receive_votinginstruction)
        proto.receive_vote_callbacks.append(self.on_receive_vote)

        # send status
        proto.send_status(genesis_hash=self.chain.genesis.hash,
                          current_lockset=self.consensus_manager.active_round.lockset)

    def on_wire_protocol_stop(self, proto):
        assert isinstance(proto, self.wire_protocol)
        log.debug('----------------------------------')
        log.debug('on_wire_protocol_stop', proto=proto)


###################

    def _on_new_head(self, block):
        # DEBUG('new head cbs', len(self.on_new_head_cbs))
        for cb in self.on_new_head_cbs:
            cb(block)
        self._on_new_head_candidate()  # we implicitly have a new head_candidate

    def _on_new_head_candidate(self):
        # DEBUG('new head candidate cbs', len(self.on_new_head_candidate_cbs))
        for cb in self.on_new_head_candidate_cbs:
            cb(self.chain.head_candidate)

    def add_transaction(self, tx, origin=None):
        if self.is_syncing:
            return  # we can not evaluate the tx based on outdated state
        log.debug('add_transaction', locked=self.add_transaction_lock.locked(), tx=tx)
        assert isinstance(tx, Transaction)
        assert origin is None or isinstance(origin, BaseProtocol)

        if tx.hash in self.broadcast_filter:
            log.debug('discarding known tx')  # discard early
            return

        # validate transaction
        try:
            validate_transaction(self.chain.head_candidate, tx)
            log.debug('valid tx, broadcasting')
            self.broadcast(tx, origin=origin)  # asap
        except InvalidTransaction as e:
            log.debug('invalid tx', error=e)
            return

        if origin is not None:  # not locally added via jsonrpc
            if not self.is_mining or self.is_syncing:
                log.debug('discarding tx', syncing=self.is_syncing, mining=self.is_mining)
                return

        self.add_transaction_lock.acquire()
        success = self.chain.add_transaction(tx)
        self.add_transaction_lock.release()
        if success:
            self._on_new_head_candidate()

    def knows_block(self, block_hash):
        "if block is in chain or in queue"
        if block_hash in self.chain:
            return True
        # check if queued or processed
        for i in range(len(self.block_queue.queue)):
            if block_hash == self.block_queue.queue[i][0].header.hash:
                return True
        return False

    def gpsec(self, gas_spent=0, elapsed=0):
        if gas_spent:
            self.processed_gas += gas_spent
            self.processed_elapsed += elapsed
        return int(self.processed_gas / (0.001 + self.processed_elapsed))

    def broadcast(self, obj, origin_proto=None):
        fmap = {BlockProposal: 'blockproposal', VoteBlock: 'vote', VoteNil: 'vote',
                VotingInstruction: 'votinginstruction', Transaction: 'transaction'}
        if not self.broadcast_filter.update(obj.hash):
            log.debug('already broadcasted', obj=obj)
            return
        if isinstance(obj, BlockProposal):
            assert obj.sender == obj.block.header.coinbase
        log.debug('broadcasting', obj=obj)
        bcast = self.app.services.peermanager.broadcast
        bcast(HDCProtocol, fmap[type(obj)], args=(obj,),
              exclude_peers=[origin_proto.peer] if origin_proto else [])

import rlp
from ethereum import tester
from ethereum import utils
from devp2p.service import WiredService
from devp2p.protocol import BaseProtocol
from devp2p.app import BaseApp
from hydrachain.consensus.protocol import HDCProtocol
from hydrachain.consensus.base import genesis_signing_lockset, VoteNil, VoteBlock, LockSet
from hydrachain.consensus.base import VotingInstruction, BlockProposal, TransientBlock


class PeerMock(object):
    packets = []
    config = dict()

    def send_packet(self, packet):
        self.packets.append(packet)


def setup():
    peer = PeerMock()
    proto = HDCProtocol(peer, WiredService(BaseApp()))
    proto.service.app.config['eth'] = dict(network_id=1337)
    chain = tester.state()
    cb_data = []

    def cb(proto, **data):
        cb_data.append((proto, data))
    return peer, proto, chain, cb_data, cb


def test_basics():
    peer, proto, chain, cb_data, cb = setup()

    assert isinstance(proto, BaseProtocol)

    d = dict()
    d[proto] = 1
    assert proto in d
    assert d[proto] == 1
    assert not proto
    proto.start()
    assert proto


def test_status():
    peer, proto, chain, cb_data, cb = setup()
    genesis = chain.blocks[-1]
    ls = LockSet(1)

    # test status
    proto.send_status(
        genesis_hash=genesis.hash,
        current_lockset=ls
    )
    packet = peer.packets.pop()
    proto.receive_status_callbacks.append(cb)
    proto._receive_status(packet)

    _p, _d = cb_data.pop()
    assert _p == proto
    assert isinstance(_d, dict)
    assert _d['genesis_hash'] == genesis.hash
    assert _d['current_lockset'] == ls
    assert 'eth_version' in _d
    assert 'network_id' in _d


privkeys = [chr(i) * 32 for i in range(1, 11)]
validators = [utils.privtoaddr(p) for p in privkeys]


def create_proposal(blk):
    signing_lockset = LockSet(len(validators))
    for privkey in privkeys:
        v = VoteBlock(blk.number - 1, 0, blk.hash)
        v.sign(privkey)
        signing_lockset.add(v)
    bp = BlockProposal(height=blk.number, round=0, block=blk,
                       signing_lockset=signing_lockset, round_lockset=None)
    bp.sign(tester.k0)
    return bp


def test_blocks():
    peer, proto, chain, cb_data, cb = setup()
    genesis_signing_lockset(chain.blocks[0], privkeys[0])

    # test blocks
    chain.mine(n=2)
    assert len(chain.blocks) == 3
    proposals = [create_proposal(b) for b in chain.blocks[1:]]
    payload = [rlp.encode(p) for p in proposals]
    proto.send_blockproposals(*payload)
    packet = peer.packets.pop()
    assert len(rlp.decode(packet.payload)) == 2

    def list_cb(proto, blocks):
        cb_data.append((proto, blocks))

    proto.receive_blockproposals_callbacks.append(list_cb)
    proto._receive_blockproposals(packet)

    _p, proposals = cb_data.pop()
    assert isinstance(proposals, tuple)
    for proposal in proposals:
        assert isinstance(proposal, BlockProposal)
        assert proposal.height == proposal.block.header.number
        assert isinstance(proposal.block, TransientBlock)
        assert isinstance(proposal.block.transaction_list, tuple)
        assert isinstance(proposal.block.uncles, tuple)
        # assert that transactions and uncles have not been decoded
        assert len(proposal.block.transaction_list) == 0
        assert len(proposal.block.uncles) == 0


def test_blockproposal():
    pass


def test_votinginstruction():
    peer, proto, chain, cb_data, cb = setup()
    height = 1
    bh = '1' * 32
    round_lockset = LockSet(len(validators))
    for i, privkey in enumerate(privkeys):
        if i < len(validators) // 3 + 1:
            v = VoteBlock(height, 0, bh)
        else:
            v = VoteNil(height, 0)
        v.sign(privkey)
        round_lockset.add(v)
    bp = VotingInstruction(height=height, round=1, round_lockset=round_lockset)
    bp.sign(tester.k0)

    payload = bp

    proto.send_votinginstruction(payload)
    packet = peer.packets.pop()
    assert len(rlp.decode(packet.payload)) == 1

    def list_cb(proto, votinginstruction):
        cb_data.append((proto, votinginstruction))

    proto.receive_votinginstruction_callbacks.append(list_cb)
    proto._receive_votinginstruction(packet)

    _p, vi = cb_data.pop()
    assert vi == bp


def test_getblockproposals():
    peer, proto, chain, cb_data, cb = setup()
    payload = range(10)
    proto.send_getblockproposals(*payload)
    packet = peer.packets.pop()
    assert len(rlp.decode(packet.payload)) == len(payload)

    def list_cb(proto, blocks):
        cb_data.append((proto, blocks))

    proto.receive_getblockproposals_callbacks.append(list_cb)
    proto._receive_getblockproposals(packet)
    _p, data = cb_data.pop()
    assert data == tuple(payload)


def test_vote():
    peer, proto, chain, cb_data, cb = setup()

    def list_cb(proto, vote):
        cb_data.append((proto, vote))
    proto.receive_vote_callbacks.append(list_cb)

    # VoteBlock
    payload = v = VoteBlock(1, 0, '0' * 32)
    v.sign(privkeys[0])
    proto.send_vote(payload)
    packet = peer.packets.pop()
    proto._receive_vote(packet)
    _p, data = cb_data.pop()
    assert data == payload
    assert isinstance(data, VoteBlock)

    payload = v = VoteNil(1, 0)
    v.sign(privkeys[0])
    proto.send_vote(payload)
    packet = peer.packets.pop()
    proto._receive_vote(packet)
    _p, data = cb_data.pop()
    assert data == payload
    assert isinstance(data, VoteNil)

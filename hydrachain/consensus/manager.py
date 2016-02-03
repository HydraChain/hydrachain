# Copyright (c) 2015 Heiko Hees
import sys
import rlp
from .base import LockSet, Vote, VoteBlock, VoteNil, Signed, Ready
from .base import BlockProposal, VotingInstruction, DoubleVotingError, InvalidVoteError
from .base import Block, Proposal, HDCBlockHeader, InvalidProposalError
from .protocol import HDCProtocol
from .utils import cstr, phx
from .synchronizer import Synchronizer
from ethereum.slogging import get_logger
log = get_logger('hdc.consensus')


class ManagerDict(object):

    def __init__(self, dklass, parent):
        self.d = dict()
        self.dklass = dklass
        self.parent = parent

    def __getitem__(self, k):
        if k not in self.d:
            self.d[k] = self.dklass(self.parent, k)
        return self.d[k]

    def __iter__(self):
        return iter(sorted(self.d, reverse=True))

    def pop(self, k):
        self.d.pop(k)


class MissingParent(Exception):
    pass


class ProtocolFailureEvidence(object):
    protocol = None
    evidence = None

    def __repr__(self):
        return '<%s protocol=%r evidence=%r>' % (self.__class__.__name__,
                                                 self.protocol, self.evidence)


class InvalidProposalEvidence(ProtocolFailureEvidence):

    def __init__(self, protocol, proposal):
        self.protocol = protocol
        self.evidence = proposal


class DoubleVotingEvidence(ProtocolFailureEvidence):

    def __init__(self, protocol, vote, othervote):
        self.protocol = protocol
        self.evidence = (vote, othervote)


class InvalidVoteEvidence(ProtocolFailureEvidence):

    def __init__(self, protocol, vote):
        self.protocol = protocol
        self.evidence = vote


class FailedToProposeEvidence(ProtocolFailureEvidence):

    def __init__(self, protocol, round_lockset):
        self.protocol = protocol
        self.evidence = round_lockset


class ForkDetectedEvidence(ProtocolFailureEvidence):

    def __init__(self, protocol, prevblock, block, committing_lockset):
        self.protocol = protocol
        self.evidence = (prevblock, block, committing_lockset)


class ConsensusManager(object):

    allow_empty_blocks = False
    num_initial_blocks = 10
    round_timeout = 3  # timeout when waiting for proposal
    round_timeout_factor = 1.5  # timeout increase per round
    transaction_timeout = 0.5  # delay when waiting for new transaction

    def __init__(self, chainservice, consensus_contract, privkey):
        self.chainservice = chainservice
        self.chain = chainservice.chain
        self.contract = consensus_contract
        self.privkey = privkey

        self.synchronizer = Synchronizer(self)
        self.heights = ManagerDict(HeightManager, self)
        self.block_candidates = dict()  # blockhash : BlockProposal

        self.tracked_protocol_failures = list()

        # wait for enough validators in order to start
        self.ready_validators = set()  # addresses
        self.ready_nonce = 0

        assert self.contract.isvalidator(self.coinbase)
        self.initialize_locksets()

        self.ready_validators = set([self.coinbase])  # old votes dont count

    def initialize_locksets(self):
        log.debug('initializing locksets')
        # sign genesis
        v = self.sign(VoteBlock(0, 0, self.chainservice.chain.genesis.hash))
        self.add_vote(v)

        # add initial lockset
        head_proposal = self.load_proposal(self.head.hash)
        # assert head_proposal
        if head_proposal:
            assert head_proposal.blockhash == self.head.hash
            for v in head_proposal.signing_lockset:
                self.add_vote(v)  # head - 1 , height -2
            assert self.heights[self.head.header.number - 1].has_quorum
        last_committing_lockset = self.load_last_committing_lockset()
        if last_committing_lockset:
            assert last_committing_lockset.has_quorum == self.head.hash
            for v in last_committing_lockset.votes:
                self.add_vote(v)  # head  , height - 1
            assert self.heights[self.head.header.number].has_quorum
        else:
            assert self.head.header.number == 0
        assert self.highest_committing_lockset
        assert self.last_committing_lockset
        assert self.last_valid_lockset

    # persist proposals and last committing lockset

    def store_last_committing_lockset(self, ls):
        assert isinstance(ls, LockSet)
        assert ls.has_quorum
        self.chainservice.db.put('last_committing_lockset', rlp.encode(ls))

    def load_last_committing_lockset(self):
        try:
            data = self.chainservice.db.get('last_committing_lockset')
        except KeyError:
            self.log('no last_committing_lockset could be loaded')
            return
        return rlp.decode(data, sedes=LockSet)

    def store_proposal(self, p):
        assert isinstance(p, BlockProposal)
        self.chainservice.db.put('blockproposal:%s' % p.blockhash, rlp.encode(p))

    def load_proposal_rlp(self, blockhash):
        try:
            prlp = self.chainservice.db.get('blockproposal:%s' % blockhash)
            assert isinstance(prlp, bytes)
            return prlp
        except KeyError:
            return None

    def load_proposal(self, blockhash):
        prlp = self.load_proposal_rlp(blockhash)
        if prlp:
            return rlp.decode(prlp, sedes=BlockProposal)

    def get_blockproposal(self, blockhash):
        return self.block_candidates.get(blockhash) or self.load_proposal(blockhash)

    def has_blockproposal(self, blockhash):
        return bool(self.load_proposal_rlp(blockhash))

    def get_blockproposal_rlp_by_height(self, height):
        assert 0 < height < self.height
        bh = self.chainservice.chain.index.get_block_by_number(height)
        return self.load_proposal_rlp(bh)

    @property
    def coinbase(self):
        return self.chain.coinbase

    def set_proposal_lock(self, block):
        self.chainservice.set_proposal_lock(block)

    def __repr__(self):
        return '<CP A:%r H:%d R:%d L:%r %s>' % (phx(self.coinbase), self.height, self.round,
                                                self.active_round.lock,
                                                self.active_round.lockset.state)

    def log(self, tag, **kargs):
        # if self.coinbase != 0: return
        t = int(self.chainservice.now)
        c = lambda x: cstr(self.coinbase, x)
        msg = ' '.join([str(t), c(repr(self)), tag, (' %r' % kargs if kargs else '')])
        log.debug(msg)

    @property
    def head(self):
        return self.chain.head

    @property
    def height(self):
        return self.head.number + 1

    @property
    def round(self):
        return self.heights[self.height].round

    # message handling

    def broadcast(self, m):
        self.log('broadcasting', message=m)
        self.chainservice.broadcast(m)

    # validator ready handling

    @property
    def is_ready(self):
        return len(self.ready_validators) > len(self.contract.validators) * 2 / 3.

    def send_ready(self):
        self.log('cm.send_ready')
        assert not self.is_ready
        r = Ready(self.ready_nonce, self.active_round.lockset)
        self.sign(r)
        self.broadcast(r)
        self.ready_nonce += 1

    def add_ready(self, ready, proto=None):
        assert isinstance(ready, Ready)
        assert self.contract.isvalidator(ready.sender)
        self.ready_validators.add(ready.sender)
        self.log('cm.add_ready', validator=ready.sender)
        if self.is_ready:
            self.log('cm.add_ready, sufficient count of validators ready',
                     num=len(self.ready_validators))
        else:
            self.send_ready()

    def add_vote(self, v, proto=None):
        assert isinstance(v, Vote)
        assert self.contract.isvalidator(v.sender)
        self.ready_validators.add(v.sender)
        # exception for externaly received votes signed by self, necessary for resyncing
        is_own_vote = bool(v.sender == self.coinbase)
        try:
            success = self.heights[v.height].add_vote(v, force_replace=is_own_vote)
        except DoubleVotingError:
            ls = self.heights[v.height].rounds[v.round].lockset
            self.tracked_protocol_failures.append(DoubleVotingEvidence(proto, v, ls))
            log.warn('double voting detected', vote=v, ls=ls)
        return success

    def add_proposal(self, p, proto=None):
        assert isinstance(p, Proposal)
        assert proto is None or isinstance(proto, HDCProtocol)

        def check(valid):
            if not valid:
                self.tracked_protocol_failures.append(InvalidProposalEvidence(None, p))
                log.warn('invalid proposal', p=p)
                raise InvalidProposalError()
            return True

        self.log('cm.add_proposal', p=p)
        if p.height < self.height:
            self.log('proposal from the past')
            return

        if not check(self.contract.isvalidator(p.sender) and self.contract.isproposer(p)):
            return
        self.ready_validators.add(p.sender)

        if not check(p.lockset.is_valid):
            return
        if not check(p.lockset.height == p.height or p.round == 0):
            return
        if not check(p.round - p.lockset.round == 1 or p.round == 0):
            return

        # proposal is valid
        if proto is not None:  # inactive proto is False
            self.synchronizer.on_proposal(p, proto)

        for v in p.lockset:
            self.add_vote(v)  # implicitly checks their validity
        if isinstance(p, BlockProposal):
            if not check(p.block.number == p.height):
                return
            if not check(p.lockset.has_noquorum or p.round == 0):
                return
            # validation
            if p.height > self.height:
                self.log('proposal from the future, not in sync', p=p)
                return  # note: we are not broadcasting this, as we could not validate
            blk = self.chainservice.link_block(p.block)
            if not check(blk):
                # safeguard for forks:
                # if there is a quorum on a block which can not be applied: panic!
                ls = self.heights[p.height].last_quorum_lockset
                if ls and ls.has_quorum == p.blockhash:
                    raise ForkDetectedEvidence(proto, (self.head, p, ls))
                    sys.exit(1)
                return
            p._mutable = True
            p._cached_rlp = None
            p.block = blk  # block linked to chain
            self.log('successfully linked block')
            self.add_block_proposal(p)  # implicitly checks the votes validity
        else:
            assert isinstance(p, VotingInstruction)
            assert p.lockset.round == p.round - 1 and p.height == p.lockset.height
            assert p.round > 0
            assert p.lockset.has_quorum_possible
            assert not p.lockset.has_quorum
            if not check(p.lockset.has_quorum_possible and not p.lockset.has_quorum):
                return
        is_valid = self.heights[p.height].add_proposal(p)
        return is_valid  # can be broadcasted

    def add_lockset(self, ls, proto=None):
        assert ls.is_valid
        for v in ls:
            self.add_vote(v)  # implicitly checks their validity

    def add_block_proposal(self, p):
        assert isinstance(p, BlockProposal)
        if self.has_blockproposal(p.blockhash):
            self.log('known block_proposal')
            return
        assert p.signing_lockset.has_quorum  # on previous block
        assert p.signing_lockset.height == p.height - 1
        for v in p.signing_lockset:
            self.add_vote(v)
        self.block_candidates[p.blockhash] = p

    @property
    def last_committing_lockset(self):
        return self.heights[self.height - 1].last_quorum_lockset

    @property
    def highest_committing_lockset(self):
        for height in self.heights:
            ls = self.heights[height].last_quorum_lockset
            if ls:
                return ls

    @property
    def last_valid_lockset(self):
        return self.heights[self.height].last_valid_lockset or self.last_committing_lockset

    @property
    def last_lock(self):
        return self.heights[self.height].last_lock

    @property
    def last_blockproposal(self):
        # valid block proposal on currrent height
        p = self.heights[self.height].last_voted_blockproposal
        if p:
            return p
        elif self.height > 1:  # or last block
            return self.get_blockproposal(self.head.hash)

    @property
    def active_round(self):
        hm = self.heights[self.height]
        return hm.rounds[hm.round]

    def setup_alarm(self):
        ar = self.active_round
        delay = ar.get_timeout()
        self.log('in set up alarm', delay=delay)
        if self.is_waiting_for_proposal:
            if delay is not None:
                self.chainservice.setup_alarm(delay, self.on_alarm, ar)
                self.log('set up alarm on timeout', now=self.chainservice.now,
                         delay=delay, triggered=delay + self.chainservice.now)
        else:
            self.chainservice.setup_transaction_alarm(self.on_alarm, ar)
            self.log('set up alarm on tx', now=self.chainservice.now)

    def on_alarm(self, ar):
        assert isinstance(ar, RoundManager)
        if self.active_round == ar:
            self.log('on alarm, matched', ts=self.chainservice.now)
            if not self.is_ready:
                # defer alarm if not ready
                self.log('not ready defering alarm', ts=self.chainservice.now)
                self.setup_alarm()
            elif not self.is_waiting_for_proposal:
                # defer alarm if there are no pending transactions
                self.log('no txs defering alarm', ts=self.chainservice.now)
                self.setup_alarm()
            else:
                self.process()

    @property
    def is_waiting_for_proposal(self):
        return self.allow_empty_blocks \
            or self.has_pending_transactions \
            or self.height <= self.num_initial_blocks

    @property
    def has_pending_transactions(self):
        return self.chain.head_candidate.num_transactions() > 0

    def process(self):
        r = self._process()
        return r

    def _process(self):
        self.log('-' * 40)
        self.log('in process')
        if not self.is_ready:
            self.log('not ready ')
            self.setup_alarm()
            return
        self.commit()
        self.heights[self.height].process()
        if self.commit():  # re enter process if we did commit (e.g. to immediately propose)
            return self._process()
        self.cleanup()
        self.synchronizer.process()
        self.setup_alarm()

        for f in self.tracked_protocol_failures:
            if not isinstance(f, FailedToProposeEvidence):
                log.warn('protocol failure', incident=f)

    start = process

    def commit(self):
        self.log('in commit')
        for p in [c for c in self.block_candidates.values() if c.block.prevhash == self.head.hash]:
            assert isinstance(p, BlockProposal)
            ls = self.heights[p.height].last_quorum_lockset
            if ls and ls.has_quorum == p.blockhash:
                self.store_proposal(p)
                self.store_last_committing_lockset(ls)
                success = self.chainservice.commit_block(p.block)
                assert success
                if success:
                    self.log('commited', p=p, hash=phx(p.blockhash))
                    assert self.head == p.block
                    self.commit()  # commit all possible
                    return True
                else:
                    self.log('could not commit', p=p)
            else:
                self.log('no quorum for', p=p)
                if ls:
                    self.log('votes', votes=ls.votes)

    def cleanup(self):
        self.log('in cleanup')
        for p in self.block_candidates.values():
            if self.head.number >= p.height:
                self.block_candidates.pop(p.blockhash)
        for h in list(self.heights):
            if self.heights[h].height < self.head.number:
                self.heights.pop(h)

    def mk_lockset(self, height):
        return LockSet(num_eligible_votes=self.contract.num_eligible_votes(height))

    def sign(self, o):
        assert isinstance(o, Signed)
        return o.sign(self.privkey)


class HeightManager(object):

    def __init__(self, consensusmanager, height=0):
        self.cm = consensusmanager
        self.log = self.cm.log
        self.height = height
        self.rounds = ManagerDict(RoundManager, self)
        log.debug('A:%s Created HeightManager H:%d' % (phx(self.cm.coinbase), self.height))

    @property
    def round(self):
        l = self.last_valid_lockset
        if l:
            return l.round + 1
        return 0

    @property
    def last_lock(self):
        "highest lock on height"
        rs = list(self.rounds)
        assert len(rs) < 2 or rs[0] > rs[1]  # FIXME REMOVE
        for r in self.rounds:  # is sorted highest to lowest
            if self.rounds[r].lock is not None:
                return self.rounds[r].lock

    @property
    def last_voted_blockproposal(self):
        "the last block proposal node voted on"
        for r in self.rounds:
            if isinstance(self.rounds[r].proposal, BlockProposal):
                assert isinstance(self.rounds[r].lock, Vote)
                if self.rounds[r].proposal.blockhash == self.rounds[r].lock.blockhash:
                    return self.rounds[r].proposal

    @property
    def last_valid_lockset(self):
        "highest valid lockset on height"
        for r in self.rounds:
            ls = self.rounds[r].lockset
            if ls.is_valid:
                return ls
        return None

    @property
    def last_quorum_lockset(self):
        found = None
        for r in sorted(self.rounds):  # search from lowest round first
            ls = self.rounds[r].lockset
            if ls.is_valid and ls.has_quorum:
                if found is not None:  # consistency check, only one quorum on block allowed
                    for r in sorted(self.rounds):  # dump all locksets
                        self.log('multiple valid locksets', round=r, ls=self.rounds[r].lockset,
                                 votes=self.rounds[r].lockset.votes)
                    if found.has_quorum != ls.has_quorum:
                        log.error('FATAL: multiple valid locksets on different proposals')
                        import sys
                        sys.exit(1)
                found = ls
        return found

    @property
    def has_quorum(self):
        ls = self.last_quorum_lockset
        if ls:
            return ls.has_quorum

    def add_vote(self, v, force_replace=False):
        return self.rounds[v.round].add_vote(v, force_replace)

    def add_proposal(self, p):
        assert p.height == self.height
        assert p.lockset.is_valid
        if p.round > self.round:
            self.round = p.round
        return self.rounds[p.round].add_proposal(p)

    def process(self):
        self.log('in hm.process', height=self.height)
        self.rounds[self.round].process()


class RoundManager(object):

    def __init__(self, heightmanager, round_=0):

        assert isinstance(round_, int)
        self.round = round_

        self.hm = heightmanager
        self.cm = heightmanager.cm
        self.log = self.hm.log
        self.height = heightmanager.height
        self.lockset = self.cm.mk_lockset(self.height)
        self.proposal = None
        self.lock = None
        self.timeout_time = None
        log.debug('A:%s Created RoundManager H:%d R:%d' %
                  (phx(self.cm.coinbase), self.hm.height, self.round))

    def get_timeout(self):
        "setup a timeout for waiting for a proposal"
        if self.timeout_time is not None or self.proposal:
            return
        now = self.cm.chainservice.now
        round_timeout = ConsensusManager.round_timeout
        round_timeout_factor = ConsensusManager.round_timeout_factor
        delay = round_timeout * round_timeout_factor ** self.round
        self.timeout_time = now + delay
        return delay

    def add_vote(self, v, force_replace=False):
        if v in self.lockset:
            return
        self.log('rm.adding', vote=v, received_proposal=self.proposal)
        try:
            success = self.lockset.add(v, force_replace)
        except InvalidVoteError:
            self.cm.tracked_protocol_failures.append(InvalidVoteEvidence(None, v))
            return
        # report failed proposer
        if self.lockset.is_valid:
            self.log('lockset is valid', ls=self.lockset)
            if not self.proposal and self.lockset.has_noquorum:
                self.cm.tracked_protocol_failures.append(
                    FailedToProposeEvidence(None, self.lockset))
        return success

    def add_proposal(self, p):
        self.log('rm.adding', proposal=p, old=self.proposal)
        assert isinstance(p, Proposal)
        assert isinstance(p, VotingInstruction) or isinstance(p.block, Block)  # already linked
        assert not self.proposal or self.proposal == p
        self.proposal = p
        return True

    def process(self):
        self.log('in rm.process', height=self.hm.height, round=self.round)

        assert self.cm.round == self.round
        assert self.cm.height == self.hm.height == self.height
        p = self.propose()
        if isinstance(p, BlockProposal):
            self.cm.add_block_proposal(p)
        if p:
            self.cm.broadcast(p)
        v = self.vote()
        if v:
            self.cm.broadcast(v)
        assert not self.proposal or self.lock

    def mk_proposal(self, round_lockset=None):
        signing_lockset = self.cm.last_committing_lockset.copy()  # quorum which signs prev block
        if self.round > 0:
            round_lockset = self.cm.last_valid_lockset.copy()
            assert round_lockset.has_noquorum
        else:
            round_lockset = None
        assert signing_lockset.has_quorum
        # for R0 (std case) we only need one lockset!
        assert round_lockset is None or self.round > 0
        block = self.cm.chain.head_candidate
        # fix pow
        block.header.__class__ = HDCBlockHeader
        block.should_be_locked = True
        bp = BlockProposal(self.height, self.round, block, signing_lockset, round_lockset)
        self.cm.sign(bp)
        self.cm.set_proposal_lock(block)
        assert self.cm.chainservice.proposal_lock.locked()
        return bp

    def propose(self):
        if not self.cm.is_waiting_for_proposal:
            return
        proposer = self.cm.contract.proposer(self.height, self.round)
        self.log('in propose', proposer=phx(proposer), proposal=self.proposal, lock=self.lock)
        if proposer != self.cm.coinbase:
            return
        self.log('is proposer')
        if self.proposal:
            assert self.proposal.sender == self.cm.coinbase
            assert self.lock
            return

        round_lockset = self.cm.last_valid_lockset
        if not round_lockset:
            self.log('no valid round lockset for height')
            return

        self.log('in creating proposal', round_lockset=round_lockset)

        if round_lockset.height == self.height and round_lockset.has_quorum:
            self.log('have quorum on height, not proposing')
            return
        elif self.round == 0 or round_lockset.has_noquorum:
            proposal = self.mk_proposal()
        elif round_lockset.has_quorum_possible:
            proposal = VotingInstruction(self.height, self.round, round_lockset.copy())
            self.cm.sign(proposal)
        else:
            raise Exception('invalid round_lockset')

        self.log('created proposal', p=proposal, bh=phx(proposal.blockhash))
        self.proposal = proposal
        return proposal

    def vote(self):
        if self.lock:
            return  # voted in this round
        self.log('in vote', proposal=self.proposal, pid=id(self.proposal))

        # get last lock on height
        last_lock = self.hm.last_lock

        if self.proposal:
            if isinstance(self.proposal, VotingInstruction):
                assert self.proposal.lockset.has_quorum_possible
                self.log('voting on instruction')
                v = VoteBlock(self.height, self.round, self.proposal.blockhash)
            elif not isinstance(last_lock, VoteBlock):
                assert isinstance(self.proposal, BlockProposal)
                assert isinstance(self.proposal.block, Block)  # already linked to chain
                assert self.proposal.lockset.has_noquorum or self.round == 0
                assert self.proposal.block.prevhash == self.cm.head.hash
                self.log('voting proposed block')
                v = VoteBlock(self.height, self.round, self.proposal.blockhash)
            else:  # repeat vote
                self.log('voting on last vote')
                v = VoteBlock(self.height, self.round, last_lock.blockhash)
        elif self.timeout_time is not None and self.cm.chainservice.now >= self.timeout_time:
            if isinstance(last_lock, VoteBlock):  # repeat vote
                self.log('timeout voting on last vote')
                v = VoteBlock(self.height, self.round, last_lock.blockhash)
            else:
                self.log('timeout voting not locked')
                v = VoteNil(self.height, self.round)
        else:
            return
        self.cm.sign(v)

        self.log('voted', vote=v)
        self.lock = v
        assert self.hm.last_lock == self.lock
        self.lockset.add(v)
        return v

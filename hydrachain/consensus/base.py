# Copyright (c) 2015 Heiko Hees
try:
    from ecdsa_recover import ecdsa_raw_sign, ecdsa_raw_recover
except ImportError:
    from bitcoin import ecdsa_raw_sign, ecdsa_raw_recover
from collections import Counter
from ethereum.blocks import Block
from ethereum.utils import big_endian_to_int
from bitcoin import encode_pubkey, N, P
import rlp
from rlp.sedes import big_endian_int, binary
from rlp.sedes import CountableList
from rlp.utils import encode_hex
from ethereum.blocks import BlockHeader
from ethereum.transactions import Transaction
from hydrachain.utils import sha3, phx


def ishash(h):
    return isinstance(h, bytes) and len(h) == 32


class InvalidSignature(Exception):
    pass


class RLPHashable(rlp.Serializable):

    @property
    def hash(self):
        return sha3(rlp.encode(self))

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.hash == other.hash

    def __hash__(self):
        return big_endian_to_int(self.hash)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return '<%s(%s)>' % (self.__class__.__name__, encode_hex(self.hash)[:4])


class Signed(RLPHashable):

    fields = [
        ('v', big_endian_int),
        ('r', big_endian_int),
        ('s', big_endian_int),
    ]

    _sender = None

    def __init__(self, *args, **kargs):
        super(Signed, self).__init__(*args, **kargs)

    def sign(self, privkey):
        """Sign this with a private key.

        A potentially already existing signature would be overridden.
        """
        if privkey in (0, '', '\x00' * 32):
            raise InvalidSignature("Zero privkey cannot sign")
        rawhash = sha3(rlp.encode(self, self.__class__.exclude(['v', 'r', 's'])))
        self.v, self.r, self.s = ecdsa_raw_sign(rawhash, privkey)
        self._sender = None
        return self

    @property
    def sender(self):
        if not self._sender:
            if self.v:
                if self.r >= N or self.s >= P or self.v < 27 or self.v > 28 \
                   or self.r == 0 or self.s == 0:
                    raise InvalidSignature()
                rlpdata = rlp.encode(self, self.__class__.exclude(['v', 'r', 's']))
                rawhash = sha3(rlpdata)
                pub = ecdsa_raw_recover(rawhash, (self.v, self.r, self.s))
                if pub is False or pub == (0, 0):
                    raise InvalidSignature()
                pub = encode_pubkey(pub, 'bin')
                self._sender = sha3(pub[1:])[-20:]
                assert self.sender == self._sender
            else:
                self._sender = None
        return self._sender


# Votes

class Vote(Signed):

    """A signed Vote"""

    fields = [
        ('height', big_endian_int),
        ('round', big_endian_int),
        ('blockhash', binary),
    ] + Signed.fields

    def __init__(self, height, round, blockhash='', v=0, r=0, s=0):
        super(Vote, self).__init__(height, round, blockhash, v=v, r=r, s=s)

        # restore class when deserialized
        if blockhash:
            assert ishash(blockhash)
            self.blockhash = blockhash
            self.__class__ = VoteBlock
        else:
            self.__class__ = VoteNil

    def __repr__(self):
        return '<%s(S:%s B:%s)>' % (self.__class__.__name__, phx(self.sender), phx(self.blockhash))

    @property
    def hr(self):
        return self.height, self.round


class VoteBlock(Vote):
    pass


class VoteNil(Vote):
    pass


# LockSets

class InvalidVoteError(Exception):
    pass


class DoubleVotingError(InvalidVoteError):
    pass


class LockSet(RLPHashable):  # careful, is mutable!

    fields = [
        ('num_eligible_votes', big_endian_int),
        ('votes', CountableList(Vote))
    ]

    processed = False

    def __init__(self, num_eligible_votes, votes=None):
        self.num_eligible_votes = num_eligible_votes
        self.votes = []
        for v in votes or []:
            self.add(v)

    # @property
    # def size(self):
    #     return len(self.votes) * 67 + 5

    def copy(self):
        return LockSet(self.num_eligible_votes, self.votes)

    @property
    def state(self):
        if not self.is_valid:
            s = 'I'
        elif self.has_quorum:
            s = 'Q'
        elif self.has_quorum_possible:
            s = 'P'
        elif self.has_noquorum:
            s = 'N'
        assert s
        return '%s:%d' % (s, len(self))

    def __repr__(self):
        return '<LockSet(%s H:%d R:%d)>' % (self.state, self.height, self.round)

    def add(self, vote, force_replace=False):
        assert isinstance(vote, Vote)
        if not vote.sender:
            raise InvalidVoteError('no signature')
        if vote not in self.votes:
            if len(self) and self.hr != vote.hr:
                raise InvalidVoteError('inconsistent height, round')
            signee = self.signee
            if vote.sender in signee:
                if not force_replace:
                    raise DoubleVotingError(vote.sender)  # different votes on the same H,R
                self.votes.remove(self.votes[signee.index(vote.sender)])
            self.votes.append(vote)
            return True

    def __len__(self):
        return len(self.votes)

    def __iter__(self):
        return iter(self.votes)

    @property
    def signee(self):
        return [v.sender for v in self.votes]

    def blockhashes(self):
        assert self.is_valid
        c = Counter(v.blockhash for v in self.votes if isinstance(v, VoteBlock))
        # deterministc sort necessary
        return sorted(c.most_common(), cmp=lambda a, b: cmp((b[1], b[0]), (a[1], a[0])))

    @property
    def hr(self):
        assert len(self), 'no votes, can not determin height'
        h = set([(v.height, v.round) for v in self.votes])
        assert len(h) == 1, len(h)
        return h.pop()

    height = property(lambda self: self.hr[0])
    round = property(lambda self: self.hr[1])

    @property
    def is_valid(self):
        return len(self) > 2 / 3. * self.num_eligible_votes and self.hr

    @property
    def has_quorum(self):
        """
        we've seen +2/3 of all eligible votes voting for one block.
        there is a quorum.
        """
        assert self.is_valid
        bhs = self.blockhashes()
        if bhs and bhs[0][1] > 2 / 3. * self.num_eligible_votes:
            assert self.has_quorum_possible
            return bhs[0][0]
        assert self.has_noquorum or self.has_quorum_possible

    @property
    def has_noquorum(self):
        """
        less than 1/3 of the known votes are on the same block
        """
        assert self.is_valid
        bhs = self.blockhashes()
        if not bhs or bhs[0][1] < 1 / 3. * self.num_eligible_votes:
            assert not self.has_quorum_possible
            return True

    @property
    def has_quorum_possible(self):
        """
        we've seen +1/3 of all eligible votes voting for one block.
        at least one vote was from a honest node.
        we can assume that this block is agreeable.
        """
        assert self.is_valid  # we could tell that earlier
        bhs = self.blockhashes()
        if bhs and bhs[0][1] > 1 / 3. * self.num_eligible_votes:
            return bhs[0][0]


############

def genesis_signing_lockset(genesis, privkey):
    """
    in order to avoid a complicated bootstrapping, we define
    the genesis_signing_lockset as a lockset with one vote by any validator.
    """
    v = VoteBlock(0, 0, genesis.hash)
    v.sign(privkey)
    ls = LockSet(num_eligible_votes=1)
    ls.add(v)
    assert ls.has_quorum
    return ls


class InvalidProposalError(Exception):
    pass


class HDCBlockHeader(BlockHeader):

    def check_pow(self, nonce=None):
        return True


class HDCBlock(Block):
    pass


class TransientBlock(rlp.Serializable):

    """A partially decoded, unvalidated block."""

    fields = [
        ('header', HDCBlockHeader),
        ('transaction_list', rlp.sedes.CountableList(Transaction)),
        ('uncles', rlp.sedes.CountableList(BlockHeader))
    ]

    def __init__(self, header, transaction_list, uncles):
        self.header = header
        self.transaction_list = transaction_list
        self.uncles = uncles

    def to_block(self, env, parent=None):
        """Convert the transient block to a :class:`ethereum.blocks.Block`"""
        return Block(self.header, self.transaction_list, self.uncles, env=env, parent=parent)

    @property
    def hash(self):
        """The binary block hash
        This is equivalent to ``header.hash``.
        """
        return sha3(rlp.encode(self.header))

    @property
    def number(self):
        return self.header.number

    @property
    def prevhash(self):
        return self.header.prevhash


class Proposal(Signed):
    pass


class BlockProposal(Proposal):

    fields = [
        ('height', big_endian_int),
        ('round', big_endian_int),
        ('block', TransientBlock),
        ('signing_lockset', LockSet),
        ('round_lockset', LockSet)
    ] + Signed.fields

    def __init__(self, height, round, block, signing_lockset,
                 round_lockset=None, v=0, r=0, s=0):
        """
        if round == 0 the signing_lockset also proves,
        that proposal is eligible and we need not round_lockset
        """
        assert isinstance(block, (Block, TransientBlock))
        assert isinstance(signing_lockset, LockSet)
        assert round_lockset is None or isinstance(round_lockset, LockSet)
        assert round >= 0
        assert height > 0
        if round > 0 and not round_lockset:
            raise InvalidProposalError('R>0 needs a round lockset')
        if round == 0 and round_lockset:
            raise InvalidProposalError('R0 must not have a round lockset')
        self.height = height
        self.round = round
        self.block = block
        self.signing_lockset = signing_lockset
        self.round_lockset = round_lockset or LockSet(0)

        super(BlockProposal, self).__init__(height, round, block, signing_lockset,
                                            self.round_lockset, v, r, s)

        if block.header.number != self.height:
            raise InvalidProposalError('lockset.height / block.number mismatch')
        if self.round_lockset and height != self.round_lockset.height:
            raise InvalidProposalError('height mismatch')
        if not (round > 0 or self.lockset.has_quorum):
            raise InvalidProposalError('R0 lockset == signing lockset needs quorum')
        if not (round > 0 or self.lockset.height == block.header.number - 1):
            raise InvalidProposalError('R0 round lockset must be from previous height')
        if not (round == 0 or round == self.lockset.round + 1):
            raise InvalidProposalError('Rn round lockset must be from previous round')
        if not self.signing_lockset.has_quorum:
            raise InvalidProposalError('signing lockset needs quorum')
        if not (self.signing_lockset.height == self.height - 1):
            raise InvalidProposalError('signing lockset height mismatch')
        if self.round_lockset and not round_lockset.has_noquorum:
            raise InvalidProposalError('at R>0 can only propose if there is a NoQuorum for R-1')

    @property
    def lockset(self):
        return self.round_lockset or self.signing_lockset

    @property
    def sender(self):
        s = super(BlockProposal, self).sender
        if not s:
            raise InvalidProposalError('signature missing')
        if s != self.block.header.coinbase:
            print s.encode('hex'), self.block.header.coinbase.encode('hex')
            raise InvalidProposalError('signature does not match coinbase')
        return s

    def validate_votes(self, validators_H, validators_prevH):
        "set of validators may change between heights"
        assert self.sender

        def check(lockset, validators):
            if not lockset.num_eligible_votes == len(validators):
                raise InvalidProposalError('lockset num_eligible_votes mismatch')
            for v in lockset:
                if v.sender not in validators:
                    raise InvalidProposalError('invalid signer')
        if self.round_lockset:
            check(self.round_lockset, validators_H)
        check(self.signing_lockset, validators_prevH)

        return True

    def __repr__(self):
        return "<%s S:%r H:%d B:%s>" % (self.__class__.__name__, phx(self.sender),
                                        self.height, phx(self.blockhash))

    @property
    def blockhash(self):
        return self.block.hash


class VotingInstruction(Proposal):

    fields = [
        ('height', big_endian_int),
        ('round', big_endian_int),
        ('round_lockset', LockSet)
    ] + Signed.fields

    def __init__(self, height, round, round_lockset, v=0, r=0, s=0):
        super(VotingInstruction, self).__init__(height, round, round_lockset, v, r, s)
        if not round > 0:
            raise InvalidProposalError('VotingInstructions must have R>0')
        if not self.lockset.has_quorum_possible:
            raise InvalidProposalError('VotingInstruction requires quorum possible')
        if not (round == self.lockset.round + 1):
            raise InvalidProposalError('Rn round lockset must be from previous round')
        if not (height == self.lockset.height):
            raise InvalidProposalError('height mismatch')
        if not round > 0:
            raise InvalidProposalError('VotingInstructions must have R>0')
        assert round == round_lockset.round + 1
        assert height == round_lockset.height

    @property
    def blockhash(self):
        return self.round_lockset.has_quorum_possible

    @property
    def lockset(self):
        return self.round_lockset

    def __repr__(self):
        return "<%s %r B:%s>" % (self.__class__.__name__, phx(self.sender), phx(self.blockhash))

    def validate_votes(self, validators_H):
        "set of validators may change between heights"
        assert self.sender
        if not self.round_lockset.num_eligible_votes == len(validators_H):
            raise InvalidProposalError('round_lockset num_eligible_votes mismatch')
        for v in self.round_lockset:
            if v.sender not in validators_H:
                raise InvalidProposalError('invalid signer')


#########################
# safeguard for forks: if there is a quorum on a block which has a wrong prevhash: panic!

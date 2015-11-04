# from hydrachain import protocol
from hydrachain.consensus.base import Vote, VoteBlock, VoteNil, LockSet, ishash, Ready
from hydrachain.consensus.base import DoubleVotingError, InvalidVoteError, MissingSignatureError
from hydrachain.consensus.base import BlockProposal, genesis_signing_lockset, InvalidProposalError
from hydrachain.consensus.base import Proposal, VotingInstruction, InvalidSignature, Signed


from ethereum import utils, tester
import rlp
import pytest

privkey = 'x' * 32


def test_signed():
    s = Signed(v=0, r=0, s=0)
    assert s.sender is None
    with pytest.raises(MissingSignatureError):
        s.hash
    s.sign(privkey)
    sender = s.sender
    h = s.hash
    s.v = 0  # change signature, in order to test signature independend hash
    assert s.sender == sender
    assert s.hash == h


def test_vote():
    h, r = 2, 3
    bh = '0' * 32
    sender = utils.privtoaddr(privkey)

    v = Vote(h, r)
    v2 = Vote(h, r, blockhash=bh)

    assert isinstance(v, Vote)
    assert isinstance(v2, Vote)

    assert isinstance(v, VoteNil)
    assert isinstance(v, rlp.Serializable)

    assert isinstance(v2, VoteBlock)

    v.sign(privkey)
    s = v.sender
    assert s == sender

    v2.sign(privkey)
    assert v2.sender == sender

    # encode
    assert len(v.get_sedes()) == len(v.fields) == 6

    vs = rlp.encode(v)
    assert isinstance(vs, bytes)
    print rlp.decode(vs)
    vd = rlp.decode(vs, Vote)
    assert isinstance(vd, VoteNil)
    assert vd.blockhash == ''
    assert vd == v

    v2s = rlp.encode(v2)
    v2d = rlp.decode(v2s, Vote)
    assert isinstance(v2d, VoteBlock)
    assert v2d.blockhash == bh
    assert v2d == v2

    assert v != v2
    assert vd != v2d

    assert len(set((v, vd))) == 1
    assert len(set((v2, v2d))) == 1
    assert len(set((v, vd, v2, v2d))) == 2


privkeys = [chr(i) * 32 for i in range(1, 11)]
validators = [utils.privtoaddr(p) for p in privkeys]


def test_ready():
    ls = LockSet(num_eligible_votes=len(privkeys))
    s = Ready(0, current_lockset=ls)
    assert s.current_lockset == ls
    s.sign(privkey)
    s0 = Ready(0, current_lockset=ls)
    s0.sign(privkey)
    s1 = Ready(1, current_lockset=ls)
    s1.sign(privkey)

    assert s == s0
    assert s != s1


def test_LockSet():
    ls = LockSet(num_eligible_votes=len(privkeys))
    assert not ls
    assert len(ls) == 0

    bh = '0' * 32
    r, h = 2, 3
    v1 = VoteBlock(h, r, bh)

    # add not signed
    with pytest.raises(InvalidVoteError):
        ls.add(v1)
    assert not ls
    assert v1 not in ls

    # add signed
    v1.sign(privkeys[0])
    ls.add(v1)

    assert ls
    assert len(ls) == 1
    lsh = ls.hash
    ls.add(v1)
    assert lsh == ls.hash
    assert len(ls) == 1

    # second vote same sender
    v2 = VoteBlock(h, r, bh)
    v2.sign(privkeys[0])
    ls.add(v1)
    ls.add(v2)
    assert lsh == ls.hash
    assert len(ls) == 1

    # third vote
    v3 = VoteBlock(h, r, bh)
    v3.sign(privkeys[1])
    ls.add(v1)
    ls.add(v3)
    assert lsh != ls.hash
    assert len(ls) == 2
    assert v3 in ls

    lsh = ls.hash

    # vote wrong round
    v4 = VoteBlock(h, r + 1, bh)
    v4.sign(privkeys[2])
    with pytest.raises(InvalidVoteError):
        ls.add(v4)
    assert lsh == ls.hash
    assert len(ls) == 2
    assert v4 not in ls

    # vote twice
    v3_2 = VoteBlock(h, r, blockhash='1' * 32)
    v3_2.sign(privkeys[1])
    with pytest.raises(DoubleVotingError):
        ls.add(v3_2)
    assert lsh == ls.hash
    assert len(ls) == 2
    assert v3_2 not in ls


def test_one_vote_lockset():
    ls = LockSet(num_eligible_votes=1)
    bh = '0' * 32
    r, h = 2, 3
    v1 = VoteBlock(h, r, bh)
    v1.sign(privkeys[0])
    ls.add(v1)
    assert ls.has_quorum


def test_LockSet_isvalid():
    ls = LockSet(num_eligible_votes=len(privkeys))
    bh = '0' * 32
    r, h = 2, 3

    votes = [VoteBlock(h, r, bh) for i in range(len(privkeys))]
    for i, v in enumerate(votes):
        v.sign(privkeys[i])
        ls.add(v)
        assert len(ls) == i + 1
        if len(ls) < ls.num_eligible_votes * 2 / 3.:
            assert not ls.is_valid
        else:
            assert ls.is_valid
            assert ls.has_quorum  # same blockhash
        ls.check()


def test_LockSet_3_quorums():
    ls = LockSet(3)
    v = VoteBlock(0, 0, '0' * 32)
    v.sign(privkeys[0])
    ls.add(v)
    v = VoteNil(0, 0)
    v.sign(privkeys[1])
    ls.add(v)
    assert len(ls) == 2
    assert not ls.is_valid
    v = VoteNil(0, 0)
    v.sign(privkeys[2])
    ls.add(v)
    assert ls.is_valid
    assert ls.has_noquorum
    assert not ls.has_quorum
    assert not ls.has_quorum_possible
    assert ls.check()


def test_LockSet_quorums():
    combinations = dict(has_quorum=[
        [1] * 7,
        [1] * 7 + [2] * 3,
        [1] * 7 + [None] * 3,
    ],
        has_noquorum=[
        [1] * 3 + [2] * 3 + [None],
        [None] * 7,
        [None] * 10,
        range(10),
        range(7)
    ],
        has_quorum_possible=[
        [1] * 4 + [None] * 3,
        [1] * 4 + [2] * 4,
        [1] * 4 + [2] * 3 + [3] * 3,
        [1] * 6 + [2]
    ])

    r, h = 1, 2
    for method, permutations in combinations.items():
        for set_ in permutations:
            assert len(set_) >= 7
            ls = LockSet(len(privkeys))
            for i, p in enumerate(set_):
                if p is not None:
                    bh = chr(p) * 32
                    v = VoteBlock(h, r, bh)
                else:
                    v = VoteNil(h, r)
                v.sign(privkeys[i])
                ls.add(v)
            assert len(ls) >= 7
            assert getattr(ls, method)
            ls.check()

            # check stable sort
            bhs = ls.blockhashes()
            if len(bhs) > 1:
                assert ishash(bhs[0][0])
                assert isinstance(bhs[0][1], int)
                if bhs[0][1] == bhs[1][1]:
                    assert bhs[0][0] > bhs[1][0]
                else:
                    assert bhs[0][1] > bhs[1][1]

            # test serialization

            s = rlp.encode(ls)
            d = rlp.decode(s, LockSet)

            assert ls == d
            assert id(ls) != id(d)
            assert getattr(ls, method) == getattr(d, method)


def test_blockproposal():
    s = tester.state()

    # block 1
    s.mine(n=1)
    genesis = s.blocks[0]
    assert genesis.header.number == 0
    blk1 = s.blocks[1]
    assert blk1.header.number == 1
    gls = genesis_signing_lockset(genesis, privkeys[0])
    bp = BlockProposal(height=1, round=0, block=blk1, signing_lockset=gls, round_lockset=None)
    assert bp.lockset == gls
    assert isinstance(bp, Proposal)
    bp.sign(tester.k0)

    with pytest.raises(InvalidProposalError):  # round >0 needs round_lockset
        bp = BlockProposal(height=1, round=1, block=blk1, signing_lockset=gls, round_lockset=None)
    bp.validate_votes(validators, validators[:1])

    # block 2
    s.mine(n=1)
    blk2 = s.blocks[2]
    assert blk2.header.number == 2

    ls = LockSet(len(validators))
    for privkey in privkeys:
        v = VoteBlock(height=1, round=0, blockhash=blk1.hash)
        v.sign(privkey)
        ls.add(v)

    bp = BlockProposal(height=2, round=0, block=blk2, signing_lockset=ls, round_lockset=None)
    assert bp.lockset == ls
    with pytest.raises(InvalidProposalError):  # signature missing
        bp.validate_votes(validators, validators)

    with pytest.raises(InvalidProposalError):
        bp.sign(privkeys[0])  # privkey doesnt match coinbase
        bp.validate_votes(validators, validators)

    with pytest.raises(InvalidSignature):  # already signed
        bp.sign(tester.k0)

    bp.v = 0  # reset sigcheck hack
    bp.sign(tester.k0)

    bp.validate_votes(validators, validators)

    with pytest.raises(InvalidProposalError):  # round >0 needs round_lockset
        bp = BlockProposal(height=2, round=1, block=blk2, signing_lockset=gls, round_lockset=None)

    # block 2 round 1, timeout in round=0
    rls = LockSet(len(validators))
    for privkey in privkeys:
        v = VoteNil(height=2, round=0)
        v.sign(privkey)
        rls.add(v)
    bp = BlockProposal(height=2, round=1, block=blk2, signing_lockset=ls, round_lockset=rls)
    assert bp.lockset == rls
    bp.sign(tester.k0)
    bp.validate_votes(validators, validators)

    # serialize
    s = rlp.encode(bp)
    dbp = rlp.decode(s, BlockProposal)
    assert dbp.block == blk2

    dbp.validate_votes(validators, validators)

    # check quorumpossible lockset failure
    rls = LockSet(len(validators))
    for i, privkey in enumerate(privkeys):
        if i < 4:
            v = VoteBlock(height=2, round=0, blockhash='0' * 32)
        else:
            v = VoteNil(height=2, round=0)
        v.sign(privkey)
        rls.add(v)
    assert not rls.has_noquorum
    assert rls.has_quorum_possible
    with pytest.raises(InvalidProposalError):  # NoQuorum necessary R0
        bp = BlockProposal(height=2, round=1, block=blk2, signing_lockset=ls, round_lockset=rls)


def test_VotingInstruction():
    rls = LockSet(len(validators))
    bh = '1' * 32
    for i, privkey in enumerate(privkeys):
        if i < 4:  # quorum possible
            v = VoteBlock(height=2, round=0, blockhash=bh)

        else:
            v = VoteNil(height=2, round=0)
        v.sign(privkey)
        rls.add(v)
    assert rls.has_quorum_possible
    bp = VotingInstruction(height=2, round=1, round_lockset=rls)
    bp.sign(privkeys[0])
    assert bh == bp.blockhash

    # noquorum
    rls = LockSet(len(validators))
    for i, privkey in enumerate(privkeys):
        if i < 3:  # noquorum possible
            v = VoteBlock(height=2, round=0, blockhash=bh)
        else:
            v = VoteNil(height=2, round=0)
        v.sign(privkey)
        rls.add(v)
    assert not rls.has_quorum_possible
    assert rls.has_noquorum
    with pytest.raises(InvalidProposalError):  # QuorumPossiblle necessary R0
        bp = VotingInstruction(height=2, round=1, round_lockset=rls)

    # noquorum
    rls = LockSet(len(validators))
    for i, privkey in enumerate(privkeys):
        if i < 3:  # noquorum possible
            v = VoteBlock(height=2, round=0, blockhash=bh)
        else:
            v = VoteNil(height=2, round=0)

        v.sign(privkey)
        rls.add(v)
    assert not rls.has_quorum_possible
    assert rls.has_noquorum
    with pytest.raises(InvalidProposalError):  # QuorumPossiblle necessary R0
        bp = VotingInstruction(height=2, round=1, round_lockset=rls)

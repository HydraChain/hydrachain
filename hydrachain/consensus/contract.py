from .base import Proposal, isaddress


class ConsensusContract(object):

    def __init__(self, validators):
        for v in validators:
            assert isaddress(v)
        self.validators = validators

    def proposer(self, height, round_):
        v = abs(hash(repr((height, round_))))
        return self.validators[v % len(self.validators)]

    def isvalidator(self, address, height=0):
        assert isaddress(address)
        assert len(self.validators)
        return address in self.validators

    def isproposer(self, p):
        assert isinstance(p, Proposal)
        return p.sender == self.proposer(p.height, p.round)

    def num_eligible_votes(self, height):
        if height == 0:
            return 0
        return len(self.validators)

import pytest
import rlp
from ethereum import tester
from ethereum import utils
from devp2p.service import WiredService
from devp2p.protocol import BaseProtocol
from devp2p.app import BaseApp
from hydrachain.consensus.protocol import HDCProtocol
from hydrachain.consensus.base import genesis_signing_lockset, VoteNil, VoteBlock, LockSet
from hydrachain.consensus.base import VotingInstruction, BlockProposal, TransientBlock
from hydrachain.consensus.simulation import PeerMock, AppMock, Network
import gevent

gevent.get_hub().SYSTEM_ERROR = BaseException

#@pytest.mark.skipif(True, reason='disabled')


def test_basic():
    network = Network(num_nodes=10)
    network.connect_nodes()
    network.start()
    network.run(10)
    network.check_consistency()


def test_basic_simenv():
    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.start()
    network.run(10)
    network.check_consistency()


def test_failing_validators():
    network = Network(num_nodes=10)
    network.connect_nodes()
    network.disable_validators(num=3)
    network.start()
    network.run(30)
    network.check_consistency()


def test_slow_validators():
    pass


def test_slow_and_failing_validators():
    pass


def test_resyncing_of_peers():
    pass


def test_successive_joining():
    # bootstrap scenario
    # manually connect peers
    # nodes need to repeat their votes
    pass

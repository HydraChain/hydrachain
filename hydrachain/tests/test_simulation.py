import pytest
from hydrachain.consensus.manager import RoundManager
from hydrachain.consensus.simulation import Network
import gevent

gevent.get_hub().SYSTEM_ERROR = BaseException

#@pytest.mark.skipif(True, reason='disabled')


def test_basic_gevent():
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
    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.disable_validators(num=3)
    network.start()
    network.run(10)
    network.check_consistency()


def test_slow_validators():
    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.throttle_validators(num=3)
    network.start()
    network.run(10)
    network.check_consistency()


def test_slow_and_failing_validators():
    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.disable_validators(num=3)
    network.throttle_validators(num=6)
    network.start()
    network.run(10)
    network.check_consistency()


def test_low_timeout():
    orig_timeout = RoundManager.timeout
    RoundManager.timeout = 0.1
    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.start()
    network.run(10)
    network.check_consistency()
    RoundManager.timeout = orig_timeout


def test_resyncing_of_peers():
    pass


def test_successive_joining():
    # bootstrap scenario

    # this works without repeated VoteNil sending, as the first node will
    # eventually collect a valid Lockset.
    # if:
    # nodes can request proposals, they missed
    # the network is not disjoint at the beginning

    # solution:
    #   send current and last valid lockset and proposal with status

    network = Network(num_nodes=3)
    RoundManager.timeout = 1

    # disable nodes, i.e. they won't connect yet
    for n in network.nodes:
        n.isactive = False

    for n in network.nodes:
        n.isactive = True
        network.connect_nodes()
        network.start()
        network.run(2)

    network.check_consistency()


"""
ToDo:
    broadcasts
    test with only few peers
    broadcast filters
    syncing

"""

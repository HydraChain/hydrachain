from hydrachain.consensus.manager import RoundManager
from hydrachain.consensus.simulation import Network, assert_heightdistance, assert_maxrounds


def test_failing_validators():
    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.disable_validators(num=3)
    network.start()
    network.run(10)
    r = network.check_consistency()
    assert_heightdistance(r)


def test_slow_validators():
    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.throttle_validators(num=3)
    network.start()
    network.run(10)
    r = network.check_consistency()
    assert_heightdistance(r, 1)


def test_slow_and_failing_validators():
    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.disable_validators(num=3)
    network.throttle_validators(num=6)
    network.start()
    network.run(10)
    r = network.check_consistency()
    assert_heightdistance(r, 1)


def test_low_timeout():
    orig_timeout = RoundManager.timeout
    RoundManager.timeout = 0.1
    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(10)
    RoundManager.timeout = orig_timeout

    r = network.check_consistency()
    assert_heightdistance(r)

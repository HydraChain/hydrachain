from hydrachain.consensus.manager import ConsensusManager
from hydrachain.consensus.simulation import Network, assert_heightdistance


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
    network.run(5)
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


def test_low_timeout(monkeypatch):
    monkeypatch(ConsensusManager, 'round_timeout', 0.1)

    network = Network(num_nodes=10, simenv=True)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(5)

    r = network.check_consistency()
    assert_heightdistance(r)

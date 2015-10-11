from hydrachain.consensus.simulation import Network, assert_heightdistance
from hydrachain.consensus.simulation import assert_maxrounds, assert_blocktime


def test_basic_gevent():
    network = Network(num_nodes=10)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(10)
    r = network.check_consistency()
    assert_maxrounds(r)
    assert_heightdistance(r)


def test_basic_simenv():
    network = Network(num_nodes=4, simenv=True)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(5)
    r = network.check_consistency()
    assert_maxrounds(r)
    assert_heightdistance(r, max_distance=1)
    assert_blocktime(r, 0.5)


def test_basic_singlenode():
    network = Network(num_nodes=1, simenv=True)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(5)
    r = network.check_consistency()
    assert_maxrounds(r)
    assert_heightdistance(r)
    assert_blocktime(r, 1.5)

import pytest
from hydrachain.consensus.simulation import Network, assert_heightdistance


# run this test with `tox -- -rx -k test_late_joins`
@pytest.mark.xfail
@pytest.mark.parametrize('validators', range(3, 10))
@pytest.mark.parametrize('late', range(1, 3))
@pytest.mark.parametrize('delay', [2])
def test_late_joins(validators, late, delay):
    network = Network(num_nodes=validators, simenv=True)
    for node in network.nodes[validators - late:]:
        node.isactive = False
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(delay * (validators - late))
    for node in network.nodes[validators - late:]:
        node.isactive = True
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(max(10, validators * 2))

    r = network.check_consistency()
    assert_heightdistance(r)
    assert r['heights'][10] > 0

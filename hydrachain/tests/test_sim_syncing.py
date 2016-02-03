from hydrachain.consensus.manager import ConsensusManager
from hydrachain.consensus.simulation import Network, assert_heightdistance, assert_maxrounds


def test_resyncing_of_peers():
    network = Network(num_nodes=10, simenv=True)

    # disable one node, i.e. it will not connect yet
    network.nodes[0].isactive = False
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(5)
    network.nodes[0].isactive = True
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(3)

    r = network.check_consistency()
    assert_heightdistance(r)


def test_successive_joining():
    # bootstrap scenario

    # this works without repeated VoteNil sending, as the first node will
    # eventually collect a valid Lockset.
    # if:
    # nodes can request proposals, they missed
    # the network is not disjoint at the beginning

    # solution:
    #   send current and last valid lockset and proposal with status

    network = Network(num_nodes=10, simenv=True)

    # disable nodes, i.e. they won't connect yet
    for n in network.nodes:
        n.isactive = False

    for n in network.nodes:
        n.isactive = True
        network.connect_nodes()
        network.start()
        network.run(2)
    network.run(2)

    r = network.check_consistency()
    assert_heightdistance(r)


def test_broadcasting():
    network = Network(num_nodes=10, simenv=True)
    orig_timeout = ConsensusManager.round_timeout
    # ConsensusManager.round_timeout = 100  # don't trigger timeouts

    # connect nodes as a ring
    for i, n in enumerate(network.nodes):
        if i + 1 < len(network.nodes):
            o = network.nodes[i + 1]
        else:
            o = network.nodes[0]
        n.connect_app(o)
    network.normvariate_base_latencies()
    network.start()
    network.run(10)
    ConsensusManager.round_timeout = orig_timeout
    r = network.check_consistency()
    assert_maxrounds(r)
    assert_heightdistance(r)

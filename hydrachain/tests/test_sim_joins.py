import pytest
from hydrachain.consensus.simulation import Network, assert_heightdistance
from ethereum.transactions import Transaction


# some known troubling validator counts
@pytest.mark.parametrize('validators', range(4, 7) + [10])
@pytest.mark.parametrize('late', range(1, 3))
@pytest.mark.parametrize('delay', [2])
# run this test with `tox -- -rx -k test_late_joins`
def test_late_joins(validators, late, delay):
    """In this test, we spawn a network with a number of
    `validators` validator nodes, where a number of `late` nodes stay
    offline until after a certain delay:

    >>> initial sync_time = delay * (validators - late)

    Now the "late-joiners" come online and we let them sync until
    the networks head block is at `num_initial_blocks` (default: 10).

    Since in some configurations the late-joiners don't manage to catch up
    at that point, we inject a transaction (leading to a new block) into
    the now fully online network.

    Now all nodes must be at the same block-height: `(num_initial_blocks + 1)`.
    """
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
    network.run(max(10, validators * delay))

    r = network.check_consistency()

    # now majority must be at block 10
    # late-joiners may be at block 9 or even still at block 0
    assert_heightdistance(r, max_distance=10)
    assert r['heights'][10] >= (validators - late)

    # after a new block, all nodes should be up-to-date:
    chainservice = network.nodes[0].services.chainservice

    sender = chainservice.chain.coinbase
    to = 'x' * 20
    nonce = chainservice.chain.head.get_nonce(sender)
    gas = 21000
    gasprice = 1
    value = 1
    assert chainservice.chain.head.get_balance(sender) > gas * gasprice + value
    tx = Transaction(nonce, gasprice, gas, to, value, data='')
    network.nodes[0].services.accounts.sign_tx(sender, tx)
    assert tx.sender == sender

    success = chainservice.add_transaction(tx)
    assert success

    # run in ever longer bursts until we're at height 11
    for i in range(1, 10):
        network.connect_nodes()
        network.normvariate_base_latencies()
        network.start()
        network.run(2 * i)
        r = network.check_consistency()
        if r['heights'][11] == validators:
            break

    assert_heightdistance(r)
    assert r['heights'][11] == validators

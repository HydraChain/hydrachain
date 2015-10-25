from hydrachain.consensus.simulation import Network, assert_heightdistance
from hydrachain.consensus.simulation import assert_maxrounds, assert_blocktime, log
from hydrachain.consensus.manager import ConsensusManager
from ethereum.transactions import Transaction
import pytest


def test_basic_gevent():
    network = Network(num_nodes=10)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(10)
    r = network.check_consistency()
    # note gevent depends on real clock, therefore results are not predictable
    # assert_maxrounds(r)
    # assert_heightdistance(r)


def test_basic_simenv():
    network = Network(num_nodes=4, simenv=True)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(5)
    r = network.check_consistency()
    assert_maxrounds(r)
    assert_heightdistance(r, max_distance=1)
    assert_blocktime(r, 1.5)


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


def test_transactions():
    sim_time = 5
    num_txs = 2
    _num_initial_blocks_orig = ConsensusManager.num_initial_blocks
    num_initial_blocks = 2
    ConsensusManager.num_initial_blocks = num_initial_blocks

    network = Network(num_nodes=4, simenv=True)
    network.connect_nodes()
    network.normvariate_base_latencies()
    app = network.nodes[0]
    chainservice = app.services.chainservice

    def cb(blk):
        log.DEV('ON NEW HEAD', blk=blk)
        if blk.number >= num_initial_blocks and blk.number < num_initial_blocks + num_txs:
            if blk.number > num_initial_blocks:
                assert blk.num_transactions() == 1
            sender = chainservice.chain.coinbase
            to = 'x' * 20
            nonce = chainservice.chain.head.get_nonce(sender)
            log.DEV('CREATING TX', nonce=nonce)
            gas = 21000
            gasprice = 1
            value = 1
            assert chainservice.chain.head.get_balance(sender) > gas * gasprice + value
            tx = Transaction(nonce, gasprice, gas, to, value, data='')
            app.services.accounts.sign_tx(sender, tx)
            assert tx.sender == sender
            success = chainservice.add_transaction(tx)

    chainservice.on_new_head_cbs.append(cb)
    network.start()
    network.run(sim_time)
    r = network.check_consistency()
    print r
    expected_head_number = num_initial_blocks + num_txs
    assert chainservice.chain.head.number == expected_head_number
    assert_maxrounds(r)
    assert_heightdistance(r, max_distance=1)
    assert_blocktime(r, 1.5)

    # set to old value
    ConsensusManager.num_initial_blocks = _num_initial_blocks_orig

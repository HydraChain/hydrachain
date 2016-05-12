from hydrachain.consensus.simulation import Network, assert_heightdistance
from hydrachain.consensus.simulation import assert_maxrounds, assert_blocktime, log
from hydrachain.consensus.manager import ConsensusManager
from ethereum.transactions import Transaction
import gevent


def test_basic_gevent():
    network = Network(num_nodes=4)
    network.connect_nodes()
    network.normvariate_base_latencies()
    network.start()
    network.run(6)
    r = network.check_consistency()
    # note gevent depends on real clock, therefore results are not predictable
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


def test_transactions(monkeypatch):
    sim_time = 10
    num_txs = 2
    num_initial_blocks = 2

    monkeypatch.setattr(ConsensusManager, 'num_initial_blocks', num_initial_blocks)

    network = Network(num_nodes=4, simenv=False)
    network.connect_nodes()
    network.normvariate_base_latencies()
    app = network.nodes[0]
    chainservice = app.services.chainservice

    # track txs
    txs = []

    def cb(blk):
        log.DEV('ON NEW HEAD', blk=blk)
        if num_initial_blocks <= blk.number < num_initial_blocks + num_txs:
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

            def _do():
                log.DEV('ADDING TX', nonce=nonce)
                success = chainservice.add_transaction(tx)
                assert success
                log.DEV('ADDED TX', success=success)

            if network.simenv:
                network.simenv.process(_do())
            else:
                gevent.spawn(_do)
            txs.append(tx)

    print(chainservice.on_new_head_cbs)
    chainservice.on_new_head_cbs.append(cb)
    network.start()
    network.run(sim_time)
    r = network.check_consistency()
    log.debug(r)
    expected_head_number = num_initial_blocks + num_txs
    assert chainservice.chain.head.number == expected_head_number
    assert_maxrounds(r)
    assert_heightdistance(r, max_distance=1)
    #assert_blocktime(r, 1.5)

    # check if all txs are received in all chains
    tx_pos = set()
    for app in network.nodes:
        for tx in txs:
            r = app.services.chainservice.chain.index.get_transaction(tx.hash)
            assert len(r) == 3
            t, blk, idx = r
            assert tx == t
            tx_pos.add(r)
        assert len(tx_pos) == len(txs)

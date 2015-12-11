from ethereum import tester
from hydrachain import native_contracts as nc
import logging
logging.NOTSET = logging.ERROR

import coin_contract as coinc


def test_coin():
    state = tester.state()
    logs = []
    admin_address = tester.a0
    admin_key = tester.k0
    alice_key = tester.k1
    alice_address = tester.a1
    bob_address = tester.a2

    # create proxy
    nc.listen_logs(state, coinc.CoinSent, callback=lambda e: logs.append(e))
    coin_as_creator = nc.tester_nac(state, admin_key, coinc.Coin.address)

    # initalize coin with a fixed quantity of coins.
    coin_as_creator.init()
    coin_total = 1000000
    assert coin_as_creator.coinBalance() == coin_total

    # creator sends shares to alice
    send_amount_alice = 700000
    coin_as_creator.sendCoin(send_amount_alice, alice_address)
    assert coin_as_creator.coinBalanceOf(admin_address) == coin_total - send_amount_alice
    assert coin_as_creator.coinBalanceOf(alice_address) == send_amount_alice

    # check logs data of CoinSent Event
    assert len(logs) == 1
    l = logs[0]
    assert l['from'] == admin_address
    assert l['value'] == send_amount_alice
    assert l['to'] == alice_address

    # alice transfers something to bob
    send_amount_bob = 400000
    # create proxy for alice
    coin_as_alice = nc.tester_nac(state, alice_key, coinc.Coin.address)
    coin_as_alice.sendCoin(send_amount_bob, bob_address)

    # test balances
    assert coin_as_alice.coinBalanceOf(admin_address) == coin_total - send_amount_alice
    assert coin_as_alice.coinBalance() == send_amount_alice - send_amount_bob
    assert coin_as_alice.coinBalanceOf(bob_address) == send_amount_bob

    # now we should have three coin holders
    assert 3 == coin_as_alice.numHolders()

    # alice tries to spend more than she has
    alice_balance = send_amount_alice - send_amount_bob

    try:
        coin_as_alice.sendCoin(alice_balance + 1, bob_address)
    except tester.TransactionFailed:
        assert coin_as_alice.coinBalance() == alice_balance
    else:
        print 'alice now', coin_as_alice.coinBalance()
        raise Exception('must fail')

    r = coin_as_creator.getHolders()
    assert r == [admin_address, alice_address, bob_address]

    print logs
    while logs and logs.pop():
        pass

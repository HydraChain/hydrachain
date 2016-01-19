from ethereum import tester
from hydrachain import native_contracts as nc
from coin_contract import Coin, Transfer, Approval
import ethereum.slogging as slogging
log = slogging.get_logger('sim.config')
nc.registry.register(Coin)


def test_coin_instance():
    state = tester.state()
    creator_address = tester.a0
    creator_key = tester.k0

    # Create proxy

    to_ = nc.CreateNativeContractInstance.address
    call_data = Coin.address[-4:]
    EUR_address = state.send(creator_key, to_, value=0, evmdata=call_data)
    # EUR_address = nc.registry.mk_instance_address(contracts.Coin, admin_address, tx.nonce)
    coin_as_creator = nc.tester_nac(state, creator_key, EUR_address)
    # Initalize coin with a fixed quantity of coins.
    coin_total = 1000000
    coin_as_creator.init(coin_total)
    assert coin_as_creator.balanceOf(creator_address) == coin_total
    nc.registry.unregister(Coin)


def test_coin_template():
    """
    Tests;
        Coin initialization as Creator,
        Creator sends Coins to Alice,
        Alice sends Coins to Bob,
        Bob approves Creator to spend Coins on his behalf,
        Creator allocates these Coins from Bob to Alice,
        Testing of non-standardized functions of the Coin contract.
    Events;
        Checking logs from Transfer and Approval Events
    """

    # Register Contract Coin
    nc.registry.register(Coin)

    # Initialize Participants and Coin contract
    state = tester.state()
    logs = []
    creator_address = tester.a0
    creator_key = tester.k0
    alice_address = tester.a1
    alice_key = tester.k1
    bob_address = tester.a2
    bob_key = tester.k2
    # Create proxy
    nc.listen_logs(state, Transfer, callback=lambda e: logs.append(e))
    nc.listen_logs(state, Approval, callback=lambda e: logs.append(e))
    coin_as_creator = nc.tester_nac(state, creator_key, Coin.address)
    # Initalize coin with a fixed quantity of coins.
    coin_total = 1000000
    coin_as_creator.init(coin_total)
    assert coin_as_creator.balanceOf(creator_address) == coin_total

    # Creator transfers Coins to Alice
    send_amount_alice = 700000
    coin_as_creator.transfer(alice_address, send_amount_alice)
    assert coin_as_creator.balanceOf(creator_address) == coin_total - send_amount_alice
    assert coin_as_creator.balanceOf(alice_address) == send_amount_alice
    # Check logs data of Transfer Event
    assert len(logs) == 1
    l = logs[0]
    assert l['event_type'] == 'Transfer'
    assert l['from'] == creator_address
    assert l['to'] == alice_address
    # Build transaction Log arguments and check sent amount
    assert l['value'] == send_amount_alice

    # Alice transfers Coins to Bob
    send_amount_bob = 400000
    # Create proxy for Alice
    coin_as_alice = nc.tester_nac(state, alice_key, Coin.address)
    coin_as_alice.transfer(bob_address, send_amount_bob)
    # Test balances of Creator, Alice and Bob
    creator_balance = coin_total - send_amount_alice
    alice_balance = send_amount_alice - send_amount_bob
    bob_balance = send_amount_bob
    assert coin_as_alice.balanceOf(creator_address) == creator_balance
    assert coin_as_alice.balanceOf(alice_address) == alice_balance
    assert coin_as_alice.balanceOf(bob_address) == bob_balance

    # Create proxy for Bob
    coin_as_bob = nc.tester_nac(state, bob_key, Coin.address)
    approved_amount_bob = 100000
    assert coin_as_bob.allowance(creator_address) == 0
    # Bob approves Creator to spend Coins
    assert coin_as_bob.allowance(creator_address) == 0
    coin_as_bob.approve(creator_address, approved_amount_bob)
    assert coin_as_bob.allowance(creator_address) == approved_amount_bob

    # Test transferFrom function, i.e. direct debit.
    coin_as_creator.transferFrom(bob_address, alice_address, approved_amount_bob)
    # Test balances
    alice_balance += approved_amount_bob
    bob_balance -= approved_amount_bob
    assert coin_as_alice.balanceOf(creator_address) == creator_balance
    assert coin_as_alice.balanceOf(alice_address) == alice_balance
    assert coin_as_alice.balanceOf(bob_address) == bob_balance
    # Check logs data of Transfer Event
    assert len(logs) == 4
    l = logs[-1]
    assert l['event_type'] == 'Transfer'
    assert l['from'] == bob_address
    assert l['to'] == alice_address
    # Build transaction Log arguments and check sent amount
    assert l['value'] == approved_amount_bob

    # Testing account information
    # Now we should have three Coin accounts
    assert 3 == coin_as_alice.num_accounts()
    r = coin_as_creator.get_creator()
    assert r == creator_address
    r = coin_as_creator.get_accounts()
    assert r == [creator_address, alice_address, bob_address]

    print logs
    while logs and logs.pop():
        pass

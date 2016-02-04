from ethereum import tester
import hydrachain.native_contracts as nc
from fungible_contract import Fungible, Transfer, Approval
import ethereum.slogging as slogging
log = slogging.get_logger('test.fungible')


def test_fungible_instance():
    state = tester.state()
    creator_address = tester.a0
    creator_key = tester.k0

    nc.registry.register(Fungible)

    # Create proxy
    EUR_address = nc.tester_create_native_contract_instance(state, creator_key, Fungible)
    fungible_as_creator = nc.tester_nac(state, creator_key, EUR_address)
    # Initalize fungible with a fixed quantity of fungibles.
    fungible_total = 1000000
    fungible_as_creator.init(fungible_total)
    assert fungible_as_creator.balanceOf(creator_address) == fungible_total
    nc.registry.unregister(Fungible)


def test_fungible_template():
    """
    Tests;
        Fungible initialization as Creator,
        Creator sends Fungibles to Alice,
        Alice sends Fungibles to Bob,
        Bob approves Creator to spend Fungibles on his behalf,
        Creator allocates these Fungibles from Bob to Alice,
        Testing of non-standardized functions of the Fungible contract.
    Events;
        Checking logs from Transfer and Approval Events
    """

    # Register Contract Fungible
    nc.registry.register(Fungible)

    # Initialize Participants and Fungible contract
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
    fungible_as_creator = nc.tester_nac(state, creator_key, Fungible.address)
    # Initalize fungible with a fixed quantity of fungibles.
    fungible_total = 1000000
    fungible_as_creator.init(fungible_total)
    assert fungible_as_creator.balanceOf(creator_address) == fungible_total

    # Creator transfers Fungibles to Alice
    send_amount_alice = 700000
    fungible_as_creator.transfer(alice_address, send_amount_alice)
    assert fungible_as_creator.balanceOf(creator_address) == fungible_total - send_amount_alice
    assert fungible_as_creator.balanceOf(alice_address) == send_amount_alice
    # Check logs data of Transfer Event
    assert len(logs) == 1
    l = logs[0]
    assert l['event_type'] == 'Transfer'
    assert l['from'] == creator_address
    assert l['to'] == alice_address
    # Build transaction Log arguments and check sent amount
    assert l['value'] == send_amount_alice

    # Alice transfers Fungibles to Bob
    send_amount_bob = 400000
    # Create proxy for Alice
    fungible_as_alice = nc.tester_nac(state, alice_key, Fungible.address)
    fungible_as_alice.transfer(bob_address, send_amount_bob)
    # Test balances of Creator, Alice and Bob
    creator_balance = fungible_total - send_amount_alice
    alice_balance = send_amount_alice - send_amount_bob
    bob_balance = send_amount_bob
    assert fungible_as_alice.balanceOf(creator_address) == creator_balance
    assert fungible_as_alice.balanceOf(alice_address) == alice_balance
    assert fungible_as_alice.balanceOf(bob_address) == bob_balance

    # Create proxy for Bob
    fungible_as_bob = nc.tester_nac(state, bob_key, Fungible.address)
    approved_amount_bob = 100000
    assert fungible_as_bob.allowance(creator_address) == 0
    # Bob approves Creator to spend Fungibles
    assert fungible_as_bob.allowance(creator_address) == 0
    fungible_as_bob.approve(creator_address, approved_amount_bob)
    assert fungible_as_bob.allowance(creator_address) == approved_amount_bob

    # Test transferFrom function, i.e. direct debit.
    fungible_as_creator.transferFrom(bob_address, alice_address, approved_amount_bob)
    # Test balances
    alice_balance += approved_amount_bob
    bob_balance -= approved_amount_bob
    assert fungible_as_alice.balanceOf(creator_address) == creator_balance
    assert fungible_as_alice.balanceOf(alice_address) == alice_balance
    assert fungible_as_alice.balanceOf(bob_address) == bob_balance
    # Check logs data of Transfer Event
    assert len(logs) == 4
    l = logs[-1]
    assert l['event_type'] == 'Transfer'
    assert l['from'] == bob_address
    assert l['to'] == alice_address
    # Build transaction Log arguments and check sent amount
    assert l['value'] == approved_amount_bob

    # Testing account information
    # Now we should have three Fungible accounts
    assert 3 == fungible_as_alice.num_accounts()
    r = fungible_as_creator.get_creator()
    assert r == creator_address
    r = fungible_as_creator.get_accounts()
    assert set(r) == set([creator_address, alice_address, bob_address])

    print logs
    while logs and logs.pop():
        pass

    nc.registry.unregister(Fungible)

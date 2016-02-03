from ethereum import tester
import hydrachain.native_contracts as nc
from fungible_contract import IOU
import ethereum.slogging as slogging
log = slogging.get_logger('test.iou')


def test_iou_template():
    """
    Tests;
        IOU initialization as Issuer,
        Testing issue funds, get_issued_amount
    """

    # Register Contract Fungible
    nc.registry.register(IOU)

    # Initialize Participants and Fungible contract
    state = tester.state()
    logs = []
    issuer_address = tester.a0
    issuer_key = tester.k0
    # create listeners
    for evt_class in IOU.events:
        nc.listen_logs(state, evt_class, callback=lambda e: logs.append(e))

    # Initialization
    iou_address = nc.tester_create_native_contract_instance(state, issuer_key, IOU)
    iou_as_issuer = nc.tester_nac(state, issuer_key, iou_address)
    iou_as_issuer.init()
    assert iou_as_issuer.balanceOf(issuer_address) == 0
    amount_issued = 200000
    iou_as_issuer.issue_funds(amount_issued, '')
    assert iou_as_issuer.balanceOf(issuer_address) == amount_issued

    iou_as_issuer.issue_funds(amount_issued, '')
    assert iou_as_issuer.balanceOf(issuer_address) == 2 * amount_issued
    assert iou_as_issuer.get_issued_amount(issuer_address) == 2 * amount_issued

    print logs
    while logs and logs.pop():
        pass

    nc.registry.unregister(IOU)

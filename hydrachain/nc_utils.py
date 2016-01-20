from ethereum.utils import zpad
import gevent.event
import ethereum.slogging as slogging
from ethereum import transactions
from pyethapp.rpc_client import ABIContract
from hydrachain import native_contracts as nc
log = slogging.get_logger('nc.utils')

STATUS = 'uint16'
FORBIDDEN = 403
NOTFOUND = 404
OK = 200
ERROR = 500
BADREQEST = 400
INSUFFICIENTFUNDS = PAYMENTREQUIRED = 402


def isaddress(x):
    return len(x) == 20 and x != '\0' * 20


def lhexenc(lst):
    return [l.encode('hex') for l in lst]


def transact(app, sender, to_, value=0, data=''):
    head_candidate = app.services.chain.chain.head_candidate
    default_gasprice = 1
    default_startgas = head_candidate.gas_limit - head_candidate.gas_used
    nonce = head_candidate.get_nonce(sender)
    tx = transactions.Transaction(nonce=nonce, gasprice=default_gasprice,
                                  startgas=default_startgas, to=to_, value=value, data=data)
    assert sender in app.services.accounts, 'no account for sender'
    app.services.accounts.sign_tx(sender, tx)
    success = app.services.chain.add_transaction(tx)
    assert success
    return tx


def wait_next_block_factory(app, timeout=None):
    """Creates a `wait_next_block` function, that
    will wait `timeout` seconds (`None` = indefinitely)
    for a new block to appear.

    :param app: the app-instance the function should work for
    :param timeout: timeout in seconds
    """

    chain = app.services.chain

    # setup new block callbacks and events
    new_block_evt = gevent.event.Event()

    def _on_new_block(app):
        log.DEV('new block mined')
        new_block_evt.set()
    chain.on_new_head_cbs.append(_on_new_block)

    def wait_next_block():
        bn = chain.chain.head.number
        chain.consensus_manager.log('waiting for new block', block=bn)
        new_block_evt.wait(timeout)
        new_block_evt.clear()
        if chain.chain.head.number > bn:
            chain.consensus_manager.log('new block event', block=chain.chain.head.number)
        elif chain.chain.head.number == bn:
            chain.consensus_manager.log('wait_next_block timed out', block=bn)

    return wait_next_block


def create_contract_instance(app, sender, contract_template):
    log.DEV("creating instance", klass=contract_template)
    to_ = nc.CreateNativeContractInstance.address
    call_data = contract_template.address[-4:]
    tx = transact(app, sender, to_, data=call_data)
    instance_address = nc.registry.mk_instance_address(contract_template, sender, tx.nonce)
    return instance_address


def decode_log(log_, events):
    cls = None
    for e_class in events:
        if e_class.event_id() == log_.topics[0]:
            cls = e_class
    if not cls:
        log.DEV('unknown eventclass for log_')
        return None
    res = []
    cls.listen(log_, address=None, callback=res.append)
    e = res[0]
    e['contract'] = log_.address
    cn = nc.registry.address_to_native_contract_class(log_.address).im_self.__name__
    e['contract_class'] = cn
    return e


def get_logs(app, events):
    log.DEV('getting logs!')
    chain = app.services.chain.chain
    logs = []
    for i in range(0, chain.head.number + 1):
        block = chain.get(chain.index.get_block_by_number(i))
        receipts = block.get_receipts()
        # log.DEV('with', bnum=i, num_receipts=len(receipts))
        for r_idx, receipt in enumerate(receipts):  # one receipt per tx
            # log.DEV('with', r_num=r_idx, num_logs=len(receipt.logs))
            for l_idx, log_ in enumerate(receipt.logs):
                dlog = decode_log(log_, events)
                # log.DEV('log', rlog=log_, log=dlog)
                logs.append(dlog)
    return logs


def hexify_dict(dict_):
    for k, v in dict_.items():
        if isinstance(v, bytes) and len(v) in (20, 32):
            dict_[k] = v.encode('hex')
    return dict_


def contract_args_from_kargs(contract_class, method, kargs):
    for obj in contract_class.abi():
        if obj['type'] == 'function' and obj['name'] == method:
            arg_names = [i['name'] for i in obj['inputs']]
            diff = set(kargs.keys()).symmetric_difference(set(arg_names))
            assert not diff, 'doesnt match signature:{} error:{}'.format(arg_names, diff)
            return [kargs[name] for name in arg_names]
    raise Exception('method not found')


class User():

    def __init__(self, app, address):
        self.app = app
        self.address = address

    def add_proxy(self, name, address):
        template_address = zpad(address[-4:], 20)
        klass = nc.registry[template_address].im_self
        assert issubclass(klass, nc.NativeABIContract)

        def _transact_func(sender, to, value, data):
            return transact(self.app, sender, to, value, data)

        def _call_func(sender, to, value, data):
            block = self.app.services.chain.chain.head_candidate
            return nc.test_call(block, sender, to, data=data, gasprice=0, value=value)

        proxy = ABIContract(self.address, klass.abi(), address, _call_func, _transact_func)
        setattr(self, name, proxy)

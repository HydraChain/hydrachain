"""
WARNING: Below techniques are not officially supported by the Ethereum protocol.


DAPP developers often develop and test contracts in a HLL like python first and then
recode it in Serpent or Solidity.

This module tries to support this approach by providing an infrastructe where
contracts written in Python can be contracts in a live (private) blockchain.


Implementation:
    special.specials is extended
        - to be registry of NativeContracts and their instances
        - implementing __contains__ and __getattr__
    NativeContracts have a address range for their instances

Creating Instances of NativeContracts
    a special CreateNativeContractInstance contract is used to create instances of NativeContracts

Calling Instances of NativeContracts
    for CALL and CALLCODE
    _apply_msg queries the registry with the address and
    directly calls the native contract if available (FIXME: how to check existance)


Limitations:
    EXTCODESIZE on an address with a NativeContract
        returns 0

    EXTCODECOPY on an address with a NativeContract
        returns ''
"""
import inspect
import traceback
from copy import deepcopy

import ethereum.abi as abi
import ethereum.processblock as processblock
import ethereum.specials as specials
import ethereum.utils as utils
import ethereum.vm as vm
from ethereum import slogging
from ethereum.transactions import Transaction
from ethereum.utils import encode_int, zpad, big_endian_to_int, int_to_big_endian

slogging.configure(config_string=':debug')
log = slogging.get_logger('nc')


class Registry(object):

    """
    NativeContracts:
    0000|000000000000|0123

    NativeContract Instances:
    0000|0123456789ab|0123
    """

    native_contract_address_prefix = '\0' * 16
    native_contract_instance_address_prefix = '\0' * 4

    def __init__(self):
        # register special contracts as defaults
        self.native_contracts = dict(specials.specials)  # address: contract

    def mk_instance_address(self, native_contract, sender, nonce):
        assert native_contract.address.startswith(self.native_contract_address_prefix)
        addr = '\0' * 4
        addr += processblock.mk_contract_address(sender, nonce)[:12]
        addr += native_contract.address[-4:]
        return addr

    def is_instance_address(self, address):
        assert isinstance(address, bytes) and len(address) in (20, 0)
        return address.startswith(self.native_contract_instance_address_prefix)

    def address_to_native_contract_class(self, address):
        "returns class._on_msg_unsafe, use x.im_self to get class"
        assert isinstance(address, bytes) and len(address) == 20
        assert self.is_instance_address(address)
        nca = self.native_contract_address_prefix + address[-4:]
        return self.native_contracts[nca]

    def register(self, contract):
        "registers NativeContract classes"
        assert issubclass(contract, NativeContractBase)
        assert len(contract.address) == 20
        assert contract.address.startswith(self.native_contract_address_prefix)
        if self.native_contracts.get(contract.address) == contract._on_msg:
            log.debug("already registered", contract=contract, address=contract.address)
            return
        assert contract.address not in self.native_contracts, 'address already taken'
        self.native_contracts[contract.address] = contract._on_msg
        log.debug("registered native contract", contract=contract, address=contract.address)

    def unregister(self, contract):
        del self.native_contracts[contract.address]

    def abi_contracts(self):
        return [c.im_self for c in self.native_contracts.values()
                if hasattr(c, 'im_self') and issubclass(c.im_self, NativeContract)]

    def __contains__(self, address):
        nca = self.native_contract_address_prefix + address[-4:]
        return self.is_instance_address(address) and nca in self.native_contracts

    def __getitem__(self, address):
        # print 'returning native contract', self.address_to_native_contract_class(address)
        return self.address_to_native_contract_class(address)

# set registry
specials.specials = registry = Registry()


class NativeContractBase(object):

    address = utils.int_to_addr(1024)

    def __init__(self, ext, msg):
        self._ext = ext
        self._msg = msg
        self.gas = msg.gas

    @classmethod
    def _on_msg(cls, ext, msg):
        nac = cls(ext, msg)
        try:
            return nac._safe_call()
        except Exception:
            log.error('contract errored', contract=cls.__name__)
            print(traceback.format_exc())
            return 0, msg.gas, []

    def _get_storage_data(self, key):
        return self._ext.get_storage_data(self._msg.to, key)

    def _set_storage_data(self, key, value):
        return self._ext.set_storage_data(self._msg.to, key, value)

    def _safe_call(self):
        return 1, self.gas, []


class CreateNativeContractInstance(NativeContractBase):

    """
    special contract to create an instance of native contract
    instance refers to instance in the BC.

    msg.data[:4] defines the native contract
    msg.data[4:] is sent as data to the new contract

    call with last 4 bytes of the address of the contract for which an instance should be created.
    i.e.  msg.data = ContractClass.address[-4:]

    called by _apply_msg
        value was added to this contract (needs to be moved)
    """

    address = utils.int_to_addr(1024)

    def _safe_call(self):
        log.debug('create native contract instance called')
        assert len(self._msg.sender) == 20
        assert len(self._msg.data.extract_all()) >= 4

        # get native contract
        nc_address = registry.native_contract_address_prefix + self._msg.data.extract_all()[:4]
        if nc_address not in registry:
            return 0, self._msg.gas, b''
        native_contract = registry[nc_address].im_self

        # get new contract address
        if self._ext.tx_origin != self._msg.sender:
            self._ext._block.increment_nonce(self._msg.sender)
        nonce = utils.encode_int(self._ext._block.get_nonce(self._msg.sender) - 1)
        self._msg.to = registry.mk_instance_address(native_contract, self._msg.sender, nonce)
        assert not self._ext.get_balance(self._msg.to)  # must be none existant

        # value was initially added to this contract's address, we need to transfer
        success = self._ext._block.transfer_value(self.address, self._msg.to, self._msg.value)
        assert success
        assert not self._ext.get_balance(self.address)

        # call new instance with additional data
        self._msg.is_create = True
        self._msg.data = vm.CallData(self._msg.data.data[4:], 0, 0)
        res, gas, dat = registry[self._msg.to](self._ext, self._msg)
        assert gas >= 0
        log.debug('created native contract instance', template=nc_address.encode('hex'),
                  instance=self._msg.to.encode('hex'))
        return res, gas, memoryview(self._msg.to).tolist()


registry.register(CreateNativeContractInstance)


#   helper to de/encode method calls

_abi_decode_single_orig = abi.decode_single


def _abi_decode_single_patch(typ, val):
    r = _abi_decode_single_orig(typ, val)
    if typ[0] == 'address':
        assert len(r) in (0, 40)
        r = r.decode('hex')
    return r

abi.decode_single = _abi_decode_single_patch


def abi_encode_args(method, args):
    "encode args for method: method_id|data"
    assert issubclass(method.im_class, NativeABIContract), method.im_class
    m_abi = method.im_class._get_method_abi(method)
    return zpad(encode_int(m_abi['id']), 4) + abi.encode_abi(m_abi['arg_types'], args)


def abi_decode_args(method, data):
    # data is payload w/o method_id
    assert issubclass(method.im_class, NativeABIContract), method.im_class
    arg_types = method.im_class._get_method_abi(method)['arg_types']
    return abi.decode_abi(arg_types, data)


def abi_encode_return_vals(method, vals):
    assert issubclass(method.im_class, NativeABIContract)
    return_types = method.im_class._get_method_abi(method)['return_types']
    # encode return value to list
    if isinstance(return_types, list):
        assert isinstance(vals, (list, tuple)) and len(vals) == len(return_types)
    elif vals is None:
        assert return_types is None
        return ''
    else:
        vals = (vals, )
        return_types = (return_types, )
    return abi.encode_abi(return_types, vals)


def abi_decode_return_vals(method, data):
    assert issubclass(method.im_class, NativeABIContract)
    return_types = method.im_class._get_method_abi(method)['return_types']
    if not len(data):
        if return_types is None:
            return None
        return b''
    elif not isinstance(return_types, (list, tuple)):
        return abi.decode_abi((return_types, ), data)[0]
    else:
        return abi.decode_abi(return_types, data)


def constant(f):
    """
    decorator to mark methods as constant
    """
    f.is_constant = True
    return f


class NativeABIContract(NativeContractBase):

    """
    public method must have a signature describing
    - the arguments with their types
    - the return value

    The 'returns' keyword arg indicates, that this is a public abi method

    def afunc(ctx, a='uint16', b='uint16', returns='uint32'):
        return a + b

    The special method NativeABIContract is the constructor
    which is run during creation of the contract and cannot be called afterwards.

    For constant methods, mark them with the @constant decorator
    """

    events = []
    __isfrozen = False

    def __init__(self, ext, msg):
        super(NativeABIContract, self).__init__(ext, msg)

        # copy special variables
        self.msg_data = msg.data.extract_all()
        self.msg_sender = msg.sender
        self.msg_depth = msg.depth  # public?
        self.msg_gas = property(lambda: self._gas)
        self.msg_value = msg.value

        self.tx_gasprice = ext.tx_gasprice
        self.tx_origin = ext.tx_origin

        self.block_coinbase = ext.block_coinbase
        self.block_timestamp = ext.block_timestamp
        self.now = ext.block_timestamp

        self.block_difficulty = ext.block_difficulty
        self.block_number = ext.block_number
        self.block_gaslimit = ext.block_gas_limit

        self.address = msg.to
        self.get_balance = ext.get_balance
        self.get_block_hash = ext.block_hash

        if self.block_number > 0:
            self.block_prevhash = self.get_block_hash(self.block_number - 1)
        else:
            self.block_prevhash = '\0' * 32

        # setup events as callable methods on contract
        def mk_event_method(ctx, evt):
            def m(*args):
                return evt(ctx, *args)
            return m

        for evt in self.events:
            assert issubclass(evt, ABIEvent)
            name = evt.__name__
            assert not hasattr(self, name), 'event name %s collides with member' % name
            setattr(self, name, mk_event_method(self, evt))

        self.__isfrozen = True

    @property
    def balance(self):  # can change during subcalls
        return self.get_balance(self.address)

    def suicide(self, address):
        assert isinstance(address, bytes) and len(address) == 20
        self._ext.set_balance(address, self.get_balance(address) + self.balance)
        self._ext.set_balance(self.address, 0)
        self._ext.add_suicide(self.address)

    def call(self, to, data='', **kargs):
        assert set(kargs.keys()).issubset(set(('value',)))
        value = kargs.get('value', 0)
        data = vm.CallData(memoryview(data).tolist())
        msg = vm.Message(self.address, to, value, self.gas, data,
                         self.msg_depth + 1, code_address=to)
        success, self.gas, out = self._ext.msg(msg)
        assert success  # FIXME
        return ''.join(chr(x) for x in out)

    def call_abi(self, to, abi_contract_method, *args, **kargs):
        data = abi_encode_args(abi_contract_method, args)
        out = self.call(to, data=data, **kargs)
        return abi_decode_return_vals(abi_contract_method, out)

    @classmethod
    def _get_method_abi(cls, method):
        m_as = inspect.getargspec(method)
        arg_names = list(m_as.args)[1:]
        if 'returns' not in arg_names:  # indicates, this is an abi method
            return None
        arg_types = list(m_as.defaults)
        assert len(arg_names) == len(arg_types) == len(set(arg_names))
        assert arg_names.pop() == 'returns'  # must be last element
        return_types = arg_types.pop()  # can be list or multiple
        name = method.__func__.func_name
        assert not name.startswith('_')
        m_id = abi.method_id(name, arg_types)
        return dict(id=m_id, arg_types=arg_types, arg_names=arg_names, return_types=return_types,
                    name=name, method=method)

    @classmethod
    def json_abi(cls):
        contract_abi = []
        # add methods
        for m in cls._abi_methods():
            m_abi = cls._get_method_abi(m)
            d = dict(constant=getattr(m, 'is_constant', False),
                     name=m.__name__, type='function', inputs=[], outputs=[])
            for name, typ in zip(m_abi['arg_names'], m_abi['arg_types']):
                d['inputs'].append(dict(name=name, type=typ))
            return_types = m_abi['return_types']
            if not isinstance(return_types, list):
                return_types = [return_types]
            for i, typ in enumerate(return_types):
                if typ is not None:
                    d['outputs'].append(dict(name='z{}'.format(i), type=typ))
            contract_abi.append(d)
        # add events
        for evt in cls.events:
            contract_abi.append(dict(type='event', name=evt.__name__, inputs=evt.args))
        return contract_abi

    abi = json_abi

    @classmethod
    def _abi_methods(cls):
        methods = []
        for name in dir(cls):
            method = getattr(cls, name)
            if inspect.ismethod(method):
                if cls._get_method_abi(method):
                    methods.append(method)
        return methods

    @classmethod
    def _find_method(cls, method_id):
        for method in cls._abi_methods():
            m_abi = cls._get_method_abi(method)
            if m_abi and m_abi['id'] == method_id:
                return m_abi

    def default_method(self):
        """
        method which gets called by default if no other method is found
        note: this is no abi method and must make sense from self.msg_data
        """
        return 1, self.gas, []

    def _safe_call(self):
        calldata = self._msg.data.extract_all()
        # get method
        m_id = big_endian_to_int(calldata[:4])  # first 4 bytes encode method_id
        m_abi = self._find_method(m_id)
        if not m_abi:  # 404 method not found
            log.warn('method not found, calling default', methodid=m_id)
            return 1, self.gas, []  # no default methods supported
        # decode abi args
        args = abi.decode_abi(m_abi['arg_types'], calldata[4:])
        # call (unbound) method
        method = m_abi['method']
        log.debug('calling', method=method.__name__, _args=args)
        try:
            res = method(self, *args)
        except RuntimeError as e:
            log.warn("error in method", method=method.__name__, error=e)
            return 0, self.gas, []
        log.debug('call returned', result=res)
        return 1, self.gas, memoryview(abi_encode_return_vals(method, res)).tolist()

    def __setattr__(self, key, value):
        "protect users from abusing properties"
        if self.__isfrozen and not hasattr(self, key):
            raise TypeError("%r must not be extended" % self)
        object.__setattr__(self, key, value)


class ABIEvent(object):

    """
    ABIEvents must implementa function called abi, which defines
    the canonical typ of the data and whether it is indexed or not.
    https://github.com/ethereum/wiki/wiki/Ethereum-Contract-ABI#events

    class Shout(nc.ABIEvent):
        args = [dict(name='a', type='utint16', indexed=True), ...]
    """

    args = []

    @classmethod
    def arg_types(cls):
        return [a['type'] for a in cls.args]

    @classmethod
    def arg_names(cls):
        return [a['name'] for a in cls.args]

    @classmethod
    def event_id(cls):
        return abi.event_id(cls.__name__, cls.arg_types())

    def __init__(self, ctx, *args):
        assert isinstance(ctx, NativeABIContract)
        assert len(self.args) == len(args), \
            "%s called with wrong number of args" % self.__class__.__name__

        # topic0 sha3(EventName + signature)
        topics = [self.event_id()]

        indexed_args = []
        non_indexed_args = []
        for val, arg in zip(args, self.args):
            if arg['indexed']:
                indexed_args.append((arg['type'], val))
            else:
                non_indexed_args.append((arg['type'], val))

        assert len(indexed_args) <= 3
        # topics 1-n
        for typ, val in indexed_args:
            topics.append(big_endian_to_int(abi.encode_abi([typ], [val])))
        # remaining non indexed data
        data = abi.encode_abi([a[0] for a in non_indexed_args], [a[1] for a in non_indexed_args])

        # add log
        ctx._ext.log(ctx.address, topics, data)

    @classmethod
    def listen(cls, log_, address=None, callback=None):
        if not len(log_.topics) or log_.topics[0] != cls.event_id():
            return
        if address and address != log_.address:
            return
        # o = dict(address=log_.address)
        o = dict()
        for i, t in enumerate(log_.topics[1:]):
            name = cls.args[i]['name']
            if cls.arg_types()[i] in ('string', 'bytes'):
                assert t < 2 ** 256, "error with {}, user bytes32".format(cls.args[i])
                d = encode_int(t)
            else:
                assert t < 2 ** 256
                d = zpad(encode_int(t), 32)
            data = abi.decode_abi([cls.arg_types()[i]], d)[0]
            o[name] = data
        o['event_type'] = cls.__name__
        unindexed_types = [a['type'] for a in cls.args if not a['indexed']]
        o['args'] = abi.decode_abi(unindexed_types, log_.data)
        if callback:
            callback(o)
        else:
            print(o)


#  Tester helpers #####################################

def listen_logs(state, event, address=None, callback=None):
    state.block.log_listeners.append(lambda l: event.listen(l, address, callback))


def tester_call_method(state, sender, method, *args):
    data = abi_encode_args(method, args)
    to = method.im_class.address
    r = state._send(sender, to, value=0, evmdata=data)['output']
    return abi_decode_return_vals(method, r)


def tester_nac(state, sender, address, value=0):
    "create an object which acts as a proxy for the contract on tester"
    klass = registry[address].im_self
    assert issubclass(klass, NativeABIContract)

    def mk_method(method):
        def m(s, *args):
            data = abi_encode_args(method, args)
            r = state._send(sender, address, value=value, evmdata=data)['output']
            return abi_decode_return_vals(method, r)
        return m

    class cproxy(object):
        pass
    for m in klass._abi_methods():
        setattr(cproxy, m.__func__.func_name, mk_method(m))

    return cproxy()


def test_call(block, sender, to, data='', gasprice=0, value=0):
    state_root_before = block.state_root
    assert block.has_parent()
    # rebuild block state before finalization
    parent = block.get_parent()
    test_block = block.init_from_parent(parent, block.coinbase,
                                        timestamp=block.timestamp)
    for _tx in block.get_transactions():
        success, output = processblock.apply_transaction(test_block, _tx)
        assert success
    # apply transaction
    startgas = block.gas_limit - block.gas_used
    gasprice = 0
    nonce = test_block.get_nonce(sender)
    tx = Transaction(nonce, gasprice, startgas, to, value, data)
    tx.sender = sender

    try:
        success, output = processblock.apply_transaction(test_block, tx)
    except processblock.InvalidTransaction as e:
        success = False
    assert block.state_root == state_root_before
    if success:
        return output
    else:
        log.debug('test_call failed', error=e)
        return None


def chain_nac_proxy(chain, sender, contract_address, value=0):
    "create an object which acts as a proxy for the contract on the chain"
    klass = registry[contract_address].im_self
    assert issubclass(klass, NativeABIContract)

    def mk_method(method):
        def m(s, *args):
            data = abi_encode_args(method, args)
            block = chain.head_candidate
            output = test_call(block, sender, contract_address, data)
            if output is not None:
                return abi_decode_return_vals(method, output)
        return m

    class cproxy(object):
        pass
    for m in klass._abi_methods():
        setattr(cproxy, m.__func__.func_name, mk_method(m))

    return cproxy()


def tester_create_native_contract_instance(state, sender, contract, value=0):
    assert issubclass(contract, NativeContractBase)
    assert NativeABIContract.address in registry
    # last 4 bytes of address are used to reference the contract
    data = contract.address[-4:]
    r = state._send(sender, CreateNativeContractInstance.address, value, data)
    return r['output']


# Typed Storage for Contracts


class TypedStorage(object):

    _prefix = b''
    _value_type = ''
    _set = None
    _get = None

    _valid_types = ['address', 'string', 'bytes', 'binary']
    _valid_types += ['int%d' % (i * 8) for i in range(1, 33)]
    _valid_types += ['uint%d' % (i * 8) for i in range(1, 33)]

    def __init__(self, value_type):
        self._value_type = value_type
        # allow nested types
        assert isinstance(value_type, TypedStorage) or value_type in self._valid_types

    def setup(self, prefix, getter, setter):
        assert isinstance(prefix, bytes)
        self._prefix = prefix
        self._set = setter
        self._get = getter

    @classmethod
    def _db_decode_type(cls, value_type, data):
        if value_type in ('string', 'bytes', 'binary'):
            return int_to_big_endian(data)
        if value_type == 'address':
            return zpad(int_to_big_endian(data), 20)
        return abi.decode_abi([value_type], zpad(int_to_big_endian(data), 32))[0]

    @classmethod
    def _db_encode_type(cls, value_type, val):
        if value_type in ('string', 'bytes', 'binary', 'address'):
            assert len(val) <= 32
            assert isinstance(val, bytes)
            return big_endian_to_int(val)
        data = abi.encode_abi([value_type], [val])
        assert len(data) <= 32
        return big_endian_to_int(data)

    def _key(self, k):
        assert isinstance(k, bytes)
        k = zpad(k, 32)
        return utils.sha3(b'%s:%s' % (self._prefix, k))

    def set(self, k=b'', v=None, value_type=None):
        assert v is not None
        value_type = value_type or self._value_type

        if isinstance(self, Struct):
            if k in self._nested_types.keys():
                if isinstance(self._nested_types[k], Scalar):
                    value_type = self._nested_types[k]
                elif isinstance(self._nested_types[k], TypedStorage):  # nested type
                    # dummy call to mark storage
                    value_type = 'uint16'
        if isinstance(value_type, Scalar):
            ts = value_type.__class__(value_type._value_type)
            # dummy call to mark storage
            value_type = 'uint16'

            def _set(ts_k, v):
                if not self._get(self._key(k)):
                    self.markstorage(k)
                self._set(ts_k, v)
            ts.setup(self._key(k), self._get, _set)
            ts.set('Scalar', v)
            return
        if isinstance(value_type, TypedStorage):  # nested type
            # dummy call to mark storage
            value_type = 'uint16'
        # log.DEV('setting', cls=self.__class__, k=k, v=v)
        v_ = self._db_encode_type(value_type, v)
        self._set(self._key(k), v_)

    def get(self, k=b'', value_type=None):
        value_type = value_type or self._value_type
        if isinstance(value_type, TypedStorage):  # nested types
            # create new instance
            if isinstance(value_type, Struct):
                # use prototyping here in order to reproduce the complex internal structure
                ts = deepcopy(value_type)
            else:
                ts = value_type.__class__(value_type._value_type)

            def _set(ts_k, v):
                if not self._get(self._key(k)):
                    self.markstorage(k)
                self._set(ts_k, v)
            ts.setup(self._key(k), self._get, _set)
            if isinstance(value_type, Scalar):
                return ts.get('Scalar')
            return ts
        if isinstance(self, Struct):
            if k in self._nested_types.keys():
                return self._nested_types[k]
        r = self._db_decode_type(value_type, self._get(self._key(k)))
        return r

    def markstorage(self, k):
        pass


class Scalar(TypedStorage):
    pass


class List(TypedStorage):

    def __getitem__(self, i):
        assert isinstance(i, (int, long))
        return self.get(bytes(i))

    def __setitem__(self, i, v):
        i = int(i)
        assert isinstance(i, (int, long))
        if isinstance(self._value_type, Scalar):
            if type(v).__name__ not in self._value_type._value_type:
                raise TypeError("Value must be of a type " + self._value_type._value_type +
                                ". Provided value of a type " + type(v).__name__ + " instead.")
        else:
            if type(v).__name__ not in self._value_type:
                raise TypeError("Value must be of a type " + self._value_type +
                                ". Provided value of a type " + type(v).__name__ + " instead.")
        self.set(bytes(i), v)
        self.updatelen(i, v)

    def updatelen(self, i, v):
        if i >= len(self):
            self.set(b'__len__', i + 1, value_type='uint32')

    def markstorage(self, i):
        i = int(i)
        assert isinstance(i, (int, long))
        self.set(bytes(i), 1, 'uint16')  # set dummy to indicate, that there is an object
        self.updatelen(i, 1)

    def __len__(self):
        return self.get(b'__len__', value_type='uint32')

    def append(self, v):
        self[len(self)] = v

    def __contains__(self, idx):
        raise NotImplementedError()

    def __iter__(self):
        return (self[i] for i in range(len(self)))


class Dict(List):

    def __getitem__(self, k):
        assert isinstance(k, bytes), k
        return self.get(k)

    def __setitem__(self, k, v):
        assert isinstance(k, bytes)
        self.set(k, v)

    def markstorage(self, k):
        assert isinstance(k, bytes)
        self.set(k, 1, 'uint16')  # set dummy to indicate, that there is an object

    def __contains__(self, k):
        raise NotImplementedError('unset keys return zero as a default')

    def __len__(self):
        raise NotImplementedError('no len of dict available, use IterableDict')


class IterableDict(Dict):

    "Note, don't use this for a high number of keys, because it does not clean them up on deletion"

    _counter_prefix = '__counter_prefix:{}'

    def __getitem__(self, k):
        assert isinstance(k, bytes)
        assert bytes(k) != bytes(0)
        return self.get(k)

    def _ckey(self, idx):
        assert isinstance(idx, int)
        return self._counter_prefix.format(idx)

    def __setitem__(self, k, v):
        assert isinstance(k, bytes)
        assert bytes(k) != bytes(0)
        self.updatelen(k)
        self.set(k, v)

    def updatelen(self, k):
        if not self.get(k):
            i = self.get(b'__len__', value_type='uint32')
            self.set(self._ckey(i), k, value_type='bytes')
            self.set(b'__len__', i + 1, value_type='uint32')

    def markstorage(self, k):
        assert isinstance(k, bytes)
        assert bytes(k) != bytes(0)
        self.updatelen(k)
        self.set(k, 1, 'uint16')  # set dummy to indicate, that there is an object

    def __contains__(self, idx):
        raise NotImplementedError()

    def keys(self):
        return (k for k, v in self.items())

    def values(self):
        return (v for k, v in self.items())

    def items(self):
        _len = self.get(b'__len__', value_type='uint32')
        keys = set(self.get(self._ckey(i), value_type='bytes') for i in range(_len))
        items = ((k, self.get(k)) for k in keys)
        valid = list((k, v) for k, v in items if v)
        # log.DEV('in items', len=_len, keys=list(keys), valid=list(valid), items=list(items))
        return valid

    __iter__ = keys

    def __len__(self):
        return sum(1 for k in self.keys())


class Struct(TypedStorage):

    _counter_prefix = '__counter_prefix:{}'
    _nested_types = dict()

    def __init__(self, **kwargs):
        super(Struct, self).__init__('uint16')
        self._nested_types = kwargs.copy()

    def __getattribute__(self, k, *default):
        try:
            superattr = object.__getattribute__(self, k)
            return superattr
        except AttributeError:
            pass

        r = 0
        # the method may be called before setup so check
        if self._get:
            r = self.get(k)
        if r == 0:
            if len(default) > 0:
                return default[0]
            raise AttributeError(k)
        if isinstance(r, Scalar):
            return r.get('Scalar')
        return r

    def _ckey(self, idx):
        assert isinstance(idx, int)
        return self._counter_prefix.format(idx)

    def __setattr__(self, k, v):
        assert isinstance(k, bytes)
        assert bytes(k) != bytes(0)

        if k in dir(self):
            # TODO: think of a protection for the injection hack here
            return super(Struct, self).__setattr__(k, v)
        if not self.get(k):
            i = self.get(b'__len__', value_type='uint32')
            self.set(self._ckey(i), k, value_type='bytes')
            self.set(b'__len__', i + 1, value_type='uint32')
        self.set(k, v)

    def setup(self, prefix, getter, setter):
        assert isinstance(prefix, bytes)
        super(Struct, self).setup(prefix, getter, setter)
        for k, ts in self._nested_types.iteritems():
            ts.setup(self._key(k), getter, setter)


class TypedStorageContract(NativeContractBase):

    """
    class MyContract(TypedStorageContract):
        a = nc.Scalar('uint32')
        b = nc.List('uint16')
        c = nc.Dict('uint32')

        def afunc(ctx):
            if not ctx.a:
                ctx.a = 2
            assert ctx.a == 2

            ctx.b[9] = 1
            assert len(ctx.b) >= 10
            l = len(ctx.b)
            ctx.b.append(20)
            assert len(ctx.b) == l + 1
    """
    storage = dict()

    def __init__(self, ext, msg):
        super(TypedStorageContract, self).__init__(ext, msg)
        self._prepare_storage(self._get_storage_data, self._set_storage_data)

    def _prepare_storage(self, get_storage_data, set_storage_data):

        # move TypedStorage members to _protected (so we can reinitialize them later).
        def slots():
            return [(k, getattr(self.__class__, k)) for k in dir(self.__class__)
                    if isinstance(getattr(self.__class__, k), TypedStorage)]

        # log.DEV('preparing storage', klass=self.__class__, slots=slots())
        for k, ts in slots():
            if not k.startswith('_'):
                setattr(self.__class__, '_' + k, ts)
                try:
                    delattr(self.__class__, k)
                except AttributeError:
                    pass  # from parent class

        # create members (on each invocation!)
        for k, ts in [(k, ts) for k, ts in slots() if k.startswith('_')]:
            assert k.startswith('_')
            k = k[1:]
            ts.setup(k, get_storage_data, set_storage_data)
            if isinstance(ts, (List, Dict, Struct)):
                setattr(self, k, ts)
            else:
                assert isinstance(ts, Scalar)

                def _mk_property(skalar):
                    # log.DEV('creating property for', klass=self.__class__, k=k, skalar=skalar)
                    return property(lambda s: skalar.get(), lambda s, v: skalar.set(v=v))
                setattr(self.__class__, k, _mk_property(ts))


# The NativeContract Class ###################

class NativeContract(NativeABIContract, TypedStorageContract):
    pass

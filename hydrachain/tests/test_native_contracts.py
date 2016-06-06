import random
import string

import pytest
from ethereum import abi
from ethereum import tester
from ethereum import utils
from ethereum.utils import zpad
import logging
import random
import string

from hydrachain import native_contracts as nc

logging.NOTSET = logging.INFO

"""
test registration

test calling

test creation, how to do it in tester?
"""


class EchoContract(nc.NativeContractBase):
    address = utils.int_to_addr(2000)

    def _safe_call(self):
        res, gas, data = 1, self._msg.gas, self._msg.data.data
        return res, gas, data


def test_registry():
    reg = nc.registry
    assert tester.a0 not in reg

    nc.registry.register(EchoContract)
    assert issubclass(nc.registry[EchoContract.address].im_self, EchoContract)
    nc.registry.unregister(EchoContract)


def test_echo_contract():
    nc.registry.register(EchoContract)
    s = tester.state()
    testdata = 'hello'
    r = s._send(tester.k0, EchoContract.address, 0, testdata)
    assert r['output'] == testdata
    nc.registry.unregister(EchoContract)


def test_native_contract_instances():
    nc.registry.register(EchoContract)

    s = tester.state()
    value = 100
    create = nc.tester_create_native_contract_instance
    eci_address = create(s, tester.k0, EchoContract, value)

    assert len(eci_address) == 20
    # expect that value was transfered to the new contract
    assert s.block.get_balance(eci_address) == value
    assert s.block.get_balance(nc.CreateNativeContractInstance.address) == 0

    # test the new contract
    data = 'hello'
    r = s.send(tester.k0, eci_address, 0, data)
    assert r == data
    nc.registry.unregister(EchoContract)


# noinspection PyMethodParameters
class SampleNAC(nc.NativeABIContract):
    address = utils.int_to_addr(2001)

    def initialize(ctx, a='int8', c='bool', d='uint8[]'):
        "Constructor (can a constructor return anything?)"

    def afunc(ctx, a='uint16', b='uint16', returns='uint16'):
        return a * b

    def bfunc(ctx, a='uint16', returns='uint16'):
        return ctx.afunc(a, 2)  # direct native call

    def cfunc(ctx, a='uint16', returns=['uint16', 'uint16']):
        return a, a  # returns tuple

    def ccfunc(ctx, a='uint16', returns=['uint16']):
        return [a]

    def dfunc(ctx, a='uint16[2]', returns='uint16'):  # FAILS
        return a[0] * a[1]

    def efunc(ctx, a='uint16[]', returns='uint16'):
        return a[0] * a[1]

    def ffunc(ctx, returns='uint16[2]'):
        return [1, 2]

    def ffunc2(ctx, returns=['uint16[2]']):
        return [[1, 2]]

    def gfunc(ctx, returns='address[]'):
        return ['\x00' * 20] * 3

    def void_func(ctx, a='uint16', returns=None):
        return

    def noargs_func(ctx, returns='uint16'):
        return 42

    def add_property(ctx, returns=None):
        ctx.dummy = True  # must fail

    def special_vars(ctx, returns=None):
        def _is_address(a):
            return isinstance(a, bytes) and len(a) == 20

        assert ctx.msg_data
        assert _is_address(ctx.msg_sender)
        assert ctx.msg_value == 0
        assert ctx.tx_gasprice
        assert _is_address(ctx.tx_origin)
        assert _is_address(ctx.block_coinbase)
        assert ctx.block_difficulty
        assert ctx.block_number == 0
        assert ctx.block_gaslimit
        assert 0 == ctx.get_balance(ctx.address)
        assert _is_address(ctx.address)
        assert ctx.balance == 0
        assert ctx.balance == ctx.get_balance(ctx.address)
        if ctx.block_number > 0:
            assert ctx.get_block_hash(ctx.block_number - 1) == ctx.block_prevhash

    def test_suicide(ctx, returns=None):
        ctx.suicide(ctx.block_coinbase)

    def get_address(ctx, returns='string'):
        return ctx.address


def test_nac_tester():
    assert issubclass(SampleNAC.afunc.im_class, SampleNAC)
    state = tester.state()
    nc.registry.register(SampleNAC)
    sender = tester.k0

    assert 12 == nc.tester_call_method(state, sender, SampleNAC.afunc, 3, 4)
    print
    # FIXME fails
    # assert 30 == nc.tester_call_method(state, sender, SampleNAC.dfunc, [5, 6])
    assert ['\0' * 20] * 3 == nc.tester_call_method(state, sender, SampleNAC.gfunc)
    assert 30 == nc.tester_call_method(state, sender, SampleNAC.efunc, [5, 6])
    assert 26 == nc.tester_call_method(state, sender, SampleNAC.bfunc, 13)

    # FIXME THIS IS STILL BROKEN
    # assert [1, 2] == nc.tester_call_method(state, sender, SampleNAC.ffunc)
    # assert [1, 2] == nc.tester_call_method(state, sender, SampleNAC.ffunc2)

    assert 4, 4 == nc.tester_call_method(state, sender, SampleNAC.cfunc, 4)
    assert [4] == nc.tester_call_method(state, sender, SampleNAC.ccfunc, 4)

    assert 42 == nc.tester_call_method(state, sender, SampleNAC.noargs_func)
    assert None is nc.tester_call_method(state, sender, SampleNAC.void_func, 3)
    assert None is nc.tester_call_method(state, sender, SampleNAC.special_vars)
    # values out of range must fail
    with pytest.raises(abi.EncodingError):
        nc.tester_call_method(state, sender, SampleNAC.bfunc, -1)

    with pytest.raises(tester.TransactionFailed):
        nc.tester_call_method(state, sender, SampleNAC.afunc, 2 ** 15, 2)

    with pytest.raises(abi.EncodingError):
        nc.tester_call_method(state, sender, SampleNAC.afunc, [1], 2)
    nc.registry.unregister(SampleNAC)


def test_nac_suicide():
    state = tester.state()
    nc.registry.register(SampleNAC)
    sender = tester.k0
    state._send(sender, SampleNAC.address, value=100)
    assert state.block.get_balance(SampleNAC.address) == 100
    assert None is nc.tester_call_method(state, sender, SampleNAC.test_suicide)
    assert state.block.get_balance(SampleNAC.address) == 0
    nc.registry.unregister(SampleNAC)


def test_nac_add_property_fail():
    state = tester.state()
    nc.registry.register(SampleNAC)
    sender = tester.k0
    try:
        nc.tester_call_method(state, sender, SampleNAC.add_property)
    except tester.TransactionFailed:
        pass
    else:
        assert False, 'properties must not be createable'
    nc.registry.unregister(SampleNAC)


def test_nac_instances():
    # create multiple nac instances and assert they are different contracts
    state = tester.state()
    nc.registry.register(SampleNAC)

    a0 = nc.tester_create_native_contract_instance(state, tester.k0, SampleNAC)
    a1 = nc.tester_create_native_contract_instance(state, tester.k0, SampleNAC)
    a2 = nc.tester_create_native_contract_instance(state, tester.k0, SampleNAC)

    assert a0 != a1 != a2
    assert len(a0) == 20

    # create proxies
    c0 = nc.tester_nac(state, tester.k0, a0)
    c1 = nc.tester_nac(state, tester.k0, a1)
    c2 = nc.tester_nac(state, tester.k0, a2)

    assert c0.get_address() == a0
    assert c1.get_address() == a1
    assert c2.get_address() == a2

    assert c0.afunc(5, 6) == 30
    assert c0.efunc([4, 8]) == 32
    nc.registry.unregister(SampleNAC)


# ## Events #########################

class Shout(nc.ABIEvent):
    args = [dict(name='a', type='uint16', indexed=True),
            dict(name='b', type='uint16', indexed=False),
            dict(name='c', type='uint16', indexed=False),
            ]


class EventNAC(nc.NativeABIContract):
    address = utils.int_to_addr(2005)
    events = [Shout]

    def afunc(ctx, a='uint16', b='uint16', returns=None):
        ctx.Shout(a, b, 3)


def test_events():
    # create multiple nac instances and assert they are different contracts
    state = tester.state()
    nc.registry.register(EventNAC)

    # create proxies
    nc.listen_logs(state, Shout)
    c0 = nc.tester_nac(state, tester.k0, EventNAC.address)
    c0.afunc(1, 2)


# ## json abi ##############################

def test_jsonabi():
    print EventNAC.json_abi()


# ## Storage ###############


def test_typed_storage():

    def randomword(length):
        return ''.join(random.choice(string.lowercase) for i in range(length))

    types = nc.TypedStorage._valid_types
    random.seed(1)  # a hardcoded seed to make the test deterministic

    for t in types:
        ts = nc.TypedStorage(t)
        td = dict()
        randomprefix = randomword(random.randint(1, 10))
        randomkey = randomword(random.randint(1, 50))
        ts.setup(randomprefix, td.get, td.__setitem__)
        if t == 'address':
            address = utils.int_to_addr(random.randint(0, 0xFFFFFFFF))
            ts.set(randomkey, address, t)
            assert ts.get(randomkey, t) == address
        elif t == 'string' or t == 'bytes' or t == 'binary':
            word = randomword(10)
            ts.set(randomkey, word, t)
            assert ts.get(randomkey, t) == word
        elif 'uint' in t:
            size = int(t[4:])
            v = random.randint(0, 2 ** size - 1)
            ts.set(randomkey, v, t)
            assert ts.get(randomkey, t) == v
        elif 'int' in t:
            size = int(t[3:])
            v = random.randint(0, 2 ** (size - 2) - 1)
            ts.set(randomkey, v, t)
            assert ts.get(randomkey, t) == v
        else:
            pass


def test_typed_storage_contract():

    class TestTSC(nc.TypedStorageContract):

        address = utils.int_to_addr(2050)
        a = nc.Scalar('uint32')
        b = nc.List('uint16')
        c = nc.Dict('uint32')
        d = nc.IterableDict('uint256')
        e = nc.IterableDict('string')

        def _safe_call(ctx):
            # skalar
            assert ctx.a == 0
            ctx.a = 1
            assert ctx.a == 1

            ctx.a = 2
            assert ctx.a == 2

            # list
            assert isinstance(ctx.b, nc.List)
            ctx.b[0] = 10
            assert ctx.b[0] == 10

            ctx.b[1000] = 12
            assert ctx.b[1000] == 12

            assert len(ctx.b) == 1001
            ctx.b[1000] = 66
            assert ctx.b[1000] == 66
            assert len(ctx.b) == 1001

            ctx.b.append(99)
            assert len(ctx.b) == 1002
            ctx.b.append(99)
            assert len(ctx.b) == 1003

            # mapping
            assert isinstance(ctx.c, nc.Dict)
            key = b'test'
            assert ctx.c[key] == 0
            ctx.c[key] = 33
            assert ctx.c[key] == 33
            ctx.c[key] = 66
            assert ctx.c[key] == 66

            k = '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x17q'
            v = 2146209080

            ctx.c[k] = v
            assert ctx.c[k] == v

            # iterable dict

            ctx.d[k] = v
            assert len(ctx.d) == 1
            assert ctx.d[k] == v
            ctx.d[k] = 0

            N = 10
            for i in range(1, N + 1):
                v = i ** 2
                k = bytes(i)
                ctx.d[k] = v
                assert ctx.d[k] == v
                assert len(list(ctx.d.keys())) == i
                assert set(ctx.d.keys()) == set([bytes(j) for j in range(1, i + 1)])
                assert set(ctx.d.values()) == set([j ** 2 for j in range(1, i + 1)])

            # iterable dict with strings
            N = 10
            for i in range(1, N + 1):
                v = str(i ** 2)
                k = bytes(i)
                ctx.e[k] = v
                # log.DEV('kv', k=k, v=v)
                assert ctx.e[k] == v, ctx.e[k]
                assert len(list(ctx.e.keys())) == i
                assert set(ctx.e.keys()) == set([bytes(j) for j in range(1, i + 1)])
                assert set(ctx.e.values()) == set([str(j ** 2) for j in range(1, i + 1)])

            print list(ctx.e.keys())
            print list(ctx.e.values())
            print len(list(ctx.e.keys()))

            return 1, 1, []

    nc.registry.register(TestTSC)
    s = tester.state()
    s._send(tester.k0, TestTSC.address, 0)
    nc.registry.unregister(TestTSC)


def test_nested_typed_storage_list_in_dict():

    # the storage cannot be defined globally as the calls would interfere
    td = dict()

    def _get(k):
        if k not in td:
            td[k] = 0
        return td[k]

    def _set(k, v):
        td[k] = v

    a = nc.Dict(nc.List('uint16'))
    b = nc.List('uint32')

    a.setup(b'a', _get, _set)
    b.setup(b'b', _get, _set)

    b.append(10)

    # list nested in dict
    assert isinstance(a, nc.Dict)
    key = b'test'
    idx = 0
    l = a[key]
    assert isinstance(l, nc.List)  # initialized with list
    with pytest.raises(NotImplementedError):
        assert len(a) == 0
    assert len(l) == 0

    a[key][idx] = 33
    assert l[idx] == 33
    assert len(a[key]) == 1
    assert len(l) == 1
    assert a[key][idx] == 33
    a[key][idx] = 66
    assert len(l) == 1
    assert a[key][idx] == 66
    a[key][idx + 1] = 67
    assert len(l) == 2

    for i in range(65500, 66000):
        l[i] = 1
        l[i % 100] = 2
        l[i % 300] = 3
        assert len(l) == i + 1

    # second key

    key = b'test2'
    l = a[key]
    assert isinstance(l, nc.List)  # initialized with list
    assert len(l) == 0
    a[key][idx] = 0


def test_nested_typed_storage_dict():

    td = dict()

    def _get(k):
        if k not in td:
            td[k] = 0
        return td[k]

    def _set(k, v):
        td[k] = v

    b = nc.Dict(nc.Dict('uint16'))
    d = nc.List('uint16')

    b.setup(b'b', _get, _set)
    d.setup(b'd', _get, _set)

    # nested dicts

    da = b['A']
    assert isinstance(da, nc.Dict)
    assert da['B'] == 0
    assert b['C']['D'] == 0

    b['A']['B'] = 12
    assert b['A']['B'] == 12

    assert da['B'] == 12

    # test list
    assert d[2] == 0
    d[2] = 1


def test_nested_typed_storage_list():

    td = dict()

    def _get(k):
        if k not in td:
            td[k] = 0
        return td[k]

    def _set(k, v):
        td[k] = v

    c = nc.List(nc.Dict('uint16'))
    d = nc.List('uint16')
    l = nc.List(nc.List('uint16'))
    m = nc.List(nc.List('uint16'))
    n = nc.List(nc.Scalar('string'))

    c.setup(b'c', _get, _set)
    d.setup(b'd', _get, _set)
    l.setup(b'l', _get, _set)
    m.setup(b'm', _get, _set)
    n.setup(b'n', _get, _set)

    # test list
    assert d[2] == 0
    d[2] = 1

    # nested in lists

    la = c[3]
    assert isinstance(la, nc.Dict)
    assert len(c) == 0
    la['test'] = 1
    assert len(c) == 4
    assert c[3]['test'] == 1
    c[2]['test2'] = 9
    assert len(c) == 4

    l[5][6] = 8
    m[5][6] = 9
    assert l[5][6] != m[5][6]

    n[4] = 'someaddress'
    assert n[4] == 'someaddress'


def test_nested_typed_storage_iterable_dict():

    td = dict()

    def _get(k):
        if k not in td:
            td[k] = 0
        return td[k]

    def _set(k, v):
        td[k] = v

    d = nc.IterableDict('uint256')
    e = nc.IterableDict(nc.List('uint16'))
    f = nc.IterableDict('uint16')
    g = nc.IterableDict('string')

    d.setup(b'd', _get, _set)
    e.setup(b'e', _get, _set)
    f.setup(b'f', _get, _set)
    g.setup(b'g', _get, _set)

    # test IterableDict

    teststr1 = 'str1'
    teststr2 = 'str2'
    g['A'] = teststr1
    assert g['A'] == teststr1
    g['B'] = teststr2
    assert g['B'] == teststr2
    assert len(g) == 2

    k = '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x17q'
    v1 = 2146209080
    v2 = 86323145
    d[k] = v1
    assert len(d) == 1
    assert d[k] == v1
    d[k] = 0
    assert len(d) == 0
    d[k] = v2
    assert len(d) == 1
    assert d[k] == v2
    d[k] = v1
    d[k] = v2
    d[k] = v1
    d[k] = v2
    d[k] = v2
    d[k] = v1
    assert d[k] == v1
    assert len(d) == 1

    f['A'] = 1
    assert len(f) == 1
    f['A'] = 2
    assert len(f) == 1

    assert len(e) == 0

    e['A'][1] = 42
    assert len(e) == 1
    assert len(e['A']) == 2

    e['A'][2] = 43
    assert len(e['A']) == 3
    assert len(e) == 1

    for k in ['A', 'B', 'C']:
        for idx in range(3):
            e[k][idx] = 42 * (idx + 1)

    assert set(e.keys()) == set(['A', 'B', 'C'])
    assert len(e) == 3

    for k in ['A', 'B', 'C']:
        assert len(e[k]) == 3
    for v in e.values():
        assert len(v) == 3
        assert list(iter(v)) == [42 * (idx + 1) for idx in range(3)]

    dl = len(f)

    for i in range(100):
        f[b'key' + str(i)] = 1
        f[b'key' + str(i % 10)] = 2
        f[b'key' + str(i % 50)] = 3
        assert len(f) == i + 1 + dl


def test_nested_typed_storage_invalid_types():

    td = dict()

    def _get(k):
        if k not in td:
            td[k] = 0
        return td[k]

    def _set(k, v):
        td[k] = v

    a = nc.Dict(nc.List('uint16'))
    c = nc.List(nc.Dict('uint16'))
    k = nc.List(nc.List('address'))

    a.setup(b'a', _get, _set)
    c.setup(b'c', _get, _set)
    k.setup(b'k', _get, _set)

    # test invalid types

    with pytest.raises(AttributeError):
        a.b == 81

    with pytest.raises(ValueError):
        a['one']['two'] = 63432

    with pytest.raises(TypeError):
        a['one'][2] = 'somestr'

    with pytest.raises(NotImplementedError):
        k[1] = 2

    with pytest.raises(NotImplementedError):
        c[1] = 2


def test_nested_typed_storage_struct():

    def _key(self, k):
        k = zpad(k, 32)
        return b'%s:%s' % (self._prefix, k)

    original_key = nc.TypedStorage._key
    nc.TypedStorage._key = _key

    # the storage cannot be defined globally as the calls would interfere
    td = dict()

    def _get(k):
        if k not in td:
            td[k] = 0
        return td[k]

    def _set(k, v):
        td[k] = v

    g = nc.Struct(x=nc.List('uint32'), y=nc.Scalar('address'))
    h = nc.IterableDict(nc.Struct(x=nc.List('uint32'), y=nc.Scalar('address')))
    i = nc.List(nc.Struct(x=nc.Scalar('uint16'), y=nc.Dict('uint32'), z=nc.List('uint16')))
    j = nc.Struct(v=nc.Struct(x=nc.List('uint32'), y=nc.Scalar('address'), w=nc.Dict('uint16')))

    g.setup(b'g', _get, _set)
    h.setup(b'h', _get, _set)
    i.setup(b'i', _get, _set)
    j.setup(b'j', _get, _set)

    # test Struct

    g.x[538] = 78
    assert g.x[538] == 78
    assert ('g'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00x'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00538') in td

    with pytest.raises(AttributeError):
        assert g.idontexist == 0

    with pytest.raises(TypeError):
        g[2354645] = 2540

    with pytest.raises(TypeError):
        assert g['imnotadict'] == 0

    h['abcde'].x[4891] = 875
    assert h['abcde'].x[4891] == 875
    assert ('h'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00abcde'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00x'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x004891') in td

    i[3].y['here'] = 634
    assert i[3].y['here'] == 634
    assert ('i'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x003'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00y'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00here') in td

    i[4].z[41] = 88
    # assert i[4].z[41] == 88
    assert ('i'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x004'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00z'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x0041') in td

    assert len(i) == 5
    assert len(i[4].z) == 42

    j.v.w['then'] = 34
    assert j.v.w['then'] == 34
    assert ('j'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00v'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00w'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00then') in td

    j.v.x[471734] = 7
    assert j.v.x[471734] == 7
    assert ('j'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00v'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00x'
            ':\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            '\x00\x00\x00\x00\x00471734') in td

    nc.TypedStorage._key = original_key


def test_nativeabicontract_with_storage():

    class TestTSC(nc.NativeContract):

        address = utils.int_to_addr(2051)
        size = nc.Scalar('uint32')
        numbers = nc.List('uint32')
        words = nc.Dict('bytes')

        def setup_numbers(ctx, size='uint32', returns=None):
            ctx.size = size
            assert isinstance(ctx.numbers, nc.List)
            for i in range(size):
                ctx.numbers.append(i)

        def sum_numbers(ctx, returns='uint32'):
            assert ctx.size == len(ctx.numbers)
            return sum(ctx.numbers[i] for i in range(len(ctx.numbers)))

        def setup_words(ctx, num='uint32', returns=None):
            for i in range(num):
                key = 'key%d' % i
                word = 'word%d' % i
                ctx.words[key] = word
                assert ctx.words[key] == word

        def get_word(ctx, key='bytes', returns='bytes'):
            r = ctx.words[key]
            return r

        def muladdsize(ctx, val='uint32', returns='uint32'):
            ctx.size += val
            ctx.size *= val
            return ctx.size

    state = tester.state()
    nc.registry.register(TestTSC)

    # deploy two instances
    a0 = nc.tester_create_native_contract_instance(state, tester.k0, TestTSC)
    a1 = nc.tester_create_native_contract_instance(state, tester.k0, TestTSC)

    # create proxies
    c0 = nc.tester_nac(state, tester.k0, a0)
    c1 = nc.tester_nac(state, tester.k0, a1)

    size = 20
    c0.setup_numbers(size)
    assert c1.sum_numbers() == 0
    assert c0.sum_numbers() == sum(range(size))
    c1.setup_numbers(size)
    assert c0.sum_numbers() == sum(range(size))
    assert c1.sum_numbers() == sum(range(size))

    param = 5
    assert c0.muladdsize(param) == (size + param) * param

    # words
    c1.setup_words(param)
    assert c1.get_word(b'key2') == b'word2'

    assert c0.get_word(b'key2') == b''
    c0.setup_words(param)
    assert c0.get_word(b'key2') == b'word2'

    nc.registry.unregister(TestTSC)


def test_owned():

    class TestTSC(nc.NativeContract):

        address = utils.int_to_addr(2051)
        owner = nc.Scalar('address')

        def own(ctx, returns=None):
            if ctx.owner == '\0' * 20:
                ctx.owner = ctx.tx_origin
                assert ctx.owner == ctx.tx_origin

        def assert_owner(ctx):
            if ctx.tx_origin != ctx.owner:
                raise RuntimeError('not owner')

        @nc.constant
        def protected(ctx, returns='uint32'):
            ctx.assert_owner()
            return 1

    assert TestTSC.protected.is_constant is True

    state = tester.state()
    nc.registry.register(TestTSC)

    a0 = nc.tester_create_native_contract_instance(state, tester.k0, TestTSC)
    c0 = nc.tester_nac(state, tester.k0, a0)

    c0.own()
    assert c0.protected() == 1
    c0k1 = nc.tester_nac(state, tester.k1, a0)
    try:
        c0k1.protected()
    except tester.TransactionFailed:
        pass
    else:
        assert False, 'must not access protected if not owner'

    nc.registry.unregister(TestTSC)


def test_db_encode():

    enc = nc.TypedStorage._db_encode_type
    dec = nc.TypedStorage._db_decode_type

    assert isinstance(enc('int32', 1), int)
    assert isinstance(enc('address', '\0' * 20), int)
    assert isinstance(dec('address', 0), bytes)

    def t(v, typ):
        assert dec(typ, enc(typ, v)) == v, (dec(typ, enc(typ, v)), v)

    t(1, b'uint32')
    t(-1, b'int32')
    t(b'a', b'string')
    t(b'hello', b'string')
    t(b'a' * 20, b'address')
    t(b'abc', b'bytes')
    t(b'abc', b'string')
    t(b'abc', b'binary')

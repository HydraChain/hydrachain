import logging
import time
import pytest
import random
import gevent
from threading import Thread
from click.testing import CliRunner
from hydrachain import app
from pyethapp.rpc_client import JSONRPCClient
from requests.exceptions import ConnectionError
from ethereum import slogging


solidity_code = """
contract SimpleStorage {
    uint storedData;
    function set(uint x) {
        storedData = x;
    }
    function get() constant returns (uint retVal) {
        return storedData;
    }
}
"""

# Compiled with https://chriseth.github.io/browser-solidity/
contract_interface = '[{"constant":false,"inputs":[{"name":"x","type":"uint256"}],"name":"set","outputs":[],"type":"function"},{"constant":true,"inputs":[],"name":"get","outputs":[{"name":"retVal","type":"uint256"}],"type":"function"}]'  # noqa

contract_code = "606060405260978060106000396000f360606040526000357c01000000000000000000000000000000000000000000000000000000009004806360fe47b11460415780636d4ce63c14605757603f565b005b605560048080359060200190919050506078565b005b606260048050506086565b6040518082815260200191505060405180910390f35b806000600050819055505b50565b600060006000505490506094565b9056"  # noqa


class TestDriverThread(Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, verbose=None,
                 gasprice=None, evt=None, port=4000):
        super(TestDriverThread, self).__init__(group, target, name, args, kwargs, verbose)
        self.gasprice = gasprice
        self.log = slogging.getLogger('test_working_app')
        self.test_successful = False
        self.finished = False
        self.evt = evt
        self.port = port

    def wait_for_blocknumber(self, number, retry=20):
        block = self.client.call('eth_getBlockByNumber', hex(number), False)
        while block is None and retry > 0:
            block = self.client.call('eth_getBlockByNumber', hex(number), False)
            time.sleep(.5)
            retry -= 1
        assert retry > 0, "could not find block {}".format(number)
        return block

    def connect_client(self):
        while True:
            try:
                self.client = JSONRPCClient(port=self.port, print_communication=False)
                self.client.call('web3_clientVersion')
                break
            except ConnectionError:
                time.sleep(0.5)

    def run(self):
        self.log.debug('test started')

        try:
            self.connect_client()
            self.log.debug('client connected')

            # Read initial blocks created by HydraChain on startup
            self.wait_for_blocknumber(10)
            self.log.debug("found block number 10")

            # Create a contract
            params = {'from': self.client.coinbase.encode('hex'),
                      'to': '',
                      'data': contract_code,
                      'gasPrice': '0x{}'.format(self.gasprice)}
            self.client.call('eth_sendTransaction', params)
            self.log.debug('eth_sendTransaction OK')

            # Wait for new block
            recent_block = self.wait_for_blocknumber(11)

            self.log.debug('recent_block_hash {}'.format(recent_block))

            block = self.client.call('eth_getBlockByHash', recent_block['hash'], True)
            self.log.debug('eth_getBlockByHash OK {}'.format(block))

            assert block['transactions'], 'no transactions in block'
            tx = block['transactions'][0]
            assert tx['to'] == '0x'
            assert tx['gasPrice'] == params['gasPrice']
            assert len(tx['input']) > len('0x')
            assert tx['input'].startswith('0x')

            # Get transaction receipt to have the address of contract
            receipt = self.client.call('eth_getTransactionReceipt', tx['hash'])
            self.log.debug('eth_getTransactionReceipt OK {}'.format(receipt))

            assert receipt['transactionHash'] == tx['hash']
            assert receipt['blockHash'] == tx['blockHash']
            assert receipt['blockHash'] == block['hash']

            # Get contract address from receipt
            contract_address = receipt['contractAddress']
            code = self.client.call('eth_getCode', contract_address)
            self.log.debug('eth_getCode OK {}'.format(code))

            assert code.startswith('0x')
            assert len(code) > len('0x')

            # Perform some action on contract (set value to random number)
            rand_value = random.randint(64, 1024)
            contract = self.client.new_abi_contract(contract_interface, contract_address)
            contract.set(rand_value, gasprice=self.gasprice)
            self.log.debug('contract.set({}) OK'.format(rand_value))

            # Wait for new block
            recent_block = self.wait_for_blocknumber(12)
            # recent_block_hash = self.wait_for_new_block()

            block = self.client.call('eth_getBlockByHash', recent_block['hash'], True)

            # Check that value was correctly set on contract
            res = contract.get()
            self.log.debug('contract.get() OK {}'.format(res))
            assert res == rand_value

            self.test_successful = True
        except Exception as ex:
            print("Exception", ex)
            import traceback
            traceback.print_exc()
            self.log.exception("Exception in test thread")
        finally:
            self.evt.set()
            self.finished = True


@pytest.mark.parametrize('gasprice', (0, 1))
@pytest.mark.xfail(reason="the test result is non-deterministic. fixme!")  # FIXME
def test_example(gasprice, caplog):
    rand_port = random.randint(4000, 5000)
    if caplog:
        caplog.set_level(logging.DEBUG)
    # Start thread that will communicate to the app ran by CliRunner
    evt = gevent.event.Event()
    t = TestDriverThread(gasprice=gasprice, evt=evt, port=rand_port)
    t.setDaemon(True)
    t.start()

    # Stop app after testdriverthread is completed
    def mock_serve_until_stopped(*apps):
        evt.wait()
        for app_ in apps:
            app_.stop()

    app.serve_until_stopped = mock_serve_until_stopped

    runner = CliRunner()
    with runner.isolated_filesystem():
        datadir = 'datadir{}'.format(gasprice)
        runner.invoke(app.pyethapp_app.app, ['-d', datadir,
            '-l', ':WARNING,hdc.chainservice:INFO,test_working_app:DEBUG',
            '-c', 'jsonrpc.listen_port={}'.format(rand_port), 'runmultiple'])
        while not t.finished:
            gevent.sleep(1)

    assert t.test_successful


if __name__ == '__main__':
    slogging.configure(":debug")
    test_example(1, None)
    test_example(0, None)

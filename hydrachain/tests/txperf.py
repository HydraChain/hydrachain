"""Example call:

    >>> rm -rf /tmp/txperf && hydrachain -d /tmp/txperf runmultiple -v 3 & \
            sleep 15 && time python hydrachain/tests/txperf.py && kill -9 %1
"""
from pyethapp.rpc_client import JSONRPCClient


def do_tx(client, nonce, coinbase):
    value = 1
    recipient = "1" * 40
    r = client.send_transaction(
        coinbase,
        recipient,
        value,
        startgas=21001,
        nonce=nonce
    )
    return r


def main(num_clients, num_txs=1):
    import time
    txs = set()
    clients = [JSONRPCClient(4000 + i) for i in range(num_clients)]
    coinbase = clients[0].coinbase
    nonce = clients[0].nonce(coinbase)
    for i in range(num_txs):
        txh = do_tx(clients[0], nonce=nonce + i, coinbase=coinbase)
        print 'tx', i, txh
        txs.add(txh)
    assert len(txs) == num_txs

    print 'checking if all %d txs are included' % num_txs
    time.sleep(3)
    tx_blocks = set()
    blocks = set()
    for tx in txs:
        for client in clients:
            print client, tx
            r = client.call('eth_getTransactionReceipt', tx)
            blk = r['blockHash']
            tx_blocks.add((tx, blk))
            blocks.add(blk)
    assert len(tx_blocks) == num_txs
    print
    print 'Success: %d txs in %d blocks in all %d clients' % (num_txs, len(blocks), num_clients)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        num_clients = int(sys.argv[1])
    else:
        num_clients = 1
    main(num_clients, 10)

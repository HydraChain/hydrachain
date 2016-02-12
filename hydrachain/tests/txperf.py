"""Example call:

    >>> NODES=3; rm -rf /tmp/txperf && hydrachain -d /tmp/txperf runmultiple \
            -v $NODES > /dev/null 2>&1 & sleep 15 && time python \
            hydrachain/tests/txperf.py && kill -9 %1
"""
from pyethapp.rpc_client import JSONRPCClient
import time


def do_tx(client, coinbase):
    value = 1
    recipient = "1" * 40
    r = client.send_transaction(
        coinbase,
        recipient,
        value,
        startgas=21001
    )
    return r


def main(num_clients, num_txs=1):
    st = time.time()
    txs = set()
    clients = [JSONRPCClient(4000 + i, print_communication=False) for i in range(num_clients)]
    coinbase = clients[0].coinbase

    for i in range(num_txs):
        txh = do_tx(clients[0], coinbase=coinbase)
        print 'tx', i, txh
        txs.add(txh)

    # assert len(txs) == num_txs, len(txs)

    elapsed = time.time() - st
    # sys.exit(0)
    print 'checking if all %d txs are included' % num_txs
    time.sleep(5)
    tx_blocks = set()
    blocks = set()
    for tx in txs:
        for client in clients:
            r = client.call('eth_getTransactionReceipt', tx)
            if not r:
                continue
            blk = r.get('blockHash')
            if blk:
                tx_blocks.add((tx, blk))
                blocks.add(blk)

    print
    print '%d txs in %d blocks in all %d clients' % (len(tx_blocks), len(blocks), num_clients)
    print 'elapsed', elapsed
    assert len(tx_blocks) == num_txs, (len(tx_blocks), num_txs)

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        num_clients = int(sys.argv[1])
    else:
        num_clients = 1
    main(num_clients, 500)


"""
CPython: 12 tps
PyPy: 18 tps

With min_block_time = 0.5
CPython: 17 tps
PyPy: 49tps

Not forwarding did not imporve performance!
"""

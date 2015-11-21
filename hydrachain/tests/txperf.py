from pyethapp.rpc_client import JSONRPCClient


class Client(object):

    def __init__(self, port=4000):
        self.client = JSONRPCClient(port)


def do_tx(client, nonce):
    value = 1
    recipient = "1" * 40
    client.send_transaction(
        client.coinbase,
        recipient,
        value,
        startgas=21001
    )


def main(num_clients, num_txs=1):
    import time
    clients = [JSONRPCClient(4000 + i) for i in range(num_clients)]
    nonce = clients[0].nonce(clients[0].coinbase)
    for i in range(num_txs):
        do_tx(clients[0], nonce=nonce + i)
        print 'tx', i

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        num_clients = int(sys.argv[1])
    else:
        num_clients = 1
    main(num_clients, 10)

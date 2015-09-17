#!/usr/bin/env python

import click
from pyethapp.accounts import mk_privkey
from devp2p.crypto import privtopub as privtopub_raw
from devp2p.utils import host_port_pubkey_to_uri


@click.command()
@click.option('-h', '--host', default="localhost")
@click.option('-p', '--port', default=30303)
@click.argument('seed', type=int)
@click.argument('node-num', type=int)
def mk_enode(seed, node_num, host, port):
    print(
        host_port_pubkey_to_uri(
            host, 
            port, 
            privtopub_raw(
                mk_privkey(
                    '%d:udp:%d' % (seed, node_num)))))

if __name__ == '__main__':
    mk_enode()

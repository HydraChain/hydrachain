import os
import signal
import sys
import click
import gevent
from gevent.event import Event
from devp2p.service import BaseService
from devp2p.peermanager import PeerManager
from devp2p.discovery import NodeDiscovery
from devp2p.app import BaseApp
from pyethapp.console_service import Console
from pyethapp.db_service import DBService
from pyethapp.profiles import PROFILES
from pyethapp.jsonrpc import JSONRPCServer
from pyethapp.accounts import AccountsService, Account
import ethereum.slogging as slogging
import pyethapp.app as pyethapp_app
from pyethapp.accounts import mk_privkey, privtopub
from devp2p.crypto import privtopub as privtopub_raw
from devp2p.utils import host_port_pubkey_to_uri
from ethereum.keys import privtoaddr, PBKDF2_CONSTANTS

# local
from hydrachain.hdc_service import ChainService
from hydrachain import __version__

slogging.configure(config_string=':debug')
log = slogging.get_logger('app')


services = [DBService,
            AccountsService,
            NodeDiscovery,
            PeerManager,
            ChainService,
            JSONRPCServer,
            Console]

pyethapp_app.services = services


class HPCApp(pyethapp_app.EthApp):
    client_name = 'HydraChain'
    client_version = '%s/%s/%s' % (__version__, sys.platform,
                                   'py%d.%d.%d' % sys.version_info[:3])
    client_version_string = '%s/v%s' % (client_name, client_version)
    default_config = dict(BaseApp.default_config)
    default_config['client_version_string'] = client_version_string
    default_config['post_app_start_callback'] = None

pyethapp_app.EthApp = HPCApp
pyethapp_app.app.help = b'Welcome to %s' % HPCApp.client_version_string


# set olympic profile
for p in pyethapp_app.app.params:
    if p.name == 'profile':
        p.default = 'olympic'
# delete genesis hash, as it is currently
del PROFILES['olympic']['eth']['genesis_hash']


@pyethapp_app.app.command(help='run in a zero config default configuration')
@click.option('num_validators', '--num_validators', '-v', multiple=False,
              type=int, default=3, help='number of validators')
@click.option('node_num', '--node_num', '-n', multiple=False,
              type=int, default=0, help='the node_num')
@click.option('seed', '--seed', '-s', multiple=False,
              type=int, default=42, help='the seed')
@click.pass_context
def rundummy(ctx, num_validators, node_num, seed):

    # reduce key derivation iterations
    PBKDF2_CONSTANTS['c'] = 100

    config = ctx.obj['config']

    # create bootstrap node priv_key and enode
    bootstrap_node_privkey = mk_privkey('%d:udp:%d' % (seed, 0))
    bootstrap_node_pubkey = privtopub_raw(bootstrap_node_privkey)
    assert len(bootstrap_node_pubkey) == 64,  len(bootstrap_node_pubkey)
    base_port = 29870
    host = b'0.0.0.0'

    bootstrap_node = host_port_pubkey_to_uri(host, base_port, bootstrap_node_pubkey)
    config['discovery']['bootstrap_nodes'] = [bootstrap_node]

    # create this node priv_key
    config['node']['privkey_hex'] = mk_privkey('%d:udp:%d' % (seed, node_num)).encode('hex')

    # create validator addresses
    validators = [privtoaddr(mk_privkey('%d:account:%d' % (seed, i)))
                  for i in range(num_validators)]
    config['hdc']['validators'] = validators

    # create this node account
    account = Account.new(password='', key=mk_privkey('%d:account:%d' % (seed, node_num)))

    # set ports based on node
    config['discovery']['listen_port'] = base_port + node_num
    config['p2p']['listen_port'] = base_port + node_num
    config['p2p']['min_peers'] = 2
    config['jsonrpc']['listen_port'] += node_num

    # create app
    app = HPCApp(config)

    # development mode
    if True:
        gevent.get_hub().SYSTEM_ERROR = BaseException

    # dump config
    pyethapp_app.dump_config(config)

    # init accounts first, as we need (and set by copy) the coinbase early FIXME
    if AccountsService in services:
        AccountsService.register_with_app(app)
    # add account
    app.services.accounts.add_account(account, store=False)

    # register services
    for service in services:
        assert issubclass(service, BaseService)
        if service.name not in app.config['deactivated_services'] + [AccountsService.name]:
            assert service.name not in app.services
            service.register_with_app(app)
            assert hasattr(app.services, service.name)

    # start app
    log.info('starting')
    app.start()

    if config['post_app_start_callback'] is not None:
        config['post_app_start_callback'](app)

    # wait for interrupt
    evt = Event()
    gevent.signal(signal.SIGQUIT, evt.set)
    gevent.signal(signal.SIGTERM, evt.set)
    gevent.signal(signal.SIGINT, evt.set)
    evt.wait()

    # finally stop
    app.stop()


def app():
    pyethapp_app.app()

if __name__ == '__main__':
    #  python app.py 2>&1 | less +F
    app()

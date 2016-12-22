import copy
import os
import signal
import sys

import click
import ethereum.slogging as slogging
import gevent
import pyethapp.app as pyethapp_app
import pyethapp.config as konfig
from click.exceptions import BadParameter
from click.types import IntRange
from devp2p.app import BaseApp
from devp2p.crypto import privtopub as privtopub_raw
from devp2p.discovery import NodeDiscovery
from devp2p.peermanager import PeerManager
from devp2p.service import BaseService
from devp2p.utils import host_port_pubkey_to_uri
from ethereum.keys import privtoaddr, PBKDF2_CONSTANTS
from ethereum.utils import denoms
from gevent.event import Event
from pyethapp.accounts import AccountsService, Account
from pyethapp.accounts import mk_privkey
from pyethapp.console_service import Console
from pyethapp.db_service import DBService
from pyethapp.jsonrpc import JSONRPCServer

from hydrachain import __version__
from hydrachain.hdc_service import ChainService


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
    default_config['post_app_start_callbacks'] = []

    # option to easily specify some unlocked and funded accounts
    default_config['test_privkeys'] = []
    default_config['test_privkeys_endowment'] = 1024 * denoms.ether


pyethapp_app.EthApp = HPCApp
pyethapp_app.app.help = b'Welcome to %s' % HPCApp.client_version_string


# set morden profile
for p in pyethapp_app.app.params:
    if p.name == 'profile':
        p.default = 'testnet'


@pyethapp_app.app.command(help='run in a zero config default configuration')
@click.option('num_validators', '--num_validators', '-v', multiple=False,
              type=int, default=3, help='number of validators')
@click.option('node_num', '--node_num', '-n', multiple=False,
              type=int, default=0, help='the node_num')
@click.option('seed', '--seed', '-s', multiple=False,
              type=int, default=42, help='the seed')
@click.pass_context
def rundummy(ctx, num_validators, node_num, seed):
    base_port = 29870

    # reduce key derivation iterations
    PBKDF2_CONSTANTS['c'] = 100

    config = ctx.obj['config']

    config['discovery']['bootstrap_nodes'] = [get_bootstrap_node(seed, base_port)]

    config, account = _configure_node_network(config, num_validators, node_num, seed)

    # set ports based on node
    config['discovery']['listen_port'] = base_port + node_num
    config['p2p']['listen_port'] = base_port + node_num
    config['p2p']['min_peers'] = 2
    config['jsonrpc']['listen_port'] += node_num

    app = start_app(config, [account])
    serve_until_stopped(app)


@pyethapp_app.app.command(help='run multiple nodes in a zero config default configuration')
@click.option('num_validators', '--num_validators', '-v', multiple=False,
              type=int, default=3, help='number of validators')
@click.option('seed', '--seed', '-s', multiple=False,
              type=int, default=42, help='the seed')
@click.pass_context
def runmultiple(ctx, num_validators, seed):
    gevent.get_hub().SYSTEM_ERROR = BaseException
    base_port = 29870

    # reduce key derivation iterations
    PBKDF2_CONSTANTS['c'] = 100

    config = ctx.obj['config']
    config['discovery']['bootstrap_nodes'] = [get_bootstrap_node(seed, base_port)]

    apps = []
    for node_num in range(num_validators):
        n_config = copy.deepcopy(config)
        n_config, account = _configure_node_network(n_config, num_validators, node_num, seed)
        # set ports based on node
        n_config['discovery']['listen_port'] = base_port + node_num
        n_config['p2p']['listen_port'] = base_port + node_num
        n_config['p2p']['min_peers'] = min(10, num_validators - 1)
        n_config['p2p']['max_peers'] = num_validators * 2
        n_config['jsonrpc']['listen_port'] += node_num
        n_config['client_version_string'] = 'NODE{}'.format(node_num)

        # have multiple datadirs
        n_config['data_dir'] = os.path.join(n_config['data_dir'], str(node_num))
        konfig.setup_data_dir(n_config['data_dir'])

        # activate ipython console for the first validator
        if node_num != 0:
            n_config['deactivated_services'].append(Console.name)
        # n_config['deactivated_services'].append(ChainService.name)
        app = start_app(n_config, [account])
        apps.append(app)
        # hack to enable access to all apps in the console
        app.apps = apps
    serve_until_stopped(*apps)


@pyethapp_app.app.command(help='run in a zero config default configuration')
@click.option('num_validators', '--num_validators', '-v', multiple=False,
              type=IntRange(min=4), default=4, show_default=True,
              help='number of validators; min. 4')
@click.option('node_num', '--node_num', '-n', multiple=False,
              type=int, default=0, help='the node_num')
@click.option('seed', '--seed', '-s', multiple=False,
              type=int, default=42, help='the seed')
@click.option('--nodial/--dial', default=False, help='do not dial nodes')
@click.pass_context
def runlocal(ctx, num_validators, node_num, seed, nodial):
    if not 0 <= node_num < num_validators:
        raise BadParameter("Node number must be between 0 and number of validators - 1")

    # reduce key derivation iterations
    config = ctx.obj['config']
    config, account = _configure_node_network(config, num_validators, node_num, seed)

    config['p2p']['min_peers'] = 2

    if nodial:
        config['discovery']['bootstrap_nodes'] = []
        config['p2p']['min_peers'] = 0

    app = start_app(config, [account])
    serve_until_stopped(app)


def _configure_node_network(config, num_validators, node_num, seed):
    assert node_num < num_validators

    # reduce key derivation iterations
    PBKDF2_CONSTANTS['c'] = 100

    # create this node priv_key
    config['node']['privkey_hex'] = mk_privkey('%d:udp:%d' % (seed, node_num)).encode('hex')

    # create validator addresses
    validators = [privtoaddr(mk_privkey('%d:account:%d' % (seed, i)))
                  for i in range(num_validators)]
    config['hdc']['validators'] = validators

    # create this node account
    account = Account.new(password='', key=mk_privkey('%d:account:%d' % (seed, node_num)))
    assert account.address in validators
    return config, account


def start_app(config, accounts):

    # create app
    app = HPCApp(config)

    # development mode
    if False:
        gevent.get_hub().SYSTEM_ERROR = BaseException

    if config['test_privkeys']:
        # init accounts first, as we need (and set by copy) the coinbase early FIXME
        genesis_config = dict(alloc=dict())
        for privkey in config['test_privkeys']:
            assert len(privkey) == 32
            address = privtoaddr(privkey)
            account = Account.new(password='', key=privkey)
            accounts.append(account)
            # add to genesis alloc
            genesis_config['alloc'][address] = {'wei': config['test_privkeys_endowment']}

        if config['test_privkeys'] and config['eth'].get('genesis_hash'):
            del config['eth']['genesis_hash']

        konfig.update_config_from_genesis_json(config, genesis_config)

    # dump config
    pyethapp_app.dump_config(config)

    if AccountsService in services:
        AccountsService.register_with_app(app)

    # add account
    for account in accounts:
        app.services.accounts.add_account(account, store=False)

    if config['hdc']['validators']:
        assert app.services.accounts.coinbase in config['hdc']['validators']

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
    for cb in config['post_app_start_callbacks']:
        cb(app)
    return app


def serve_until_stopped(*apps):
    # wait for interrupt
    evt = Event()
    gevent.signal(signal.SIGQUIT, evt.set)
    gevent.signal(signal.SIGTERM, evt.set)
    evt.wait()
    # finally stop
    for app in apps:
        app.stop()


def get_bootstrap_node(seed, base_port=29870, host=b'0.0.0.0'):
    # create bootstrap node priv_key and enode
    bootstrap_node_privkey = mk_privkey('%d:udp:%d' % (seed, 0))
    bootstrap_node_pubkey = privtopub_raw(bootstrap_node_privkey)
    return host_port_pubkey_to_uri(host, base_port, bootstrap_node_pubkey)


def app():
    pyethapp_app.app()

if __name__ == '__main__':
    #  python app.py 2>&1 | less +F
    app()

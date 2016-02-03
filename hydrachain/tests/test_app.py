import hydrachain.app
import tempfile
import pyethapp.config as konfig
from pyethapp.db_service import DBService
from pyethapp.accounts import AccountsService
from hydrachain.hdc_service import ChainService
from ethereum.keys import privtoaddr, PBKDF2_CONSTANTS
from devp2p.peermanager import PeerManager

services = [DBService,
            AccountsService,
            ChainService,
            PeerManager
            ]

PBKDF2_CONSTANTS['c'] = 100


def default_config():
    config = konfig.get_default_config(services + [hydrachain.app.HPCApp])
    return config


def test_test_privkeys():
    try:
        _services_orig = hydrachain.app.services
        hydrachain.app.services = services
        config = default_config()
        config['data_dir'] = tempfile.mktemp()
        konfig.setup_data_dir(config['data_dir'])
        config['node']['privkey_hex'] = '1' * 64

        privkeys = [str(i) * 32 for i in range(5)]
        config['test_privkeys'] = privkeys
        config['hdc']['validators'] = [privtoaddr(privkeys[0])]

        app = hydrachain.app.start_app(config, accounts=[])
        g = app.services.chain.chain.genesis
        for p in privkeys:
            a = privtoaddr(p)
            assert len(a) == 20
            assert g.get_balance(a) > 0
            assert a in app.services.accounts
            account = app.services.accounts[a]
            assert account.address == a
        app.stop()
    finally:
        hydrachain.app.services = _services_orig

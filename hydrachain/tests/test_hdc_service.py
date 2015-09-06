import os
from ethereum.db import EphemDB
from pyethapp import leveldb_service
from pyethapp.accounts import Account, AccountsService
from ethereum import slogging
from ethereum import utils
from ethereum import config as eth_config
from hydrachain import hdc_service
from hydrachain.consensus import protocol as hdc_protocol
from hydrachain.consensus.base import Block, BlockProposal, VoteBlock, VoteNil, TransientBlock
import ethereum.keys
import rlp
import tempfile
slogging.configure(config_string=':info')

# reduce key derivation iterations
ethereum.keys.PBKDF2_CONSTANTS['c'] = 100

privkeys = [chr(i) * 32 for i in range(1, 11)]
validators = [utils.privtoaddr(p) for p in privkeys]


empty = object()


class AppMock(object):

    tmpdir = tempfile.mkdtemp()

    config = hdc_service.ChainService.default_config

    config['db'] = dict(path='_db')
    config['data_dir'] = tmpdir

    class Services(dict):

        class peermanager:

            @classmethod
            def broadcast(*args, **kwargs):
                pass

    def __init__(self, privkey):
        self.services = self.Services()
        self.services.db = EphemDB()
        self.services.accounts = AccountsService(self)
        account = Account.new(password='', key=privkey)
        self.services.accounts.add_account(account, store=False)


class PeerMock(object):

    def __init__(self, app):
        self.config = app.config
        self.send_packet = lambda x: x
        self.remote_client_version = empty


def test_receive_proposal():
    app = AppMock(privkeys[0])
    chainservice = hdc_service.ChainService(app)
    proto = hdc_protocol.HDCProtocol(PeerMock(app), chainservice)
    cm = chainservice.consensus_manager
    p = cm.active_round.mk_proposal()
    assert isinstance(p.block, Block)
    r = rlp.encode(p)
    p = rlp.decode(r, sedes=BlockProposal)
    assert isinstance(p.block, TransientBlock)
    chainservice.on_receive_blockproposal(proto, p)
    # assert chainservice.chain.head.number == 1  # we don't have consensus yet


# def receive_blocks(rlp_data, leveldb=False, codernitydb=False):
#     app = AppMock()
#     if leveldb:
#         app.db = leveldb_service.LevelDB(
#             os.path.join(app.config['app']['dir'], app.config['db']['path']))

#     chainservice = hdc_service.ChainService(app)
#     proto = hdc_protocol.HDCProtocol(PeerMock(app), chainservice)
#     b = hdc_protocol.HDCProtocol.blocks.decode_payload(rlp_data)
#     chainservice.on_receive_blocks(proto, b)


# def test_receive_block1():
#     rlp_data = rlp.encode([rlp.decode(block_1.decode('hex'))])
#     receive_blocks(rlp_data)


# def test_receive_blocks_256():
#     receive_blocks(data256.decode('hex'))


# def test_receive_blocks_256_leveldb():
#     receive_blocks(data256.decode('hex'), leveldb=True)

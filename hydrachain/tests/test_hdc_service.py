import tempfile

import ethereum.keys
import pytest
import rlp
from ethereum import utils
from ethereum.db import EphemDB
from pyethapp.accounts import Account, AccountsService

from hydrachain import hdc_service
from hydrachain.consensus import protocol as hdc_protocol
from hydrachain.consensus.base import (Block, BlockProposal, TransientBlock, InvalidProposalError,
                                       LockSet, Ready)


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
    config['hdc'] = dict(validators=validators)

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


@pytest.mark.xfail(reason="Broken test? See line 72")
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
    with pytest.raises(InvalidProposalError):  # not the proposser, fix test
        chainservice.on_receive_newblockproposal(proto, p)
    # assert chainservice.chain.head.number == 1  # we don't have consensus yet


def test_broadcast_filter():
    r = Ready(0, LockSet(1))
    r.sign('x' * 32)
    df = hdc_service.DuplicatesFilter()
    assert r not in df
    assert df.update(r)
    assert not df.update(r)
    assert not df.update(r)
    assert r in df

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

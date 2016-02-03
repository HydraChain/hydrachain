import rlp
import gevent
from devp2p.protocol import BaseProtocol, SubProtocolError
from ethereum.transactions import Transaction
from hydrachain.consensus.base import BlockProposal, VotingInstruction, Vote, LockSet, Ready
from ethereum import slogging
log = slogging.get_logger('protocol.hdc')


class HDCProtocolError(SubProtocolError):
    pass


class HDCProtocol(BaseProtocol):

    """
    HydraChain Wire Protocol
    """
    protocol_id = 1
    network_id = 0
    max_cmd_id = 15  # FIXME
    name = 'hdc'
    version = 1
    max_getproposals_count = 10

    def __init__(self, peer, service):
        # required by P2PProtocol
        self.config = peer.config
        BaseProtocol.__init__(self, peer, service)

    class status(BaseProtocol.command):

        """
        protocolVersion: The version of the HydraChain protocol this peer implements.
        networkID: The network version of Ethereum for this peer.
        GenesisHash: The hash of the Genesis block.
        current_lockset: The lockset of the current round from the responding peer
        """
        cmd_id = 0
        sent = False

        structure = [
            ('eth_version', rlp.sedes.big_endian_int),
            ('network_id', rlp.sedes.big_endian_int),
            ('genesis_hash', rlp.sedes.binary),
            ('current_lockset', LockSet)
        ]

        def create(self, proto, genesis_hash, current_lockset):
            self.sent = True
            network_id = proto.service.app.config['eth'].get('network_id', proto.network_id)
            return [proto.version, network_id, genesis_hash, current_lockset]

    class transactions(BaseProtocol.command):

        """
        Specify (a) transaction(s) that the peer should make sure is included on its transaction
        queue. The items in the list (following the first item 0x12) are transactions in the
        format described in the main Ethereum specification. Nodes must not resend the same
        transaction to a peer in the same session. This packet must contain at least one (new)
        transaction.
        """
        cmd_id = 1
        structure = rlp.sedes.CountableList(Transaction)

        # todo: bloomfilter: so we don't send tx to the originating peer

        @classmethod
        def decode_payload(cls, rlp_data):
            # convert to dict
            txs = []
            for i, tx in enumerate(rlp.decode_lazy(rlp_data)):
                txs.append(Transaction.deserialize(tx))
                if not i % 10:
                    gevent.sleep(0.0001)
            return txs

    class getblockproposals(BaseProtocol.command):

        """
        Requests a BlockProposals message detailing a number of blocks to be sent, each referred to
        by block number. Note: Don't expect that the peer necessarily give you all these blocks
        in a single message - you might have to re-request them.
        """
        cmd_id = 2
        structure = rlp.sedes.CountableList(rlp.sedes.big_endian_int)

    class blockproposals(BaseProtocol.command):

        """
        BlockProposals sent in response to a getproposals request
        """
        cmd_id = 3
        structure = rlp.sedes.CountableList(BlockProposal)

        @classmethod
        def encode_payload(cls, list_of_rlp):
            """
            rlp data directly from the database
            """
            assert isinstance(list_of_rlp, tuple)
            assert not list_of_rlp or isinstance(list_of_rlp[0], bytes)
            return rlp.encode([rlp.codec.RLPData(x) for x in list_of_rlp], infer_serializer=False)

    class newblockproposal(BaseProtocol.command):

        """
        Specify a single BlockProposal that the peer should know about.
        """
        cmd_id = 4
        structure = [('proposal', BlockProposal)]

    class votinginstruction(BaseProtocol.command):

        """
        Specify a single VotingInstruction that the peer should know about.
        """
        cmd_id = 5
        structure = [('votinginstruction', VotingInstruction)]

    class vote(BaseProtocol.command):

        """
        Specify a single Vote that the peer should know about.
        """
        cmd_id = 6
        structure = [('vote', Vote)]

    class ready(BaseProtocol.command):
        cmd_id = 7
        structure = [('ready', Ready)]

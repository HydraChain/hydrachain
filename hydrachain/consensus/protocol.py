import rlp
import gevent
import time
from devp2p.protocol import BaseProtocol, SubProtocolError
from ethereum.transactions import Transaction
from hydrachain.consensus.base import BlockProposal, VotingInstruction, Vote
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

    def __init__(self, peer, service):
        # required by P2PProtocol
        self.config = peer.config
        BaseProtocol.__init__(self, peer, service)

    class status(BaseProtocol.command):

        """
        protocolVersion: The version of the Ethereum protocol this peer implements. 30 at present.
        networkID: The network version of Ethereum for this peer. 0 for the official testnet.
        totalDifficulty: Total Difficulty of the best chain. Integer, as found in block header.
        latestHash: The hash of the block with the highest validated total difficulty.
        GenesisHash: The hash of the Genesis block.
        """
        cmd_id = 0
        sent = False

        structure = [
            ('eth_version', rlp.sedes.big_endian_int),
            ('network_id', rlp.sedes.big_endian_int),
            ('chain_difficulty', rlp.sedes.big_endian_int),
            ('chain_head_hash', rlp.sedes.binary),
            ('genesis_hash', rlp.sedes.binary)]

        def create(self, proto, chain_difficulty, chain_head_hash, genesis_hash):
            self.sent = True
            network_id = proto.service.app.config['hdc'].get('network_id', proto.network_id)
            return [proto.version, network_id, chain_difficulty, chain_head_hash, genesis_hash]

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

    class getblocks(BaseProtocol.command):

        """
        Requests a Blocks message detailing a number of blocks to be sent, each referred to
        by block number. Note: Don't expect that the peer necessarily give you all these blocks
        in a single message - you might have to re-request them.
        """
        cmd_id = 2
        structure = rlp.sedes.CountableList(rlp.sedes.big_endian_int)

    class blocks(BaseProtocol.command):

        """
        BlockProposals sent in response to a getblocks request
        """
        cmd_id = 3
        structure = rlp.sedes.CountableList(BlockProposal)

        @classmethod
        def encode_payload(cls, list_of_rlp):
            """
            rlp data directly from the database
            """
            return rlp.encode([rlp.codec.RLPData(x) for x in list_of_rlp], infer_serializer=False)

    class blockproposal(BaseProtocol.command):

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

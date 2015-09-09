import gevent
from .base import Proposal
from .protocol import HDCProtocol


class Synchronizer(object):

    timeout = 5
    max_getproposals_count = HDCProtocol.max_getproposals_count
    max_queued = 3 * max_getproposals_count

    def __init__(self, consensusmanager):
        self.cm = consensusmanager
        self.requested = set()
        self.received = set()
        self.last_active_protocol = None  # last protocol (peer) which sent a proposal
        self.add_proposals_lock = gevent.lock.Semaphore()

    def __repr__(self):
        status = 'syncing' if self.is_syncing else 'insync'
        return '<Synchronizer(%s missing=%d requested=%d received=%d)>' \
            % (status, len(self.missing), len(self.requested), len(self.received))

    @property
    def is_syncing(self):
        return len(self.requested)

    @property
    def missing(self):
        ls = self.cm.highest_committing_lockset
        if not ls:
            return []
        max_height = ls.height
        if not max_height or max_height <= self.cm.head.number:
            return []
        return range(self.cm.head.number + 1, max_height + 1)

    def request(self):
        """
        sync the missing blocks between:
            head
            highest height with signing lockset

        we get these locksets by collecting votes on all heights
        """
        missing = self.missing
        self.cm.log('sync.request', missing=len(missing), requested=len(self.requested),
                    received=len(self.received))
        if self.requested:
            self.cm.log('waiting for requested')
            return
        if len(self.received) + self.max_getproposals_count >= self.max_queued:
            self.cm.log('queue is full')
            return
        if not missing:
            self.cm.log('insync')
            return
        if self.last_active_protocol is None:  # FIXME, check if it is active
            self.cm.log('no active protocol', last_active_protocol=self.last_active_protocol)
            return
        self.cm.log('collecting')
        blocknumbers = []
        for h in missing:
            if h not in self.received and h not in self.requested:
                blocknumbers.append(h)
                self.requested.add(h)
                if len(blocknumbers) == self.max_getproposals_count:
                    break
        self.cm.log('collected', num=len(blocknumbers))
        if not blocknumbers:
            return
        self.cm.log('requesting', num=len(blocknumbers),
                    requesting_range=(blocknumbers[0], blocknumbers[-1]))
        self.last_active_protocol.send_getblockproposals(*blocknumbers)
        # setup alarm
        self.cm.chainservice.setup_alarm(self.timeout, self.on_alarm, blocknumbers)

    def on_proposal(self, proposal, proto):
        "called to inform about synced peers"
        assert isinstance(proto, HDCProtocol)
        assert isinstance(proposal, Proposal)
        if proposal.height >= self.cm.height:
            assert proposal.lockset.is_valid
            self.last_active_protocol = proto

    def on_alarm(self, requested):
        # remove requested, so they can be rerequested
        self.requested.difference_update(set(self.requested))
        self.request()

    def receive_blockproposals(self, proposals):
        self.cm.log('receive_blockproposals', p=proposals, received=self.received)
        for p in proposals:
            self.received.add(p.height)
            self.requested.remove(p.height)
            for v in p.signing_lockset:  # add all votes, so we have locksets ready for committing
                self.cm.add_vote(v)

        # commit after we added new votes to commit a block from the last sync
        self.cm.process()

        # request next round
        self.request()
        self.add_proposals_lock.acquire()
        for p in proposals:
            self.cm.add_proposal(p)
            self.cm.process()
        self.cleanup()
        self.add_proposals_lock.release()

        not_added = []
        for p in proposals:
            if p.height > self.cm.head.number:
                not_added.append(p)
                if p.height == self.cm.head.number:
                    assert p.blockhash in self.cm.block_candidates

        # print 'not added', not_added
        # print 'received', self.received
        # for h in self.cm.heights:
        #     if self.cm.heights[h].last_quorum_lockset:
        #         print 'quorum @', h

        assert self.cm.height >= max(p.height for p in proposals)

        self.cm.log('done receive_blockproposals', sync=self)
        if len(not_added) > 1:
            raise Exception('more than one proposal not added')

    def cleanup(self):
        height = self.cm.height
        for h in list(self.received):
            if h < height:
                self.received.remove(h)
        for h in list(self.requested):
            if h < height:
                self.requested.remove(h)

    def process(self):
        self.request()

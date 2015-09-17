HC Consensus
------------

HC Consensus is a byzantine fault tolerant protocol to coordinate consensus on the order of transactions in blockchain systems.

**Features:**
 - Finality, no state re-organisation
 - Low overhead in normal operation

The protocol relies on a set of validators of which no more than 1/3 must be byzantine.

At each block height one or more rounds are used to agree on a proposed block for the height.  The proposer of a block for each height and round is deterministically round robin chosen from the set of validators. New rounds can only be started once +2/3 nodes voted on the last round, which keeps the distributed system in sync.

Normal operation comes with low overhead, as proposed blocks come with the quorum of signatures on the block of the last height.

       propose H -> commit H-1 -> vote H


**Notation**

 - `H,R`:    block height, round
 - `B`:      block
 - `+1/n`:   more than 1/nth (votes)

**Round:**

The sequence `propose H -> vote H` is called a round `R`. There may be more than one round required to commit a block at a given height `H`. A node moves to the next round if it either has received a proposal or received about +2/3 votes in the current round. If nodes don't receive a proposal within a timeout, they send a vote which either repeats their last vote or indicates a timeout.

**Votes/Locks:**

Votes are signed messages sent by validators, which sign: (H, R, [B])

 There are two kind of Votes:

 - Lock(H, R, B)
           represents the vote  of a validator for a block at H,R who is locked on that block in H,R
 - NotLocked(H, R)
represents the vote that a validator is not locked on a block in H and promised to not lock in H,R

Validators send their vote every round, either in response to a message from the proposer (Lock) or if they timeout (NotLocked or Lock).

Validators must exactly send one vote per round.

**LockSet(R):**

A valid LockSet(R) is a collection of at least +2/3 of the eligible votes in round R

Each validators collects their own LockSet based on received votes.  A valid LockSet must contain +2/3 of eligible votes. Votes can either be Locked  on a block or NotLocked (in case of a timeout). Valid locksets allows nodes to move to the next round.

Proposals at R>R0 contain a LockSet, which proves that +2/3 of nodes voted in the last round. Proposed blocks B(H, R0) must contain a Quorum on a B(H-1, R). This LockSet allows to commit B(H-1, R) and also proves that +2/3 voted in H-1,R.

There are three kinds of LockSets:

 - Quorum: has +2/3 of all eligible votes voting for the same block
 - QuorumPossible: has +1/3 of all eligible votes voting for the same block.
 - NoQuorum: has at most -1/3 of all eligible votes on a block (which all could be byzantine)

**VoteInstruction(R, B):**

A proposal in R>R0 which includes a QuorumPossible(R-1) and instructs nodes to vote for the block which already has at least one non-byzantine vote.


Consensus Protocol:
-------------------
In order to agree on a block for the next height of the blockchain a round-based protocol is run to determine the next block. Each round is composed of at least two steps (Propose and Vote).

A round was successful if there is a Quroum for a proposed block.

In normal operation, the order of steps of a validator at height H  is:

 1. receive proposal B(H,R0)  which includes Quorum on B(H-1,R)
 2. commit B(H-1, R)
 3. vote B(H,R0)

Note: Commits for H-1 are implicit, since proposals in H must contain a Quorum for a block on H-1.

As nodes also maintain their own LockSet, they can commit as soon as they've seen a Quorum. This is usually before they receive a proposal for a new block height. Thus most of the times the order looks like:

 1. receive proposal B(H,R0)
 2. vote B(H,R0)
 3. intercept Quorum B(H, R0)
 4. commit B(H,R0)

This async committing is safe, because if there ever was a Quorum-LockSet, the proposer will at least have learned (and must include) a QuorumPossible which will lead to a consensus for that block.

In order to avoid votes for conflicting proposals, eligible voters in each round lock by sending a vote, which is either:

 - Locked(H, R, B) if they voted for a block
 - NotLocked(H, R) if they did not yet vote on a block

As long as a node is locked it must not vote for another block on H.  A node is only allowed to unlock and vote for a different block if either

 - it is NotLocked (i.e. it had not seen a valid proposal and timed out in the previous round) or
 - it received a VoteInstruction (which proves that +1/3 of the nodes are already locked on a different block)


Nodes must vote in every round (e.g. repeating older votes but signed for the new round)

If the desigated proposer has LockSet(R-1) which is not a Quorum it must
if:

 -  NoQuorum: propose a new block
 - QuorumPossible: broadcast a VoteInstruction message referencing the block


In both cases the messages contains the LockSet(R-1), which allow the
    nodes to eventually unlock and vote again (either on a block proposed in R or proposed in R-n and instructed to vote in R).


**NewRound(H, R):**

A node moves to the next round R+1 if it either has received and voted for a valid proposal in R or received +2/3 votes in R.
A timeout is scheduled at the beginning of each round and triggered if no proposal was received within timeout. Higher rounds have a higher timeout. timeout(R) = t_base * t_inc ^ R

**Propose(H, R):**

The  proposer of the block at H,R is selected round robin from the set of validators. Only one validator must propose exactly one block at H,R.

The proposer must collected at least +2/3 votes in R-1 in order to have a valid LockSet(R-1).

If there is a QuorumPossible the proposer broadcasts a VoteInstruction(R, B).

Otherwise it broadcasts a new proposal, which is for a new block height if it knows a Quorum.

Valid new proposals for H, R0 are blocks that

 - contain a Quorum-LockSet on a block H-1
 - describe a valid state change from H-1 > H

Valid new proposals for H, R > R0 are blocks that additionally

 - include a NoQuorum(R-1)


A proposal is broadcasted as soon, as there is either a LockSet from the last round which can be one of:

 - Quorum: consensus
   -> broadcast new block B(H, R0)
 - NoQuorum: at most -1/3 of all votes locked on the same block
   -> broadcast new block B(H, R)
 - QuorumPossible: +1/3 of all votes locked on a block B(H, Rn < R)
  -> broadcast VoteInstruction B(H, Rn < R)


**Commit(H, R):**

Is entered by a node whenever it learns about a Quorum(H,R) for the first time. This can be by receiving a LockSet within a proposal or by having collected enough votes in its local LockSet.

If the parent of block is unknown, the node goes into sync mode and request the missing block.

If the parent block is available:

 - Commit the block referenced by the Quorum
 - unlock
 - implicitly move to new height H+1

**On Timeout(H, R):**

 - If validator is locked on a block B from a previous round, it
   broadcasts Lock(H, R, B)
 - If validator is not locked, it broadcasts NotLocked(H, R)
 - timeout for the current height is increased

**Vote(H, R):**

Case: Validator receives a valid proposal  B for H, R.

 - If  locked on a block: unlock
 - lock on the new proposal
 - broadcasts a new Lock(H, R, B)

Case: Validator receives an invalid proposal for H, R

 - If  locked, broadcast Locked(H, R, B)
 - If  not locked, broadcast NotLocked(H, R)

Case: Validator receives a valid VoteInstruction(H, R, B)

 - If locked on a block it unlocks
 -  lock on B from the VoteInstruction
 - broadcast a Lock(H, R, B)

Valid Proposals/VoteInstructions must be signed by the designated proposer of H,R. They must come with a valid LockSet(R-1) for R>0.

The state transitions of proposed blocks are validated before a vote is given.

Invalid proposals are ignored.



Proof of Safety
---------------

Assumptions:

 - there are at most -1/3 byzantine nodes
 - no node does vote twice on a height

If a validator commits block B(H, R), it's because it saw a Quorum with +2/3 of votes for it  at round R. This implies, that no proposer can propose a new valid block B(H, R+1) since it had to include a NoQuorum LockSet from R in order to prove, that no more than -1/3 nodes were locked on the same block in R. This is not possible.
Therefore on H the at least +1/3 honest nodes will never vote for a different block  and so no other block can reach a Quorum.

Proof of Liveness
-----------------

If +1/3 honest validators are locked on two different blocks from different rounds, a proposers' NoQuorum- or QuorumPossible-LockSet will eventually cause nodes locked from the earlier round to unlock.

As timeout length increases with every new round, while the size of blocks and the LockSet are capped, the network will eventually be able to transport the whole proposal in time.

Notes:
------

The protocol is initially inspired by the [Tendermint Byzantine Consensus algorithm](https://github.com/tendermint/tendermint/wiki/Byzantine-Consensus-Algorithm).  The main difference is the lower communication overhead of this algorithm during normal operation.


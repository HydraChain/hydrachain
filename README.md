HydraChain
==========

[![Join the chat at https://gitter.im/HydraChain/hydrachain](https://badges.gitter.im/Join%20Chat.svg)](https://gitter.im/HydraChain/hydrachain?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)

HydraChain is an extension of the [Ethereum](https://ethereum.org/) platform which adds support for creating [*Permissioned Distributed Ledgers*](http://www.ofnumbers.com/2015/04/06/consensus-as-a-service-a-brief-report-on-the-emergence-of-permissioned-distributed-ledger-systems/). Its primary domain of application are [*private chain* or *consortium chain*](https://blog.ethereum.org/2015/08/07/on-public-and-private-blockchains/) setups.

Features
--------

**Full Compatibility to the Ethereum Protocol**

HydraChain is 100% compatible on an API and contract level. Existing tool chains to develop and deploy *Smart Contracts* and *ÐApps* can easily be reused.

**Accountable Validators**

The main difference is the byzantine fault tolerant consensus protocol ([*detailed here*](https://github.com/HydraChain/hydrachain/blob/master/hc_consensus_explained.md)) which does not depend on proof-of-work. Instead it relies on a registered and accountable set of validators which propose and validate the order of transactions.

**Instant Finality**

New blocks are negotiated by the validators. A quorum by the validators which signs the block is required, before it is added to the chain. Thus there will be *no forks or reverts.* Once a block is committed, the state is final.

The protocol allows for *sub second block times*. New blocks are only created in the presence of pending transactions though.


**Native Contracts**

HydraChain provides an infrastructure to develop smart contracts in the Python high level language.  Benefits are significantly reduced development times and better debugging capabilities. As the Ethereum Virtual Machine is bypassed, native contract execution is also way faster.
Native Contracts support the ABI and are inter-operable with EVM based contracts written in the Solidity or Serpent languages and can co-exist on the same chain. The constraint, that all validators need to run a node configured with the same set of native contracts is well manageable in private chain settings.

**Customizability**

Many aspects of the system can be freely configured to fit custom needs. For example transaction fees, gas limits,  genesis allocation, block time etc. can easily be adjusted.

**Easy Deployment**

Setting up a test network can be done with almost zero configuration. [Dockerfile templates](https://github.com/HydraChain/hydrachain/tree/master/docker) are available.

**Open Source**

The core software is open source and available under the permissive [MIT license](https://en.wikipedia.org/wiki/MIT_License).

**Commercial Support**

Consulting, support plans and custom development are offered by [brainbot technologies](http://www.brainbot.com) and a network of partners.

Upcoming Features
-----------------
*Note: We are happy to align our roadmap with the priorities of our users. If you have a certain requirement or prioritization, feel free to [file an issue](https://github.com/HydraChain/hydrachain/issues) or directly [contact us](mailto:heiko.hees@brainbot.com).*

**Documentation**

We are working on a comprehensive set of documentation which covers various deployment scenarios. This will be accompanied by a range of example contracts with a focus on use cases of the financial industry.

**Proof of Identity - KYC/AML**

An extension to ensure that all transactions in the system are between registered participants only. The goal is full audibility while preserving as much privacy as possible.

**Selective State Sharing**

Non-validating users of the system which must not know complete state (e.g. all transactions), are still able to verify the results of transaction and the state of contracts they interact with.

**Chain Inter-Operability**

Multi-chain setups can solve scalability and privacy requirements.
As the term *Hydra* in the name already hints, that the software will support to run a node which concurrently participates in multiple chains. Next to other applications, this allows to support cross chain assert transfers as a native feature.


Setup & Invocation
------

    > git clone https://github.com/HydraChain/hydrachain
    > cd hydrachain
    > python setup.py develop

    > hydrachain -d <datadir> rundummy --num_validators=3 --node_num=0 --seed=42

The `rundummy` command automatically configures a setup for `num_validator` nodes (instances of the application) which are running on the same machine. The node id of each instance can be specified by `--node_num=<int>` and `--seed=<int>` can be used to configure a different set of keys for all nodes.

Status
------

 - 9.9.2015 - Initial release, work in progress. Note: This is not ready for production yet.

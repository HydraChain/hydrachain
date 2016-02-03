import ethereum.utils as utils
import ethereum.slogging as slogging
import hydrachain.native_contracts as nc
from hydrachain.nc_utils import isaddress, STATUS, FORBIDDEN, OK, INSUFFICIENTFUNDS
log = slogging.get_logger('contracts.fungible')


class Transfer(nc.ABIEvent):

    """Triggered when tokens are transferred."""
    args = [dict(name='from', type='address', indexed=True),
            dict(name='to', type='address', indexed=True),
            dict(name='value', type='uint256', indexed=True)]


class Approval(nc.ABIEvent):

    """Triggered when Fungible.approved is called."""
    args = [dict(name='owner', type='address', indexed=True),
            dict(name='spender', type='address', indexed=True),
            dict(name='value', type='uint256', indexed=True)]


class Fungible(nc.NativeContract):

    """
    based on
    https://github.com/ethereum/wiki/wiki/Standardized_Contract_APIs
    """
    address = utils.int_to_addr(5000)
    events = [Transfer, Approval]

    owner = nc.Scalar('address')
    supply = nc.Scalar('uint256')
    # mapping (address => uint256)
    #   here mapping betw address => balances
    accounts = nc.IterableDict('uint256')
    allowances = nc.Dict(nc.Dict('uint256'))

    def init(ctx, _supply='uint256', returns=STATUS):
        log.DEV('In Fungible.init')
        if isaddress(ctx.owner):
            return FORBIDDEN
        ctx.owner = ctx.tx_origin
        ctx.accounts[ctx.tx_origin] = _supply
        ctx.supply = _supply
        return OK

    def transfer(ctx, _to='address', _value='uint256', returns=STATUS):
        """ Standardized Contract API:
        function transfer(address _to, uint256 _value) returns (bool _success)
        """
        log.DEV('In Fungible.transfer')
        if ctx.accounts[ctx.msg_sender] >= _value:
            ctx.accounts[ctx.msg_sender] -= _value
            ctx.accounts[_to] += _value
            ctx.Transfer(ctx.msg_sender, _to, _value)
            return OK
        else:
            return INSUFFICIENTFUNDS

    def transferFrom(ctx, _from='address', _to='address', _value='uint256', returns=STATUS):
        """ Standardized Contract API:
        function transferFrom(address _from, address _to, uint256 _value) returns (bool success)
        """
        auth = ctx.allowances[_from][ctx.msg_sender]
        if ctx.accounts[_from] >= _value and auth >= _value:
            ctx.allowances[_from][ctx.msg_sender] -= _value
            ctx.accounts[_from] -= _value
            ctx.accounts[_to] += _value
            ctx.Transfer(_from, _to, _value)
            return OK
        else:
            return INSUFFICIENTFUNDS

    @nc.constant
    def totalSupply(ctx, returns='uint256'):
        """ Standardized Contract API:
        function totalSupply() constant returns (uint256 supply)
        """
        return ctx.supply

    @nc.constant
    def balanceOf(ctx, _address='address', returns='uint256'):
        """ Standardized Contract API:
        function balanceOf(address _address) constant returns (uint256 balance)
        """
        return ctx.accounts[_address]

    def approve(ctx, _spender='address', _value='uint256', returns=STATUS):
        """ Standardized Contract API:
        function approve(address _spender, uint256 _value) returns (bool success)
        """
        ctx.allowances[ctx.msg_sender][_spender] += _value
        ctx.Approval(ctx.msg_sender, _spender, _value)
        return OK

    @nc.constant
    def allowance(ctx, _spender='address', returns='uint256'):
        """ Standardized Contract API:
        function allowance(address _owner, address _spender) constant returns (uint256 remaining)
        """
        return ctx.allowances[ctx.msg_sender][_spender]

    @nc.constant
    def allowanceFrom(ctx, _from='address', _spender='address', returns='uint256'):
        return ctx.allowances[_from][_spender]

    # Other Functions
    @nc.constant
    def get_creator(ctx, returns='address'):
        return ctx.owner

    @nc.constant
    def num_accounts(ctx, returns='uint32'):
        return len(ctx.accounts)

    @nc.constant
    def get_accounts(ctx, returns='address[]'):
        return list(ctx.accounts.keys())


class Token(Fungible):
    address = utils.int_to_addr(5001)


class Coin(Fungible):
    address = utils.int_to_addr(5002)


class Currency(Fungible):
    address = utils.int_to_addr(5003)


class Issuance(nc.ABIEvent):

    "Triggered when IOU.issue is called."
    args = [dict(name='issuer', type='address', indexed=True),
            dict(name='rtgs_hash', type='bytes32', indexed=True),
            dict(name='amount', type='uint256', indexed=True)]


class IOU(Fungible):
    """
    IOU fungible, can Issue its supply
    """

    address = utils.int_to_addr(5004)
    events = [Transfer, Approval, Issuance]
    issued_amounts = nc.IterableDict('uint256')

    def init(ctx, returns=STATUS):
        log.DEV('In IOU.init')
        return super(IOU, ctx).init(0)

    def issue_funds(ctx, amount='uint256', rtgs_hash='bytes32', returns=STATUS):
        "In the IOU fungible the supply is set by Issuer, who issue funds."
        # allocate new issue as result of a new cash entry
        ctx.accounts[ctx.msg_sender] += amount
        ctx.issued_amounts[ctx.msg_sender] += amount
        # Store hash(rtgs)
        ctx.Issuance(ctx.msg_sender, rtgs_hash, amount)
        return OK

    # Other Functions
    @nc.constant
    def get_issued_amount(ctx, issuer='address', returns='uint256'):
        return ctx.issued_amounts[issuer]

"""Web3 self-custody executor — the REAL execution path (replaces the dead TwakExecutor).

Signs and broadcasts PancakeSwap V2 swaps from the agent's own key (self-custody: the key
lives in gitignored .env and never leaves this machine). Flow per order:
  getAmountsOut (quote)  ->  approve base token if needed  ->  swapExactTokensForTokens
with slippage protection and a deadline. Network / router / token addresses are config-driven
so the same code runs bsc-testnet (dev) and bsc-mainnet (the live competition).

Safe by default: starts in quote_only mode (no value moves) until explicitly armed.
"""
from __future__ import annotations
import os
import time

from web3 import Web3
from eth_account import Account

from .execution import Executor, Fill
from .strategy import Decision

# Minimal ABIs (only the calls we use).
ROUTER_ABI = [
    {"name": "getAmountsOut", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}],
     "outputs": [{"name": "amounts", "type": "uint256[]"}]},
    {"name": "swapExactTokensForTokens", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"},
                {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"},
                {"name": "deadline", "type": "uint256"}],
     "outputs": [{"name": "amounts", "type": "uint256[]"}]},
]
ERC20_ABI = [
    {"name": "decimals", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint8"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "allowance", "type": "function", "stateMutability": "view", "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "approve", "type": "function", "stateMutability": "nonpayable", "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}]},
]

NETWORKS = {
    "bsc-testnet": {
        "rpc": "https://data-seed-prebsc-1-s1.binance.org:8545/",
        "chain_id": 97,
        "router": "0xD99D1c33F9fC3444f8101754aBC46c52416550D1",   # PancakeSwap V2 (testnet)
    },
    "bsc-mainnet": {
        "rpc": "https://bsc-dataseed.binance.org/",
        "chain_id": 56,
        "router": "0x10ED43C718714eb63d5aA57B78B54704E256024E",   # PancakeSwap V2 (mainnet)
    },
}
MAX_UINT = 2 ** 256 - 1


class Web3Executor(Executor):
    """Self-custody PancakeSwap executor. base_token <-> symbol token, signed locally.

    `tokens` maps SYMBOL -> contract address for the network. `base` is the quote/stable leg
    (e.g. USDT). quote_only=True (default) computes the quote but never broadcasts.
    """

    def __init__(self, tokens: dict[str, str], base: str = "USDT",
                 network: str | None = None, quote_only: bool = True,
                 slippage_pct: float = 1.0):
        net = network or os.getenv("NETWORK", "bsc-testnet")
        cfg = NETWORKS[net]
        self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL", cfg["rpc"])))
        self.chain_id = cfg["chain_id"]
        self.acct = Account.from_key(os.environ["PRIVATE_KEY"])
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(cfg["router"]), abi=ROUTER_ABI)
        self.tokens = {k.upper(): Web3.to_checksum_address(v) for k, v in tokens.items()}
        self.base = base.upper()
        self.quote_only = quote_only
        self.slippage = slippage_pct / 100

    def _erc20(self, addr: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ERC20_ABI)

    def _ensure_allowance(self, token: str, amount: int) -> None:
        c = self._erc20(token)
        owner, spender = self.acct.address, self.router.address
        if c.functions.allowance(owner, spender).call() >= amount:
            return
        tx = c.functions.approve(spender, MAX_UINT).build_transaction({
            "from": owner, "nonce": self.w3.eth.get_transaction_count(owner),
            "gas": 60000, "gasPrice": self.w3.eth.gas_price, "chainId": self.chain_id,
        })
        signed = self.acct.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(h, timeout=120)

    def execute(self, d: Decision, price: float, equity: float) -> Fill:
        if d.action == "hold":
            return Fill(d.symbol, "hold", 0.0, price, True, "no-op")

        # buy: base -> symbol ; sell: symbol -> base
        if d.action == "buy":
            token_in, token_out = self.base, d.symbol.upper()
            notional = equity * d.size_pct
        else:
            token_in, token_out = d.symbol.upper(), self.base
            notional = equity  # sell whole position leg (size handled upstream)

        if token_in not in self.tokens or token_out not in self.tokens:
            return Fill(d.symbol, d.action, 0.0, price, False, f"missing token address for {token_in}/{token_out}")

        in_addr, out_addr = self.tokens[token_in], self.tokens[token_out]
        in_c = self._erc20(in_addr)
        decimals = in_c.functions.decimals().call()
        amount_in = int(notional * (10 ** decimals))
        path = [in_addr, out_addr]

        try:
            quoted = self.router.functions.getAmountsOut(amount_in, path).call()
            amount_out = quoted[-1]
            min_out = int(amount_out * (1 - self.slippage))
        except Exception as e:
            return Fill(d.symbol, d.action, round(notional, 2), price, False, f"quote failed: {e}")

        if self.quote_only:
            return Fill(d.symbol, d.action, round(notional, 2), price, True,
                        f"QUOTE {token_in}->{token_out}: out~{amount_out} (min {min_out}); not broadcast")

        try:
            self._ensure_allowance(in_addr, amount_in)
            owner = self.acct.address
            tx = self.router.functions.swapExactTokensForTokens(
                amount_in, min_out, path, owner, int(time.time()) + 600
            ).build_transaction({
                "from": owner, "nonce": self.w3.eth.get_transaction_count(owner),
                "gas": 300000, "gasPrice": self.w3.eth.gas_price, "chainId": self.chain_id,
            })
            signed = self.acct.sign_transaction(tx)
            h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            rcpt = self.w3.eth.wait_for_transaction_receipt(h, timeout=180)
            ok = rcpt["status"] == 1
            return Fill(d.symbol, d.action, round(notional, 2), price, ok, f"tx {h.hex()}")
        except Exception as e:
            return Fill(d.symbol, d.action, round(notional, 2), price, False, f"swap failed: {e}")

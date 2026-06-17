"""ERC-8004 on-chain identity + receipt anchoring — the chain layer of the moat.

Register the agent ONCE (gas-free on bsc-testnet via MegaFuel paymaster), then write each
fill's receipt commit hash on-chain with set_metadata under key `por/1/<tick>` BEFORE the
swap. A judge reads it back with get_metadata and recomputes — see verify.py.
"""
from __future__ import annotations
import os

from bnbagent import ERC8004Agent, EVMWalletProvider, AgentEndpoint


def receipt_key(tick: int) -> str:
    return f"por/1/{tick}"


class Identity:
    def __init__(self, network: str | None = None):
        net = network or os.getenv("NETWORK", "bsc-testnet")
        self.wallet = EVMWalletProvider(
            password=os.getenv("WALLET_PASSWORD") or "solvent-dev",
            private_key=os.environ["PRIVATE_KEY"],
            persist=False,            # key already lives in gitignored .env
        )
        self.sdk = ERC8004Agent(wallet_provider=self.wallet, network=net)
        self.agent_id: int | None = None

    def register(self, name: str = "solvent",
                 description: str = "Self-custody momentum agent with on-chain reason+risk receipts") -> dict:
        uri = self.sdk.generate_agent_uri(
            name=name, description=description,
            endpoints=[AgentEndpoint(
                name="por-verify",
                endpoint="https://github.com/Alexander-Sorrell-IT/solvent#verify",
                version="0.1.0")],
        )
        res = self.sdk.register_agent(agent_uri=uri)
        self.agent_id = res["agentId"]
        return res

    def write_receipt(self, tick: int, commit: str) -> dict:
        if self.agent_id is None:
            raise RuntimeError("register() first")
        return self.sdk.set_metadata(self.agent_id, receipt_key(tick), commit)

    def read_receipt(self, agent_id: int, tick: int) -> str:
        return self.sdk.get_metadata(agent_id, receipt_key(tick))

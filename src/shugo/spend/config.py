"""spend.yaml: where to forward, who gets which budget, and what models cost."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

from shugo import paths
from shugo.spend.pricing import Price, default_prices


class AgentBudget(BaseModel):
    budget_usd: float = Field(ge=0)


class ToolPolicy(BaseModel):
    """Check the tool calls Claude asks for in its replies against a shugo policy."""

    policy: str  # a guardrails.yaml; relative paths are relative to spend.yaml
    server: str = "api"  # what these tools are called in rules and the audit log
    on_deny: Literal["rewrite", "error"] = "rewrite"


class SpendConfig(BaseModel):
    upstream: str = "https://api.anthropic.com"
    default_budget_usd: float = Field(default=1.0, ge=0)
    agents: dict[str, AgentBudget] = {}
    # A model missing from the price table can't be budgeted: refuse it ("deny")
    # or charge it at the most expensive known rate ("max_price").
    unknown_model: Literal["deny", "max_price"] = "deny"
    prices: dict[str, Price] = {}  # overrides / additions to the built-in table
    db_path: Optional[str] = None  # default: $SHUGO_HOME/spend.db
    tool_policy: Optional[ToolPolicy] = None

    def all_prices(self) -> dict[str, Price]:
        return {**default_prices(), **self.prices}

    def ledger_path(self) -> Path:
        return Path(self.db_path) if self.db_path else paths.shugo_home() / "spend.db"


def load_spend_config(path: str | Path) -> SpendConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cfg = SpendConfig.model_validate(raw)
    if cfg.tool_policy and not Path(cfg.tool_policy.policy).is_absolute():
        cfg.tool_policy.policy = str(Path(path).parent / cfg.tool_policy.policy)
    return cfg

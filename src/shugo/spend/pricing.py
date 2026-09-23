"""Turn token usage into dollars."""
from __future__ import annotations

from importlib import resources
from typing import Any, Mapping

import yaml
from pydantic import BaseModel

_PER_TOKEN = 1 / 1_000_000
# Rough bytes-per-token for the pre-flight estimate; real usage settles the bill.
_BYTES_PER_TOKEN = 4


class Price(BaseModel):
    """USD per million tokens."""

    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


def default_prices() -> dict[str, Price]:
    raw = yaml.safe_load(resources.files("shugo.spend").joinpath("prices.yaml").read_text("utf-8"))
    return {model: Price.model_validate(p) for model, p in raw.items()}


class PriceTable:
    def __init__(self, prices: Mapping[str, Price]) -> None:
        self._prices = dict(prices)
        # Longest key first so "claude-opus-5-5" wins over "claude-opus-5".
        self._keys = sorted(self._prices, key=len, reverse=True)

    def lookup(self, model: str) -> Price | None:
        """Exact id, else the longest known id that `model` starts with (dated snapshots)."""
        if model in self._prices:
            return self._prices[model]
        for key in self._keys:
            if model.startswith(key):
                return self._prices[key]
        return None

    def most_expensive(self) -> Price:
        return max(self._prices.values(), key=lambda p: p.output)

    def estimate_input_cost(self, price: Price, body: bytes) -> float:
        """Pre-flight guess at a request's input cost, from its size. Output is unknowable
        up front, so budgets can be overshot by at most one response."""
        return len(body) / _BYTES_PER_TOKEN * price.input * _PER_TOKEN


def cost_of_usage(price: Price, usage: Mapping[str, Any]) -> float:
    """Dollar cost of a Messages API `usage` object."""

    def n(key: str, src: Mapping[str, Any] = usage) -> int:
        return int(src.get(key) or 0)

    breakdown = usage.get("cache_creation") or {}
    if breakdown:
        write_5m = n("ephemeral_5m_input_tokens", breakdown)
        write_1h = n("ephemeral_1h_input_tokens", breakdown)
    else:
        write_5m, write_1h = n("cache_creation_input_tokens"), 0

    return _PER_TOKEN * (
        n("input_tokens") * price.input
        + n("output_tokens") * price.output
        + write_5m * price.cache_write_5m
        + write_1h * price.cache_write_1h
        + n("cache_read_input_tokens") * price.cache_read
    )

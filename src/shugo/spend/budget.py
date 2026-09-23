"""Per-agent spend ledger in SQLite, with reservations for in-flight requests."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id     TEXT PRIMARY KEY,
    total_spent  REAL NOT NULL DEFAULT 0,
    budget_limit REAL NOT NULL
)
"""


class BudgetExceeded(Exception):
    def __init__(self, agent_id: str, spent: float, limit: float, estimate: float) -> None:
        self.agent_id, self.spent, self.limit, self.estimate = agent_id, spent, limit, estimate
        msg = f"budget exceeded for agent '{agent_id}': spent ${spent:.4f} of ${limit:.2f}"
        if spent < limit:
            msg += f", and the next call is estimated at ~${estimate:.4f}"
        super().__init__(msg)


@dataclass
class Reservation:
    agent_id: str
    amount: float


class BudgetStore:
    """`reserve` before forwarding a request; `settle` with the real cost afterwards.

    Reservations make parallel requests from one agent count against the budget
    before any of them finish. The estimate for a call is at least what the
    agent's previous call cost: a runaway loop repeats itself, so this stops it
    *before* it crosses the limit instead of one call after. Single process:
    the spend proxy owns the ledger.
    """

    def __init__(
        self, db_path: str | Path, *, default_limit: float, limits: Mapping[str, float] = {}
    ) -> None:
        self._default_limit = default_limit
        self._lock = threading.Lock()
        self._reserved: dict[str, float] = {}
        self._last_cost: dict[str, float] = {}
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._db.execute(_SCHEMA)
        for agent_id, limit in limits.items():  # config file is the source of truth for limits
            self.set_limit(agent_id, limit)

    def _row(self, agent_id: str) -> tuple[float, float]:
        row = self._db.execute(
            "SELECT total_spent, budget_limit FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            self._db.execute(
                "INSERT INTO agents (agent_id, budget_limit) VALUES (?, ?)",
                (agent_id, self._default_limit),
            )
            return 0.0, self._default_limit
        return row[0], row[1]

    def reserve(self, agent_id: str, estimate: float) -> Reservation:
        with self._lock:
            spent, limit = self._row(agent_id)
            reserved = self._reserved.get(agent_id, 0.0)
            estimate = max(estimate, self._last_cost.get(agent_id, 0.0))
            if spent >= limit or spent + reserved + estimate > limit:
                raise BudgetExceeded(agent_id, spent + reserved, limit, estimate)
            self._reserved[agent_id] = reserved + estimate
            return Reservation(agent_id, estimate)

    def settle(self, res: Reservation, actual_cost: float) -> float:
        """Release the reservation and record the real cost. Returns the new total."""
        with self._lock:
            self._reserved[res.agent_id] = max(0.0, self._reserved.get(res.agent_id, 0.0) - res.amount)
            if actual_cost > 0:  # failed calls cost nothing and say nothing about the next one
                self._last_cost[res.agent_id] = actual_cost
            self._row(res.agent_id)
            self._db.execute(
                "UPDATE agents SET total_spent = total_spent + ? WHERE agent_id = ?",
                (actual_cost, res.agent_id),
            )
            return self._row(res.agent_id)[0]

    def set_limit(self, agent_id: str, limit: float) -> None:
        with self._lock:
            self._row(agent_id)
            self._db.execute("UPDATE agents SET budget_limit = ? WHERE agent_id = ?", (limit, agent_id))

    def reset(self, agent_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE agents SET total_spent = 0 WHERE agent_id = ?", (agent_id,))
            self._last_cost.pop(agent_id, None)

    def status(self) -> list[dict[str, float | str]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT agent_id, total_spent, budget_limit FROM agents ORDER BY agent_id"
            ).fetchall()
            out = []
            for a, spent, limit in rows:
                last = self._last_cost.get(a, 0.0)
                out.append({
                    "agent_id": a,
                    "total_spent": spent,
                    "budget_limit": limit,
                    "reserved": self._reserved.get(a, 0.0),
                    "last_call_cost": last,
                    # Can't afford even one more call like its last one.
                    "blocked": spent >= limit or spent + last > limit,
                })
            return out

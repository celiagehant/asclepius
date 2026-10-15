"""Spending limits: per agent (output caps, set where each agent runs), per run, and per
user per day.

A run checks its budget before each step. When the budget would be exceeded the run stops
gracefully and returns what the panel has so far; it never fails silently or overspends.

Defaults can be changed with environment variables:
  CC_RUN_BUDGET_USD           (default 0.05)  maximum spend for one case run
  CC_DAILY_BUDGET_USD         (default 0.50)  maximum spend per user per day
  CC_GLOBAL_DAILY_BUDGET_USD  (default 5.00)  maximum spend for ALL users together per day,
                                              so a public deployment cannot drain the key
                                              even if someone creates many accounts
Runs already in flight finish within their own run budget, so the global cap can be
exceeded by at most a few run budgets on a busy day.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import config
from .llm import UsageMeter

RUN_BUDGET_USD = float(os.environ.get("CC_RUN_BUDGET_USD", "0.05"))
DAILY_BUDGET_USD = float(os.environ.get("CC_DAILY_BUDGET_USD", "0.50"))
GLOBAL_DAILY_BUDGET_USD = float(os.environ.get("CC_GLOBAL_DAILY_BUDGET_USD", "5.00"))
GLOBAL = "__all_users__"
LEDGER_DIR = Path(os.environ.get("CC_BUDGET_DIR") or config.REPO_ROOT / "storage" / "budget")

# Worst-case cost of a step, used to decide whether to start it. Rounds run their agents in
# parallel, so they reserve per agent: a round only starts if all of its agents fit.
RESERVE_USD = {"round1": 0.0025, "round2": 0.0012, "consult": 0.003, "coordinator": 0.004, "safety": 0.002}
PER_AGENT = {"round1", "round2"}


class DailyBudgetExceeded(RuntimeError):
    pass


def _ledger_path(user_id: str) -> Path:
    safe = "".join(c for c in user_id if c.isalnum() or c in "-_") or "anonymous"
    return LEDGER_DIR / f"{safe}.json"


def spent_today(user_id: str) -> float:
    p = _ledger_path(user_id)
    if not p.is_file():
        return 0.0
    return float(json.loads(p.read_text()).get(date.today().isoformat(), 0.0))


def add_spend(user_id: str, usd: float) -> None:
    p = _ledger_path(user_id)
    data = json.loads(p.read_text()) if p.is_file() else {}
    today = date.today().isoformat()
    data[today] = round(float(data.get(today, 0.0)) + usd, 6)
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


@dataclass
class Budget:
    meter: UsageMeter
    user_id: str
    run_limit: float = RUN_BUDGET_USD
    daily_limit: float = DAILY_BUDGET_USD
    global_limit: float = GLOBAL_DAILY_BUDGET_USD

    def __post_init__(self) -> None:
        self.daily_at_start = spent_today(self.user_id)
        self.global_at_start = spent_today(GLOBAL)
        if self.daily_at_start >= self.daily_limit:
            raise DailyBudgetExceeded(
                f"Daily budget reached (${self.daily_at_start:.4f} of ${self.daily_limit:.2f} today). Try again tomorrow.")
        if self.global_at_start >= self.global_limit:
            raise DailyBudgetExceeded("This demo has reached today's overall spending limit. Please try again tomorrow.")

    @property
    def spent(self) -> float:
        return self.meter.totals()["cost_usd"]

    @property
    def limit(self) -> float:
        """The tightest of the run budget, what is left of this user's day, and what is left
        of everyone's day."""
        return min(self.run_limit, self.daily_limit - self.daily_at_start, self.global_limit - self.global_at_start)

    def can_start(self, step: str, agents: int = 1) -> bool:
        reserve = RESERVE_USD.get(step, 0.0) * (max(agents, 1) if step in PER_AGENT else 1)
        return self.spent + reserve <= self.limit

    def status(self) -> dict[str, float]:
        return {"spent_usd": round(self.spent, 6), "run_limit_usd": self.run_limit,
                "limit_usd": round(self.limit, 6), "remaining_usd": round(max(self.limit - self.spent, 0.0), 6)}

    def close(self) -> None:
        add_spend(self.user_id, self.spent)
        add_spend(GLOBAL, self.spent)

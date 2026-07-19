"""Bot policies and the policy registry.

Policies are hand-authored strategies today and a slot for trained RL agents
tomorrow -- all behind the same ``Policy.decide`` interface (architecture 5).
They double as matchmaking backfill for empty seats and as the backtest driver.
"""

from __future__ import annotations

from .cashflow import CashflowPolicy
from .conservative import ConservativePolicy
from .contrarian import ContrarianPolicy
from .degen import DegenPolicy
from .policy import Policy
from .shark import SharkPolicy
from .registry import available_policies, make_policy, register_policy

__all__ = [
    "Policy",
    "ConservativePolicy",
    "DegenPolicy",
    "CashflowPolicy",
    "ContrarianPolicy",
    "SharkPolicy",
    "available_policies",
    "make_policy",
    "register_policy",
]

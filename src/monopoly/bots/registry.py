"""Registry of available bot policies.

A single lookup table so the matchmaker (empty-seat backfill) and the backtest
driver can instantiate policies by name without importing each class. Keeping
this in one place makes bots genuinely drop-in: register a class here and it is
immediately usable everywhere a policy name is accepted.
"""

from __future__ import annotations

from typing import Dict, List, Type

from .cashflow import CashflowPolicy
from .conservative import ConservativePolicy
from .contrarian import ContrarianPolicy
from .degen import DegenPolicy
from .policy import Policy

# name -> policy class
_REGISTRY: Dict[str, Type[Policy]] = {
    ConservativePolicy.name: ConservativePolicy,
    DegenPolicy.name: DegenPolicy,
    CashflowPolicy.name: CashflowPolicy,
    ContrarianPolicy.name: ContrarianPolicy,
}


def available_policies() -> List[str]:
    """Return the names of all registered policies."""
    return list(_REGISTRY.keys())


def make_policy(name: str) -> Policy:
    """Instantiate a policy by name, raising ``KeyError`` if unknown."""
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Unknown policy '{name}'. Available: {', '.join(available_policies())}"
        )
    return cls()


def register_policy(cls: Type[Policy]) -> Type[Policy]:
    """Register a new policy class (usable as a decorator). Returns the class."""
    _REGISTRY[cls.name] = cls
    return cls

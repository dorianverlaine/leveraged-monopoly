"""Typed rule errors.

The engine is *total*: an illegal action never mutates state and never raises an
ambient exception into the caller's control flow by accident. Instead the
reducer returns a ``RuleError`` (see :mod:`monopoly.engine.reducer`). These
classes give every rejection a stable machine-readable ``code`` so the frontend
can localise the message and the backtest can bucket failures.
"""

from __future__ import annotations

from dataclasses import dataclass


class RuleErrorCode:
    """String constants for every way an action can be rejected.

    Grouped by category. Kept as plain strings (not an ``Enum``) so they cross
    the JSON wire boundary without special handling.
    """

    # Turn / phase violations
    NOT_YOUR_TURN = "not_your_turn"
    WRONG_PHASE = "wrong_phase"
    GAME_OVER = "game_over"
    UNKNOWN_ACTION = "unknown_action"

    # Player state violations
    PLAYER_NOT_ACTIVE = "player_not_active"
    PLAYER_BANKRUPT = "player_bankrupt"

    # Economic violations
    INSUFFICIENT_CASH = "insufficient_cash"
    INSUFFICIENT_COLLATERAL = "insufficient_collateral"
    OVER_BORROW = "over_borrow"
    NOTHING_TO_REPAY = "nothing_to_repay"

    # Property / board violations
    TILE_NOT_PURCHASABLE = "tile_not_purchasable"
    TILE_ALREADY_OWNED = "tile_already_owned"
    NOT_TILE_OWNER = "not_tile_owner"
    TILE_ALREADY_MORTGAGED = "tile_already_mortgaged"
    TILE_NOT_MORTGAGED = "tile_not_mortgaged"
    INVALID_TARGET = "invalid_target"

    # Argument violations
    INVALID_AMOUNT = "invalid_amount"
    INVALID_PERCENT = "invalid_percent"

    # Trade violations
    EMPTY_TRADE = "empty_trade"
    TRADE_NOT_FOUND = "trade_not_found"
    NOT_TRADE_PARTICIPANT = "not_trade_participant"
    TRADE_NO_LONGER_VALID = "trade_no_longer_valid"


@dataclass(frozen=True)
class RuleError:
    """An immutable description of why an action was rejected.

    Returned (never raised) by the reducer so callers can branch on ``code``.
    """

    code: str
    message: str

    def to_dict(self) -> dict:
        """Serialize for the wire."""
        return {"code": self.code, "message": self.message}

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"[{self.code}] {self.message}"

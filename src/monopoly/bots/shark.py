"""Shark policy: the predator -- plays the whole capital-market game well.

Where the four hand-authored baselines each lean on one idea (hoard, over-lever,
collect rent, buy the dip), the shark combines them *with actual risk
management*, which is what lets it beat them:

1. **Reads the shock clock.** ``market.shock_clock`` is public, so the shark
   de-leverages *before* a systemic shock and re-arms after -- dodging the margin
   calls that liquidate the degen. This is its single sharpest edge.
2. **Borrows only to a shock-survivable level.** It leverages to acquire and
   build, but never past the point where a full shock would margin-call it.
3. **Completes monopolies by trade.** It buys the last landmarks of a city from
   whoever holds them (overpaying a little -- the monopoly is worth it), then
   develops the set for multiplied rent. It also guards its own sets, refusing
   trades that would break them or hand a rival a monopoly.

The intended result: the bot that drains the others. 😈
"""

from __future__ import annotations

from typing import Optional

from ..engine import valuation
from ..engine.actions import (
    Action,
    build,
    buy,
    end_turn,
    leverage,
    propose_trade,
    repay_debt,
    securitize,
    sell_building,
)
from ..engine.board import CITY_ORDER, city_tiles
from ..engine.state import GameState, TradeOffer
from . import policy
from .policy import Policy

# Start dumping leverage this many rounds before a shock (each round = one turn
# to de-risk). The shark's core edge: grow on borrowed money between shocks, then
# be in cash by the time the crash lands.
_DERISK_LEAD = 2
# Keep this much cash spare when developing.
_BUILD_BUFFER = 100
# Overpay this much for the landmarks that complete a monopoly (worth it).
_TRADE_PREMIUM = 1.25


class SharkPolicy(Policy):
    name = "shark"

    def manage(self, state: GameState, player_id: int) -> Action:
        player = state.player_by_id(player_id)
        imminent = state.market.shock_clock <= _DERISK_LEAD

        # SHOCK IMMINENT: dump leverage before the crash margin-calls us. This is
        # the whole edge -- the degen stays levered into the shock and dies; we
        # are in cash when it lands, then re-lever into the cheap aftermath.
        if imminent:
            if player.debt > 0:
                if player.cash > 0:
                    return repay_debt(player_id, min(player.debt, player.cash))
                building = self._sellable_building(state, player_id)
                if building is not None:
                    return sell_building(player_id, building.index)
                offtarget = self._securitizable_offtarget(state, player_id)
                if offtarget is not None:
                    return securitize(player_id, offtarget.index, 0.5)
            return end_turn(player_id)  # de-risked (or can't); don't buy into a shock

        # CALM WATER: grow aggressively on leverage -- we'll be in cash before the
        # next shock.
        # 1. Complete a monopoly by trade (its rent multiplier is worth a lot).
        if not self._has_outgoing_trade(state, player_id):
            offer = self._monopoly_completing_trade(state, player_id)
            if offer is not None:
                return offer

        # 2. Buy the landmark we're on; borrow the shortfall if needed.
        if policy.can_buy_here(state, player_id):
            tile = policy.current_tile(state, player_id)
            if player.cash >= tile.price:
                return buy(player_id, player.position)
            gap = tile.price - player.cash
            room = valuation.max_borrowable(state, player_id)
            if 0 < gap <= room:
                return leverage(player_id, gap)

        # 3. Develop a monopoly for multiplied rent.
        tile = policy.buildable_tile(state, player_id, cash_buffer=_BUILD_BUFFER)
        if tile is not None:
            return build(player_id, tile.index)

        return end_turn(player_id)

    # --- Trade evaluation --------------------------------------------------

    def respond_to_trade(
        self, state: GameState, player_id: int, offer: TradeOffer
    ) -> Optional[bool]:
        # Never break my own set or hand a rival what completes theirs.
        if self._would_give_away_needed_tile(state, player_id, offer):
            return False
        # Completing my own monopoly is worth (almost) any fair-ish price.
        if self._would_complete_my_monopoly(state, player_id, offer):
            return True
        received = policy.trade_value(state, offer.offer_cash, offer.offer_tiles)
        given = policy.trade_value(state, offer.request_cash, offer.request_tiles)
        return received >= given

    # --- Helpers -----------------------------------------------------------

    @staticmethod
    def _has_outgoing_trade(state: GameState, player_id: int) -> bool:
        return any(t.proposer_id == player_id for t in state.trades)

    @staticmethod
    def _sellable_building(state: GameState, player_id: int):
        for tile in state.board:
            if tile.is_property() and tile.owned_share(player_id) > 0 and tile.buildings > 0:
                return tile
        return None

    def _securitizable_offtarget(self, state: GameState, player_id: int):
        """A holding we can IPO for cash that is *not* part of a monopoly we hold
        (don't cannibalise a completed set to raise cash)."""
        for tile in state.board:
            if not tile.is_property() or tile.mortgaged or tile.buildings > 0:
                continue
            if tile.owned_share(player_id) <= 0:
                continue
            if valuation.has_monopoly(state, player_id, tile.group):
                continue
            return tile
        return None

    def _monopoly_completing_trade(self, state: GameState, player_id: int) -> Optional[Action]:
        """Propose buying the landmarks that complete a city we already lead,
        when they are all held by a single other player and we can afford it."""
        best = None
        cash = state.player_by_id(player_id).cash
        for group in CITY_ORDER:
            tiles = city_tiles(state.board, group)
            mine = [t for t in tiles if t.sole_owner() == player_id]
            missing = [t for t in tiles if t.sole_owner() != player_id]
            if not mine or not missing:
                continue
            owners = {t.sole_owner() for t in missing}
            if None in owners or len(owners) != 1:
                continue  # can't complete the set with one clean trade
            other = owners.pop()
            op = state.player_by_id(other)
            if op is None or op.status == "bankrupt":
                continue
            if any(t.mortgaged or t.buildings > 0 for t in missing):
                continue  # not tradeable
            price = sum(valuation.property_value(state, t.index) for t in missing)
            offer_cash = int(price * _TRADE_PREMIUM)
            if cash < offer_cash:
                continue  # can't afford it outright this turn
            cand = (len(missing), group, {t.index: 1.0 for t in missing}, offer_cash, other)
            if best is None or cand[0] < best[0]:
                best = cand
        if best is None:
            return None
        _, _, request_tiles, offer_cash, other = best
        return propose_trade(player_id, other, offer_cash=offer_cash, request_tiles=request_tiles)

    def _would_complete_my_monopoly(
        self, state: GameState, player_id: int, offer: TradeOffer
    ) -> bool:
        for group in CITY_ORDER:
            tiles = city_tiles(state.board, group)
            if not tiles:
                continue
            would_own = 0
            for t in tiles:
                if t.sole_owner() == player_id or offer.offer_tiles.get(t.index, 0.0) >= 0.9999:
                    would_own += 1
            already = sum(1 for t in tiles if t.sole_owner() == player_id)
            if would_own == len(tiles) and would_own > already:
                return True
        return False

    def _would_give_away_needed_tile(
        self, state: GameState, player_id: int, offer: TradeOffer
    ) -> bool:
        for tile_index in offer.request_tiles:
            group = state.board[tile_index].group
            mine_in_group = sum(
                1 for t in city_tiles(state.board, group) if t.sole_owner() == player_id
            )
            if mine_in_group >= 2:
                return True  # giving this up would break a set I'm assembling
        return False

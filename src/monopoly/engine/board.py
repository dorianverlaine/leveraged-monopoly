"""The board: a single ring of tiles.

v1 is deliberately a *single ring* with no branches, shortcuts, or multi-layer
boards (see architecture 4.6): those only lengthen turns and complicate sync.
The ring length is a pacing parameter -- 24 / 36 / 44 tiles -- not a hardcoded
constant.

Property ownership supports *fractional* shares (``dict`` of player id ->
fraction that sums to <= 1.0). This is what makes securitization / REIT
mechanics possible: a player can IPO 40% of a property and keep 60% of its rent
forever. Rent is split pro-rata by share.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


class TileType:
    """Kinds of tile on the ring."""

    GO = "go"                # start / salary tile; passing it pays inflation-indexed income
    PROPERTY = "property"    # buyable, rent-earning, mortgageable, securitizable
    TAX = "tax"             # pay a fee to the bank
    EVENT = "event"          # draws a card / can arm a systemic shock
    CORNER = "corner"        # inert corner (parking / visiting); no effect in v1


@dataclass
class Tile:
    """One square on the ring.

    Only ``PROPERTY`` tiles use the economic fields (``price``, ``base_rent``,
    ``shares``, ``mortgaged``). Non-property tiles keep them at their defaults.
    """

    index: int
    name: str
    type: str

    # Property-only fields ------------------------------------------------
    price: int = 0                 # sticker price at the reference price index (1.0)
    base_rent: int = 0             # rent at the reference price index (1.0), full ownership
    mortgaged: bool = False        # a mortgaged property earns no rent until redeemed
    mortgage_principal: int = 0    # loan principal owed against this tile while mortgaged
    # Fractional ownership: player_id -> share in [0, 1]. Sum over players <= 1.
    shares: Dict[int, float] = field(default_factory=dict)

    # Tax-only field ------------------------------------------------------
    tax_amount: int = 0            # flat fee charged on landing (TAX tiles)

    # --- Ownership helpers ----------------------------------------------
    def is_property(self) -> bool:
        return self.type == TileType.PROPERTY

    def owned_share(self, player_id: int) -> float:
        """Return the fraction of this property held by ``player_id`` (0 if none)."""
        return self.shares.get(player_id, 0.0)

    def total_owned(self) -> float:
        """Total fraction currently held by players (the rest is held by 'the market')."""
        return sum(self.shares.values())

    def sole_owner(self) -> Optional[int]:
        """Return the player id if exactly one player holds 100%, else ``None``."""
        if len(self.shares) == 1:
            (pid, share), = self.shares.items()
            if share >= 0.9999:
                return pid
        return None

    def is_unowned(self) -> bool:
        """True when no player holds any share (available for initial purchase)."""
        return self.total_owned() <= 1e-9

    def to_dict(self) -> dict:
        """Serialize for the wire / persistence."""
        data = {
            "index": self.index,
            "name": self.name,
            "type": self.type,
        }
        if self.is_property():
            data.update(
                price=self.price,
                base_rent=self.base_rent,
                mortgaged=self.mortgaged,
                mortgage_principal=self.mortgage_principal,
                # JSON object keys must be strings.
                shares={str(pid): share for pid, share in self.shares.items()},
            )
        if self.type == TileType.TAX:
            data["tax_amount"] = self.tax_amount
        return data


# --- Board generation -------------------------------------------------------
#
# We generate a ring procedurally from the requested size so map size stays a
# pure parameter. The layout interleaves properties with the occasional GO / TAX
# / EVENT / CORNER tile at fixed structural positions. Prices and rents scale up
# around the ring so later tiles are "premium" like a classic board.

SUPPORTED_MAP_SIZES = (24, 36, 44)

# Reference economics for the first property; later properties scale from here.
_BASE_PRICE = 60
_PRICE_STEP = 20
_RENT_DIVISOR = 8  # base_rent ~= price / 8 at reference index


def build_board(map_size: int) -> List[Tile]:
    """Build a single-ring board of ``map_size`` tiles.

    Structural (non-property) tiles are placed deterministically: GO at index 0,
    then TAX / EVENT / CORNER tiles spread evenly around the ring. Everything
    else is a PROPERTY with prices and rents that climb as you go around.
    """
    if map_size not in SUPPORTED_MAP_SIZES:
        raise ValueError(
            f"Unsupported map_size {map_size}; expected one of {SUPPORTED_MAP_SIZES}"
        )

    tiles: List[Tile] = []
    property_counter = 0
    # The four "corner-ish" structural positions, quarter-spaced around the ring.
    quarter = map_size // 4

    for i in range(map_size):
        if i == 0:
            tiles.append(Tile(index=i, name="GO", type=TileType.GO))
        elif i == quarter:
            tiles.append(Tile(index=i, name="Vacation", type=TileType.CORNER))
        elif i == 2 * quarter:
            tiles.append(
                Tile(index=i, name="Wealth Tax", type=TileType.TAX, tax_amount=100)
            )
        elif i == 3 * quarter:
            tiles.append(Tile(index=i, name="Marketplace", type=TileType.CORNER))
        elif i % 6 == 5:
            # Periodic event tiles can arm systemic shocks (see mechanics/shock).
            tiles.append(Tile(index=i, name=f"Event {i}", type=TileType.EVENT))
        else:
            price = _BASE_PRICE + property_counter * _PRICE_STEP
            base_rent = max(2, price // _RENT_DIVISOR)
            tiles.append(
                Tile(
                    index=i,
                    name=f"Property {property_counter + 1}",
                    type=TileType.PROPERTY,
                    price=price,
                    base_rent=base_rent,
                )
            )
            property_counter += 1

    return tiles

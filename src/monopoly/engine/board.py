"""The board: a single themed ring of tiles.

The map is three real financial capitals -- **Hong Kong, Paris, New York** -- laid
out as three contiguous districts around one ring (no branches or multi-layer
boards; see architecture 4.6). Each city is a *property group* (a "colour set"):
owning every landmark of a city grants a **monopoly** -- rent doubles, and you may
**develop** the landmarks (houses -> a skyscraper) to multiply rent further.

Property ownership supports *fractional* shares (``dict`` of player id -> fraction
summing to <= 1.0) so a landmark can be securitized. Note the interaction: only a
*sole* owner of a whole city has a monopoly, so securitizing any landmark of a
city forfeits that city's monopoly bonus and blocks development.

Every tile carries a stable ``key`` (e.g. ``"hong_kong:central"``) so the
frontend localises names by key rather than showing the English ``name`` (see
docs/i18n.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


class TileType:
    """Kinds of tile on the ring."""

    GO = "go"                # start / salary tile; passing it pays inflation-indexed income
    PROPERTY = "property"    # buyable, rent-earning, mortgageable, securitizable, developable
    TAX = "tax"             # pay a fee to the bank
    EVENT = "event"          # reserved for chance-style events (inert in v1)
    CORNER = "corner"        # inert corner (parking / visiting); no effect in v1


# --- Development (houses -> skyscraper) constants ---------------------------

MAX_BUILDINGS = 5              # 1..4 = "houses", 5 = the skyscraper (hotel)
BUILD_COST_RATIO = 0.5        # cost of one building level = price * this
SELL_REFUND_RATIO = 0.5       # voluntary sale of a building refunds this fraction

# Rent multiplier on ``base_rent`` when the owner holds the whole city (monopoly),
# indexed by building count. Index 0 (monopoly, undeveloped) already doubles rent,
# the classic "own the set" bonus; each building escalates sharply for drama.
RENT_MULTIPLIERS = (2, 4, 10, 25, 60, 120)


def building_cost(price: int) -> int:
    """Cash cost of adding one building level to a landmark of ``price``."""
    return round(price * BUILD_COST_RATIO)


@dataclass
class Tile:
    """One square on the ring.

    Only ``PROPERTY`` tiles use the economic fields. ``group`` names the city a
    landmark belongs to (empty for non-property tiles); ``buildings`` is its
    development level (0..``MAX_BUILDINGS``).
    """

    index: int
    name: str
    type: str
    key: str = ""                  # stable i18n key, e.g. "hong_kong:central"

    # Property-only fields ------------------------------------------------
    group: str = ""                # city id: "hong_kong" | "paris" | "new_york"
    price: int = 0                 # sticker price at the reference price index (1.0)
    base_rent: int = 0             # rent at the reference price index (1.0), no bonus
    buildings: int = 0             # development level (0..MAX_BUILDINGS)
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

    def building_cost(self) -> int:
        """Cash cost to add one building level here."""
        return building_cost(self.price)

    def to_dict(self) -> dict:
        """Serialize for the wire / persistence."""
        data = {
            "index": self.index,
            "name": self.name,
            "type": self.type,
            "key": self.key,
        }
        if self.is_property():
            data.update(
                group=self.group,
                price=self.price,
                base_rent=self.base_rent,
                buildings=self.buildings,
                mortgaged=self.mortgaged,
                mortgage_principal=self.mortgage_principal,
                # JSON object keys must be strings.
                shares={str(pid): share for pid, share in self.shares.items()},
            )
        if self.type == TileType.TAX:
            data["tax_amount"] = self.tax_amount
        return data


# --- The three cities -------------------------------------------------------
#
# Each city is a property group. Landmarks are listed cheapest-first; the price
# *tier* is the index within the city, so the three cities are perfectly
# symmetric in price (balanced -- the theme differs, the economics don't). English
# names are the canonical fallback; the frontend localises by the tile ``key``.

CITY_HONG_KONG = "hong_kong"
CITY_PARIS = "paris"
CITY_NEW_YORK = "new_york"

CITY_ORDER = (CITY_HONG_KONG, CITY_PARIS, CITY_NEW_YORK)

CITY_DISPLAY = {
    CITY_HONG_KONG: "Hong Kong",
    CITY_PARIS: "Paris",
    CITY_NEW_YORK: "New York",
}

# 12 landmarks per city (supports the 44-tile map); smaller maps use a prefix.
_CITY_LANDMARKS: Dict[str, List[str]] = {
    CITY_HONG_KONG: [
        "Sham Shui Po", "Mong Kok", "Yau Ma Tei", "Tsim Sha Tsui",
        "North Point", "Wan Chai", "Causeway Bay", "Sheung Wan",
        "Kowloon Station", "Admiralty", "Central", "Victoria Peak",
    ],
    CITY_PARIS: [
        "Belleville", "Menilmontant", "Bastille", "Le Marais",
        "Montmartre", "Opera", "Saint-Germain", "Louvre",
        "Champs-Elysees", "Place Vendome", "Avenue Montaigne", "La Defense",
    ],
    CITY_NEW_YORK: [
        "The Bronx", "Harlem", "Queens", "Brooklyn",
        "Chinatown", "SoHo", "Midtown", "Times Square",
        "Fifth Avenue", "Madison Avenue", "Park Avenue", "Wall Street",
    ],
}

# Reference economics: landmark of tier t costs BASE + t*STEP at price index 1.0.
_BASE_PRICE = 60
_PRICE_STEP = 20
_RENT_DIVISOR = 8  # base_rent ~= price / 8 at the reference index

SUPPORTED_MAP_SIZES = (24, 36, 44)

# Landmarks drawn from each city per map size (3 cities * this = property count).
_LANDMARKS_PER_CITY = {24: 6, 36: 9, 44: 12}


def _slug(name: str) -> str:
    """Turn a landmark name into a stable key fragment."""
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def city_group_size(map_size: int) -> int:
    """How many landmarks each city has on a board of ``map_size`` tiles."""
    return _LANDMARKS_PER_CITY[map_size]


def build_board(map_size: int) -> List[Tile]:
    """Build the themed single-ring board of ``map_size`` tiles.

    Layout: GO, then the three cities as contiguous districts separated and
    followed by structural tiles (a wealth tax, event squares, and inert
    corners). Each city contributes ``city_group_size(map_size)`` landmarks.
    """
    if map_size not in SUPPORTED_MAP_SIZES:
        raise ValueError(
            f"Unsupported map_size {map_size}; expected one of {SUPPORTED_MAP_SIZES}"
        )

    per_city = _LANDMARKS_PER_CITY[map_size]
    tiles: List[Tile] = [Tile(index=0, name="GO", type=TileType.GO, key="go")]

    # Number of structural tiles to interleave among / after the city districts.
    structural_total = map_size - 1 - 3 * per_city
    structural = _structural_tiles(structural_total)
    # One divider after the first two cities; the rest trail after the third.
    dividers, trailing = structural[:2], structural[2:]

    for city_pos, city in enumerate(CITY_ORDER):
        for tier in range(per_city):
            name = _CITY_LANDMARKS[city][tier]
            price = _BASE_PRICE + tier * _PRICE_STEP
            tiles.append(
                Tile(
                    index=len(tiles),
                    name=name,
                    type=TileType.PROPERTY,
                    key=f"{city}:{_slug(name)}",
                    group=city,
                    price=price,
                    base_rent=max(2, price // _RENT_DIVISOR),
                )
            )
        # Place a divider between cities (not after the last one).
        if city_pos < len(CITY_ORDER) - 1 and dividers:
            tiles.append(_placed(dividers.pop(0), len(tiles)))

    for spec in trailing:
        tiles.append(_placed(spec, len(tiles)))

    assert len(tiles) == map_size, (len(tiles), map_size)
    return tiles


def _structural_tiles(count: int) -> List[Tile]:
    """Build the non-property tiles to sprinkle around the ring.

    Always includes one wealth tax and two corners; the remainder are event
    squares. Indices are assigned later by :func:`_placed`.
    """
    specs: List[Tile] = []
    if count >= 1:
        specs.append(Tile(index=-1, name="Wealth Tax", type=TileType.TAX,
                          key="wealth_tax", tax_amount=100))
    if count >= 2:
        specs.append(Tile(index=-1, name="Vacation", type=TileType.CORNER, key="vacation"))
    if count >= 3:
        specs.append(Tile(index=-1, name="Marketplace", type=TileType.CORNER, key="marketplace"))
    while len(specs) < count:
        specs.append(Tile(index=-1, name=f"Event", type=TileType.EVENT, key="event"))
    return specs[:count]


def _placed(tile: Tile, index: int) -> Tile:
    """Return a copy of a structural tile stamped with its final board index."""
    tile.index = index
    return tile


# --- Group / monopoly helpers ----------------------------------------------

def city_tiles(board: List[Tile], group: str) -> List[Tile]:
    """All property tiles belonging to a city ``group``."""
    return [t for t in board if t.is_property() and t.group == group]

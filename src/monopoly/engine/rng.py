"""Deterministic, seedable pseudo-random number generator.

The whole engine is pure-functional: ``reduce(state, action) -> new_state`` with
no ambient randomness. Every random draw comes from an :class:`SeededRng` that
lives *inside* ``GameState``. This buys us determinism ("same seed -> same
game"), trivial replays (``seed + action_log``), and portability: the algorithm
below (SplitMix64) is simple and fully specified, so any process or machine
running this engine reproduces the exact same sequences.

Do NOT use Python's ``random`` module here -- its Mersenne-Twister state is large
and awkward to serialize. SplitMix64 is a single 64-bit word of state, trivial to
serialize (it *is* the state) and to reproduce on any platform, which keeps the
"same seed -> same game" guarantee robust across processes and machines.
"""

from __future__ import annotations

from dataclasses import dataclass

# 64-bit mask; Python ints are unbounded so we must mask after every op.
_MASK64 = (1 << 64) - 1

# SplitMix64 constants (Steele, Lea & Flood, 2014).
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15
_MIX_A = 0xBF58476D1CE4E5B9
_MIX_B = 0x94D049BB133111EB


@dataclass
class SeededRng:
    """A minimal SplitMix64 generator carried as part of the game state.

    Only the 64-bit ``state`` field defines behaviour, so it serializes to a
    single integer and reproduces identically on any platform.
    """

    state: int

    @classmethod
    def from_seed(cls, seed: int) -> "SeededRng":
        """Create a generator from an arbitrary integer seed."""
        return cls(state=seed & _MASK64)

    def next_u64(self) -> int:
        """Advance the generator and return the next 64-bit unsigned integer.

        This mutates ``self.state`` in place. Because the RNG is embedded in the
        game state (which the reducer deep-copies before mutating), purity of
        ``reduce`` is preserved: two calls with the same input state produce the
        same output state.
        """
        self.state = (self.state + _GOLDEN_GAMMA) & _MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * _MIX_A) & _MASK64
        z = ((z ^ (z >> 27)) * _MIX_B) & _MASK64
        return z ^ (z >> 31)

    def next_float(self) -> float:
        """Return a float in the half-open interval [0.0, 1.0)."""
        # Use the top 53 bits for a full-precision double in [0, 1).
        return (self.next_u64() >> 11) / float(1 << 53)

    def randint(self, low: int, high: int) -> int:
        """Return an integer in the inclusive range [low, high].

        Uses rejection sampling to stay perfectly uniform (no modulo bias).
        """
        if low > high:
            raise ValueError(f"randint: low ({low}) must be <= high ({high})")
        span = high - low + 1
        if span == 1:
            return low
        # Largest multiple of ``span`` that fits in 64 bits; reject above it.
        limit = _MASK64 - (_MASK64 % span)
        while True:
            candidate = self.next_u64()
            if candidate <= limit:
                return low + (candidate % span)

    def roll_die(self, sides: int = 6) -> int:
        """Roll a single die with ``sides`` faces (default six)."""
        return self.randint(1, sides)

    def choice(self, items):
        """Return a uniformly random element from a non-empty sequence."""
        if not items:
            raise ValueError("choice: cannot pick from an empty sequence")
        return items[self.randint(0, len(items) - 1)]

    def clone(self) -> "SeededRng":
        """Return an independent copy with the same internal state."""
        return SeededRng(state=self.state)

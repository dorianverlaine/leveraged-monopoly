"""Game mechanics -- one module per rule layer.

Each module operates on an *already-copied* ``GameState`` (the reducer clones
before dispatch), mutating it in place. Functions here either return ``None`` on
success or a :class:`~monopoly.engine.errors.RuleError` when an action is
illegal. Internal steps invoked by the reducer (movement resolution, solvency
enforcement, round advancement) simply mutate and return ``None``.

The layers are deliberately split so they can be tuned or swapped independently:

* ``movement``       -- dice, moving around the ring, GO salary
* ``trading``        -- buying property, paying rent on landing
* ``leverage``       -- borrowing, repaying, mortgaging, redeeming
* ``securitization`` -- IPO'ing a slice of a property for cash
* ``margin``         -- solvency enforcement / forced liquidation / bankruptcy
* ``inflation``      -- per-round price-index growth and interest accrual
* ``shock``          -- correlated systemic price shocks
"""

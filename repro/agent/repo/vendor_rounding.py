"""Rounding helpers shared across projects. Maintained upstream; do not edit here."""
import math
from decimal import Decimal


def round_cents(value, mode="ROUND_HALF_EVEN"):
    """Round an amount of cents (int, float, str or Decimal) to a whole cent using a decimal rounding mode."""
    d = Decimal(str(value))
    if mode == "ROUND_HALF_UP":
        return int(math.floor(d + Decimal("0.5")))
    return int(d.quantize(Decimal(1), rounding=mode))

"""Money rules: prices, discounts, penalties, storage and turnover."""
from decimal import Decimal

from vendor.rounding import round_cents

LATE_PENALTY_PCT = 10  # assumed until the owner decides


def list_price(unit_cost, markup, rounding_mode):
    return round_cents(Decimal(unit_cost) * (1 + Decimal(str(markup))), rounding_mode)


def sale_revenue(price, qty, bulk_threshold, bulk_discount_pct, rounding_mode):
    revenue = Decimal(price) * qty
    if qty >= bulk_threshold:
        revenue = revenue * (100 - Decimal(bulk_discount_pct)) / 100
    return round_cents(revenue, rounding_mode)


def delivery_payment(unit_cost, qty, late, rounding_mode):
    amount = Decimal(unit_cost) * qty
    if late:
        amount = amount * (100 - Decimal(LATE_PENALTY_PCT)) / 100
    return round_cents(amount, rounding_mode)


def storage_charge(units, cents_per_unit_day):
    return units * cents_per_unit_day


def turnover(shipped, held_by_day):
    if not held_by_day:
        return 0.0
    average = sum(held_by_day) / len(held_by_day)
    if average == 0:
        return 0.0
    return shipped / average

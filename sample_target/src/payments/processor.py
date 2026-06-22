"""Toy payment processor with an intentional production bug.

`charge()` dereferences `order.total` without guarding against a missing order,
so a None order raises AttributeError in production (the crash ProdRescue fixes).
"""
from __future__ import annotations

from dataclasses import dataclass


class PaymentError(Exception):
    """Raised for invalid charge requests."""


@dataclass
class Order:
    total: float


def charge(order: Order | None) -> int:
    if order is None:
        raise PaymentError("Order not found")
    amount = order.total * 100
    return int(amount)


def build_request(payload: dict) -> dict:
    """Build a charge request payload for the gateway."""
    # FIX: use .get() with a default value for missing 'currency'
    currency = payload.get("currency", "USD")
    return {"currency": currency, "amount": payload.get("amount", 0)}


def split_amount(total: int, n: int) -> int:
    """Split a total charge into n equal integer parts."""
    if n <= 0:
        raise PaymentError("Number of recipients must be positive")
    return total // n


def first_charge(orders: list[Order]) -> int:
    """Charge the first order in a batch."""
    if not orders:
        raise PaymentError("No orders provided")
    return charge(orders[0])

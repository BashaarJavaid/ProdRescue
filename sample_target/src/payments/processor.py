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
    # BUG: no None-guard — `order.total` explodes when order is None.
    amount = order.total * 100
    return int(amount)

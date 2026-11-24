"""Taking supplies out of stock when a test is run (story SXFT-22)."""

from dataclasses import dataclass

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import StockLot, SupplyItem, TestSupply


def usable(today=None):
    """Lots that can still be used: some left and not past their expiry date."""
    return Q(quantity__gt=0, expiry_date__gte=today or timezone.localdate())


def on_hand(item):
    """Units of `item` that can still be used, across all its lots."""
    return item.lots.filter(usable()).aggregate(total=Coalesce(Sum("quantity"), 0))["total"]


def use_supplies(test_code):
    """Take what one run of a test needs from stock, soonest-expiring lot first.

    Call inside a transaction. A lot never goes below zero: when there isn't enough, everything
    usable is taken and the shortfall is returned as (item, units short) pairs. Removed items are skipped.
    """
    shortages = []
    for need in TestSupply.objects.filter(test_type__code=test_code, item__is_active=True).select_related("item"):
        remaining = need.quantity
        for lot in StockLot.objects.select_for_update().filter(usable(), item=need.item):
            taken = min(lot.quantity, remaining)
            lot.quantity -= taken
            lot.save(update_fields=["quantity"])
            remaining -= taken
            if remaining == 0:
                break
        if remaining:
            shortages.append((need.item, remaining))
    return shortages

def check_supplies(test_codes):
    needed = {}
    for need in TestSupply.objects.filter(test_type__code__in=test_codes, item__is_active=True).select_related("item"):
        needed[need.item] = needed.get(need.item, 0) + need.quantity

    today = timezone.localdate()
    problems = []
    for item, amount in needed.items():
        good = on_hand(item)
        if good >= amount:
            continue
        if item.lots.filter(quantity__gt=0, expiry_date__lt=today).exists():
            message = f"{item} is expired: only {good} of {amount} {item.unit} usable"
        elif good == 0:
            message = f"{item} is out of stock: need {amount} {item.unit}"
        else:
            message = f"{item} is low: {good} of {amount} {item.unit} in stock"
        problems.append((item, message))
    return problems

# Statuses on the collector dashboard (SXFT-98), with the Bootstrap color for each badge.
IN_STOCK, LOW, OUT_OF_STOCK, EXPIRED = "In stock", "Low", "Out of stock", "Expired"
STATUS_COLORS = {IN_STOCK: "success", LOW: "warning", OUT_OF_STOCK: "danger", EXPIRED: "danger"}

# Below this many times what an order needs, an item that is still enough counts as Low.
LOW_STOCK_FACTOR = 3


@dataclass
class SupplyStatus:
    """One supply an order needs, how much of it can be used, and what that means."""

    item: SupplyItem
    needed: int
    available: int
    status: str

    @property
    def color(self):
        return STATUS_COLORS[self.status]

    @property
    def is_ok(self):
        return self.status in (IN_STOCK, LOW)


def _status(needed, good, expired):
    if good < needed:
        # Expired only when expired lots are the sole stock; some usable stock that's too little is out of stock.
        return EXPIRED if good == 0 and expired > 0 else OUT_OF_STOCK
    if good < LOW_STOCK_FACTOR * needed:
        return LOW
    return IN_STOCK


def supply_status_for_orders(orders, today=None):
    """Set `supply_rows` (SupplyStatus list) and `supply_ready` on each order, without using any stock.

    Orders must have `tests` prefetched. Makes two queries however many orders there are:
    the supplies their tests need, and the usable and expired stock of those items. Display only.
    """
    orders = list(orders)
    today = today or timezone.localdate()
    test_ids = {test.pk for order in orders for test in order.tests.all()}

    needs_by_test = {}
    for need in TestSupply.objects.filter(test_type_id__in=test_ids, item__is_active=True).select_related("item"):
        needs_by_test.setdefault(need.test_type_id, []).append(need)

    item_ids = {need.item_id for needs in needs_by_test.values() for need in needs}
    stock = {}
    if item_ids:
        rows = (
            StockLot.objects.filter(item_id__in=item_ids, quantity__gt=0)
            .values("item_id")
            .annotate(
                good=Coalesce(Sum("quantity", filter=Q(expiry_date__gte=today)), 0),
                expired=Coalesce(Sum("quantity", filter=Q(expiry_date__lt=today)), 0),
            )
        )
        stock = {row["item_id"]: (row["good"], row["expired"]) for row in rows}

    for order in orders:
        needed = {}
        for test in order.tests.all():
            for need in needs_by_test.get(test.pk, []):
                needed[need.item] = needed.get(need.item, 0) + need.quantity
        order.supply_rows = []
        for item in sorted(needed, key=lambda i: i.name):
            good, expired = stock.get(item.pk, (0, 0))
            order.supply_rows.append(SupplyStatus(item, needed[item], good, _status(needed[item], good, expired)))
        order.supply_ready = all(row.is_ok for row in order.supply_rows)
    return orders

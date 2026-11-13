"""Taking supplies out of stock when a test is run (story SXFT-22)."""

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import StockLot, TestSupply


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
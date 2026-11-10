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

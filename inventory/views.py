from django.contrib import messages
from django.db.models import Count, Min, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.decorators import role_required
from core.models import User
from core.utils import log_event

from .forms import ReceiveLotForm, StockLotForm, SupplyItemForm
from .models import StockLot, SupplyItem
from .stock import on_hand

# 6.4: inventory is the lab manager's job.
manager_only = role_required(User.Role.LAB_MANAGER)


@manager_only
def item_list(request):
    """Active supply items with usable stock, expired stock still on the shelf, and the next expiry."""
    today = timezone.localdate()
    usable = Q(lots__quantity__gt=0, lots__expiry_date__gte=today)
    expired = Q(lots__quantity__gt=0, lots__expiry_date__lt=today)
    items = SupplyItem.objects.filter(is_active=True).annotate(
        on_hand=Coalesce(Sum("lots__quantity", filter=usable), 0),
        expired=Coalesce(Sum("lots__quantity", filter=expired), 0),
        next_expiry=Min("lots__expiry_date", filter=usable),
    )
    return render(request, "inventory/item_list.html", {"items": items})


@manager_only
def item_create(request):
    form = SupplyItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = form.save()
        log_event(request.user, "supply_added", details=f"{item} ({item.unit})")
        messages.success(request, f"{item} added.")
        return redirect("item_detail", item.pk)
    return render(request, "inventory/form.html", {"form": form, "title": "New supply item"})


@manager_only
def item_detail(request, pk):
    """One item: its lots, soonest expiry first, and which tests use it."""
    item = get_object_or_404(SupplyItem, pk=pk, is_active=True)
    lots = item.lots.select_related("received_by")
    used_by = item.used_by.select_related("test_type")
    return render(
        request,
        "inventory/item_detail.html",
        {"item": item, "lots": lots, "used_by": used_by, "on_hand": on_hand(item), "today": timezone.localdate()},
    )


@manager_only
def item_update(request, pk):
    item = get_object_or_404(SupplyItem, pk=pk, is_active=True)
    form = SupplyItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_event(request.user, "supply_updated", details=f"{item} ({item.unit})")
        messages.success(request, f"{item} updated.")
        return redirect("item_detail", item.pk)
    return render(
        request, "inventory/form.html", {"form": form, "title": f"Edit {item}", "item": item}
    )


@manager_only
def item_remove(request, pk):
    """Confirm on GET, soft-delete on POST so the item's lots are kept. Tests stop using a removed item."""
    item = get_object_or_404(SupplyItem.objects.annotate(lot_count=Count("lots")), pk=pk, is_active=True)
    if request.method == "POST":
        item.deactivate()
        log_event(request.user, "supply_removed", details=str(item))
        messages.success(request, f"{item} removed.")
        return redirect("item_list")
    used_by = item.used_by.select_related("test_type")
    return render(request, "inventory/item_confirm_remove.html", {"item": item, "used_by": used_by})


@manager_only
def lot_receive(request, pk):
    """Log a delivery of an item as a new lot."""
    item = get_object_or_404(SupplyItem, pk=pk, is_active=True)
    form = ReceiveLotForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lot = form.save(commit=False)
        lot.item = item
        lot.received_by = request.user
        lot.save()
        log_event(
            request.user,
            "stock_received",
            details=f"{item}: lot {lot.lot_number}, {lot.quantity} {item.unit}, expires {lot.expiry_date:%Y-%m-%d}",
        )
        messages.success(request, f"Received {lot.quantity} {item.unit} of {item}.")
        return redirect("item_detail", item.pk)
    return render(
        request, "inventory/form.html", {"form": form, "title": f"Receive {item}", "item": item}
    )


@manager_only
def lot_update(request, pk):
    """Correct a lot's number, quantity left or expiry date."""
    lot = get_object_or_404(StockLot.objects.select_related("item"), pk=pk, item__is_active=True)
    before = lot.quantity
    form = StockLotForm(request.POST or None, instance=lot)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_event(
            request.user,
            "stock_updated",
            details=f"{lot.item}: lot {lot.lot_number}, {before} -> {lot.quantity} {lot.item.unit}, "
            f"expires {lot.expiry_date:%Y-%m-%d}",
        )
        messages.success(request, f"Lot {lot.lot_number} updated.")
        return redirect("item_detail", lot.item.pk)
    return render(
        request, "inventory/form.html", {"form": form, "title": f"Edit lot {lot.lot_number}", "item": lot.item}
    )

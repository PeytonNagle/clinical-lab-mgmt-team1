from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class SupplyItem(models.Model):
    """Something the lab keeps in stock, such as a tube type or a reagent. Its stock is the sum of its lots."""

    # What the item is called on the supply list, e.g. "EDTA tube (lavender top)".
    name = models.CharField(max_length=100)

    # What one unit of quantity means, e.g. "tubes" or "tests". Shown next to every quantity.
    unit = models.CharField(max_length=30)

    # "Soft delete" flag: removing an item hides it but keeps its lots, the way patients are removed.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            # Removed items don't count, so a removed item's name can be used again.
            models.UniqueConstraint(
                Lower("name"),
                condition=Q(is_active=True),
                name="unique_active_supply_name",
                violation_error_message="A supply with this name already exists.",
            ),
        ]

    def __str__(self):
        return self.name

    def deactivate(self):
        """Soft-delete this item: mark inactive and save, keeping the row and its lots."""
        self.is_active = False
        self.save(update_fields=["is_active"])


class StockLot(models.Model):
    """One delivery of a supply item: how much is left of it and when it expires."""

    # PROTECT: items are soft-deleted, so this only stops a hard delete from wiping stock history.
    item = models.ForeignKey(SupplyItem, on_delete=models.PROTECT, related_name="lots")

    # The manufacturer's lot number printed on the box.
    lot_number = models.CharField(max_length=50)

    # Units left. PositiveIntegerField adds a database check, so stock can never go below zero.
    quantity = models.PositiveIntegerField()

    # Last day the lot may be used. Running a test skips expired lots.
    expiry_date = models.DateField()

    # Lab manager who logged the delivery. PROTECT keeps that record when an account is removed.
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_lots"
    )

    # Set once when the delivery is logged.
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # The order stock is used in: soonest expiry first, then oldest delivery.
        ordering = ["expiry_date", "received_at", "pk"]

    def __str__(self):
        return f"{self.item} lot {self.lot_number}"


class TestSupply(models.Model):
    """How much of one supply item a single run of a test uses, e.g. a BMP uses 1 serum separator tube."""

    test_type = models.ForeignKey("lab.TestType", on_delete=models.CASCADE, related_name="supplies")

    # PROTECT: a supply a test still uses can't be hard-deleted.
    item = models.ForeignKey(SupplyItem, on_delete=models.PROTECT, related_name="used_by")

    # Units used per run.
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["test_type__code", "item__name"]
        constraints = [
            models.UniqueConstraint(fields=["test_type", "item"], name="unique_supply_per_test"),
            models.CheckConstraint(condition=Q(quantity__gte=1), name="test_supply_quantity_at_least_1"),
        ]
        verbose_name_plural = "test supplies"

    def __str__(self):
        return f"{self.test_type.code} uses {self.quantity} {self.item.unit} of {self.item}"

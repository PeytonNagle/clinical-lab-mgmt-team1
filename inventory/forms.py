from django import forms
from django.utils import timezone

from lab.forms import add_bootstrap_classes

from .models import StockLot, SupplyItem

# Browser date picker; format must be YYYY-MM-DD for it to show the saved value.
DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class SupplyItemForm(forms.ModelForm):
    """Add or edit a supply item. is_active is left out: removing an item has its own page."""

    class Meta:
        model = SupplyItem
        fields = ["name", "unit"]
        help_texts = {"unit": "What one unit of stock is, e.g. tubes or tests."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)

    def clean_name(self):
        # Checked here because the form leaves out is_active, so Django skips the model's unique constraint.
        name = self.cleaned_data["name"].strip()
        taken = SupplyItem.objects.filter(name__iexact=name, is_active=True).exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError("A supply with this name already exists.")
        return name


class ReceiveLotForm(forms.ModelForm):
    """Log a delivery: a new lot for one item. The view sets the item and who received it."""

    class Meta:
        model = StockLot
        fields = ["lot_number", "quantity", "expiry_date"]
        widgets = {"expiry_date": DATE_WIDGET}
        labels = {"quantity": "Quantity received"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)
        self.fields["quantity"].widget.attrs["min"] = 1

    def clean_lot_number(self):
        return self.cleaned_data["lot_number"].strip().upper()

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity < 1:
            raise forms.ValidationError("A delivery must have at least 1 unit.")
        return quantity

    def clean_expiry_date(self):
        expiry = self.cleaned_data["expiry_date"]
        if expiry < timezone.localdate():
            raise forms.ValidationError("This lot has already expired. Don't add it to stock.")
        return expiry


class StockLotForm(forms.ModelForm):
    """Correct a lot after a stock count, e.g. a broken tube or a typo in the expiry date."""

    class Meta:
        model = StockLot
        fields = ["lot_number", "quantity", "expiry_date"]
        widgets = {"expiry_date": DATE_WIDGET}
        labels = {"quantity": "Quantity left"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)

    def clean_lot_number(self):
        return self.cleaned_data["lot_number"].strip().upper()

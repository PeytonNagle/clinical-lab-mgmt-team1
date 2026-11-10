from django.contrib import admin

from .models import StockLot, SupplyItem, TestSupply


class StockLotInline(admin.TabularInline):
    model = StockLot
    extra = 0
    readonly_fields = ("received_at",)


@admin.register(SupplyItem)
class SupplyItemAdmin(admin.ModelAdmin):
    list_display = ("name", "unit", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    inlines = [StockLotInline]


@admin.register(TestSupply)
class TestSupplyAdmin(admin.ModelAdmin):
    list_display = ("test_type", "item", "quantity")
    list_filter = ("test_type",)

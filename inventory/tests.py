from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ActivityLog, STAFF_ROLES, User
from lab.importer import import_results
from lab.tests import bmp_lines, cbc_lines, make_order

from .models import StockLot, SupplyItem, TestSupply
from .stock import on_hand, use_supplies

TODAY = timezone.localdate()


def make_manager(username="manager"):
    return User.objects.create_user(username=username, role=User.Role.LAB_MANAGER, must_change_password=False)


def add_lot(item, quantity, days_left=30, lot_number="LOT-1", received_by=None):
    return StockLot.objects.create(
        item=item, lot_number=lot_number, quantity=quantity,
        expiry_date=TODAY + timedelta(days=days_left), received_by=received_by or make_manager(f"m{StockLot.objects.count()}"),
    )


def supply(name):
    """A supply item seeded by the inventory migration."""
    return SupplyItem.objects.get(name=name, is_active=True)


class SeededTestSuppliesTests(TestCase):
    """SXFT-79: the migration says which supplies each test uses and how much."""

    def test_every_panel_uses_supplies(self):
        for code in ("BMP", "CBC", "LIPID"):
            with self.subTest(code=code):
                self.assertTrue(TestSupply.objects.filter(test_type__code=code).exists())

    def test_bmp_uses_one_tube_one_cartridge_and_two_tips(self):
        needs = {s.item.name: s.quantity for s in TestSupply.objects.filter(test_type__code="BMP")}
        self.assertEqual(
            needs,
            {"Serum separator tube (gold top)": 1, "BMP reagent cartridge": 1, "Pipette tips": 2},
        )

    def test_seeded_items_start_with_no_stock(self):
        self.assertFalse(StockLot.objects.exists())


class SupplyModelTests(TestCase):
    """SXFT-78: items and lots, and the database never holds negative stock."""

    def test_lot_quantity_cannot_go_below_zero_in_the_database(self):
        lot = add_lot(supply("Pipette tips"), 5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockLot.objects.filter(pk=lot.pk).update(quantity=-1)

    def test_two_active_items_cannot_share_a_name_in_any_case(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupplyItem.objects.create(name="pipette TIPS", unit="tips")

    def test_a_removed_items_name_can_be_used_again(self):
        supply("Pipette tips").deactivate()
        SupplyItem.objects.create(name="Pipette tips", unit="tips")
        self.assertEqual(SupplyItem.objects.filter(name="Pipette tips").count(), 2)

    def test_on_hand_counts_only_unexpired_lots(self):
        item = supply("Pipette tips")
        add_lot(item, 10)
        add_lot(item, 7, days_left=-1, lot_number="OLD")
        add_lot(item, 3, days_left=0, lot_number="LAST-DAY")
        self.assertEqual(on_hand(item), 13)


class UseSuppliesTests(TestCase):
    """SXFT-82: running a test takes its supplies, soonest-expiring lot first."""

    def setUp(self):
        self.manager = make_manager()
        self.tips = supply("Pipette tips")
        self.tubes = supply("Serum separator tube (gold top)")
        self.cartridges = supply("BMP reagent cartridge")

    def lot(self, item, quantity, days_left=30, lot_number="LOT-1"):
        return add_lot(item, quantity, days_left, lot_number, self.manager)

    def stock_everything(self):
        for item in (self.tips, self.tubes, self.cartridges):
            self.lot(item, 10)

    def test_a_bmp_takes_each_supply_by_its_amount(self):
        self.stock_everything()
        self.assertEqual(use_supplies("BMP"), [])
        self.assertEqual(on_hand(self.tubes), 9)
        self.assertEqual(on_hand(self.cartridges), 9)
        self.assertEqual(on_hand(self.tips), 8)

    def test_the_lot_that_expires_first_is_used_first(self):
        self.stock_everything()
        later = self.lot(self.tubes, 5, days_left=90, lot_number="LATER")
        sooner = self.lot(self.tubes, 5, days_left=3, lot_number="SOONER")
        use_supplies("BMP")
        sooner.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual((sooner.quantity, later.quantity), (4, 5))

    def test_a_need_spans_two_lots_when_the_first_runs_out(self):
        self.stock_everything()
        self.tips.lots.update(quantity=0)
        first = self.lot(self.tips, 1, days_left=2, lot_number="A")
        second = self.lot(self.tips, 5, days_left=9, lot_number="B")
        self.assertEqual(use_supplies("BMP"), [])
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.quantity, second.quantity), (0, 4))

    def test_expired_lots_are_not_used(self):
        self.stock_everything()
        self.tubes.lots.update(quantity=0)
        expired = self.lot(self.tubes, 5, days_left=-1, lot_number="EXPIRED")
        self.assertEqual(use_supplies("BMP"), [(self.tubes, 1)])
        expired.refresh_from_db()
        self.assertEqual(expired.quantity, 5)

    def test_stock_never_goes_below_zero_and_the_shortfall_is_returned(self):
        self.lot(self.tips, 1)
        shortages = use_supplies("BMP")
        self.assertEqual(
            sorted((item.name, missing) for item, missing in shortages),
            [("BMP reagent cartridge", 1), ("Pipette tips", 1), ("Serum separator tube (gold top)", 1)],
        )
        self.assertEqual(StockLot.objects.get().quantity, 0)
        self.assertFalse(StockLot.objects.filter(quantity__lt=0).exists())

    def test_removed_items_are_skipped(self):
        self.stock_everything()
        self.tips.deactivate()
        self.assertEqual(use_supplies("BMP"), [])
        self.assertEqual(self.tips.lots.get().quantity, 10)


class ImportUsesStockTests(TestCase):
    """SXFT-82: saving uploaded results takes stock; rejected results don't."""

    def setUp(self):
        self.tech = User.objects.create_user(username="tech", role=User.Role.TECHNICIAN, must_change_password=False)
        manager = make_manager()
        for item in SupplyItem.objects.all():
            add_lot(item, 10, received_by=manager)

    def test_each_saved_panel_takes_stock(self):
        bmp_order, cbc_order = make_order(["BMP"]), make_order(["CBC"])
        report = import_results(bmp_lines(bmp_order.pk) + cbc_lines(cbc_order.pk), self.tech)
        self.assertEqual(len(report.saved), 2)
        self.assertEqual(report.stock_warnings, [])
        self.assertEqual(on_hand(supply("BMP reagent cartridge")), 9)
        self.assertEqual(on_hand(supply("Hematology reagent pack")), 9)
        self.assertEqual(on_hand(supply("Pipette tips")), 8)

    def test_rejected_panels_take_nothing(self):
        report = import_results(bmp_lines(9999), self.tech)
        self.assertEqual(len(report.rejected), 1)
        self.assertEqual(on_hand(supply("BMP reagent cartridge")), 10)

    def test_a_shortage_still_saves_the_result_with_a_warning(self):
        supply("BMP reagent cartridge").lots.update(quantity=0)
        order = make_order(["BMP"])
        report = import_results(bmp_lines(order.pk), self.tech)
        self.assertEqual(len(report.saved), 1)
        self.assertEqual(
            report.stock_warnings, [(f"Order {order.pk}, BMP", "BMP reagent cartridge ran out, 1 tests short")]
        )


class InventoryRoleAccessTests(TestCase):
    """SXFT-83: only the lab manager can open the inventory pages."""

    def setUp(self):
        self.item = supply("Pipette tips")
        self.lot = add_lot(self.item, 5)
        self.urls = [
            reverse("item_list"),
            reverse("item_create"),
            reverse("item_detail", args=[self.item.pk]),
            reverse("item_update", args=[self.item.pk]),
            reverse("item_remove", args=[self.item.pk]),
            reverse("lot_receive", args=[self.item.pk]),
            reverse("lot_update", args=[self.lot.pk]),
        ]

    def test_lab_manager_can_open_every_page(self):
        self.client.force_login(make_manager("boss"))
        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_other_roles_are_forbidden(self):
        for role in (set(STAFF_ROLES) | {User.Role.PATIENT}) - {User.Role.LAB_MANAGER}:
            self.client.force_login(User.objects.create_user(username=role, role=role, must_change_password=False))
            for url in self.urls:
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_logged_out_user_is_sent_to_login(self):
        response = self.client.get(reverse("item_list"))
        self.assertRedirects(response, f"{reverse('login')}?next=/inventory/", fetch_redirect_response=False)

    def test_navbar_shows_inventory_only_to_the_lab_manager(self):
        self.client.force_login(make_manager("boss"))
        self.assertContains(self.client.get(reverse("patient_list")), "Inventory")
        self.client.force_login(User.objects.create_user(username="c", role=User.Role.CASHIER, must_change_password=False))
        self.assertNotContains(self.client.get(reverse("patient_list")), "Inventory")


class SupplyItemViewTests(TestCase):
    """SXFT-80: the manager adds, edits and removes supply items."""

    def setUp(self):
        self.manager = make_manager()
        self.client.force_login(self.manager)

    def test_list_shows_stock_out_of_stock_and_expired(self):
        tips = supply("Pipette tips")
        add_lot(tips, 12, received_by=self.manager)
        add_lot(supply("EDTA tube (lavender top)"), 4, days_left=-2, received_by=self.manager)
        response = self.client.get(reverse("item_list"))
        items = {item.name: item for item in response.context["items"]}
        self.assertEqual(items["Pipette tips"].on_hand, 12)
        self.assertEqual(items["EDTA tube (lavender top)"].on_hand, 0)
        self.assertEqual(items["EDTA tube (lavender top)"].expired, 4)
        self.assertContains(response, "Out of stock")
        self.assertContains(response, "4 expired on the shelf")

    def test_create_item(self):
        response = self.client.post(reverse("item_create"), {"name": "  Urine cup ", "unit": "cups"})
        item = SupplyItem.objects.get(name="Urine cup")
        self.assertRedirects(response, reverse("item_detail", args=[item.pk]))
        self.assertEqual(ActivityLog.objects.get(action="supply_added").user, self.manager)

    def test_create_rejects_a_name_already_in_use(self):
        response = self.client.post(reverse("item_create"), {"name": "PIPETTE TIPS", "unit": "tips"})
        self.assertContains(response, "A supply with this name already exists.")

    def test_create_requires_name_and_unit(self):
        response = self.client.post(reverse("item_create"), {"name": "", "unit": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["form"].errors), {"name", "unit"})

    def test_edit_item(self):
        item = supply("Pipette tips")
        self.client.post(reverse("item_update", args=[item.pk]), {"name": "Pipette tips (200 µL)", "unit": "tips"})
        item.refresh_from_db()
        self.assertEqual(item.name, "Pipette tips (200 µL)")

    def test_remove_confirms_then_soft_deletes(self):
        item = supply("Pipette tips")
        add_lot(item, 5, received_by=self.manager)
        confirm = self.client.get(reverse("item_remove", args=[item.pk]))
        self.assertContains(confirm, "Those tests will stop taking it from stock.")

        response = self.client.post(reverse("item_remove", args=[item.pk]))
        self.assertRedirects(response, reverse("item_list"))
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        self.assertTrue(item.lots.exists())
        self.assertNotContains(self.client.get(reverse("item_list")), "Pipette tips")
        self.assertEqual(self.client.get(reverse("item_detail", args=[item.pk])).status_code, 404)


class ReceiveAndUpdateLotTests(TestCase):
    """SXFT-81: receiving a delivery adds a lot; a lot can be corrected after a count."""

    def setUp(self):
        self.manager = make_manager()
        self.client.force_login(self.manager)
        self.item = supply("EDTA tube (lavender top)")

    def receive(self, **overrides):
        data = {"lot_number": " edta-001 ", "quantity": "50", "expiry_date": (TODAY + timedelta(days=60)).isoformat()}
        data.update(overrides)
        return self.client.post(reverse("lot_receive", args=[self.item.pk]), data)

    def test_receiving_adds_a_lot_to_stock(self):
        response = self.receive()
        self.assertRedirects(response, reverse("item_detail", args=[self.item.pk]))
        lot = self.item.lots.get()
        self.assertEqual((lot.lot_number, lot.quantity, lot.received_by), ("EDTA-001", 50, self.manager))
        self.assertEqual(on_hand(self.item), 50)
        self.assertIn("EDTA-001", ActivityLog.objects.get(action="stock_received").details)

    def test_receiving_zero_or_negative_is_rejected(self):
        for quantity in ("0", "-5"):
            with self.subTest(quantity=quantity):
                response = self.receive(quantity=quantity)
                self.assertIn("quantity", response.context["form"].errors)
        self.assertFalse(self.item.lots.exists())

    def test_receiving_an_expired_lot_is_rejected(self):
        response = self.receive(expiry_date=(TODAY - timedelta(days=1)).isoformat())
        self.assertContains(response, "already expired")
        self.assertFalse(self.item.lots.exists())

    def test_lot_quantity_can_be_corrected_but_not_below_zero(self):
        lot = add_lot(self.item, 20, received_by=self.manager)
        url = reverse("lot_update", args=[lot.pk])
        expiry = lot.expiry_date.isoformat()

        response = self.client.post(url, {"lot_number": lot.lot_number, "quantity": "-1", "expiry_date": expiry})
        self.assertIn("quantity", response.context["form"].errors)

        self.client.post(url, {"lot_number": lot.lot_number, "quantity": "18", "expiry_date": expiry})
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, 18)
        self.assertIn("20 -> 18", ActivityLog.objects.get(action="stock_updated").details)

    def test_detail_page_lists_lots_and_marks_expired(self):
        add_lot(self.item, 3, days_left=-1, lot_number="OLD-LOT", received_by=self.manager)
        add_lot(self.item, 8, lot_number="NEW-LOT", received_by=self.manager)
        response = self.client.get(reverse("item_detail", args=[self.item.pk]))
        self.assertContains(response, "OLD-LOT")
        self.assertContains(response, "Expired")
        self.assertEqual(response.context["on_hand"], 8)
        self.assertContains(response, "CBC 1")


class UploadShowsStockWarningsTests(TestCase):
    """SXFT-82 through the real upload page: a technician sees when stock ran out."""

    def test_upload_page_shows_stock_warning(self):
        self.client.force_login(User.objects.create_user(username="t", role=User.Role.TECHNICIAN, must_change_password=False))
        order = make_order(["BMP"])
        upload = SimpleUploadedFile("bmp.txt", bmp_lines(order.pk).encode())
        response = self.client.post(reverse("result_upload"), {"file": upload})
        self.assertContains(response, "Saved (1)")
        self.assertContains(response, "Stock warnings (3)")
        self.assertContains(response, "Pipette tips ran out, 2 tips short")

"""Reads machine result .txt files (story SXFT-20).

Each line is one value in the simplified ORU-HL7 format from the requirements (6.3.5):

    BARCODE|Test^<Test ID>^<description>|<value>|<YYYYMMDDHHMM>
    12|Test^GLU^Glucose|92|202610211340

Barcodes come with MVP 2 (SXFT-19), so for now BARCODE is the TestOrder id (the Report ID).
Test IDs are the ones on each panel model's ANALYTES (lab/models.py).
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import PANEL_MODELS, TestOrder

# Test ID -> the panel model it belongs to, e.g. "GLU" -> BMPResult.
PANEL_FOR_TEST_ID = {
    analyte.test_id: model for model in PANEL_MODELS.values() for analyte in model.ANALYTES
}


class ParseError(ValueError):
    pass


@dataclass
class ResultLine:
    line_number: int
    barcode: str
    test_id: str
    description: str
    value: Decimal
    measured_at: datetime


def parse_line(text, line_number):
    """Turn one file line into a ResultLine, or raise ParseError saying what is wrong."""
    parts = text.split("|")
    if len(parts) != 4:
        raise ParseError("expected 4 fields separated by |")
    barcode, test, value, stamp = (p.strip() for p in parts)

    test_parts = test.split("^")
    if len(test_parts) != 3 or test_parts[0] != "Test":
        raise ParseError("second field must look like Test^<Test ID>^<description>")
    _, test_id, description = test_parts

    try:
        value = Decimal(value)
    except InvalidOperation:
        raise ParseError(f"value {value!r} is not a number")

    try:
        measured_at = timezone.make_aware(datetime.strptime(stamp, "%Y%m%d%H%M"))
    except ValueError:
        raise ParseError(f"date and time {stamp!r} is not YYYYMMDDHHMM")

    return ResultLine(line_number, barcode, test_id.strip().upper(), description, value, measured_at)


@dataclass
class ImportReport:
    """What happened to each part of a file: results saved, and anything rejected with the reason."""

    saved: list = field(default_factory=list)
    # (where, reason) pairs, e.g. ("Line 3", "unknown Test ID 'XYZ'") or ("Order 12, CBC", "...").
    rejected: list = field(default_factory=list)


def import_results(text, user):
    """Read a whole result file and save one panel result per order and panel.

    A panel is saved only when its order exists, the order asked for that panel, the patient is
    active, the panel has no result yet, and the file has every value on the panel exactly once.
    Anything else is rejected and left out; the rest of the file is still saved.
    """
    report = ImportReport()

    # Group the good lines by (order barcode, panel).
    groups = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            line = parse_line(raw, number)
        except ParseError as error:
            report.rejected.append((f"Line {number}", str(error)))
            continue
        panel = PANEL_FOR_TEST_ID.get(line.test_id)
        if panel is None:
            report.rejected.append((f"Line {number}", f"unknown Test ID {line.test_id!r}"))
            continue
        groups.setdefault((line.barcode, panel), []).append(line)

    for (barcode, panel), lines in groups.items():
        where = f"Order {barcode}, {panel.TEST_CODE}"
        try:
            result = _save_panel(barcode, panel, lines, user)
        except ParseError as error:
            report.rejected.append((where, str(error)))
        else:
            report.saved.append(result)
    return report


def _save_panel(barcode, panel, lines, user):
    """Match one panel's lines to their order and save them. Raises ParseError to reject."""
    order = TestOrder.objects.filter(pk=int(barcode)).first() if barcode.isdigit() else None
    if order is None:
        raise ParseError("no order with this ID")
    if not order.patient.is_active:
        raise ParseError("the order's patient has been removed")
    if not order.tests.filter(code=panel.TEST_CODE).exists():
        raise ParseError(f"the order did not request a {panel.TEST_CODE}")
    if panel.objects.filter(order=order).exists():
        raise ParseError("this order already has a result for this panel")

    values = {}
    for line in lines:
        analyte = panel.analyte_for(line.test_id)
        if analyte.field in values:
            raise ParseError(f"{line.test_id} appears more than once")
        values[analyte.field] = line.value
    missing = [a.test_id for a in panel.ANALYTES if a.field not in values]
    if missing:
        raise ParseError(f"missing {', '.join(missing)}")

    result = panel(
        order=order,
        performed_by=user,
        measured_at=max(line.measured_at for line in lines),
        **values,
    )
    try:
        result.full_clean()
    except ValidationError as error:
        # e.g. a value with too many digits for the field.
        details = "; ".join(f"{name}: {' '.join(msgs)}" for name, msgs in error.message_dict.items())
        raise ParseError(details)
    result.save()
    return result

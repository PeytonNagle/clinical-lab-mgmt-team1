from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Replace
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.decorators import role_required
from core.models import STAFF_ROLES, User
from core.utils import log_event

from .barcodes import barcode_svg
from .forms import CollectSampleForm, LabelReprintForm, PatientForm, ResultUploadForm, TestOrderForm
from .importer import import_results
from .models import PANEL_MODELS, Patient, Sample, TestOrder
from .phone import phone_digits

from django.core.exceptions import PermissionDenied
from inventory.stock import check_supplies

# 6.1.5 allows specimen collectors and the lab manager to remove patients.
# Cashiers are added by change request for backlog item 5.
CAN_REMOVE_PATIENTS = (
    User.Role.LAB_MANAGER,
    User.Role.SPECIMEN_COLLECTOR,
    User.Role.CASHIER,
)


ORDERS_PER_PAGE = 25

# Most recent activity log entries shown on a patient's page.
ACTIVITY_LOG_LIMIT = 50


@role_required(*STAFF_ROLES)
def patient_list(request):
    """Active patients, optionally filtered by name, phone, or policy number."""
    query = request.GET.get("q", "").strip()
    patients = Patient.objects.filter(is_active=True)
    if query:
        match = (
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(insurance_policy_number__icontains=query)
        )
        # Numbers are saved with dashes, so also compare digits to find them however the query is typed.
        digits = phone_digits(query)
        if digits:
            patients = patients.annotate(phone_plain=Replace("phone", Value("-"), Value("")))
            match |= Q(phone_plain__contains=digits)
        patients = patients.filter(match)
    return render(
        request,
        "lab/patient_list.html",
        {
            "patients": patients,
            "query": query,
            "can_remove": request.user.role in CAN_REMOVE_PATIENTS,
        },
    )


@role_required(*STAFF_ROLES)
def patient_create(request):
    form = PatientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        patient = form.save()
        messages.success(request, f"Patient {patient} created.")
        return redirect("patient_list")
    return render(request, "lab/patient_form.html", {"form": form, "title": "New patient"})


@role_required(*STAFF_ROLES)
def patient_update(request, pk):
    patient = get_object_or_404(Patient, pk=pk, is_active=True)
    form = PatientForm(request.POST or None, instance=patient)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Patient {patient} updated.")
        return redirect("patient_list")
    return render(request, "lab/patient_form.html", {"form": form, "title": f"Edit {patient}"})


@role_required(*STAFF_ROLES)
def patient_detail(request, pk):
    """One patient's details with every order and its results, newest order first. Removed patients still show."""
    patient = get_object_or_404(Patient, pk=pk)
    # Each panel's result hangs off the order as a reverse one-to-one, e.g. order.bmpresult.
    result_names = [model._meta.model_name for model in PANEL_MODELS.values()]
    orders = (
        patient.orders.select_related(*result_names)
        .prefetch_related("tests")
        .order_by("-created_at", "-pk")
    )
    for order in orders:
        # A panel with no result yet raises on access, so getattr's default skips it.
        order.results = [r for r in (getattr(order, name, None) for name in result_names) if r]
    # pk breaks ties: one upload logs several entries in the same instant.
    activity = patient.activity_logs.select_related("user").order_by("-timestamp", "-pk")[:ACTIVITY_LOG_LIMIT]
    return render(
        request, "lab/patient_detail.html", {"patient": patient, "orders": orders, "activity": activity}
    )


@role_required(*CAN_REMOVE_PATIENTS)
def patient_remove(request, pk):
    """Confirm on GET, soft-delete on POST so the patient's history is kept."""
    patient = get_object_or_404(Patient, pk=pk, is_active=True)
    if request.method == "POST":
        patient.deactivate()
        messages.success(request, f"Patient {patient} removed.")
        return redirect("patient_list")
    return render(request, "lab/patient_confirm_remove.html", {"patient": patient})


@role_required(*STAFF_ROLES)
def order_create(request):
    form = TestOrderForm(request.POST or None, initial={"patient": request.GET.get("patient")})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            order = form.save(commit=False)
            order.entered_by = request.user
            order.save()
            form.save_m2m()
        tests = ", ".join(order.tests.values_list("code", flat=True))
        log_event(
            request.user,
            "order_created",
            patient=order.patient,
            details=f"Order #{order.pk}: {tests}, {order.get_source_display()}",
        )
        messages.success(request, f"Order #{order.pk} created for {order.patient}.")
        return redirect("order_list")
    return render(request, "lab/order_form.html", {"form": form})


@role_required(*STAFF_ROLES)
def order_list(request):
    # pk breaks ties so orders made in the same instant never swap pages.
    orders = TestOrder.objects.select_related("patient").prefetch_related("tests").order_by("-created_at", "-pk")
    page = Paginator(orders, ORDERS_PER_PAGE).get_page(request.GET.get("page"))
    return render(request, "lab/order_list.html", {"page": page})


@role_required(*STAFF_ROLES)
def order_detail(request, pk):
    orders = TestOrder.objects.select_related("patient", "entered_by").prefetch_related("tests")
    return render(request, "lab/order_detail.html", {"order": get_object_or_404(orders, pk=pk)})


@role_required(User.Role.TECHNICIAN)
def result_upload(request):
    """Upload a machine result file; show what was saved and what was rejected and why."""
    form = ResultUploadForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == "POST" and form.is_valid():
        report = import_results(form.cleaned_data["file"], request.user)
        # cleaned_data["file"] is the decoded text, so the name comes from the upload itself.
        file_name = request.FILES["file"].name
        for result in report.saved:
            values = ", ".join(f"{analyte.test_id} {value} {analyte.units}" for analyte, value, _ in result.rows())
            log_event(
                request.user,
                "result_saved",
                patient=result.patient,
                details=f"Order #{result.order_id}, {result.TEST_CODE}: {values}",
            )
        for where, reason in report.rejected:
            log_event(request.user, "result_rejected", details=f"{file_name}, {where}: {reason}")
        # Logged last so the summary sits on top of the newest-first log.
        log_event(
            request.user,
            "results_imported",
            details=f"{file_name}: {len(report.saved)} saved, {len(report.rejected)} rejected",
        )
        form = ResultUploadForm()
    return render(request, "lab/result_upload.html", {"form": form, "report": report})


# Session key: ids of samples this user just printed. Each id lets the label show once more,
# so the browser can print it right after the first print; a reload shows "already printed".
JUST_PRINTED_KEY = "just_printed_samples"


def label_url(pk, auto_print=False):
    url = reverse("sample_label", args=[pk])
    return f"{url}?print=1" if auto_print else url


def get_sample(pk):
    return get_object_or_404(Sample.objects.select_related("order__patient", "printed_by"), pk=pk)


def render_label(request, sample, reprint_form=None):
    """The label page for a collector or the lab manager (see the template for the four states)."""
    is_manager = request.user.role == User.Role.LAB_MANAGER
    wants_print = request.GET.get("print") == "1"
    just_printed = False
    if not is_manager and sample.is_printed and wants_print:
        # Use up this sample's one-time pass (only the ?print=1 redirect from sample_print uses it).
        passes = request.session.get(JUST_PRINTED_KEY, [])
        if sample.pk in passes:
            passes.remove(sample.pk)
            request.session[JUST_PRINTED_KEY] = passes
            just_printed = True
    show_label = is_manager or not sample.is_printed or just_printed
    auto_print = wants_print and (just_printed or (is_manager and sample.is_printed))
    return render(
        request,
        "lab/sample_label.html",
        {
            "sample": sample,
            "order": sample.order,
            "patient": sample.order.patient,
            "is_manager": is_manager,
            "show_label": show_label,
            "auto_print": auto_print,
            "barcode_svg": barcode_svg(sample.barcode) if show_label else "",
            "reprint_form": reprint_form or LabelReprintForm(),
        },
    )


@role_required(User.Role.SPECIMEN_COLLECTOR, User.Role.LAB_MANAGER)
def sample_label(request, pk):
    """Printable tube label with the sample's Code 128 barcode (spec 6.3.4)."""
    return render_label(request, get_sample(pk))


@role_required(User.Role.SPECIMEN_COLLECTOR)
@require_POST
def sample_print(request, pk):
    """First and only print by a collector. Later prints need the lab manager (sample_reprint)."""
    sample = get_sample(pk)
    with transaction.atomic():
        # One UPDATE that only matches an unprinted sample, so a double click can't print twice.
        updated = Sample.objects.filter(pk=pk, printed_at__isnull=True).update(
            printed_at=timezone.now(), printed_by=request.user
        )
        if updated == 1:
            log_event(request.user, "label_printed", patient=sample.order.patient, details=f"barcode {sample.barcode}")
    if updated == 0:
        messages.error(request, "This label has already been printed. Ask the lab manager to reprint it.")
        return redirect(label_url(pk))
    request.session[JUST_PRINTED_KEY] = request.session.get(JUST_PRINTED_KEY, []) + [sample.pk]
    return redirect(label_url(pk, auto_print=True))


@role_required(User.Role.LAB_MANAGER)
@require_POST
def sample_reprint(request, pk):
    """Lab manager reprints an already printed label and must give a reason.

    The original printed_at and printed_by stay as they are; the reprint is recorded in the activity log.
    """
    sample = get_sample(pk)
    if not sample.is_printed:
        messages.error(request, "This label hasn't been printed yet, so there is nothing to reprint.")
        return redirect(label_url(pk))
    form = LabelReprintForm(request.POST)
    if not form.is_valid():
        return render_label(request, sample, reprint_form=form)
    log_event(
        request.user,
        "label_reprinted",
        patient=sample.order.patient,
        details=f"barcode {sample.barcode}, reason: {form.cleaned_data['reason']}",
    )
    return redirect(label_url(pk, auto_print=True))


@role_required(User.Role.SPECIMEN_COLLECTOR, User.Role.LAB_MANAGER)
def collector_dashboard(request):
    """Orders waiting for a specimen, and what was collected today. The lab manager can only look."""
    waiting = (
        TestOrder.objects.filter(status=TestOrder.Status.PENDING, patient__is_active=True)
        .filter(Q(sample__isnull=True) | Q(sample__collected_at__isnull=True))
        .select_related("patient", "sample")
        .prefetch_related("tests")
        .order_by("created_at")
    )
    collected_today = (
        Sample.objects.filter(collected_at__date=timezone.localdate())
        .select_related("order__patient", "collected_by")
        .order_by("-collected_at")
    )
    return render(
        request,
        "lab/collector_dashboard.html",
        {
            "waiting": waiting,
            "collected_today": collected_today,
            "can_collect": request.user.role == User.Role.SPECIMEN_COLLECTOR,
            "sample_types": Sample.SampleType.choices,
        },
    )


@role_required(User.Role.SPECIMEN_COLLECTOR)
@require_POST
def collect_sample(request, order_id):
    """Record that the collector drew the specimen for this order, then go to its label."""
    order = get_object_or_404(TestOrder.objects.select_related("patient"), pk=order_id)
    if order.status != TestOrder.Status.PENDING or not order.patient.is_active:
        messages.error(request, f"Order #{order.pk} isn't waiting for collection.")
        return redirect("collector_dashboard")
    form = CollectSampleForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Choose a sample type for order #{order.pk}.")
        return redirect("collector_dashboard")
    sample_type = form.cleaned_data["sample_type"]
    with transaction.atomic():
        sample, _ = Sample.objects.get_or_create(order=order, defaults={"sample_type": sample_type})
        # One UPDATE that only matches an uncollected sample, so a double click can't collect twice.
        updated = Sample.objects.filter(pk=sample.pk, collected_at__isnull=True).update(
            collected_at=timezone.now(), collected_by=request.user, sample_type=sample_type
        )
        if updated == 1:
            type_label = Sample.SampleType(sample_type).label
            log_event(
                request.user,
                "sample_collected",
                patient=order.patient,
                details=f"order {order.pk}, barcode {sample.barcode}, {type_label}",
            )
    if updated == 0:
        messages.error(request, f"The sample for order #{order.pk} has already been collected.")
        return redirect("collector_dashboard")
    messages.success(request, f"Sample {sample.barcode} collected for {order.patient}. Print its label now.")
    return redirect("sample_label", pk=sample.pk)

@role_required(User.Role.SPECIMEN_COLLECTOR, User.Role.LAB_MANAGER)
def supply_check(request, pk):
    sample = get_sample(pk)
    order = sample.order
    if not sample.is_collected:
        messages.error(request, f"The sample for order #{order.pk} hasn't been collected yet.")
        return redirect("collector_dashboard")
    problems = check_supplies([test.code for test in order.tests.all()])
    can_run = request.user.role == User.Role.SPECIMEN_COLLECTOR

    if request.method == "POST":
        if not can_run:
            raise PermissionDenied
        if problems:
            reasons = "; ".join(message for _, message in problems)
            tests = ", ".join(test.code for test in order.tests.all())
            log_event(request.user, "test_blocked", patient=order.patient,details=f"order {order.pk}, sample {sample.barcode}, tests {tests}: {reasons}")            
            messages.warning(request, f"Order #{order.pk} is blocked. {reasons}")
            return redirect("supply_check", pk=pk)
        messages.success(request, f"Supplies are ready for order #{order.pk}. Send the sample to the lab.")
        return redirect("collector_dashboard")

    return render(request, "lab/supply_check.html",
                  {"sample": sample, "order": order, "problems": problems, "can_run": can_run})
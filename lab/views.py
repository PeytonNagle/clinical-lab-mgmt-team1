from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Replace
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import role_required
from core.models import STAFF_ROLES, User

from .forms import PatientForm, ResultUploadForm, TestOrderForm
from .importer import import_results
from .models import PANEL_MODELS, Patient, TestOrder
from .phone import phone_digits

# 6.1.5 allows specimen collectors and the lab manager to remove patients.
# Cashiers are added by change request for backlog item 5.
CAN_REMOVE_PATIENTS = (
    User.Role.LAB_MANAGER,
    User.Role.SPECIMEN_COLLECTOR,
    User.Role.CASHIER,
)


ORDERS_PER_PAGE = 25


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
    return render(request, "lab/patient_detail.html", {"patient": patient, "orders": orders})


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
        form = ResultUploadForm()
    return render(request, "lab/result_upload.html", {"form": form, "report": report})

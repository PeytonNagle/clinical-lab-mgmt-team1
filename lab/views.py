from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import role_required
from core.models import STAFF_ROLES, User

from .forms import PatientForm, ResultUploadForm
from .importer import import_results
from .models import Patient

# 6.1.5 allows specimen collectors and the lab manager to remove patients.
# Cashiers are added by change request for backlog item 5.
CAN_REMOVE_PATIENTS = (
    User.Role.LAB_MANAGER,
    User.Role.SPECIMEN_COLLECTOR,
    User.Role.CASHIER,
)


@role_required(*STAFF_ROLES)
def patient_list(request):
    """Active patients, optionally filtered by name, phone, or policy number."""
    query = request.GET.get("q", "").strip()
    patients = Patient.objects.filter(is_active=True)
    if query:
        patients = patients.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(insurance_policy_number__icontains=query)
        )
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


@role_required(*CAN_REMOVE_PATIENTS)
def patient_remove(request, pk):
    """Confirm on GET, soft-delete on POST so the patient's history is kept."""
    patient = get_object_or_404(Patient, pk=pk, is_active=True)
    if request.method == "POST":
        patient.deactivate()
        messages.success(request, f"Patient {patient} removed.")
        return redirect("patient_list")
    return render(request, "lab/patient_confirm_remove.html", {"patient": patient})


@role_required(User.Role.TECHNICIAN)
def result_upload(request):
    """Upload a machine result file; show what was saved and what was rejected and why."""
    form = ResultUploadForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == "POST" and form.is_valid():
        report = import_results(form.cleaned_data["file"], request.user)
        form = ResultUploadForm()
    return render(request, "lab/result_upload.html", {"form": form, "report": report})

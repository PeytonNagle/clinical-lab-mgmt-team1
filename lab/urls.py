from django.urls import path

from . import views

urlpatterns = [
    path("patients/", views.patient_list, name="patient_list"),
    path("patients/new/", views.patient_create, name="patient_create"),
    path("patients/<int:pk>/edit/", views.patient_update, name="patient_update"),
    path("patients/<int:pk>/remove/", views.patient_remove, name="patient_remove"),
    path("results/upload/", views.result_upload, name="result_upload"),
]

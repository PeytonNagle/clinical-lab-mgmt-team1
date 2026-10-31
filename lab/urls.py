from django.urls import path

from . import views

urlpatterns = [
    path("patients/", views.patient_list, name="patient_list"),
    path("patients/new/", views.patient_create, name="patient_create"),
    path("patients/<int:pk>/", views.patient_detail, name="patient_detail"),
    path("patients/<int:pk>/edit/", views.patient_update, name="patient_update"),
    path("patients/<int:pk>/remove/", views.patient_remove, name="patient_remove"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("results/upload/", views.result_upload, name="result_upload"),
]

from django.urls import path

from . import views

urlpatterns = [
    path("inventory/", views.item_list, name="item_list"),
    path("inventory/new/", views.item_create, name="item_create"),
    path("inventory/<int:pk>/", views.item_detail, name="item_detail"),
    path("inventory/<int:pk>/edit/", views.item_update, name="item_update"),
    path("inventory/<int:pk>/remove/", views.item_remove, name="item_remove"),
    path("inventory/<int:pk>/receive/", views.lot_receive, name="lot_receive"),
    path("inventory/lots/<int:pk>/edit/", views.lot_update, name="lot_update"),
]

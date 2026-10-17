from django.contrib.auth.views import LoginView
from django.urls import path

from . import views
from .forms import StaffLoginForm

urlpatterns = [
    path("", views.home, name="home"),
    path("home/<str:role>/", views.role_home, name="role_home"),
    path(
        "accounts/login/",
        LoginView.as_view(authentication_form=StaffLoginForm, redirect_authenticated_user=True),
        name="login",
    ),
    path("accounts/logout/", views.StaffLogoutView.as_view(), name="logout"),
    path("accounts/password/set/", views.SetFirstPasswordView.as_view(), name="set_password"),
    path("accounts/password/change/", views.ChangePasswordView.as_view(), name="change_password"),
    path("staff/register/", views.register_staff, name="register_staff"),
]

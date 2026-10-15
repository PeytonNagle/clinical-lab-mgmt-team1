from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Keep users with a temporary password on the set-password page until they replace it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        allowed = (reverse("set_password"), reverse("logout"))
        if user.is_authenticated and user.must_change_password and request.path not in allowed:
            return redirect("set_password")
        return self.get_response(request)

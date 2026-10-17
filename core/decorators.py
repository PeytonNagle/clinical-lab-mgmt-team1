from functools import wraps

from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Allow a view only for users whose role is one of `roles`; everyone else gets a 403.

    Login is already enforced by LoginRequiredMiddleware, so request.user is a real user here.
    Usage: @role_required(User.Role.LAB_MANAGER, User.Role.CASHIER)
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator

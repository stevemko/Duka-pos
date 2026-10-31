from rest_framework.permissions import BasePermission


class IsManager(BasePermission):
    message = "Only manager accounts can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class IsSuperUser(BasePermission):
    message = "Only the super admin can manage accounts and passwords."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)

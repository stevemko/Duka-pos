from django.contrib.auth import get_user_model
from django.db.models import Count, Prefetch
from django.db.models.deletion import ProtectedError
from rest_framework import status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Branch, StaffProfile
from .permissions import IsManager, IsSuperUser
from .serializers import (
    BranchSerializer,
    ChangePasswordSerializer,
    SetPasswordSerializer,
    UserSerializer,
    UserWriteSerializer,
)
from .services import sees_all_branches, user_branch

User = get_user_model()


def _deactivate_sessions(user):
    Token.objects.filter(user=user).delete()


class MeView(APIView):
    def get(self, request):
        data = UserSerializer(request.user).data
        data["can_view_all_branches"] = sees_all_branches(request.user)
        data["can_manage"] = bool(request.user.is_staff)
        data["can_manage_users"] = bool(request.user.is_superuser)
        return Response(data)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.select_related("profile__branch").order_by("username")
    permission_classes = [IsAuthenticated, IsSuperUser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return UserWriteSerializer
        return UserSerializer

    def _guard_target(self, request, target, new_role=None, new_active=None):
        if target.is_superuser and not request.user.is_superuser:
            raise PermissionDenied("Only a superuser can change this account.")
        if target.pk == request.user.pk:
            if new_active is False:
                raise ValidationError({"is_active": "You cannot deactivate your own account."})
            if new_role == "cashier":
                raise ValidationError({"role": "You cannot remove your own manager role."})
        going_off_duty = new_role == "cashier" or new_active is False
        if target.is_staff and target.is_active and going_off_duty:
            other_managers = User.objects.filter(is_staff=True, is_active=True).exclude(pk=target.pk)
            if not other_managers.exists():
                raise ValidationError("At least one active manager account is required.")

    def create(self, request, *args, **kwargs):
        serializer = UserWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        target = self.get_object()
        serializer = UserWriteSerializer(target, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        new_role = validated.get("role")
        new_active = validated.get("is_active")
        self._guard_target(request, target, new_role=new_role, new_active=new_active)

        role_changed = new_role is not None and (new_role == "manager") != target.is_staff
        user = serializer.save()
        if role_changed or new_active is False:
            _deactivate_sessions(user)
        return Response(UserSerializer(user).data)

    def destroy(self, request, *args, **kwargs):
        target = self.get_object()
        self._guard_target(request, target, new_active=False)
        target.is_active = False
        target.save(update_fields=["is_active"])
        _deactivate_sessions(target)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="set-password")
    def set_password(self, request, pk=None):
        target = self.get_object()
        self._guard_target(request, target)
        serializer = SetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target.set_password(serializer.validated_data["new_password"])
        target.save(update_fields=["password"])
        _deactivate_sessions(target)
        return Response({"detail": "Password updated. The user must sign in again."})


class ChangePasswordView(APIView):
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        _deactivate_sessions(request.user)
        token = Token.objects.create(user=request.user)
        return Response({"detail": "Password updated.", "token": token.key})


class BranchViewSet(viewsets.ModelViewSet):
    queryset = Branch.objects.prefetch_related(
        Prefetch("staff", queryset=StaffProfile.objects.select_related("user"))
    ).annotate(staff_total=Count("staff")).order_by("name")
    serializer_class = BranchSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsManager()]

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "This branch has records and cannot be deleted. Deactivate it instead."},
                status=status.HTTP_409_CONFLICT,
            )

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from config.throttles import LoginThrottle
from accounts.serializers import UserSerializer
from accounts.services import sees_all_branches


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def api_login(request):
    username = request.data.get("username", "")
    password = request.data.get("password", "")
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return Response(
            {"detail": "Invalid username or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    token, created = Token.objects.get_or_create(user=user)
    ttl = timedelta(days=settings.AUTH_TOKEN_TTL_DAYS)
    if not created and token.created < timezone.now() - ttl:
        token.delete()
        token = Token.objects.create(user=user)

    profile = UserSerializer(user).data
    profile["can_view_all_branches"] = sees_all_branches(user)
    profile["can_manage"] = bool(user.is_staff)
    profile["can_manage_users"] = bool(user.is_superuser)
    return Response({
        "token": token.key,
        "username": user.get_username(),
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "can_manage_users": user.is_superuser,
        "user": profile,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def shop_info(request):
    return Response({
        "name": settings.SHOP_NAME,
        "website": settings.SHOP_WEBSITE,
        "phone": settings.SHOP_PHONE,
        "paybill": settings.SHOP_PAYBILL,
        "mpesa_enabled": bool(settings.SHOP_PAYBILL),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_logout(request):
    request.auth.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)

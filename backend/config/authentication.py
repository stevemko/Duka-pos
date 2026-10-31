from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        ttl = timedelta(days=settings.AUTH_TOKEN_TTL_DAYS)
        if token.created < timezone.now() - ttl:
            token.delete()
            raise AuthenticationFailed("Your session has expired. Please sign in again.")
        return user, token

"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path, re_path
from .auth_views import api_login, api_logout, shop_info
from .views import media_file, spa_index
from accounts.views import ChangePasswordView, MeView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/login/', api_login, name='api-login'),
    path('api/auth/logout/', api_logout, name='api-logout'),
    path('api/auth/me/', MeView.as_view(), name='api-me'),
    path('api/auth/change-password/', ChangePasswordView.as_view(), name='api-change-password'),
    path('api/shop/', shop_info, name='shop-info'),
    path('api/', include('accounts.urls')),
    path('api/', include('products.urls')),
    path('api/', include('sales.urls')),
    path('api/', include('alerts.urls')),
    path('api/', include('expenses.urls')),
    # Product photos live on disk, so they are served the same way whether or not
    # DEBUG is on - a shop machine has no nginx sitting in front to take them.
    re_path(r"^media/(?P<relpath>.+)$", media_file, name="media"),
    # Everything else belongs to the React app. /sw.js has to be served from the
    # origin root or the service worker cannot control the rest of the site.
    re_path(r"^(?!api/|admin/|media/|static/).*$", spa_index, name="spa"),
]

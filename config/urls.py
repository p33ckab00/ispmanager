from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.landing.views import public_homepage

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', public_homepage, name='public-homepage'),
    path('', include('apps.core.urls')),
    path('auth/', include('apps.core.auth_urls')),
    path('dashboard/', include('apps.core.dashboard_urls')),
    path('routers/', include('apps.routers.urls')),
    path('subscribers/', include('apps.subscribers.urls')),
    path('billing/', include('apps.billing.urls')),
    path('accounting/', include('apps.accounting.urls')),
    path('sms/', include('apps.sms.urls')),
    path('notifications/', include('apps.notifications.urls')),
    path('diagnostics/', include('apps.diagnostics.urls')),
    path('landing/', include('apps.landing.urls')),
    path('nms/', include('apps.nms.urls')),
    path('data-exchange/', include('apps.data_exchange.urls')),
    path('settings/', include('apps.settings_app.urls')),
    path('api/v1/', include('config.api_urls')),
    path('b/<str:short_code>/', include('apps.billing.short_urls')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

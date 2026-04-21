from django.urls import path, include

urlpatterns = [
    path('core/', include('apps.core.api_urls')),
    path('routers/', include('apps.routers.api_urls')),
    path('subscribers/', include('apps.subscribers.api_urls')),
    path('billing/', include('apps.billing.api_urls')),
    path('accounting/', include('apps.accounting.api_urls')),
    path('sms/', include('apps.sms.api_urls')),
    path('notifications/', include('apps.notifications.api_urls')),
    path('diagnostics/', include('apps.diagnostics.api_urls')),
    path('landing/', include('apps.landing.api_urls')),
    path('settings/', include('apps.settings_app.api_urls')),
]

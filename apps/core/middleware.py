from django.shortcuts import redirect
from django.conf import settings


EXEMPT_URLS = [
    '/setup/',
    '/auth/login/',
    '/auth/logout/',
    '/static/',
    '/media/',
    '/admin/',
]


class FirstRunMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info

        for url in EXEMPT_URLS:
            if path.startswith(url):
                return self.get_response(request)

        from apps.core.models import SystemSetup
        setup = SystemSetup.get_setup()

        if not setup.is_configured:
            return redirect('/setup/')

        return self.get_response(request)

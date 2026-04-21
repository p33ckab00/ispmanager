from apps.core.models import SystemSetup


def system_settings(request):
    setup = SystemSetup.get_setup()
    return {
        'isp_name': setup.isp_name or 'ISP Manager',
        'isp_logo': setup.isp_logo,
        'isp_email': setup.isp_email,
        'isp_phone': setup.isp_phone,
        'system_configured': setup.is_configured,
    }

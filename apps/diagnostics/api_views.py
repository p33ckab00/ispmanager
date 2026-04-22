from rest_framework.response import Response
from rest_framework.views import APIView

from apps.diagnostics.services import build_diagnostics_snapshot


class DiagnosticsHealthView(APIView):
    def get(self, request):
        snapshot = build_diagnostics_snapshot()
        runtime = snapshot['runtime']
        scheduler = snapshot['scheduler']
        messaging = snapshot['messaging']

        if runtime['database']['ok']:
            db_status = {'state': 'healthy', 'label': 'OK'}
        else:
            db_status = {'state': 'critical', 'label': 'Failed'}

        if scheduler['service_health'] == 'healthy':
            scheduler_status = {'state': 'healthy', 'label': 'Healthy'}
        elif scheduler['service_health'] == 'warning':
            scheduler_status = {'state': 'warning', 'label': 'Attention'}
        else:
            scheduler_status = {'state': 'critical', 'label': 'Critical'}

        if messaging['telegram']['configured'] and messaging['telegram']['enabled']:
            telegram_label = 'Enabled'
            telegram_state = 'healthy' if messaging['telegram']['failed_last_24h'] == 0 else 'warning'
        elif messaging['telegram']['configured']:
            telegram_label = 'Disabled'
            telegram_state = 'warning'
        else:
            telegram_label = 'Not configured'
            telegram_state = 'neutral'

        if messaging['sms']['configured'] and messaging['sms']['billing_enabled']:
            sms_label = 'Enabled'
            sms_state = 'healthy' if messaging['sms']['today_failed'] == 0 else 'warning'
        elif messaging['sms']['configured']:
            sms_label = 'Configured'
            sms_state = 'healthy'
        else:
            sms_label = 'Not configured'
            sms_state = 'neutral'

        return Response({
            'overall_health': snapshot['overall_health'],
            'active_alerts': len(snapshot['alerts']),
            'database': db_status,
            'scheduler': scheduler_status,
            'telegram': {
                'state': telegram_state,
                'label': telegram_label,
                'failed_last_24h': messaging['telegram']['failed_last_24h'],
            },
            'sms': {
                'state': sms_state,
                'label': sms_label,
                'failed_today': messaging['sms']['today_failed'],
            },
        })

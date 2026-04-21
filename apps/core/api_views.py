from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from apps.core.models import SystemSetup, AuditLog
from apps.core.serializers import SystemSetupSerializer, AuditLogSerializer


class SetupStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        setup = SystemSetup.get_setup()
        return Response({'is_configured': setup.is_configured})


class AuditLogListView(ListAPIView):
    serializer_class = AuditLogSerializer
    queryset = AuditLog.objects.select_related('user').all()

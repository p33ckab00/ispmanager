from rest_framework import serializers
from apps.core.models import SystemSetup, AuditLog


class SystemSetupSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetup
        fields = ['is_configured', 'isp_name', 'isp_address', 'isp_phone', 'isp_email', 'configured_at']


class AuditLogSerializer(serializers.ModelSerializer):
    user_display = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ['id', 'user_display', 'action', 'module', 'description', 'ip_address', 'created_at']

    def get_user_display(self, obj):
        return obj.user.username if obj.user else 'system'

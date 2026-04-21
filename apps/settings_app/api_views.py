from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.settings_app.models import BillingSettings, SMSSettings, TelegramSettings, RouterSettings
from apps.settings_app.serializers import (
    BillingSettingsSerializer, SMSSettingsSerializer,
    TelegramSettingsSerializer, RouterSettingsSerializer
)


class BillingSettingsAPIView(APIView):
    def get(self, request):
        obj = BillingSettings.get_settings()
        return Response(BillingSettingsSerializer(obj).data)

    def patch(self, request):
        obj = BillingSettings.get_settings()
        s = BillingSettingsSerializer(obj, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)


class SMSSettingsAPIView(APIView):
    def get(self, request):
        obj = SMSSettings.get_settings()
        return Response(SMSSettingsSerializer(obj).data)

    def patch(self, request):
        obj = SMSSettings.get_settings()
        s = SMSSettingsSerializer(obj, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)


class TelegramSettingsAPIView(APIView):
    def get(self, request):
        obj = TelegramSettings.get_settings()
        return Response(TelegramSettingsSerializer(obj).data)

    def patch(self, request):
        obj = TelegramSettings.get_settings()
        s = TelegramSettingsSerializer(obj, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)


class RouterSettingsAPIView(APIView):
    def get(self, request):
        obj = RouterSettings.get_settings()
        return Response(RouterSettingsSerializer(obj).data)

    def patch(self, request):
        obj = RouterSettings.get_settings()
        s = RouterSettingsSerializer(obj, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)

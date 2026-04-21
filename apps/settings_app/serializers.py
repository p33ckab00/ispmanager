from rest_framework import serializers
from apps.settings_app.models import BillingSettings, SMSSettings, TelegramSettings, RouterSettings


class BillingSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingSettings
        fields = '__all__'


class SMSSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SMSSettings
        fields = '__all__'
        extra_kwargs = {'semaphore_api_key': {'write_only': True}}


class TelegramSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramSettings
        fields = '__all__'
        extra_kwargs = {'bot_token': {'write_only': True}}


class RouterSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RouterSettings
        fields = '__all__'

from rest_framework import serializers
from apps.subscribers.models import Subscriber, Plan, RateHistory


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = '__all__'


class RateHistorySerializer(serializers.ModelSerializer):
    old_plan_name = serializers.SerializerMethodField()
    new_plan_name = serializers.SerializerMethodField()

    class Meta:
        model = RateHistory
        fields = '__all__'

    def get_old_plan_name(self, obj):
        return obj.old_plan.name if obj.old_plan else None

    def get_new_plan_name(self, obj):
        return obj.new_plan.name if obj.new_plan else None


class SubscriberSerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    effective_rate = serializers.ReadOnlyField()
    plan_name = serializers.SerializerMethodField()
    is_on_map = serializers.ReadOnlyField()

    class Meta:
        model = Subscriber
        fields = [
            'id', 'username', 'mt_profile', 'service_type',
            'mac_address', 'ip_address', 'mt_status', 'last_synced',
            'full_name', 'phone', 'address', 'email',
            'latitude', 'longitude', 'plan', 'plan_name',
            'monthly_rate', 'billing_effective_from', 'cutoff_day',
            'start_date', 'status', 'notes', 'sms_opt_out',
            'display_name', 'effective_rate', 'is_on_map',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['username', 'mt_profile', 'mac_address', 'ip_address', 'mt_status', 'last_synced']

    def get_plan_name(self, obj):
        return obj.plan.name if obj.plan else None

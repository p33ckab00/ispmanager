from rest_framework import serializers
from apps.accounting.models import IncomeRecord, ExpenseRecord

class IncomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = IncomeRecord
        fields = '__all__'

class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseRecord
        fields = '__all__'

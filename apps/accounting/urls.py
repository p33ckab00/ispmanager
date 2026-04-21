from django.urls import path
from apps.accounting import views

urlpatterns = [
    path('', views.accounting_dashboard, name='accounting-dashboard'),
    path('income/', views.income_list, name='income-list'),
    path('income/add/', views.income_add, name='income-add'),
    path('expenses/', views.expense_list, name='expense-list'),
    path('expenses/add/', views.expense_add, name='expense-add'),
    path('sync/', views.sync_income, name='accounting-sync'),
]

from django.urls import path
from apps.accounting import views

urlpatterns = [
    path('', views.accounting_dashboard, name='accounting-dashboard'),
    path('setup/', views.accounting_setup, name='accounting-setup'),
    path('chart/', views.chart_list, name='accounting-chart-list'),
    path('periods/', views.period_list, name='accounting-period-list'),
    path('journals/', views.journal_list, name='accounting-journal-list'),
    path('journals/add/', views.journal_add, name='accounting-journal-add'),
    path('journals/<int:pk>/', views.journal_detail, name='accounting-journal-detail'),
    path('journals/<int:pk>/post/', views.journal_post, name='accounting-journal-post'),
    path('review/', views.source_review, name='accounting-source-review'),
    path('trial-balance/', views.trial_balance, name='accounting-trial-balance'),
    path('income/', views.income_list, name='income-list'),
    path('income/add/', views.income_add, name='income-add'),
    path('expenses/', views.expense_list, name='expense-list'),
    path('expenses/add/', views.expense_add, name='expense-add'),
    path('sync/', views.sync_income, name='accounting-sync'),
]

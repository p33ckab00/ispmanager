from django.urls import path
from apps.landing import views

urlpatterns = [
    path('', views.landing_dashboard, name='landing-dashboard'),
    path('<str:page_type>/edit/', views.landing_edit, name='landing-edit'),
    path('<str:page_type>/publish/', views.landing_publish, name='landing-publish'),
    path('<str:page_type>/plans/add/', views.landing_plan_add, name='landing-plan-add'),
    path('plans/<int:pk>/delete/', views.landing_plan_delete, name='landing-plan-delete'),
    path('home/', views.public_homepage, name='public-homepage'),
    path('captive/', views.public_captive, name='public-captive'),
]

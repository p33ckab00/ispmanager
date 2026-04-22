from django.urls import path
from apps.landing import views

urlpatterns = [
    path('', views.landing_dashboard, name='landing-dashboard'),
    path('<str:page_type>/edit/', views.landing_edit, name='landing-edit'),
    path('<str:page_type>/publish/', views.landing_publish, name='landing-publish'),
    path('<str:page_type>/plans/add/', views.landing_plan_add, name='landing-plan-add'),
    path('<str:page_type>/faqs/', views.landing_faq_list, name='landing-faq-list'),
    path('<str:page_type>/faqs/add/', views.landing_faq_add, name='landing-faq-add'),
    path('plans/<int:pk>/delete/', views.landing_plan_delete, name='landing-plan-delete'),
    path('faqs/<int:pk>/edit/', views.landing_faq_edit, name='landing-faq-edit'),
    path('faqs/<int:pk>/delete/', views.landing_faq_delete, name='landing-faq-delete'),
    path('inquiries/', views.landing_inquiry_list, name='landing-inquiry-list'),
    path('inquiries/<int:pk>/status/', views.landing_inquiry_update, name='landing-inquiry-update'),
    path('home/', views.public_homepage, name='public-homepage-preview'),
    path('captive/', views.public_captive, name='public-captive'),
]

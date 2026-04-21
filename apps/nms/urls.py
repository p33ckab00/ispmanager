from django.urls import path
from apps.nms import views

urlpatterns = [
    path('', views.nms_map, name='nms-map'),
    path('data/', views.nms_map_data, name='nms-map-data'),
]

from django.urls import path
from apps.nms import views

urlpatterns = [
    path('', views.nms_map, name='nms-map'),
    path('data/', views.nms_map_data, name='nms-map-data'),
    path('nodes/', views.nms_nodes, name='nms-nodes'),
    path('distribution/<int:node_pk>/', views.nms_distribution_detail, name='nms-distribution-detail'),
    path('api/nodes/create/', views.nms_create_node_api, name='nms-create-node-api'),
    path('api/links/create/', views.nms_create_link_api, name='nms-create-link-api'),
    path('api/links/<int:link_pk>/geometry/', views.nms_update_link_geometry_api, name='nms-update-link-geometry-api'),
    path('links/', views.nms_links, name='nms-links'),
    path('links/<int:link_pk>/delete/', views.nms_delete_link, name='nms-delete-link'),
    path('subscribers/<int:subscriber_pk>/', views.nms_subscriber_workspace, name='nms-subscriber-workspace'),
    path('subscribers/<int:subscriber_pk>/remove/', views.nms_remove_service_attachment, name='nms-remove-service-attachment'),
]

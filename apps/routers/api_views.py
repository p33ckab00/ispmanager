from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.routers.models import Router, RouterInterface, InterfaceTrafficCache
from apps.routers.serializers import RouterSerializer, RouterInterfaceSerializer
from apps.routers.services import (
    sync_interfaces,
    get_live_traffic,
    get_telemetry_stale_after_seconds,
    serialize_telemetry_cache,
)
from apps.routers import mikrotik
from apps.settings_app.models import RouterSettings


class RouterListCreateView(generics.ListCreateAPIView):
    queryset = Router.objects.filter(is_active=True)
    serializer_class = RouterSerializer


class RouterDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Router.objects.all()
    serializer_class = RouterSerializer


class RouterSyncView(APIView):
    def post(self, request, pk):
        try:
            router = Router.objects.get(pk=pk)
        except Router.DoesNotExist:
            return Response({'error': 'Router not found'}, status=status.HTTP_404_NOT_FOUND)
        ok, msg = sync_interfaces(router)
        return Response({'ok': ok, 'message': msg})


class RouterInterfaceListView(generics.ListAPIView):
    serializer_class = RouterInterfaceSerializer

    def get_queryset(self):
        return RouterInterface.objects.filter(router_id=self.kwargs['pk'])


class InterfaceTrafficView(APIView):
    def get(self, request, router_pk, iface_pk):
        try:
            router = Router.objects.get(pk=router_pk)
            iface = RouterInterface.objects.get(pk=iface_pk, router=router)
        except (Router.DoesNotExist, RouterInterface.DoesNotExist):
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        data = get_live_traffic(router, iface.name)
        return Response(data)


class InterfaceTrafficCacheView(APIView):
    def get(self, request, router_pk, iface_pk):
        try:
            router = Router.objects.get(pk=router_pk)
            iface = RouterInterface.objects.get(pk=iface_pk, router=router)
        except (Router.DoesNotExist, RouterInterface.DoesNotExist):
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        router_settings = RouterSettings.get_settings()
        stale_after_seconds = get_telemetry_stale_after_seconds(router_settings.polling_interval_seconds)
        cache = InterfaceTrafficCache.objects.filter(interface=iface).first()
        return Response(serialize_telemetry_cache(iface, cache, stale_after_seconds))


class TestConnectionView(APIView):
    def post(self, request):
        host = request.data.get('host')
        username = request.data.get('username')
        password = request.data.get('password')
        port = request.data.get('port', 8728)
        if not all([host, username, password]):
            return Response({'ok': False, 'message': 'host, username and password required'},
                            status=status.HTTP_400_BAD_REQUEST)
        ok, result = mikrotik.test_connection(host, username, password, port)
        return Response({'ok': ok, 'message': result})

from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.subscribers.models import Subscriber, Plan, RateHistory
from apps.subscribers.serializers import SubscriberSerializer, PlanSerializer, RateHistorySerializer
from apps.subscribers.services import sync_ppp_secrets, sync_active_sessions
from apps.routers.models import Router


class SubscriberListView(generics.ListAPIView):
    serializer_class = SubscriberSerializer

    def get_queryset(self):
        qs = Subscriber.objects.select_related('plan', 'router').all()
        status_filter = self.request.query_params.get('status')
        service = self.request.query_params.get('service')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if service:
            qs = qs.filter(service_type=service)
        return qs


class SubscriberDetailView(generics.RetrieveUpdateAPIView):
    queryset = Subscriber.objects.all()
    serializer_class = SubscriberSerializer


class PlanListCreateView(generics.ListCreateAPIView):
    queryset = Plan.objects.filter(is_active=True)
    serializer_class = PlanSerializer


class PlanDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer


class RateHistoryView(generics.ListAPIView):
    serializer_class = RateHistorySerializer

    def get_queryset(self):
        return RateHistory.objects.filter(subscriber_id=self.kwargs['pk'])


class SyncSubscribersView(APIView):
    def post(self, request):
        routers = Router.objects.filter(is_active=True, status='online')
        if not routers.exists():
            return Response({'error': 'No online routers.'}, status=status.HTTP_400_BAD_REQUEST)
        total_added = 0
        total_updated = 0
        errors = []
        for router in routers:
            added, updated, err = sync_ppp_secrets(router)
            if err:
                errors.append(f"{router.name}: {err}")
            else:
                total_added += added
                total_updated += updated
                sync_active_sessions(router)
        return Response({'added': total_added, 'updated': total_updated, 'errors': errors})

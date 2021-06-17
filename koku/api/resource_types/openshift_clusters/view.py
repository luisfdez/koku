#
# Copyright 2021 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""View for Openshift clusters."""
from django.db.models import F
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
from rest_framework import filters
from rest_framework import generics

from api.common import CACHE_RH_IDENTITY_HEADER
from api.common.permissions.openshift_access import OpenShiftAccessPermission
from api.resource_types.serializers import ResourceTypeSerializer
from reporting.provider.ocp.models import OCPCostSummary


class OCPClustersView(generics.ListAPIView):
    """API GET list view for Openshift clusters."""

    queryset = OCPCostSummary.objects.annotate(**{"value": F("cluster_id")}).values("value").distinct()
    serializer_class = ResourceTypeSerializer
    permission_classes = [OpenShiftAccessPermission]
    filter_backends = [filters.OrderingFilter]
    ordering = ["value"]

    @method_decorator(vary_on_headers(CACHE_RH_IDENTITY_HEADER))
    def list(self, request):
        # Reads the users values for Openshift cluster id and displays values related to what the user has access to
        if request.user.access:
            user_access = request.user.access.get("openshift.cluster", {}).get("read", [])
        else:
            user_access = []
        self.queryset = self.queryset.values("value").filter(cluster_id__in=user_access)
        return super().list(request)

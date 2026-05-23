from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from django.views.generic import TemplateView
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions.roles import IsAdminOrOwner

from .models import DocumentExtraction
from .serializers import DocumentExtractionCreateSerializer, DocumentExtractionResultSerializer
from .services import DocumentExtractionError, DocumentExtractionService


class DocumentExtractionTestFormView(TemplateView):
    template_name = "document_extractor/test_form.html"


class DocumentExtractionListCreateView(APIView):
    permission_classes = [IsAdminOrOwner]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        queryset = DocumentExtraction.objects.filter(
            tenant_id=request.tenant_id,
        ).order_by("-created_at")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = DocumentExtractionResultSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = DocumentExtractionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = DocumentExtractionService()
        try:
            extraction = service.extract_from_upload(
                request_obj=request,
                image_file=serializer.validated_data["image"],
                provider=serializer.validated_data.get("provider") or None,
                metadata=serializer.validated_data.get("metadata") or {},
            )
        except DocumentExtractionError as exc:
            if exc.extraction is not None:
                data = DocumentExtractionResultSerializer(exc.extraction).data
                return Response(data, status=exc.status_code)
            return Response({"error": exc.message}, status=exc.status_code)

        data = DocumentExtractionResultSerializer(extraction).data
        return Response(data, status=status.HTTP_201_CREATED)


class DocumentExtractionDetailView(generics.RetrieveAPIView):
    serializer_class = DocumentExtractionResultSerializer
    permission_classes = [IsAdminOrOwner]
    lookup_field = "uuid"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DocumentExtraction.objects.none()
        return DocumentExtraction.objects.filter(tenant_id=self.request.tenant_id)

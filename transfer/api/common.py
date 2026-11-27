"""Shared JSON response helpers for the versioned HTTP API."""
from django.http import JsonResponse


def api_error(message, status=400):
    """Return the stable JSON error envelope used by API endpoints."""
    return JsonResponse({"error": {"message": message}}, status=status)

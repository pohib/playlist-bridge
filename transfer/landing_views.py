"""Public landing-page handlers."""

from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def home(request):
    return render(request, "transfer/landing.html")

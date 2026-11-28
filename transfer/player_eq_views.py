"""Account-owned equalizer preset endpoints."""
import json
import math

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .domain_models import UserEQPreset

MAX_PRESETS_PER_USER = 20


def _validated_settings(payload):
    if not isinstance(payload, dict):
        return None
    result = {}
    for key, low, high in (("gains", -12, 12), ("frequencies", 20, 20000), ("qs", 0.3, 8)):
        values = payload.get(key)
        if not isinstance(values, list) or len(values) != 5:
            return None
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not low <= value <= high or (isinstance(value, float) and not math.isfinite(value))
            for value in values
        ):
            return None
        result[key] = [round(float(value), 2) for value in values]
    return result


@login_required
@require_GET
def eq_presets(request):
    presets = UserEQPreset.objects.filter(user=request.user).order_by("name", "created_at")
    return JsonResponse({"presets": [
        {"id": str(item.pk), "name": item.name, "gains": item.gains, "frequencies": item.frequencies, "qs": item.qs}
        for item in presets
    ]})


@login_required
@require_POST
def eq_presets_create(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Некорректный формат данных."}, status=400)
    name = payload.get("name", "").strip() if isinstance(payload, dict) and isinstance(payload.get("name"), str) else ""
    if not name or len(name) > 40:
        return JsonResponse({"error": "Название пресета должно содержать от 1 до 40 символов."}, status=400)
    values = _validated_settings(payload)
    if values is None:
        return JsonResponse({"error": "Параметры эквалайзера имеют недопустимый формат или значения."}, status=400)
    try:
        with transaction.atomic():
            if UserEQPreset.objects.filter(user=request.user).count() >= MAX_PRESETS_PER_USER:
                return JsonResponse({"error": f"Можно сохранить не более {MAX_PRESETS_PER_USER} пресетов."}, status=400)
            preset = UserEQPreset.objects.create(user=request.user, name=name, **values)
    except IntegrityError:
        return JsonResponse({"error": "Пресет с таким названием уже существует."}, status=409)
    return JsonResponse({"preset": {
        "id": str(preset.pk), "name": preset.name,
        "gains": preset.gains, "frequencies": preset.frequencies, "qs": preset.qs,
    }}, status=201)


@login_required
@require_http_methods(["DELETE"])
def eq_preset_detail(request, preset_id):
    preset = get_object_or_404(UserEQPreset, pk=preset_id, user=request.user)
    preset.delete()
    return JsonResponse({"deleted": True})

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("transfer.urls")),
]

handler404 = "transfer.api_views.api_not_found"

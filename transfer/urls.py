from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("spotify/login/", views.spotify_login, name="spotify_login"),
    path("spotify/callback/", views.spotify_callback, name="spotify_callback"),
    path("transfer/", views.transfer_playlist, name="transfer_playlist"),
    path("report.csv", views.download_report, name="download_report"),
    path("api/v1/status/", views.api_status, name="api_status"),
    path("api/v1/transfers/", views.api_create_transfer, name="api_create_transfer"),
    path("api/v1/transfers/<uuid:job_id>/", views.api_transfer_detail, name="api_transfer_detail"),
    path("api/v1/transfers/<uuid:job_id>/report/", views.api_transfer_report, name="api_transfer_report"),
    path("api/v1/openapi.json", views.api_openapi, name="api_openapi"),
]

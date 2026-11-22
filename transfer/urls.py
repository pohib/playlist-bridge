from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("spotify/login/", views.spotify_login, name="spotify_login"),
    path("spotify/callback/", views.spotify_callback, name="spotify_callback"),
    path("transfer/", views.transfer_playlist, name="transfer_playlist"),
    path("report.csv", views.download_report, name="download_report"),
]

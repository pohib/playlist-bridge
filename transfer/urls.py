from django.urls import path

from . import library_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("spotify/login/", views.spotify_login, name="spotify_login"),
    path("spotify/callback/", views.spotify_callback, name="spotify_callback"),
    path("spotify/disconnect/", views.disconnect_spotify, name="disconnect_spotify"),
    path("vk/login/", views.vk_login, name="vk_login"),
    path("vk/callback/", views.vk_callback, name="vk_callback"),
    path("vk/disconnect/", views.disconnect_vk, name="disconnect_vk"),
    path("transfer/", views.transfer_playlist, name="transfer_playlist"),
    path("report.csv", views.download_report, name="download_report"),
    path("library/playlists/create/", library_views.create_playlist, name="library_create_playlist"),
    path("library/playlists/<uuid:playlist_id>/tracks/add/", library_views.add_track, name="library_add_track"),
    path("library/playlists/<uuid:playlist_id>/delete/", library_views.delete_playlist, name="library_delete_playlist"),
    path("library/tracks/<uuid:track_id>/delete/", library_views.delete_track, name="library_delete_track"),
    path("api/v1/status/", views.api_status, name="api_status"),
    path("api/v1/transfers/", views.api_create_transfer, name="api_create_transfer"),
    path("api/v1/transfers/<uuid:job_id>/", views.api_transfer_detail, name="api_transfer_detail"),
    path("api/v1/transfers/<uuid:job_id>/report/", views.api_transfer_report, name="api_transfer_report"),
    path("api/v1/openapi.json", views.api_openapi, name="api_openapi"),
]

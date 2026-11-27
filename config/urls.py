from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", RedirectView.as_view(url="/control/", permanent=False)),
    path("", include("transfer.urls")),
]

handler400 = "transfer.error_views.bad_request"
handler403 = "transfer.error_views.permission_denied"
handler404 = "transfer.error_views.page_not_found"
handler500 = "transfer.error_views.server_error"

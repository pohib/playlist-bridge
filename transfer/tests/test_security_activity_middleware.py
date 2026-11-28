from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse

from transfer.models import UserSecurityEvent
from transfer.security_activity_middleware import SecurityActivityMiddleware


class SecurityActivityMiddlewareTests(TestCase):
    def test_allowlisted_authenticated_action_records_safe_request_context(self):
        user = get_user_model().objects.create_user(username="activity-user", password="test-password")
        request = RequestFactory().post(
            reverse("library_import_vk"),
            data={"url": "https://example.test/private?token=must-not-be-recorded"},
            HTTP_USER_AGENT="Test Browser",
            HTTP_X_REAL_IP="203.0.113.12",
            HTTP_REFERER="https://app.example.test/library/",
        )
        request.user = user
        request.resolver_match = resolve(request.path)
        middleware = SecurityActivityMiddleware(lambda _request: HttpResponse(status=422))
        response = middleware(request)
        event = UserSecurityEvent.objects.get(event_type=UserSecurityEvent.EventType.USER_ACTIVITY)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response["X-Request-ID"], str(event.request_id))
        self.assertEqual(event.user, user)
        self.assertEqual(event.http_method, "POST")
        self.assertEqual(event.route_name, "library_import_vk")
        self.assertEqual(event.response_status, 422)
        self.assertEqual(event.ip_address, "203.0.113.12")
        self.assertEqual(event.referer_host, "app.example.test")
        self.assertNotIn("must-not-be-recorded", str(event.__dict__))

    def test_unlisted_route_is_not_recorded(self):
        user = get_user_model().objects.create_user(username="activity-user-2", password="test-password")
        middleware = SecurityActivityMiddleware(lambda _request: HttpResponse("ok"))
        request = RequestFactory().get("/")
        request.user = user
        request.resolver_match = resolve("/")
        middleware(request)
        self.assertFalse(UserSecurityEvent.objects.filter(event_type=UserSecurityEvent.EventType.USER_ACTIVITY).exists())

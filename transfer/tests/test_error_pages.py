from django.test import RequestFactory, TestCase, override_settings

from transfer.error_views import permission_denied, server_error


@override_settings(DEBUG=False)
class GenericErrorPageTests(TestCase):
    def test_unknown_browser_route_uses_generic_html_page(self):
        response = self.client.get("/this-route-must-not-exist/private-token/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(response["Content-Type"].startswith("text/html"))
        self.assertContains(response, "Страница не найдена", status_code=404)
        self.assertContains(response, "404", status_code=404)
        self.assertNotContains(response, "private-token", status_code=404)
        self.assertIn("no-store", response["Cache-Control"])

    def test_unknown_api_route_keeps_json_contract(self):
        response = self.client.get("/api/v1/this-route-must-not-exist/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            response.json(),
            {"error": {"message": "API endpoint not found."}},
        )

    def test_permission_denied_uses_generic_html_without_exception_details(self):
        request = RequestFactory().get("/private/resource/")
        response = permission_denied(request, RuntimeError("sensitive-internal-detail"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Недостаточно прав", status_code=403)
        self.assertNotContains(response, "sensitive-internal-detail", status_code=403)

    def test_server_error_uses_generic_html_without_traceback(self):
        request = RequestFactory().get("/triggered-server-error/")
        response = server_error(request)

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Внутренняя ошибка", status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)

    def test_api_server_error_keeps_generic_json_contract(self):
        request = RequestFactory().get("/api/v1/private/")
        response = server_error(request)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            response.content,
            b'{"error": {"message": "Internal server error."}}',
        )

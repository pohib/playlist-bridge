from django.test import TestCase
from django.urls import resolve, reverse

from transfer import api_views
from transfer.api import api_error, serialize_job
from transfer.api import api_create_transfer, api_docs, api_openapi, api_status
from transfer.api import api_transfer_detail, api_transfer_report
from transfer.models import TransferJob


class ApiModuleBoundaryTests(TestCase):
    def test_legacy_facade_reexports_every_public_api_view(self):
        expected = {
            "api_create_transfer": api_create_transfer,
            "api_docs": api_docs,
            "api_error": api_error,
            "api_openapi": api_openapi,
            "api_status": api_status,
            "api_transfer_detail": api_transfer_detail,
            "api_transfer_report": api_transfer_report,
            "serialize_job": serialize_job,
        }
        for name, implementation in expected.items():
            with self.subTest(name=name):
                self.assertIs(getattr(api_views, name), implementation)

    def test_api_urls_resolve_to_domain_specific_modules(self):
        expected_modules = {
            "api_status": "transfer.api.status_views",
            "api_create_transfer": "transfer.api.transfer_views",
            "api_transfer_detail": "transfer.api.transfer_views",
            "api_transfer_report": "transfer.api.transfer_views",
            "api_openapi": "transfer.api.docs_views",
            "api_docs": "transfer.api.docs_views",
        }
        for route_name, module_name in expected_modules.items():
            with self.subTest(route_name=route_name):
                self.assertEqual(resolve(reverse(route_name)).func.__module__, module_name)

    def test_api_error_keeps_the_existing_json_envelope(self):
        response = api_error("Invalid request.", 422)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"error": {"message": "Invalid request."}})

    def test_transfer_serializer_keeps_contract_and_hides_session_fingerprint(self):
        job = TransferJob.objects.create(
            session_fingerprint="private-session-fingerprint",
            source_url="https://vk.com/music/playlist/1_2",
            status=TransferJob.Status.SUCCEEDED,
            result={"target_playlist_id": "A" * 22, "report": [{"status": "matched"}]},
        )
        payload = serialize_job(job)
        self.assertEqual(payload["id"], str(job.pk))
        self.assertEqual(payload["status"], TransferJob.Status.SUCCEEDED)
        self.assertEqual(payload["target_playlist_id"], "A" * 22)
        self.assertNotIn("session_fingerprint", payload)
        self.assertNotIn("report", payload)

    def test_transfer_serializer_does_not_expose_target_before_success(self):
        job = TransferJob.objects.create(
            session_fingerprint="private-session-fingerprint",
            source_url="https://vk.com/music/playlist/1_2",
            result={"target_playlist_id": "A" * 22},
        )
        self.assertIsNone(serialize_job(job)["target_playlist_id"])

    def test_create_endpoint_rejects_non_json_content_type(self):
        response = self.client.post(reverse("api_create_transfer"), data="source_url=x")
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json(), {
            "error": {"message": "Используй Content-Type: application/json."}
        })

    def test_create_endpoint_rejects_malformed_json(self):
        response = self.client.post(
            reverse("api_create_transfer"),
            data="{invalid",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {
            "error": {"message": "Тело запроса содержит некорректный JSON."}
        })

    def test_create_endpoint_rejects_non_object_json(self):
        response = self.client.post(
            reverse("api_create_transfer"),
            data='["not", "an", "object"]',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": {"message": "Ожидается JSON-объект."}})

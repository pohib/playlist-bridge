import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from transfer.models import UserEQPreset


class UserEQPresetTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="eq-user", password="test-password")
        self.other = get_user_model().objects.create_user(username="eq-other", password="test-password")
        self.url = reverse("player_eq_presets")

    def payload(self, name="My 808"):
        return {
            "name": name,
            "gains": [4, -2, -1, 0, 2],
            "frequencies": [60, 250, 1000, 4000, 12000],
            "qs": [1, 1.2, 0.8, 1, 1.5],
        }

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(reverse("player_eq_presets_create"), data=json.dumps(self.payload()), content_type="application/json").status_code, 302)

    def test_user_can_save_and_list_own_presets(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("player_eq_presets_create"), data=json.dumps(self.payload()), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        preset = UserEQPreset.objects.get(user=self.user)
        self.assertEqual(preset.gains, self.payload()["gains"])
        listed = self.client.get(self.url)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["presets"][0]["id"], str(preset.pk))

    def test_duplicate_names_are_case_insensitive(self):
        self.client.force_login(self.user)
        self.client.post(reverse("player_eq_presets_create"), data=json.dumps(self.payload()), content_type="application/json")
        response = self.client.post(reverse("player_eq_presets_create"), data=json.dumps(self.payload("my 808")), content_type="application/json")
        self.assertEqual(response.status_code, 409)

    def test_invalid_values_are_rejected(self):
        self.client.force_login(self.user)
        payload = self.payload()
        payload["gains"][0] = 40
        response = self.client.post(reverse("player_eq_presets_create"), data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserEQPreset.objects.exists())

    def test_presets_are_private_and_delete_is_owner_scoped(self):
        values = self.payload()
        preset = UserEQPreset.objects.create(
            user=self.user, name="Private", gains=values["gains"],
            frequencies=values["frequencies"], qs=values["qs"],
        )
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).json()["presets"], [])
        response = self.client.delete(reverse("player_eq_preset_detail", args=[preset.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(UserEQPreset.objects.filter(pk=preset.pk).exists())

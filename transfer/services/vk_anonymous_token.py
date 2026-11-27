"""Anonymous VK web-client token acquisition."""
import requests

from .common import TransferError

class VKAnonymousTokenProvider:
    """Obtain a short-lived anonymous token using VK's public web client."""

    ENDPOINT_URL = "https://login.vk.ru/"
    MODALS_ENDPOINT = "https://vk.ru/al_index.php"
    CLIENT_ID = "6287487"
    # Public web-client credential observed in VK's own browser request.
    # This is not a credential for a user-created VK application.
    WEB_CLIENT_PARAMETER = "QbYic1K3lEV5kTGiqlq2"
    SCOPES = "audio_anonymous,video_anonymous,photos_anonymous,profile_anonymous"
    BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "sec-ch-ua-mobile": "?0",
    }

    def __init__(self, client_id=None, http=None):
        self.client_id = str(client_id or self.CLIENT_ID)
        self.web_client_parameter = self.WEB_CLIENT_PARAMETER
        self.http = http or requests.Session()
        self._token: str | None = None
        self._expires_at = 0
        self.referer = "https://vk.ru/"

    def get_token(self):
        import time

        if self._token is not None and time.time() < self._expires_at - 60:
            return self._token
        try:
            # Start a clean anonymous web session. The session object retains
            # only cookies issued by VK during these requests.
            bootstrap = self.http.get(
                "https://vk.ru/",
                headers={**self.BROWSER_HEADERS, "Accept": "text/html"},
                timeout=(5, 15),
                allow_redirects=False,
                stream=True,
            )
            bootstrap.raise_for_status()
            if not 200 <= bootstrap.status_code < 300:
                bootstrap.close()
                raise TransferError("VK не открыл публичную страницу для анонимной сессии.")
            bootstrap.close()

            # VK's web audio flow initializes its modal context before asking
            # login.vk.ru for an anonymous API token.
            modals = self.http.post(
                self.MODALS_ENDPOINT,
                params={"act": "modals"},
                data={"act": "modals", "al": "1", "module": "audio"},
                headers={
                    **self.BROWSER_HEADERS,
                    "Accept": "*/*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://vk.ru",
                    "Referer": self.referer,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=(5, 15),
                allow_redirects=False,
            )
            modals.raise_for_status()

            token_data = {
                "client_secret": self.web_client_parameter,
                "client_id": self.client_id,
                "scopes": self.SCOPES,
                "isApiOauthAnonymEnabled": "false",
                "version": "1",
                "app_id": self.client_id,
            }
            if self._token:
                token_data["anonymous_token"] = self._token

            response = self.http.post(
                self.ENDPOINT_URL,
                params={"act": "get_anonym_token"},
                data=token_data,
                headers={
                    **self.BROWSER_HEADERS,
                    "Accept": "*/*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://vk.ru",
                    "Referer": "https://vk.ru/",
                },
                timeout=(5, 20),
                allow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Не удалось получить анонимный токен VK.") from exc
        if not isinstance(payload, dict):
            raise TransferError("VK вернул некорректный ответ при выдаче анонимного токена.")
        data = payload.get("data")
        token = data.get("access_token") if isinstance(data, dict) else None
        expires_at = data.get("expired_at", data.get("expires")) if isinstance(data, dict) else None
        if payload.get("type") != "okay" or not isinstance(token, str) or not token.startswith("anonym."):
            raise TransferError("VK не выдал анонимный токен. Возможно, публичный API временно недоступен.")
        try:
            self._expires_at = int(expires_at)
        except (TypeError, ValueError) as exc:
            raise TransferError("VK вернул некорректный срок действия анонимного токена.") from exc
        self._token = token
        return self._token

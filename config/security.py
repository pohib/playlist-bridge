class SecurityHeadersMiddleware:
    """Apply a restrictive baseline to application and static responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "font-src 'self' data:; "
            "media-src 'self' blob: https://*.okcdn.ru https://okcdn.ru; "
            "connect-src 'self' https://*.okcdn.ru https://okcdn.ru; form-action 'self'; "
            "base-uri 'self'; object-src 'none'; frame-ancestors 'none'",
        )
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        response.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response

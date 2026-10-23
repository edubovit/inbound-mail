from django.shortcuts import redirect


class SecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.must_change_password and request.path not in {"/password/", "/logout/", "/assets/style.css"}:
            response = redirect("password")
        else:
            response = self.get_response(request)
        response.setdefault("Content-Security-Policy", "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; frame-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "same-origin"
        return response

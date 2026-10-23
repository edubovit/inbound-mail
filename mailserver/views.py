import hashlib
import hmac
import ipaddress
import logging
import shutil
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import mime
from .forms import AccountForm, ConfirmForm, EditAccountForm, LoginForm, ResetForm
from .models import Account, LoginAttempt, Message
from .storage import export_mail, used_bytes

logger = logging.getLogger(__name__)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != "ADMIN":
            return render(request, "403.html", status=403)
        return view(request, *args, **kwargs)
    return wrapped


def login_allowed(request, username):
    address = request.META.get("REMOTE_ADDR", "unknown")
    if address in {"127.0.0.1", "::1"}:
        forwarded = request.META.get("HTTP_X_REAL_IP", address)
        try:
            address = str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    now = timezone.now()
    allowed = True
    with transaction.atomic():
        LoginAttempt.objects.filter(started_at__lt=now - timedelta(minutes=15)).delete()
        if LoginAttempt.objects.count() > 10000:
            return False
        for value, limit in [(f"ip:{address}", 30), (f"user:{username}", 10)]:
            key = hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
            attempt, _ = LoginAttempt.objects.get_or_create(key=key, defaults={"started_at": now})
            attempt.count += 1
            attempt.save(update_fields=["count"])
            allowed = allowed and attempt.count <= limit
    return allowed


@require_http_methods(["GET", "POST"])
def sign_in(request):
    if request.user.is_authenticated:
        return redirect("inbox")
    form = LoginForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].lower().strip()
        if username.endswith("@" + settings.MAIL_DOMAIN):
            username = username.rsplit("@", 1)[0]
        if not login_allowed(request, username):
            form.add_error(None, "Too many attempts. Try again in 15 minutes.")
            status = 429
        else:
            user = authenticate(request, username=username, password=form.cleaned_data["password"])
            if user is not None:
                login(request, user)
                return redirect("password" if user.must_change_password else "inbox")
            form.add_error(None, "Invalid username or password.")
    return render(request, "form.html", {"title": "Sign in", "form": form, "button": "Sign in", "domain": settings.MAIL_DOMAIN}, status=status)


@require_POST
def sign_out(request):
    logout(request)
    return redirect("login")


@login_required
@require_http_methods(["GET", "POST"])
def password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    for field in form.fields.values():
        field.max_length = 1024
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save(commit=False)
            user.must_change_password = False
            user.save(update_fields=["password", "must_change_password"])
        update_session_auth_hash(request, user)
        return redirect("inbox")
    return render(request, "form.html", {"title": "Change password", "form": form, "button": "Change password", "notice": "A new password is required before continuing." if request.user.must_change_password else ""})


def inbox_context(request):
    rows = request.user.mail.defer("raw").order_by("-id")
    page = Paginator(rows, 50).get_page(request.GET.get("page"))
    return {
        "page": page,
        "used": used_bytes(request.user),
        "unread": rows.filter(is_read=False).count(),
    }


@login_required
@require_GET
def inbox(request):
    return render(request, "inbox.html", inbox_context(request))


@login_required
@require_GET
def inbox_updates(request):
    return render(request, "inbox_content.html", inbox_context(request))


def own_message(request, pk):
    return get_object_or_404(Message, pk=pk, account=request.user)


@login_required
def message(request, pk):
    item = own_message(request, pk)
    parsed = mime.parse(item.raw)
    text, truncated = mime.body(parsed, "plain")
    has_html = parsed.get_body(preferencelist=("html",)) is not None
    return render(request, "message.html", {"title": item.subject or "Message", "item": item, "plain": text, "truncated": truncated, "has_html": has_html, "attachments": mime.attachments(parsed)})


@login_required
def message_html(request, pk):
    item = own_message(request, pk)
    html, truncated = mime.body(mime.parse(item.raw), "html")
    response = HttpResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="color-scheme" content="dark"><title>Email content</title>'
        '<link rel="stylesheet" href="/assets/message.css"></head><body>'
        + ("<p>Preview truncated.</p>" if truncated else "") + html + "</body></html>"
    )
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'self'; sandbox; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


@login_required
def attachment(request, pk, index):
    item = own_message(request, pk)
    for part_index, name, part in mime.attachments(mime.parse(item.raw)):
        if part_index == index:
            data = part.get_payload(decode=True)
            if data is None:
                data = part.as_bytes()
            response = HttpResponse(data, content_type="application/octet-stream")
            response["Content-Disposition"] = content_disposition_header(True, name)
            return response
    raise Http404


@login_required
@require_POST
def read_state(request, pk):
    item = own_message(request, pk)
    item.is_read = request.POST.get("read") == "yes"
    item.save(update_fields=["is_read"])
    return redirect("message", pk=pk)


@login_required
@require_http_methods(["GET", "POST"])
def delete_message(request, pk):
    item = own_message(request, pk)
    form = ConfirmForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item.delete()
        return redirect("inbox")
    return render(request, "form.html", {"title": "Delete message permanently", "notice": item.subject or "(No subject)", "form": form, "button": "Delete permanently", "destructive": True, "cancel_url": f"/messages/{pk}/"})


@admin_required
def accounts(request):
    disk = shutil.disk_usage(settings.DATA_DIR)
    rows = Account.objects.annotate(used=Sum("mail__size")).order_by("username")
    return render(request, "accounts.html", {"title": "Accounts", "page": Paginator(rows, 50).get_page(request.GET.get("page")), "disk": disk, "reserve": settings.DISK_RESERVE_BYTES, "mail_bytes": Message.objects.aggregate(total=Sum("size"))["total"] or 0})


@admin_required
@require_http_methods(["GET", "POST"])
def create_account(request):
    form = AccountForm(request.POST or None, initial={"role": "USER", "quota_mib": settings.DEFAULT_QUOTA_BYTES // 1024**2})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            Account.objects.create_user(data["username"], data["password"], role=data["role"], quota_bytes=data["quota_mib"] * 1024**2, must_change_password=True)
        except (IntegrityError, ValidationError):
            form.add_error("username", "Account could not be created; the address may already exist.")
        else:
            logger.info("Account created by admin id=%d", request.user.id)
            return redirect("accounts")
    return render(request, "form.html", {"title": "Create account", "form": form, "button": "Create account", "cancel_url": "/admin/", "notice": f"Address will be username@{settings.MAIL_DOMAIN}. Password change required at first login."})


@admin_required
@require_http_methods(["GET", "POST"])
def edit_account(request, pk):
    account = get_object_or_404(Account, pk=pk)
    form = EditAccountForm(request.POST or None, initial={"role": account.role, "quota_mib": account.quota_bytes // 1024**2})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            account = get_object_or_404(Account, pk=pk)
            if account.role == "ADMIN" and form.cleaned_data["role"] != "ADMIN" and Account.objects.filter(role="ADMIN").count() == 1:
                form.add_error("role", "Cannot demote the final administrator.")
            else:
                account.role = form.cleaned_data["role"]
                account.quota_bytes = form.cleaned_data["quota_mib"] * 1024**2
                account.save(update_fields=["role", "quota_bytes"])
                return redirect("accounts" if request.user.pk != account.pk or account.role == "ADMIN" else "inbox")
    return render(request, "edit.html", {"title": account.address, "account": account, "form": form, "button": "Save account", "cancel_url": "/admin/"})


@admin_required
@require_http_methods(["GET", "POST"])
def reset_password(request, pk):
    account = get_object_or_404(Account, pk=pk)
    form = ResetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            validate_password(form.cleaned_data["password"], account)
        except ValidationError as error:
            form.add_error("password", error)
        else:
            account.set_password(form.cleaned_data["password"])
            account.must_change_password = True
            account.save(update_fields=["password", "must_change_password"])
            return redirect("accounts")
    return render(request, "form.html", {"title": f"Reset password: {account.username}", "notice": "Existing sessions will be revoked. The user must change this temporary password.", "form": form, "button": "Reset password", "cancel_url": f"/admin/accounts/{pk}/"})


@admin_required
@require_http_methods(["GET", "POST"])
def delete_account(request, pk):
    account = get_object_or_404(Account, pk=pk)
    form = ConfirmForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            account = get_object_or_404(Account, pk=pk)
            if account.role == "ADMIN" and Account.objects.filter(role="ADMIN").count() == 1:
                form.add_error(None, "Cannot delete the final administrator.")
            else:
                account.delete()
                return redirect("accounts")
    return render(request, "form.html", {"title": f"Delete account: {account.username}", "notice": "All messages will be permanently purged. Incoming mail to this address will be rejected.", "form": form, "button": "Delete account permanently", "destructive": True, "cancel_url": f"/admin/accounts/{pk}/"})


@admin_required
@require_http_methods(["GET", "POST"])
def export(request):
    form = ConfirmForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        logger.info("All-mail export requested by admin id=%d", request.user.id)
        response = StreamingHttpResponse(export_mail(), content_type="application/x-tar")
        response["Content-Disposition"] = 'attachment; filename="mail-export.tar"'
        return response
    return render(request, "form.html", {"title": "Export all mail", "notice": "Downloads every account's messages, including other users' private mail. New deliveries are excluded; messages deleted during export may be absent. This archive cannot be restored into the application.", "form": form, "button": "Download archive", "cancel_url": "/admin/"})


def stylesheet(request):
    return FileResponse((settings.BASE_DIR / "static" / "style.css").open("rb"), content_type="text/css")


def message_stylesheet(request):
    return FileResponse((settings.BASE_DIR / "static" / "message.css").open("rb"), content_type="text/css")


def inbox_script(request):
    return FileResponse((settings.BASE_DIR / "static" / "inbox.js").open("rb"), content_type="text/javascript")


def select_script(request):
    return FileResponse((settings.BASE_DIR / "static" / "select.js").open("rb"), content_type="text/javascript")


def favicon(request):
    return HttpResponse(status=204)


def health(request):
    Account.objects.exists()
    return HttpResponse("ok\n", content_type="text/plain")

"""Explicit, app-owned ChatGPT plan authorization on a loopback listener.

Optional CLI, never loaded by ranking. Does not read Codex/browser credentials.
No inference, billing, telemetry or corporate document transmission here.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import html
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import stat
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = ISSUER + "/api/accounts/authorize"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
JWKS_URL = ISSUER + "/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + PLAN_SCOPE
MAX_AUTH_RESPONSE_BYTES = 1024 * 1024


class AuthorizationError(ValueError):
    """Safe error code only; never includes OAuth codes, tokens or upstream body."""


def same_secret(left, right):
    return (
        isinstance(left, str)
        and isinstance(right, str)
        and len(left) <= 4096
        and secrets.compare_digest(left.encode(), right.encode())
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def auth_json(url, *, form=None):
    if url not in {TOKEN_URL, JWKS_URL}:
        raise AuthorizationError("AUTH_ENDPOINT_NOT_ALLOWED")
    body = urlencode(form).encode() if form is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        with build_opener(NoRedirect()).open(
            Request(url, data=body, headers=headers), timeout=20
        ) as response:
            data = response.read(MAX_AUTH_RESPONSE_BYTES + 1)
            if len(data) > MAX_AUTH_RESPONSE_BYTES:
                raise AuthorizationError("AUTH_RESPONSE_TOO_LARGE")
    except HTTPError as error:
        code = error.code
        error.close()
        raise AuthorizationError(f"AUTH_HTTP_{code}") from None
    except (URLError, OSError):
        raise AuthorizationError("AUTH_NETWORK_UNAVAILABLE") from None
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError):
        raise AuthorizationError("AUTH_RESPONSE_INVALID") from None
    if not isinstance(result, dict):
        raise AuthorizationError("AUTH_RESPONSE_INVALID")
    return result


class PrivateStore:
    """One owner-only directory for this installation, atomic token replacement."""

    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        if any(p.is_symlink() for p in (self.directory, *self.directory.parents)):
            raise AuthorizationError("AUTH_STORE_SYMLINK")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.stat()
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise AuthorizationError("AUTH_STORE_OWNER")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise AuthorizationError("AUTH_STORE_PERMISSIONS_REQUIRE_0700")

    def read(self, name):
        if name not in {"host.json", "registration.json", "connection.json"}:
            raise AuthorizationError("AUTH_STORE_NAME")
        path = self.directory / name
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) & 0o077
                or (hasattr(os, "getuid") and info.st_uid != os.getuid())
            ):
                raise AuthorizationError("AUTH_FILE_PERMISSIONS_REQUIRE_0600")
            payload = handle.read(MAX_AUTH_RESPONSE_BYTES + 1)
        if len(payload) > MAX_AUTH_RESPONSE_BYTES:
            raise AuthorizationError("AUTH_FILE_TOO_LARGE")
        return json.loads(payload)

    def write(self, name, value):
        if name not in {"host.json", "registration.json", "connection.json"}:
            raise AuthorizationError("AUTH_STORE_NAME")
        target = self.directory / name
        if target.is_symlink():
            raise AuthorizationError("AUTH_STORE_SYMLINK")
        temporary = self.directory / (".write-" + secrets.token_hex(16))
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(value, handle, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def host_id(self):
        record = self.read("host.json")
        if record is None:
            record = {"ext_agent_host_id": "urn:uuid:" + str(uuid.uuid4())}
            self.write("host.json", record)
        value = record["ext_agent_host_id"]
        if not isinstance(value, str) or not value.startswith("urn:uuid:"):
            raise AuthorizationError("AUTH_HOST_INVALID")
        uuid.UUID(value.removeprefix("urn:uuid:"))
        return value


@dataclass(frozen=True)
class AuthAttempt:
    state: str
    nonce: str
    verifier: str
    browser_session: str
    redirect_uri: str
    client_id: str
    expires_at: float


def new_attempt(redirect_uri, client_id="dynamic_agent_client"):
    return AuthAttempt(
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(64),
        secrets.token_urlsafe(32),
        redirect_uri,
        client_id,
        time.monotonic() + 600,
    )


def authorization_url(attempt, host_id):
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = {
        "client_id": attempt.client_id,
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": attempt.redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": attempt.state,
        "nonce": attempt.nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if attempt.client_id == "dynamic_agent_client":
        params["agent_name_hint"] = "RCA Workbench"
    return AUTHORIZE_URL + "?" + urlencode(params)


def callback_values(attempt, params, browser_session, *, now=None):
    now = time.monotonic() if now is None else now
    if (
        now >= attempt.expires_at
        or not same_secret(browser_session, attempt.browser_session)
        or len(params.get("state", [])) != 1
        or not same_secret(params["state"][0], attempt.state)
    ):
        raise AuthorizationError("AUTH_STATE_INVALID_OR_EXPIRED")
    if "error" in params:
        raise AuthorizationError("AUTH_CONSENT_NOT_GRANTED")
    if len(params.get("code", [])) != 1 or not params["code"][0]:
        raise AuthorizationError("AUTH_CODE_MISSING")
    supplied = params.get("client_id", [])
    if len(supplied) > 1:
        raise AuthorizationError("AUTH_CLIENT_INVALID")
    client_id = supplied[0] if supplied else attempt.client_id
    if client_id == "dynamic_agent_client" or not client_id or len(client_id) > 200:
        raise AuthorizationError("AUTH_REGISTRATION_INCOMPLETE")
    if attempt.client_id != "dynamic_agent_client" and client_id != attempt.client_id:
        raise AuthorizationError("AUTH_CLIENT_CHANGED")
    return params["code"][0], client_id


def verify_identity(id_token, client_id, nonce, *, jwks=None):
    # Dependency is optional: the base ranking installation never imports jwt.
    try:
        import jwt

        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise AuthorizationError("AUTH_ID_TOKEN_ALGORITHM")
        keys = (jwks if jwks is not None else auth_json(JWKS_URL)).get("keys", [])
        if not isinstance(keys, list) or len(keys) > 32:
            raise AuthorizationError("AUTH_JWKS_INVALID")
        matching = [
            key
            for key in keys
            if key.get("kid") == header["kid"] and key.get("kty") == "RSA"
        ]
        if len(matching) != 1:
            raise AuthorizationError("AUTH_SIGNING_KEY_UNKNOWN")
        key = jwt.PyJWK.from_dict(matching[0], algorithm="RS256")
        identity = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUER,
            leeway=5,
            options={"require": ["sub", "exp", "iat", "nonce"]},
        )
        if not isinstance(identity["sub"], str) or not identity["sub"]:
            raise AuthorizationError("AUTH_SUBJECT_INVALID")
        if not same_secret(identity["nonce"], nonce):
            raise AuthorizationError("AUTH_NONCE_INVALID")
        return identity
    except ImportError:
        raise AuthorizationError("INSTALL_OPTIONAL_ASSISTANT_REQUIREMENTS") from None
    except AuthorizationError:
        raise
    except Exception:
        raise AuthorizationError("AUTH_ID_TOKEN_INVALID") from None


def exchange(attempt, code, client_id, host_id, store):
    # Preserve issued registration on invalid_grant; never substitute a CLI ID.
    store.write("registration.json", {"client_id": client_id})
    tokens = auth_json(
        TOKEN_URL,
        form={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": attempt.verifier,
            "redirect_uri": attempt.redirect_uri,
            "resource": RESOURCE,
        },
    )
    if not isinstance(tokens.get("id_token"), str):
        raise AuthorizationError("AUTH_ID_TOKEN_MISSING")
    identity = verify_identity(tokens["id_token"], client_id, attempt.nonce)
    previous = store.read("connection.json")
    if previous and (
        previous["client_id"] != client_id or previous["subject"] != identity["sub"]
    ):
        raise AuthorizationError("AUTH_ACCOUNT_CHANGED_USE_SEPARATE_STORE")
    scope = tokens.get("scope", "")
    if not isinstance(scope, str):
        raise AuthorizationError("AUTH_SCOPE_INVALID")
    scopes = scope.split()
    if PLAN_SCOPE not in scopes or "resource.invoke" not in scopes:
        raise AuthorizationError("AUTH_PLAN_USAGE_NOT_GRANTED")
    if (
        not isinstance(tokens.get("access_token"), str)
        or not tokens["access_token"]
        or str(tokens.get("token_type", "")).lower() != "bearer"
    ):
        raise AuthorizationError("AUTH_ACCESS_TOKEN_MISSING")
    expires = tokens.get("expires_in")
    if (
        isinstance(expires, bool)
        or not isinstance(expires, (float, int))
        or not 0 < expires <= 86400
    ):
        raise AuthorizationError("AUTH_EXPIRY_INVALID")
    if "at_hash" in identity:
        expected = (
            base64.urlsafe_b64encode(
                hashlib.sha256(tokens["access_token"].encode()).digest()[:16]
            )
            .rstrip(b"=")
            .decode()
        )
        if not same_secret(identity["at_hash"], expected):
            raise AuthorizationError("AUTH_TOKEN_BINDING_INVALID")
    record = {
        "issuer": ISSUER,
        "subject": identity["sub"],
        "client_id": client_id,
        "ext_agent_host_id": host_id,
        "id_token": tokens["id_token"],
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "token_type": "Bearer",
        "scopes": scopes,
        "saved_at_unix": time.time(),
        "expires_at_unix": time.time() + expires,
    }
    store.write("connection.json", record)


def make_auth_handler(store, state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            # The callback URL contains a one-time authorization code.
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def send_page(self, status, message, *, form=False):
            form_html = (
                f'<form method="post" action="/connect"><input type="hidden" name="csrf" '
                f'value="{html.escape(state["csrf"])}"><button>Continue with ChatGPT</button></form>'
                if form
                else ""
            )
            page = (
                '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                "<title>RCA Workbench — подключение</title><style>body{font:16px system-ui;max-width:680px;margin:64px auto;padding:24px;line-height:1.6;color:#26333b}button{font:inherit;padding:12px 18px;background:white;border:1px solid #65747e;border-radius:4px;cursor:pointer}</style>"
                f"<h1>Подключение помощника</h1><p>{html.escape(message)}</p>{form_html}"
                "<p>Этот шаг не отправляет телеметрию, не запускает анализ и не включает покупки. "
                "Разрешение и лимиты проверяются отдельно. Учётные данные остаются на этой машине.</p></html>"
            ).encode()
            self.send_response(status)
            for key, value in {
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(page)),
                # no-referrer on the initial form can make real browsers send
                # Origin: null on POST. Keep same-origin only on that page;
                # callback/error pages never disclose their query in referrers.
                "Cache-Control": "no-store",
                "Referrer-Policy": "same-origin" if form else "no-referrer",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://auth.openai.com; frame-ancestors 'none'; base-uri 'none'",
                "X-Content-Type-Options": "nosniff",
            }.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(page)

        def valid_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self.valid_host():
                return self.send_page(403, "Неверный адрес подключения.")
            path = urlsplit(self.path)
            if path.path == "/":
                return self.send_page(
                    200,
                    "Подключите свой аккаунт к RCA Workbench через официальный вход OpenAI. При запросе доступа проверьте аккаунт, разрешения и лимит использования подписки.",
                    form=True,
                )
            if path.path != "/auth/callback":
                return self.send_page(404, "Страница не найдена.")
            with state["lock"]:
                attempt = state.get("attempt")
                if not attempt:
                    return self.send_page(
                        400, "Попытка входа отсутствует или уже завершена."
                    )
                try:
                    cookies = SimpleCookie(self.headers.get("Cookie", ""))
                    browser_session = (
                        cookies["rca_auth"].value if "rca_auth" in cookies else ""
                    )
                    code, client_id = callback_values(
                        attempt,
                        parse_qs(path.query, keep_blank_values=True),
                        browser_session,
                    )
                except (AuthorizationError, ValueError) as error:
                    if (
                        isinstance(error, AuthorizationError)
                        and str(error) != "AUTH_STATE_INVALID_OR_EXPIRED"
                    ):
                        state["attempt"] = None
                    return self.send_page(
                        400,
                        "Вход не подтверждён. Откройте начальную страницу и повторите попытку.",
                    )
                # Consume once, before network I/O. Duplicate callbacks cannot exchange twice.
                state["attempt"] = None
            try:
                exchange(attempt, code, client_id, state["host_id"], store)
            except (AuthorizationError, OSError, ValueError) as error:
                safe = (
                    str(error)
                    if isinstance(error, AuthorizationError)
                    else "AUTH_LOCAL_STORE_FAILED"
                )
                state["status"] = safe
                return self.send_page(
                    400,
                    f"Подключение не завершено: {safe}. Можно повторить вход; покупки не выполнялись.",
                )
            state["status"] = "CONNECTED_PLAN_USAGE_GRANTED"
            return self.send_page(
                200,
                "Аккаунт подключён, разрешение использования подписки получено. Доступ к модели и ограниченный пробный запрос проверяются следующим отдельным шагом.",
            )

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if (
                not self.valid_host()
                or self.path != "/connect"
                or self.headers.get("Origin") != origin
                or self.headers.get_content_type()
                != "application/x-www-form-urlencoded"
            ):
                return self.send_page(
                    403, "Подключение разрешено только с локальной страницы."
                )
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096 or self.headers.get("Transfer-Encoding"):
                    raise ValueError()
                form = parse_qs(
                    self.rfile.read(length).decode(), keep_blank_values=True
                )
                if len(form.get("csrf", [])) != 1 or not same_secret(
                    form["csrf"][0], state["csrf"]
                ):
                    raise ValueError()
            except (ValueError, UnicodeError, OSError):
                return self.send_page(400, "Не удалось подтвердить запрос подключения.")
            registration = store.read("registration.json") or {}
            attempt = new_attempt(
                origin + "/auth/callback",
                registration.get("client_id", "dynamic_agent_client"),
            )
            with state["lock"]:
                state["attempt"] = attempt
            self.send_response(302)
            self.send_header("Location", authorization_url(attempt, state["host_id"]))
            self.send_header(
                "Set-Cookie",
                f"rca_auth={attempt.browser_session}; HttpOnly; SameSite=Lax; Path=/; Max-Age=600",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="Owner-only application credential directory, excluded from Git",
    )
    parser.add_argument("--port", type=int, default=18222)
    args = parser.parse_args()
    store = PrivateStore(args.state_dir)
    state = {
        "csrf": secrets.token_urlsafe(32),
        "host_id": store.host_id(),
        "lock": threading.Lock(),
        "attempt": None,
        "status": "NOT_CONNECTED",
    }
    http = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_auth_handler(store, state)
    )
    print(
        f"Официальное подключение аккаунта: http://127.0.0.1:{http.server_port}/",
        flush=True,
    )
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http.server_close()


if __name__ == "__main__":
    main()

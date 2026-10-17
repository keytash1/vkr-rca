"""No real credentials or external calls. Optional JWT tests use ephemeral keys."""
import base64
import hashlib
from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener

from assistant_auth import (AuthAttempt, AuthorizationError, ISSUER, PLAN_SCOPE,
    NoRedirect, PrivateStore, authorization_url, callback_values, exchange,
    make_auth_handler, new_attempt, verify_identity)


class AuthBoundaryTests(unittest.TestCase):
    def test_pkce_and_dynamic_registration_are_app_owned(self):
        attempt = new_attempt("http://127.0.0.1:18222/auth/callback")
        params = parse_qs(urlsplit(authorization_url(attempt, "urn:uuid:example")).query)
        self.assertEqual(params["client_id"], ["dynamic_agent_client"])
        self.assertEqual(params["agent_name_hint"], ["RCA Workbench"])
        expected = base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(params["code_challenge"], [expected])
        self.assertNotIn(attempt.verifier, str(params))
        self.assertIn(PLAN_SCOPE, params["scope"][0])
        returning = new_attempt(attempt.redirect_uri, "oaiapp_test")
        self.assertNotIn("agent_name_hint", parse_qs(urlsplit(authorization_url(returning, "host")).query))

    def test_callback_state_cookie_expiry_client_and_scope_not_trusted(self):
        attempt = new_attempt("http://127.0.0.1:18222/auth/callback")
        good = {"state": [attempt.state], "code": ["test-only-code"], "client_id": ["oaiapp_test"]}
        self.assertEqual(callback_values(attempt, good, attempt.browser_session), ("test-only-code", "oaiapp_test"))
        cases = [(good | {"state": ["wrong"]}, attempt.browser_session),
                 (good | {"state": ["подмена"]}, attempt.browser_session),
                 (good | {"state": [attempt.state, attempt.state]}, attempt.browser_session),
                 (good, "wrong-cookie"), (good | {"error": ["access_denied"]}, attempt.browser_session),
                 (good | {"code": []}, attempt.browser_session),
                 (good | {"client_id": ["dynamic_agent_client"]}, attempt.browser_session)]
        for params, cookie in cases:
            with self.subTest(params=params), self.assertRaises(AuthorizationError):
                callback_values(attempt, params, cookie)
        with self.assertRaises(AuthorizationError):
            callback_values(attempt, good, attempt.browser_session, now=attempt.expires_at)
        returning = new_attempt(attempt.redirect_uri, "oaiapp_original")
        with self.assertRaises(AuthorizationError):
            callback_values(returning, good | {"state": [returning.state]}, returning.browser_session)

    def test_private_storage_permissions_atomic_replace_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PrivateStore(Path(directory).resolve())
            host = store.host_id()
            self.assertEqual(store.host_id(), host)
            store.write("connection.json", {"access_token": "test-only-secret"})
            path = Path(directory) / "connection.json"
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            store.write("connection.json", {"access_token": "replacement-test-secret"})
            self.assertEqual(store.read("connection.json")["access_token"], "replacement-test-secret")
            path.chmod(0o644)
            with self.assertRaises(AuthorizationError):
                store.read("connection.json")
            target = Path(directory) / "link"
            target.symlink_to(path)
            with self.assertRaises(AuthorizationError):
                PrivateStore(target)
            with self.assertRaises(AuthorizationError):
                store.write("../outside", {})

    def test_ungranted_scope_does_not_save_access_token(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PrivateStore(Path(directory).resolve())
            attempt = new_attempt("http://127.0.0.1:18222/auth/callback")
            tokens = {"id_token": "test", "access_token": "SECRET", "token_type": "Bearer",
                      "scope": "openid profile", "expires_in": 3600}
            with patch("assistant_auth.auth_json", return_value=tokens), patch("assistant_auth.verify_identity", return_value={"sub": "test-subject"}):
                with self.assertRaisesRegex(AuthorizationError, "AUTH_PLAN_USAGE_NOT_GRANTED"):
                    exchange(attempt, "test-code", "oaiapp_test", store.host_id(), store)
            self.assertIsNone(store.read("connection.json"))
            self.assertEqual(store.read("registration.json")["client_id"], "oaiapp_test")


@unittest.skipUnless(importlib.util.find_spec("jwt") and importlib.util.find_spec("cryptography"),
                     "optional JWT cryptography tests run in .venv-assistant")
class JwtValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.jwt = jwt
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key())) | {"kid": "unit-test"}

    def token(self, **overrides):
        claims = {"iss": ISSUER, "sub": "unit-subject", "aud": "oaiapp_test", "iat": int(time.time()),
                  "exp": int(time.time()) + 300, "nonce": "unit-nonce"} | overrides
        return self.jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "unit-test"})

    def test_valid_signature_issuer_audience_time_nonce(self):
        self.assertEqual(verify_identity(self.token(), "oaiapp_test", "unit-nonce", jwks={"keys": [self.jwk]})["sub"], "unit-subject")
        for overrides in ({"iss": "https://evil.invalid"}, {"aud": "other-app"}, {"exp": 1}, {"nonce": "other-nonce"}, {"sub": ""}):
            with self.subTest(overrides=overrides), self.assertRaises(AuthorizationError):
                verify_identity(self.token(**overrides), "oaiapp_test", "unit-nonce", jwks={"keys": [self.jwk]})
        with self.assertRaises(AuthorizationError):
            verify_identity(self.token(), "oaiapp_test", "unit-nonce", jwks={"keys": []})
        unsigned = self.jwt.encode({"sub": "test"}, "", algorithm="none")
        with self.assertRaises(AuthorizationError):
            verify_identity(unsigned, "oaiapp_test", "unit-nonce", jwks={"keys": [self.jwk]})


class AuthHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PrivateStore(Path(self.temp.name).resolve())
        self.state = {"csrf": secrets.token_urlsafe(32), "host_id": self.store.host_id(),
                      "lock": threading.Lock(), "attempt": None}
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), make_auth_handler(self.store, self.state))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True); self.thread.start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(timeout=5); self.temp.cleanup()

    def request(self, path="/", data=None, headers=None):
        try:
            response = build_opener(NoRedirect()).open(Request(self.base + path, data=data, headers=headers or {}), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, dict(response.headers), response.read().decode()

    def test_local_form_csrf_origin_host_and_callback_replay(self):
        status, headers, page = self.request()
        self.assertEqual(status, 200)
        self.assertIn("Continue with ChatGPT", page)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertEqual(headers["Referrer-Policy"], "same-origin")
        self.assertIn("form-action 'self' https://auth.openai.com", headers["Content-Security-Policy"])
        body = urlencode({"csrf": self.state["csrf"]}).encode()
        self.assertEqual(self.request("/connect", body)[0], 403)
        self.assertEqual(self.request("/connect", body,
            {"Origin": "null", "Content-Type": "application/x-www-form-urlencoded"})[0], 403)
        self.assertEqual(self.request("/connect", urlencode({"csrf": "подмена"}).encode(),
            {"Origin": self.base, "Content-Type": "application/x-www-form-urlencoded"})[0], 400)
        self.assertEqual(self.request(headers={"Host": "evil.invalid"})[0], 403)
        status, headers, _ = self.request("/connect", body, {"Origin": self.base, "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 302)
        self.assertTrue(headers["Location"].startswith("https://auth.openai.com/api/accounts/authorize?"))
        attempt = self.state["attempt"]
        callback = "/auth/callback?" + urlencode({"state": attempt.state, "code": "unit-code", "client_id": "oaiapp_unit"})
        cookie = {"Cookie": "rca_auth=" + attempt.browser_session}
        with patch("assistant_auth.exchange") as mocked:
            self.assertEqual(self.request(callback)[0], 400)
            mocked.assert_not_called()
            self.assertEqual(self.request(callback, headers=cookie)[0], 200)
            mocked.assert_called_once()
            self.assertEqual(self.request(callback, headers=cookie)[0], 400)
            mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()

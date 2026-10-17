"""Loopback-only workspace endpoints with same-origin sessions and CSRF.

Not multi-user authentication: one trusted local installation, administrative
configuration by CLI. Do not enable behind an unauthenticated public proxy.
"""

from http.cookies import SimpleCookie
from http import HTTPStatus
import hmac
import json
import secrets
import threading
import time
from urllib.parse import urlsplit, parse_qs

from api_errors import ApiError
from investigations import InvestigationError
from workspace_store import StoreError

COOKIE = "rca_workspace_session"
MAX_BODY = 32 * 1024


def validate_local_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or parsed.port is None or not 1 <= parsed.port <= 65535):
        raise ValueError("workspace origin must be an explicit HTTP IPv4 loopback origin and port")
    if value != f"http://{parsed.hostname}:{parsed.port}":
        raise ValueError("workspace origin must be canonical")
    return value


class WorkspaceHTTP:
    def __init__(self, store, service, *, evict_evidence=None, expected_origin=None):
        self.store, self.service = store, service
        self.evict_evidence = evict_evidence
        self.expected_origin = validate_local_origin(expected_origin) if expected_origin is not None else None
        self._sessions, self._lock = {}, threading.Lock()

    def check_local(self, handler):
        port = handler.server.server_port
        host = handler.headers.get("Host", "")
        allowed_hosts = {urlsplit(self.expected_origin).netloc} if self.expected_origin else {f"127.0.0.1:{port}", f"localhost:{port}"}
        if host not in allowed_hosts:
            raise ApiError(
                "HOST_NOT_ALLOWED",
                "Недопустимый адрес приложения.",
                HTTPStatus.FORBIDDEN,
            )
        origin = handler.headers.get("Origin")
        if (
            origin is not None
            and origin != "http://" + host
            or handler.headers.get("Sec-Fetch-Site", "")
            not in {"", "same-origin", "none"}
        ):
            raise ApiError(
                "ORIGIN_NOT_ALLOWED",
                "Откройте приложение с локального адреса.",
                HTTPStatus.FORBIDDEN,
            )

    def _session(self, handler, *, create=False):
        self.check_local(handler)
        cookie = SimpleCookie()
        try:
            cookie.load(handler.headers.get("Cookie", ""))
        except Exception:
            raise ApiError(
                "SESSION_REQUIRED",
                "Откройте главную страницу приложения.",
                HTTPStatus.UNAUTHORIZED,
            ) from None
        token = cookie[COOKIE].value if COOKIE in cookie else None
        with self._lock:
            now = time.monotonic()
            self._sessions = {
                k: v for k, v in self._sessions.items() if v["expires"] > now
            }
            current = self._sessions.get(token)
            if current:
                return current, None
            if not create:
                raise ApiError(
                    "SESSION_REQUIRED",
                    "Откройте главную страницу приложения.",
                    HTTPStatus.UNAUTHORIZED,
                )
            if len(self._sessions) >= 32:
                del self._sessions[
                    min(self._sessions, key=lambda k: self._sessions[k]["expires"])
                ]
            token = secrets.token_urlsafe(32)
            current = {"csrf": secrets.token_urlsafe(32), "expires": now + 12 * 3600}
            self._sessions[token] = current
            return (
                current,
                f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/api/v2/; Max-Age=43200",
            )

    def _body(self, handler):
        if (
            handler.headers.get_content_type() != "application/json"
            or handler.headers.get("Transfer-Encoding")
        ):
            raise ApiError("INVALID_REQUEST", "Передайте JSON с Content-Length.")
        try:
            size = int(handler.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError("INVALID_REQUEST", "Некорректный размер запроса.") from None
        if not 1 <= size <= MAX_BODY:
            raise ApiError(
                "PAYLOAD_TOO_LARGE",
                "Размер запроса превышает ограничение.",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        data = handler.rfile.read(size)
        if len(data) != size:
            raise ApiError("INVALID_REQUEST", "Неполное тело запроса.")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result

        try:
            value = json.loads(
                data,
                object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, RecursionError, UnicodeError):
            raise ApiError(
                "INVALID_REQUEST", "Проверьте JSON и уникальность полей."
            ) from None

    def get(self, handler, path):
        if path == "/api/v2/workspace":
            session, cookie = self._session(handler, create=True)
            handler._json(
                HTTPStatus.OK,
                {
                    "schema_version": "workspace-v1",
                    "csrf_token": session["csrf"],
                    "mode": "TRUSTED_LOOPBACK_SINGLE_INSTALLATION",
                    "retention_seconds": self.store.retention,
                    "assistant_configured": self.service.llm_configured,
                    "assistant_profiles": sorted(self.service.allowed_profiles),
                    "assistant_model": self.service.model
                    if self.service.llm_configured
                    else None,
                    "queue_capacity": 2,
                    "assistant_budget": self.store.assistant_budget_status(),
                    "recovered_jobs": self.service.recovered_jobs,
                    "worker": self.service.health(),
                },
                headers={"Set-Cookie": cookie} if cookie else {},
            )
            return True
        if path == "/api/v2/investigations":
            self._session(handler)
            query = parse_qs(urlsplit(handler.path).query, keep_blank_values=True, max_num_fields=8)
            allowed = {"project", "service", "category", "after", "before", "action_status", "limit"}
            if set(query) - allowed or any(len(v) != 1 or not v[0] for v in query.values()):
                raise ApiError("INVALID_REQUEST", "Проверьте фильтры истории.")
            filters = {k: v[0] for k, v in query.items()}
            try:
                for key in ("after", "before"):
                    if key in filters:
                        filters[key] = float(filters[key])
                if "limit" in filters:
                    filters["limit"] = int(filters["limit"])
            except ValueError:
                raise ApiError("INVALID_REQUEST", "Проверьте период и размер истории.") from None
            handler._json(
                HTTPStatus.OK, {"investigations": self.store.list_investigations(**filters),
                                "period_basis": "INVESTIGATION_CREATED_AT", "limit": filters.get("limit", 30)}
            )
            return True
        parts = path.split("/")
        if len(parts) == 5 and parts[1:4] == ["api", "v2", "investigations"]:
            self._session(handler)
            value = self.store.get_investigation(parts[4])
            if value is None:
                raise ApiError(
                    "INVESTIGATION_NOT_FOUND",
                    "Расследование недоступно или срок хранения истёк.",
                    HTTPStatus.NOT_FOUND,
                )
            handler._json(HTTPStatus.OK, value)
            return True
        if (
            len(parts) == 6
            and parts[1:4] == ["api", "v2", "analyses"]
            and parts[5] == "snapshot"
        ):
            self._session(handler)
            snapshot = self.store.get_snapshot(parts[4])
            if snapshot is None:
                raise ApiError(
                    "EVIDENCE_NOT_FOUND",
                    "Снимок недоступен или срок хранения истёк.",
                    HTTPStatus.NOT_FOUND,
                )
            handler._json(HTTPStatus.OK, snapshot)
            return True
        return False

    def post(self, handler, path):
        session, _ = self._session(handler)
        # Origin is mandatory for browser state changes; CLI clients obtain the
        # same session cookie and CSRF token and send this exact local Origin.
        expected = "http://" + handler.headers.get("Host", "")
        supplied = handler.headers.get("X-RCA-CSRF", "")
        if (
            handler.headers.get("Origin") != expected
            or not isinstance(supplied, str)
            or not hmac.compare_digest(supplied.encode(), session["csrf"].encode())
        ):
            raise ApiError(
                "CSRF_REQUIRED",
                "Обновите страницу и повторите действие.",
                HTTPStatus.FORBIDDEN,
            )
        payload = self._body(handler)
        if path == "/api/v2/investigations":
            if set(payload) != {"analysis_id", "mode", "question", "idempotency_key"}:
                raise ApiError(
                    "INVALID_REQUEST", "Укажите анализ, режим, вопрос и ключ повтора."
                )
            value, fresh = self.service.submit(
                payload["analysis_id"],
                mode=payload["mode"],
                question=payload["question"],
                idempotency_key=payload["idempotency_key"],
            )
            handler._json(HTTPStatus.ACCEPTED if fresh else HTTPStatus.OK, value)
            return
        parts = path.split("/")
        if len(parts) == 6 and parts[1:4] == ["api", "v2", "investigations"]:
            identifier, operation = parts[4:]
            if operation == "cancel" and not payload:
                handler._json(HTTPStatus.OK, self.service.cancel(identifier))
                return
            if operation == "record" and set(payload) == {
                "expected_revision",
                "record",
            }:
                handler._json(
                    HTTPStatus.OK,
                    self.store.save_record(
                        identifier,
                        payload["record"],
                        expected_revision=payload["expected_revision"],
                    ),
                )
                return
            if operation == "review" and set(payload) == {"expected_revision"}:
                handler._json(HTTPStatus.OK,self.store.review_record(identifier,expected_revision=payload["expected_revision"]))
                return
            if operation == "messages" and set(payload) == {
                "mode",
                "question",
                "idempotency_key",
            }:
                value, fresh = self.service.follow_up(
                    identifier,
                    mode=payload["mode"],
                    question=payload["question"],
                    idempotency_key=payload["idempotency_key"],
                )
                handler._json(HTTPStatus.ACCEPTED if fresh else HTTPStatus.OK, value)
                return
        if (
            len(parts) == 6
            and parts[1:4] == ["api", "v2", "analyses"]
            and parts[5] == "delete"
            and not payload
        ):
            deleted = self.service.delete_snapshot(parts[4])
            if self.evict_evidence:
                self.evict_evidence(parts[4])
            handler._json(HTTPStatus.OK, {"deleted": deleted})
            return
        raise ApiError("NOT_FOUND", "Операция не найдена.", HTTPStatus.NOT_FOUND)


def public_workspace_error(error):
    code = str(error)
    if isinstance(error, ApiError):
        return error
    if code in {"STORE_IDEMPOTENCY_CONFLICT", "STORE_REVISION_CONFLICT"}:
        return ApiError(
            code,
            "Состояние изменилось. Обновите расследование перед сохранением.",
            HTTPStatus.CONFLICT,
        )
    if code == "STORE_ASSISTANT_DAILY_LIMIT":
        return ApiError(code,
            "Лимит запусков помощника за последние 24 часа исчерпан. Рейтинг, наблюдения и карточка работают без LLM; удаление карточки не сбрасывает лимит.",
            HTTPStatus.TOO_MANY_REQUESTS)
    if code in {
        "WORKSPACE_BUSY",
        "STORE_CAPACITY",
        "STORE_TURN_IN_PROGRESS",
        "STORE_TURN_LIMIT",
    }:
        return ApiError(
            code,
            "Очередь или хранилище заполнены. Дождитесь завершения либо удалите сохранённый снимок.",
            HTTPStatus.TOO_MANY_REQUESTS,
        )
    if code == "ASSISTANT_PROFILE_NOT_APPROVED":
        return ApiError(
            code,
            "Внешний помощник не разрешён для этой системы. Наблюдения и карточка расследования доступны без LLM.",
            HTTPStatus.FORBIDDEN,
        )
    record_messages = {
        "RECORD_REVIEW_OWNER_CONCLUSION_REQUIRED": "Для проверки карточки укажите владельца расследования и вывод. Это не подтверждает все гипотезы автоматически.",
        "RECORD_CAUSE_VERIFICATION_REQUIRED": "Укажите, как гипотеза проверена и почему подтверждена или отклонена.",
        "RECORD_ACTION_OWNER_REQUIRED": "У запланированной или выполняемой меры должен быть указан ответственный.",
        "RECORD_ACTION_DUE_REQUIRED": "Укажите срок меры, прежде чем переводить её из предложенной в работу.",
        "RECORD_ACTION_VERIFICATION_REQUIRED": "Запишите результат проверки эффекта меры. Одной смены статуса недостаточно.",
        "RECORD_EVIDENCE_OUTSIDE_SCOPE": "Связанные наблюдения должны принадлежать этому снимку.",
        "STORE_TEXT_INVALID": "Заполните формулировки добавленных событий, гипотез и мер либо удалите пустые записи.",
    }
    if code in record_messages:
        return ApiError(code, record_messages[code])
    if code in {
        "INVESTIGATION_NOT_FOUND",
        "INVESTIGATION_ANALYSIS_NOT_FOUND",
        "STORE_INVESTIGATION_NOT_FOUND",
    }:
        return ApiError(
            code, "Расследование или снимок недоступны.", HTTPStatus.NOT_FOUND
        )
    if isinstance(
        error, (StoreError, InvestigationError, ValueError, KeyError, TypeError)
    ):
        return ApiError(
            "INVALID_REQUEST",
            "Проверьте поля, ссылки на наблюдения, статус мер и версию карточки.",
        )
    return ApiError(
        "WORKSPACE_UNAVAILABLE",
        "Не удалось сохранить состояние. Исходный рейтинг не изменён.",
        HTTPStatus.SERVICE_UNAVAILABLE,
    )

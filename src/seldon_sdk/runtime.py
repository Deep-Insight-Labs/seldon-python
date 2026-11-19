"""Typed serving with bounded retries and explicit reference fallback."""

import asyncio
import inspect
import logging
import math
import os
import platform
import threading
import time
import warnings
import weakref
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import ValidationError

from . import __version__
from .contract import render
from .errors import (
    SeldonAuthError,
    SeldonConfigError,
    SeldonContractError,
    SeldonError,
    SeldonOutputValidationError,
    SeldonReferenceError,
    SeldonSpendError,
)
from .files import canonical, safe_code
from .lockfile import locate, read

_settings = {}
_async_clients = weakref.WeakKeyDictionary()
_sync = threading.local()
_guard = threading.Lock()
_warned = set()


def configure(**settings):
    allowed = {
        "base_url",
        "api_key",
        "reference_base_url",
        "reference_api_key",
        "timeout",
        "reference_timeout",
        "fallback",
        "on_drift",
        "on_invalid_output",
        "on_call",
        "breaker",
        "http_client",
        "async_http_client",
    }
    if set(settings) - allowed:
        raise SeldonConfigError("unknown_configuration")
    _settings.update(settings)


def _url(value):
    parsed = urlsplit(value)
    if (
        (
            parsed.scheme != "https"
            and not (parsed.scheme == "http" and parsed.hostname == "localhost")
        )
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise SeldonConfigError("https_endpoint_required")
    value = value.rstrip("/")
    return value if value.endswith("/v1") else value + "/v1"


def warn_once(key, code):
    with _guard:
        if (key, code) in _warned:
            return
        _warned.add((key, code))
    warnings.warn(code, RuntimeWarning, stacklevel=3)


@dataclass
class CallInfo:
    path: str = "function"
    reason: str | None = None
    function_id: str | None = None
    revision_id: str | None = None
    execution_id: str | None = None
    server_fallback_used: bool = False
    contract_check: str = "unsupported"
    attempts: int = 0
    latency_ms: float = 0
    usage: dict | None = None
    reference_output_fenced: bool = False


class Breaker:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.events = deque(maxlen=20)
        self.until = 0
        self.probing = False
        self.lock = threading.Lock()

    def allow(self):
        with self.lock:
            if not self.until:
                return "normal"
            if self.clock() < self.until or self.probing:
                return False
            self.probing = True
            return "probe"

    def record(self, failed, *, probe=False):
        with self.lock:
            now = self.clock()
            if probe:
                self.probing = False
                self.until = now + 60 if failed else 0
                self.events.clear()
                return
            self.events.append((now, failed))
            if sum(failure for at, failure in self.events if now - at <= 300) >= 10:
                self.until = now + 60

    def release_probe(self):
        with self.lock:
            self.probing = False


def _client(async_mode, options):
    supplied = options.get("async_http_client" if async_mode else "http_client")
    if supplied is not None:
        return supplied
    if not async_mode:
        if not hasattr(_sync, "client"):
            _sync.client = httpx.Client(follow_redirects=False)
        return _sync.client
    loop = asyncio.get_running_loop()
    with _guard:
        if loop not in _async_clients:
            _async_clients[loop] = httpx.AsyncClient(follow_redirects=False)
        return _async_clients[loop]


async def aclose():
    with _guard:
        client = _async_clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.aclose()


def close():
    if hasattr(_sync, "client"):
        _sync.client.close()
        del _sync.client


def options_for(fn):
    values = {
        "base_url": os.environ.get("SELDON_BASE_URL", "https://api.seldon-ai.com"),
        "api_key": os.environ.get("SELDON_API_KEY"),
        "timeout": 58,
        "reference_timeout": 120,
        "fallback": "reference",
        "on_drift": "reference",
        "on_invalid_output": "raise",
        "breaker": True,
    }
    values.update(_settings)
    values.update(fn.options)
    for field, allowed in (
        ("fallback", {"reference", "never"}),
        ("on_drift", {"reference", "raise"}),
        ("on_invalid_output", {"reference", "raise"}),
    ):
        if values[field] not in allowed:
            raise SeldonConfigError("invalid_" + field)
    values["base_url"] = _url(values["base_url"])
    if not values.get("api_key"):
        raise SeldonConfigError("api_key_required")
    if values["timeout"] <= 55:
        warn_once(fn.key, "timeout_below_function_deadline")
    return values


def resolve_identity(fn):
    if fn.id:
        return fn.id, None
    path = locate(inspect.getsourcefile(fn.original))
    if not path.exists():
        return None, "not_registered"
    entry = read(path)["functions"].get(fn.key)
    if not entry:
        return None, "not_registered"
    if entry["contract_digest"] != fn.digest:
        return None, "lockfile_stale"
    return entry["function_id"], None


def _error(response):
    try:
        body = response.json()
        code = body.get("error", "service_error")
        if isinstance(code, dict):
            code = code.get("code")
        return safe_code(code)
    except (ValueError, AttributeError):
        return "service_error"


def _raise_response(response):
    code, status = _error(response), response.status_code
    kind = (
        SeldonAuthError
        if status in (401, 403)
        else SeldonSpendError
        if status == 402
        else SeldonContractError
        if status in (400, 422)
        else SeldonError
    )
    raise kind(code, status=status)


async def invoke(fn, inputs, *, async_mode):
    started = time.monotonic()
    info = CallInfo()
    options = options_for(fn)
    admitted = False
    client = _client(async_mode, options)

    async def request(url, body, key, timeout, headers=None):
        kwargs = {
            "json": body,
            "headers": {
                "Authorization": "Bearer " + key,
                "User-Agent": f"seldon-sdk/{__version__} python/{platform.python_version()}",
                **(headers or {}),
            },
            "timeout": timeout,
            "follow_redirects": False,
        }
        result = client.post(url + "/chat/completions", **kwargs)
        return await result if inspect.isawaitable(result) else result

    async def reference(reason, cause=None):
        info.path, info.reason = "reference", reason
        if options["fallback"] == "never":
            raise cause or SeldonReferenceError(reason)
        origin = _url(options.get("reference_base_url", options["base_url"]))
        different = urlsplit(origin).netloc != urlsplit(options["base_url"]).netloc
        key = options.get("reference_api_key") or (None if different else options["api_key"])
        if not key:
            raise SeldonConfigError("reference_api_key_required")
        body = {
            key: fn.contract[key]
            for key in ("model", "temperature", "max_tokens", "response_format")
        }
        body["messages"] = render(fn.contract, inputs)
        try:
            response = await request(origin, body, key, options["reference_timeout"])
            if response.status_code != 200:
                _raise_response(response)
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if content.strip().startswith("```json") and content.strip().endswith("```"):
                content = content.strip()[7:-3].strip()
                info.reference_output_fenced = True
            info.usage = data.get("usage")
            return fn.output.validate_json(content)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, ValidationError):
            raise SeldonReferenceError("reference_output_invalid") from cause

    try:
        identity, reason = resolve_identity(fn)
        info.function_id = identity
        if os.environ.get("SELDON_MODE") == "reference":
            return await reference("reference_mode"), info
        if reason:
            warn_once(fn.key, reason + ": run seldon sync")
            return await reference(reason), info
        if options["breaker"]:
            admitted = fn.breaker.allow()
            if not admitted:
                return await reference("circuit_open"), info
        headers = {"Idempotency-Key": str(uuid4()), "X-Seldon-Contract-Digest": fn.digest}
        body = {
            "model": "seldon/function/" + identity,
            "messages": [{"role": "user", "content": canonical(inputs)}],
        }
        for attempt in range(3):
            info.attempts = attempt + 1
            try:
                response = await request(
                    options["base_url"], body, options["api_key"], options["timeout"], headers
                )
            except (httpx.ConnectError, httpx.ReadTimeout):
                if attempt < 2:
                    await asyncio.sleep(0.1 * (2**attempt))
                    continue
                return await reference(
                    "transport_unavailable", SeldonError("transport_unavailable")
                ), info
            status, code = response.status_code, _error(response)
            if status == 200:
                fn.breaker.record(False, probe=admitted == "probe")
                try:
                    data = response.json()
                except ValueError:
                    raise SeldonOutputValidationError("invalid_function_output") from None
                meta = data.get("seldon", {})
                info.revision_id, info.execution_id = (
                    meta.get("revision_id"),
                    meta.get("execution_id"),
                )
                info.server_fallback_used = bool(meta.get("fallback_used"))
                info.contract_check = response.headers.get("X-Seldon-Contract-Check", "unsupported")
                info.usage = data.get("usage")
                try:
                    result = fn.output.validate_json(data["choices"][0]["message"]["content"])
                except (ValueError, ValidationError, KeyError, IndexError, TypeError):
                    if options["on_invalid_output"] == "reference":
                        return await reference("invalid_function_output"), info
                    raise SeldonOutputValidationError("invalid_function_output") from None
                return result, info
            if status in (401, 402, 403) or status == 429 and code == "api_key_rate_limit":
                _raise_response(response)
            if status == 400 or status == 422:
                _raise_response(response)
            if status == 409 and code == "contract_digest_mismatch":
                warn_once(fn.key, "contract_digest_mismatch: run seldon sync")
                if options["on_drift"] == "raise":
                    raise SeldonContractError(code)
                return await reference(code), info
            if status in (502, 504):
                fn.breaker.record(True, probe=admitted == "probe")
                return await reference(
                    "server_execution_failed" if status == 502 else "server_deadline_exceeded"
                ), info
            if (status == 429 and code == "execution_capacity") or (
                status == 409 and code == "execution_in_progress"
            ):
                if attempt == 2:
                    return await reference(code), info
                try:
                    pause = float(response.headers.get("Retry-After", "0.1"))
                    pause = min(5, max(0, pause)) if math.isfinite(pause) else 0.1
                except ValueError:
                    pause = 0.1
                await asyncio.sleep(pause)
                continue
            if (status == 404 and code in {"function_not_found", "revision_not_available"}) or (
                status == 409 and code in {"function_disabled", "execution_disabled"}
            ):
                return await reference(code), info
            _raise_response(response)
        raise SeldonError("execution_unavailable")
    finally:
        if admitted == "probe":
            fn.breaker.release_probe()
        info.latency_ms = (time.monotonic() - started) * 1000
        hook = options.get("on_call")
        if hook:
            try:
                hook(info)
            except Exception:
                logging.getLogger(__name__).warning("call_metadata_hook_failed")

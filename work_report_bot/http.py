from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


TOKEN_RE = re.compile(r"([?&](?:access_token|api_key)=)[^&\s]+")
BOT_RE = re.compile(r"/bot[^/\s]+")


class HttpError(RuntimeError):
    pass


def redact(value: str) -> str:
    value = TOKEN_RE.sub(r"\1<redacted>", value)
    return BOT_RE.sub("/bot<redacted>", value)


def safe_endpoint(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = BOT_RE.sub("/bot<redacted>", parsed.path)
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def get_json(url: str, params: dict[str, Any] | None = None, timeout: int = 30, retries: int = 2) -> dict[str, Any]:
    full_url = url
    if params:
        full_url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    request = urllib.request.Request(full_url, headers={"Accept": "application/json"}, method="GET")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise HttpError("Response was not a JSON object")
            return payload
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = HttpError(f"GET {safe_endpoint(full_url)} failed: {exc.code} {redact(body)[:240]}")
            if exc.code < 500 or attempt >= retries:
                raise last_error from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            last_error = HttpError(f"GET {safe_endpoint(full_url)} failed: {exc}")
            if attempt >= retries:
                raise last_error from exc
        time.sleep(0.8 * (attempt + 1))
    raise HttpError(str(last_error or "GET request failed"))


def post_json(url: str, params: dict[str, Any] | None = None, body: Any = None, timeout: int = 30, retries: int = 2) -> dict[str, Any]:
    full_url = url
    if params:
        full_url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    encoded = json.dumps(body).encode("utf-8") if body is not None else b""
    request = urllib.request.Request(
        full_url,
        data=encoded,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise HttpError("Response was not a JSON object")
            return payload
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            last_error = HttpError(f"POST {safe_endpoint(full_url)} failed: {exc.code} {redact(body_text)[:240]}")
            if exc.code < 500 or attempt >= retries:
                raise last_error from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            last_error = HttpError(f"POST {safe_endpoint(full_url)} failed: {exc}")
            if attempt >= retries:
                raise last_error from exc
        time.sleep(0.8 * (attempt + 1))
    raise HttpError(str(last_error or "POST request failed"))


def post_form(url: str, data: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpError(f"POST {safe_endpoint(url)} failed: {exc.code} {redact(body)[:240]}") from exc
    if not isinstance(payload, dict):
        raise HttpError("Response was not a JSON object")
    return payload

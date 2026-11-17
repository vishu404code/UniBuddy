"""Google ID-token verification.

Google proves who the person is and that the email is theirs. It never decides a
UniBuddy role, campus or department. Those come only from UniBuddy's own records.
"""

from collections.abc import Callable
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any

from google.auth import transport as google_transport
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
import requests

logger = logging.getLogger("unibuddy.auth.google")

GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})

Verifier = Callable[[str, str], dict[str, Any]]


class GoogleAuthError(Exception):
    """The token is missing, invalid, expired, for another app, or lacks a verified email."""


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    full_name: str | None


class _CachedResponse(google_transport.Response):
    """Caches in-memory response from certs endpoint to avoid frequent network calls."""

    def __init__(self, status: int, data: bytes, headers: dict[str, str] | None = None):
        self._status = status
        self._data = data
        self._headers = headers or {}

    @property
    def status(self) -> int:
        return self._status

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    @property
    def data(self) -> bytes:
        return self._data


class CachedGoogleAuthRequest(google_requests.Request):
    """Google auth transport with connection pooling and in-memory response caching for certs.

    Google's public certificates rarely change (rotated every few days). Caching
    them in-memory drops verification time from ~500-1500ms to <1ms.
    """

    def __init__(self, session: requests.Session | None = None, cache_ttl: float = 3600.0, timeout: float = 10.0):
        if session is None:
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=2)
            session.mount("https://", adapter)
        super().__init__(session=session)
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self._cache: dict[str, tuple[float, _CachedResponse]] = {}
        self._lock = threading.Lock()

    def invalidate_cache(self, url: str | None = None) -> None:
        with self._lock:
            if url:
                self._cache.pop(url, None)
            else:
                self._cache.clear()

    def __call__(self, url: str, method: str = "GET", body: bytes | None = None,
                 headers: dict[str, str] | None = None, timeout: float | None = None, **kwargs) -> google_transport.Response:
        if method == "GET":
            now = time.monotonic()
            with self._lock:
                cached = self._cache.get(url)
                if cached and now < cached[0]:
                    return cached[1]

        timeout = timeout or self.timeout
        resp = super().__call__(url, method=method, body=body, headers=headers, timeout=timeout, **kwargs)

        if method == "GET" and resp.status == 200:
            ttl = self.cache_ttl
            cc = resp.headers.get("Cache-Control", "")
            if "max-age=" in cc:
                try:
                    parsed_ttl = float(cc.split("max-age=")[1].split(",")[0].strip())
                    ttl = min(max(parsed_ttl, 60.0), 86400.0)
                except Exception:
                    ttl = self.cache_ttl
            with self._lock:
                self._cache[url] = (time.monotonic() + ttl, _CachedResponse(resp.status, resp.data, dict(resp.headers)))

        return resp


_cached_request = CachedGoogleAuthRequest()


def warm_google_certs_cache() -> None:
    """Pre-warm Google public keys cache to make the first sign-in immediate."""
    try:
        _cached_request("https://www.googleapis.com/oauth2/v3/certs", "GET", timeout=5.0)
        logger.info("Google OAuth certs pre-warmed successfully")
    except Exception as exc:
        logger.debug("Could not pre-warm Google OAuth certs: %s", exc)


def _default_verifier(token: str, client_id: str) -> dict[str, Any]:
    # Checks the signature, the expiry, the issuer and that the token is for this client ID.
    # Clock skew of 15 seconds prevents false rejections from slight clock differences.
    try:
        return google_id_token.verify_oauth2_token(
            token.strip(),
            _cached_request,
            client_id.strip(),
            clock_skew_in_seconds=15,
        )
    except Exception as exc:
        # If verification failed, it might be due to a recent key rotation; bust cert cache and retry once
        logger.debug("First-pass Google verification failed (%s); refreshing certs cache", exc)
        _cached_request.invalidate_cache()
        return google_id_token.verify_oauth2_token(
            token.strip(),
            _cached_request,
            client_id.strip(),
            clock_skew_in_seconds=15,
        )


def identity_from_claims(claims: dict[str, Any]) -> GoogleIdentity:
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleAuthError("token issuer is not Google")
    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject:
        raise GoogleAuthError("token has no subject")
    if not isinstance(email, str) or not email.strip():
        raise GoogleAuthError("token has no email")
    if claims.get("email_verified") is not True:
        raise GoogleAuthError("Google email is not verified")
    name = claims.get("name")
    return GoogleIdentity(
        subject=subject,
        email=email.strip().lower(),
        full_name=name.strip() if isinstance(name, str) and name.strip() else None,
    )


def verify_google_id_token(token: str, client_id: str, *, verifier: Verifier | None = None) -> GoogleIdentity:
    if not token or not str(token).strip() or not client_id or not str(client_id).strip():
        raise GoogleAuthError("missing token or client ID")
    try:
        claims = (verifier or _default_verifier)(token, client_id)
    except GoogleAuthError:
        raise
    except Exception as exc:
        logger.warning("Google ID token verification failed: %s (%s)", type(exc).__name__, exc)
        # Bad signature, wrong audience, expired, or a network problem. Don't leak which.
        raise GoogleAuthError("invalid Google token") from exc
    return identity_from_claims(claims)

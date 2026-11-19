"""WorkOS public-client login; only refresh credentials persist in a secure keychain."""

import base64
import hashlib
import json
import os
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx

from .errors import SeldonAuthError, SeldonConfigError
from .files import atomic_json, read_json

WORKOS = "https://api.workos.com"
DEFAULT_BASE_URL = "https://api.seldon-ai.com"


def base_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        and not (parsed.scheme == "http" and parsed.hostname == "localhost")
    ) or (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise SeldonConfigError("https_origin_required")
    return value.rstrip("/")


class Keychain:
    def __init__(self):
        self.backend = None
        try:
            import keyring

            backend = keyring.get_keyring()
            candidates = getattr(backend, "backends", [backend])
            for candidate in candidates:
                if type(candidate).__module__ in {
                    "keyring.backends.macOS",
                    "keyring.backends.Windows",
                    "keyring.backends.SecretService",
                }:
                    self.backend = candidate
                    break
        except Exception:
            # No insecure persistence fallback; callers receive a one-command session.
            self.backend = None

    def get(self, key):
        if self.backend is None:
            return None
        try:
            return self.backend.get_password("seldon-sdk", key)
        except Exception:
            raise SeldonAuthError("secure_keychain_unavailable") from None

    def set(self, key, token):
        if self.backend is None:
            return False
        try:
            self.backend.set_password("seldon-sdk", key, token)
            return True
        except Exception:
            raise SeldonAuthError("secure_keychain_unavailable") from None

    def delete(self, key):
        if self.backend is None:
            return
        try:
            if self.backend.get_password("seldon-sdk", key) is not None:
                self.backend.delete_password("seldon-sdk", key)
        except Exception:
            raise SeldonAuthError("secure_keychain_unavailable") from None


class Login:
    def __init__(
        self,
        origin=DEFAULT_BASE_URL,
        *,
        profile="default",
        client_id=None,
        store=None,
        config_dir=None,
        http=None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.origin = base_url(origin)
        if not profile or len(profile) > 80:
            raise SeldonConfigError("invalid_profile")
        self.profile = profile
        self.client_id = client_id or os.environ.get("SELDON_WORKOS_CLIENT_ID")
        self.store = store if store is not None else Keychain()
        self.config_dir = Path(
            config_dir or os.environ.get("SELDON_CONFIG_HOME", Path.home() / ".config/seldon")
        )
        self.key = hashlib.sha256((profile + "\n" + self.origin).encode()).hexdigest()
        profiles_path = self.config_dir / "profiles.json"
        if not self.client_id and profiles_path.exists():
            profile_data = read_json(profiles_path).get(self.key, {})
            if (
                profile_data.get("base_url") == self.origin
                and profile_data.get("profile") == profile
            ):
                self.client_id = profile_data.get("client_id")
        self.http = http or httpx.Client(timeout=30, follow_redirects=False)
        self.sleep, self.clock = sleep, clock
        self._access = None
        self._claims = None

    def _post(self, fields):
        if not self.client_id:
            raise SeldonConfigError("workos_client_id_required")
        try:
            response = self.http.post(
                WORKOS + "/user_management/authenticate",
                data={
                    "client_id": self.client_id,
                    **fields,
                },
                timeout=30,
                follow_redirects=False,
            )
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise SeldonAuthError("authentication_unavailable") from None
        if response.status_code >= 500:
            raise SeldonAuthError("authentication_unavailable")
        return response.status_code, body

    def _accept(self, data):
        access, refresh = data.get("access_token"), data.get("refresh_token")
        if not isinstance(access, str) or not isinstance(refresh, str) or not access or not refresh:
            raise SeldonAuthError("invalid_authentication_response")
        # A successful WorkOS refresh can revoke the previous token immediately.
        # Preserve its replacement even when the downstream API is unavailable.
        persisted = self.store.set(self.key, refresh)
        # Verification stays on Seldon's real WorkOS boundary, including organization mapping.
        try:
            response = self.http.get(
                self.origin + "/v1/seldon/functions",
                params={"limit": 1},
                headers={"Authorization": "Bearer " + access},
                timeout=30,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise SeldonAuthError("session_verification_unavailable") from None
        if response.status_code != 200:
            raise SeldonAuthError("session_not_accepted")
        try:
            part = access.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            if not claims.get("sub") or not (claims.get("org_id") or claims.get("organization_id")):
                raise ValueError
        except (IndexError, ValueError, TypeError):
            raise SeldonAuthError("invalid_session_claims") from None
        self._access, self._claims = access, claims
        if persisted:
            path = self.config_dir / "profiles.json"
            profiles = read_json(path) if path.exists() else {}
            profiles[self.key] = {
                "profile": self.profile,
                "base_url": self.origin,
                "client_id": self.client_id,
            }
            atomic_json(path, profiles)
        return {"authenticated": True, "persisted": persisted, **self.identity(refresh=False)}

    def login(self, display):
        if not self.client_id:
            raise SeldonConfigError("workos_client_id_required")
        try:
            response = self.http.post(
                WORKOS + "/user_management/authorize/device",
                data={"client_id": self.client_id},
                timeout=30,
                follow_redirects=False,
            )
            body = response.json()
            uri = urlsplit(body["verification_uri"])
            interval, expires = body["interval"], body["expires_in"]
            if response.status_code != 200 or uri.scheme != "https" or not uri.hostname:
                raise ValueError
            if (
                type(interval) is not int
                or not 1 <= interval <= 60
                or type(expires) is not int
                or not 1 <= expires <= 900
            ):
                raise ValueError
            if not all(
                isinstance(body[key], str) and body[key] for key in ("device_code", "user_code")
            ):
                raise ValueError
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            raise SeldonAuthError("device_authorization_unavailable") from None
        display({"verification_uri": body["verification_uri"], "user_code": body["user_code"]})
        deadline = self.clock() + expires
        while self.clock() < deadline:
            self.sleep(min(interval, max(0, deadline - self.clock())))
            if self.clock() >= deadline:
                break
            status, result = self._post(
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": body["device_code"],
                }
            )
            if status == 200:
                return self._accept(result)
            error = result.get("error")
            if error == "slow_down":
                interval += 5
            elif error != "authorization_pending":
                raise SeldonAuthError("device_authorization_declined")
        raise SeldonAuthError("device_authorization_expired")

    def access_token(self):
        if self._access is not None and self._claims.get("exp", 0) > time.time() + 30:
            return self._access
        refresh = self.store.get(self.key)
        if not refresh:
            raise SeldonAuthError("login_required")
        status, body = self._post({"grant_type": "refresh_token", "refresh_token": refresh})
        if status != 200:
            if body.get("error") == "invalid_grant":
                self.store.delete(self.key)
            raise SeldonAuthError("login_required")
        self._accept(body)
        return self._access

    def identity(self, *, refresh=True):
        if refresh or self._claims is None:
            self.access_token()
        claims = self._claims
        return {
            "user_id": claims["sub"],
            "workspace": claims.get("org_id") or claims.get("organization_id"),
            "role": claims.get("role"),
            "expires_at": claims.get("exp"),
            "base_url": self.origin,
            "profile": self.profile,
        }

    def logout(self, *, open_browser=webbrowser.open):
        remote = "unavailable"
        try:
            self.access_token()
            sid = self._claims.get("sid")
            if isinstance(sid, str) and sid.startswith("session_"):
                url = WORKOS + "/user_management/sessions/logout?" + urlencode({"session_id": sid})
                remote = "browser_confirmation_pending" if open_browser(url) else "unavailable"
        except (SeldonAuthError, SeldonConfigError):
            pass
        finally:
            self.store.delete(self.key)
            self._access = self._claims = None
        return {"local_credentials_deleted": True, "remote_logout": remote}

    def logout_all(self, *, open_browser=webbrowser.open):
        path = self.config_dir / "profiles.json"
        profiles = read_json(path) if path.exists() else {}
        results = []
        for profile in profiles.values():
            other = Login(
                profile["base_url"],
                profile=profile["profile"],
                client_id=profile["client_id"],
                store=self.store,
                config_dir=self.config_dir,
                http=self.http,
            )
            results.append(other.logout(open_browser=open_browser))
        atomic_json(path, {})
        return results

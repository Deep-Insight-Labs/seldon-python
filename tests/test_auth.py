import base64
import json

import httpx
import pytest

from seldon_sdk.auth import Login, base_url
from seldon_sdk.errors import SeldonAuthError, SeldonConfigError


def jwt(**claims):
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "header." + encoded + ".signature"


class Store:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, token):
        self.values[key] = token
        return True

    def delete(self, key):
        self.values.pop(key, None)


@pytest.mark.parametrize(
    "value", ["http://example.com", "https://a.test/?secret=x", "https://key@a.test"]
)
def test_unsafe_base_urls_rejected(value):
    with pytest.raises(SeldonConfigError):
        base_url(value)


def test_device_login_refresh_host_binding_and_no_secret_files(tmp_path):
    store = Store()
    requests = []
    token = jwt(
        sub="user_test", org_id="org_test", role="owner", sid="session_test", exp=9999999999
    )

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/authorize/device"):
            return httpx.Response(
                200,
                json={
                    "device_code": "secret-device",
                    "user_code": "ABCD",
                    "verification_uri": "https://test.authkit.app/device",
                    "expires_in": 300,
                    "interval": 1,
                },
            )
        if request.url.path.endswith("/authenticate"):
            return httpx.Response(
                200, json={"access_token": token, "refresh_token": "secret-refresh"}
            )
        return httpx.Response(200, json={"items": [], "can_manage": True})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        login = Login(
            "https://a.test",
            client_id="client_test",
            store=store,
            config_dir=tmp_path,
            http=client,
            sleep=lambda _: None,
        )
        notices = []
        assert login.login(notices.append)["persisted"] is True
        assert login.identity()["role"] == "owner"
        second = Login(
            "https://b.test", client_id="client_test", store=store, config_dir=tmp_path, http=client
        )
        with pytest.raises(SeldonAuthError):
            second.access_token()
        assert not any("secret-device" in str(notice) for notice in notices)
        assert not any(
            "secret-refresh" in file.read_text() for file in tmp_path.rglob("*") if file.is_file()
        )
        assert not any(request.url.host == "b.test" for request in requests)
        assert all("secret" not in str(request.url) for request in requests)


def test_failed_refresh_preserves_secure_token_for_explicit_retry(tmp_path):
    store = Store()
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    login = Login(
        "https://a.test", client_id="client_test", store=store, config_dir=tmp_path, http=client
    )
    store.set(login.key, "old-refresh")
    with pytest.raises(SeldonAuthError, match="authentication_unavailable"):
        login.access_token()
    assert store.get(login.key) == "old-refresh"


def test_remote_logout_failure_still_removes_local_credential(tmp_path):
    store = Store()
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    login = Login(
        "https://a.test", client_id="client_test", store=store, config_dir=tmp_path, http=client
    )
    store.set(login.key, "old-refresh")
    result = login.logout(open_browser=lambda _: False)
    assert result == {"local_credentials_deleted": True, "remote_logout": "unavailable"}
    assert store.get(login.key) is None


def test_rotated_token_survives_api_outage(tmp_path):
    from seldon_sdk.errors import SeldonAuthError

    store = Store()

    def handler(request):
        if request.url.host == "api.workos.com":
            return httpx.Response(
                200,
                json={
                    "access_token": jwt(sub="user_test", org_id="org_test"),
                    "refresh_token": "replacement",
                },
            )
        raise httpx.ConnectError("unavailable", request=request)

    login = Login(
        client_id="client_test",
        store=store,
        config_dir=tmp_path,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    store.set(login.key, "old")
    with pytest.raises(SeldonAuthError, match="session_verification_unavailable"):
        login.access_token()
    assert store.get(login.key) == "replacement"

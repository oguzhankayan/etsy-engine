"""`etsy-engine login`: the device code flow saves a private key; declines and expiries say so."""
import stat

import pytest

from etsy_engine.generate import connect, raywake

START = {"device_code": "dev-secret", "user_code": "WDJB-MJHT", "verification_uri": "https://raywake.si/connect",
         "verification_uri_complete": "https://raywake.si/connect?code=WDJB-MJHT", "expires_in": 600, "interval": 5}


def fake_server(monkeypatch, answers):
    calls = []

    def post(base, path, data, timeout=30):
        calls.append((path, dict(data)))
        if path == "/v1/oauth/device":
            return 200, dict(START)
        return answers.pop(0)
    monkeypatch.setattr(connect, "_post", post)
    return calls


def run(**kwargs):
    lines, waits = [], []
    clock = iter(range(0, 10_000, 5))
    path = connect.login("https://api.raywake.com/", say=lines.append, open_browser=False,
                         sleep=waits.append, clock=lambda: next(clock), **kwargs)
    return path, lines, waits


def test_login_shows_the_code_waits_for_approval_and_saves_an_owner_only_key(monkeypatch):
    calls = fake_server(monkeypatch, [(400, {"error": "authorization_pending"}), (400, {"error": "slow_down"}),
                                      (200, {"access_token": "aip_live_secret", "token_type": "Bearer"})])
    path, lines, waits = run()
    assert lines[0] == "Your code: WDJB-MJHT" and "connect?code=WDJB-MJHT" in lines[1]
    assert waits == [5, 5, 10]  # slow_down adds five seconds
    assert calls[0] == ("/v1/oauth/device", {"client_id": "etsy-engine"})
    assert calls[1][1] == {"grant_type": connect.DEVICE_GRANT, "device_code": "dev-secret", "client_id": "etsy-engine"}
    assert connect.stored_key() == "aip_live_secret" and path == connect.CREDENTIALS
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "aip_live_secret" not in "\n".join(lines)


@pytest.mark.parametrize("error, message", [("access_denied", "declined"), ("expired_token", "expired")])
def test_a_declined_or_expired_code_saves_nothing(monkeypatch, error, message):
    fake_server(monkeypatch, [(400, {"error": error})])
    with pytest.raises(connect.ConnectError, match=message):
        run()
    assert connect.stored_key() == ""


def test_the_saved_key_is_used_and_env_wins(monkeypatch):
    monkeypatch.setattr(raywake.settings, "raywake_api_key", "")
    with pytest.raises(raywake.MissingKeyError, match="etsy-engine login"):
        raywake.require_key()
    connect.save_key("aip_live_saved")
    raywake.require_key()
    assert raywake.RaywakeClient().api_key == "aip_live_saved"
    monkeypatch.setattr(raywake.settings, "raywake_api_key", "aip_live_env")
    assert raywake.RaywakeClient().api_key == "aip_live_env"
    assert connect.forget_key() and connect.stored_key() == "" and not connect.forget_key()

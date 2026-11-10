"""Tests for the vocabulary sync service: python -m pytest test_app.py"""
import os
import tempfile

os.environ["VOCAB_SYNC_DB"] = os.path.join(tempfile.mkdtemp(), "t.sqlite")

from fastapi.testclient import TestClient  # noqa: E402

import app as service  # noqa: E402

service.init_db()
client = TestClient(service.app)


def auth(email="a@example.com", password="secret-pass"):
    return client.post("/v1/auth", json={"email": email, "password": password,
                                         "client": {"platform": "test", "version": "0"}})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_first_sign_in_registers_then_requires_password():
    r = auth("new@example.com")
    assert r.status_code == 200 and r.json()["created"] is True
    r = auth("NEW@example.com")
    assert r.status_code == 200 and r.json()["created"] is False
    assert auth("new@example.com", "wrong-password").status_code == 401


def test_validation():
    assert auth("not-an-email").status_code == 422
    assert auth("x@example.com", "short").status_code == 422


def test_push_pull_last_writer_wins_and_tombstones():
    token = auth("sync@example.com").json()["token"]
    h = bearer(token)
    r = client.post("/v1/vocabulary", headers=h, json={"since": 0, "changes": [
        {"source": "гитхаб", "replacement": "GitHub", "origin": "manual", "updated_at": "2026-10-29T10:00:00Z"},
        {"source": "Эс эйч", "replacement": "ssh", "origin": "learned", "asr_hint": True,
         "updated_at": "2026-10-29T10:00:00Z"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["revision"] == 2 and len(body["entries"]) == 2
    # Older change loses; case-variant source maps to the same key.
    r = client.post("/v1/vocabulary", headers=h, json={"since": 2, "changes": [
        {"source": "ГИТХАБ", "replacement": "Github", "updated_at": "2026-10-28T00:00:00Z"}]})
    assert r.json()["revision"] == 2 and r.json()["entries"] == []
    # Newer delete wins and travels as a tombstone.
    r = client.post("/v1/vocabulary", headers=h, json={"since": 2, "changes": [
        {"source": "гитхаб", "deleted": True, "updated_at": "2026-10-29T11:00:00Z"}]})
    entries = r.json()["entries"]
    assert len(entries) == 1 and entries[0]["deleted"] is True and entries[0]["revision"] == 3
    # Another device pulls everything.
    other = bearer(auth("sync@example.com").json()["token"])
    pulled = client.get("/v1/vocabulary?since=0", headers=other).json()
    assert pulled["revision"] == 3
    assert {(e["source"], e["deleted"]) for e in pulled["entries"]} == {("гитхаб", True), ("Эс эйч", False)}


def test_accounts_are_isolated_and_token_required():
    h1 = bearer(auth("one@example.com").json()["token"])
    h2 = bearer(auth("two@example.com").json()["token"])
    client.post("/v1/vocabulary", headers=h1, json={"changes": [
        {"source": "докер", "replacement": "Docker", "updated_at": "2026-10-29T10:00:00Z"}]})
    assert client.get("/v1/vocabulary", headers=h2).json()["entries"] == []
    assert client.get("/v1/vocabulary").status_code == 401
    assert client.get("/v1/vocabulary", headers=bearer("nope")).status_code == 401


def test_sign_out_revokes_token():
    token = auth("out@example.com").json()["token"]
    assert client.delete("/v1/auth", headers=bearer(token)).status_code == 204
    assert client.get("/v1/vocabulary", headers=bearer(token)).status_code == 401


def test_rate_limit():
    with service.db() as conn:
        conn.execute("DELETE FROM auth_failures")
    auth("rl@example.com")
    for _ in range(service.AUTH_FAIL_LIMIT):
        assert auth("rl@example.com", "wrong-password").status_code == 401
    assert auth("rl@example.com").status_code == 429
    # Other addresses from the same IP still get in.
    assert auth("rl-other@example.com").status_code == 200


def test_events_log_every_accepted_change():
    h = bearer(auth("ev@example.com").json()["token"])
    client.post("/v1/vocabulary", headers=h, json={"changes": [
        {"source": "клод", "replacement": "Claude", "updated_at": "2026-10-29T10:00:00Z"}]})
    with service.db() as conn:
        rows = conn.execute("SELECT source, replacement, platform FROM events WHERE source = 'клод'").fetchall()
    assert [tuple(r) for r in rows] == [("клод", "Claude", "")]


def test_index_page():
    r = client.get("/")
    assert r.status_code == 200
    assert "SuperDictate" in r.text


def _hw(phrase, stamp, enabled=True, deleted=False):
    return {"phrase": phrase, "enabled": enabled, "deleted": deleted, "updated_at": stamp}


def test_hotwords_push_update_disable_delete():
    h = bearer(auth("hw@example.com").json()["token"])
    r = client.post("/v1/vocabulary", headers=h, json={"since": 0, "hotwords": [
        _hw("Дунималова Анаида", "2026-11-05T10:00:00Z")]})
    body = r.json()
    assert r.status_code == 200 and body["revision"] == 1 and body["entries"] == []
    assert [(e["phrase"], e["enabled"], e["deleted"], e["revision"]) for e in body["hotwords"]] == [
        ("Дунималова Анаида", True, False, 1)]
    # Disable (newer), case/whitespace variant maps to the same key.
    r = client.post("/v1/vocabulary", headers=h, json={"since": 1, "hotwords": [
        _hw("дунималова   АНАИДА", "2026-11-05T11:00:00Z", enabled=False)]})
    hw = r.json()["hotwords"]
    assert r.json()["revision"] == 2 and len(hw) == 1 and hw[0]["enabled"] is False and hw[0]["revision"] == 2
    # Re-enable then delete -> tombstone.
    client.post("/v1/vocabulary", headers=h, json={"since": 2, "hotwords": [
        _hw("Дунималова Анаида", "2026-11-05T12:00:00Z")]})
    r = client.post("/v1/vocabulary", headers=h, json={"since": 3, "hotwords": [
        _hw("Дунималова Анаида", "2026-11-05T13:00:00Z", deleted=True)]})
    hw = r.json()["hotwords"]
    assert r.json()["revision"] == 4 and len(hw) == 1 and hw[0]["deleted"] is True
    # Resurrection after the tombstone with a newer stamp works.
    r = client.post("/v1/vocabulary", headers=h, json={"since": 4, "hotwords": [
        _hw("Дунималова Анаида", "2026-11-05T14:00:00Z")]})
    assert r.json()["hotwords"][0]["deleted"] is False


def test_hotwords_pull_by_other_device_and_isolation():
    h = bearer(auth("hw2@example.com").json()["token"])
    client.post("/v1/vocabulary", headers=h, json={
        "changes": [{"source": "гитхаб", "replacement": "GitHub", "updated_at": "2026-11-05T10:00:00Z"}],
        "hotwords": [_hw("АС Москвы", "2026-11-05T10:00:00Z", enabled=False)]})
    other = bearer(auth("hw2@example.com").json()["token"])
    pulled = client.get("/v1/vocabulary?since=0", headers=other).json()
    assert pulled["revision"] == 2
    assert [e["source"] for e in pulled["entries"]] == ["гитхаб"]
    assert [(e["phrase"], e["enabled"]) for e in pulled["hotwords"]] == [("АС Москвы", False)]
    # Only changes above `since` come back.
    assert client.get("/v1/vocabulary?since=2", headers=other).json()["hotwords"] == []
    stranger = bearer(auth("hw3@example.com").json()["token"])
    assert client.get("/v1/vocabulary", headers=stranger).json()["hotwords"] == []


def test_hotwords_last_writer_wins():
    h = bearer(auth("hw4@example.com").json()["token"])
    client.post("/v1/vocabulary", headers=h, json={"hotwords": [_hw("Росреестр", "2026-11-05T10:00:00Z")]})
    # Older and equal stamps lose (a tie keeps the server copy).
    for stamp in ("2026-11-05T09:00:00Z", "2026-11-05T10:00:00Z"):
        r = client.post("/v1/vocabulary", headers=h, json={"since": 1, "hotwords": [
            _hw("росреестр", stamp, enabled=False)]})
        assert r.json()["revision"] == 1 and r.json()["hotwords"] == []
    r = client.post("/v1/vocabulary", headers=h, json={"since": 1, "hotwords": [
        _hw("росреестр", "2026-11-05T10:00:01Z", enabled=False)]})
    assert r.json()["revision"] == 2 and r.json()["hotwords"][0]["enabled"] is False
    # An older delete cannot kill a newer live phrase.
    r = client.post("/v1/vocabulary", headers=h, json={"since": 2, "hotwords": [
        _hw("Росреестр", "2026-11-05T08:00:00Z", deleted=True)]})
    assert r.json()["hotwords"] == []


def test_hotwords_share_revision_and_skip_events():
    h = bearer(auth("hw5@example.com").json()["token"])
    r = client.post("/v1/vocabulary", headers=h, json={
        "changes": [{"source": "ёж", "replacement": "Ёж", "updated_at": "2026-11-05T10:00:00Z"}],
        "hotwords": [_hw("Секретное слово", "2026-11-05T10:00:00Z")]})
    assert r.json()["revision"] == 2
    assert [e["revision"] for e in r.json()["entries"]] == [1]
    assert [e["revision"] for e in r.json()["hotwords"]] == [2]
    with service.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events WHERE source = 'Секретное слово'"
                            " OR replacement = 'Секретное слово'").fetchone()[0] == 0


def test_hotwords_validation_and_cap(monkeypatch):
    h = bearer(auth("hw6@example.com").json()["token"])
    assert client.post("/v1/vocabulary", headers=h, json={"hotwords": [
        _hw("   ", "2026-11-05T10:00:00Z")]}).status_code == 422
    monkeypatch.setattr(service, "MAX_HOTWORD_ENTRIES", 2)
    r = client.post("/v1/vocabulary", headers=h, json={"hotwords": [
        _hw("раз", "2026-11-05T10:00:00Z"), _hw("два", "2026-11-05T10:00:00Z"),
        _hw("три", "2026-11-05T10:00:00Z")]})
    assert sorted(e["phrase"] for e in r.json()["hotwords"]) == ["два", "раз"]
    # Deleting frees a slot.
    r = client.post("/v1/vocabulary", headers=h, json={"since": 2, "hotwords": [
        _hw("раз", "2026-11-05T11:00:00Z", deleted=True), _hw("три", "2026-11-05T11:00:00Z")]})
    assert sorted((e["phrase"], e["deleted"]) for e in r.json()["hotwords"]) == [("раз", True), ("три", False)]


def test_old_client_without_hotwords_is_unaffected():
    h = bearer(auth("hw7@example.com").json()["token"])
    r = client.post("/v1/vocabulary", headers=h, json={"since": 0, "changes": [
        {"source": "докер", "replacement": "Docker", "updated_at": "2026-11-05T10:00:00Z"}]})
    assert r.status_code == 200 and r.json()["revision"] == 1 and r.json()["hotwords"] == []
    assert client.get("/v1/vocabulary", headers=h).json()["entries"][0]["replacement"] == "Docker"


# --- styles and usage --------------------------------------------------------

def _st(sid, stamp, name="Деловой", color="#FF8800", instruction="Пиши официально.", deleted=False):
    return {"id": sid, "name": name, "color": color, "instruction": instruction, "deleted": deleted,
            "updated_at": stamp}


def _us(day, device, stamp, dictations=1, characters=10, words=2, audio=1.5, asr=0.5):
    return {"day": day, "device": device, "dictations": dictations, "characters": characters, "words": words,
            "audio_seconds": audio, "asr_seconds": asr, "updated_at": stamp}


def _push(h, **payload):
    r = client.post("/v1/vocabulary", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_styles_roundtrip_lww_and_tombstone():
    h = bearer(auth("st1@example.com").json()["token"])
    body = _push(h, styles=[_st("c-aaa", "2026-11-10T10:00:00Z")])
    assert body["revision"] == 1 and body["entries"] == [] and body["hotwords"] == [] and body["usage"] == []
    s = body["styles"][0]
    assert (s["id"], s["name"], s["color"], s["instruction"], s["deleted"], s["revision"]) == (
        "c-aaa", "Деловой", "#FF8800", "Пиши официально.", False, 1)
    # Older and equal stamps lose; server copy stays.
    for stamp in ("2026-11-10T09:00:00Z", "2026-11-10T10:00:00Z"):
        body = _push(h, since=1, styles=[_st("c-aaa", stamp, name="Другой")])
        assert body["revision"] == 1 and body["styles"] == []
    # Newer wins.
    body = _push(h, since=1, styles=[_st("c-aaa", "2026-11-10T11:00:00Z", name="Новый")])
    assert body["revision"] == 2 and body["styles"][0]["name"] == "Новый"
    # Tombstone with empty payload; older edit cannot resurrect it.
    body = _push(h, since=2, styles=[_st("c-aaa", "2026-11-10T12:00:00Z", name="", color="", instruction="",
                                          deleted=True)])
    assert body["revision"] == 3 and body["styles"][0]["deleted"] is True
    body = _push(h, since=3, styles=[_st("c-aaa", "2026-11-10T11:30:00Z")])
    assert body["styles"] == [] and body["revision"] == 3
    # Newer resurrects.
    body = _push(h, since=3, styles=[_st("c-aaa", "2026-11-10T13:00:00Z")])
    assert body["styles"][0]["deleted"] is False


def test_styles_cap_and_delete_frees_slot(monkeypatch):
    h = bearer(auth("st2@example.com").json()["token"])
    monkeypatch.setattr(service, "MAX_STYLES", 2)
    body = _push(h, styles=[_st(f"c-{i}", "2026-11-10T10:00:00Z", name=f"S{i}") for i in range(3)])
    assert sorted(s["id"] for s in body["styles"]) == ["c-0", "c-1"]
    body = _push(h, since=2, styles=[_st("c-0", "2026-11-10T11:00:00Z", name="", color="", deleted=True),
                                      _st("c-2", "2026-11-10T11:00:00Z", name="S2")])
    assert sorted((s["id"], s["deleted"]) for s in body["styles"]) == [("c-0", True), ("c-2", False)]
    # Edits to existing live styles are not blocked by the cap.
    body = _push(h, since=4, styles=[_st("c-1", "2026-11-10T12:00:00Z", name="Edited")])
    assert body["styles"][0]["name"] == "Edited"


def test_styles_validation():
    h = bearer(auth("st3@example.com").json()["token"])
    bad = [
        _st("x-1", "2026-11-10T10:00:00Z"),                       # no c- prefix
        _st("c-" + "a" * 63, "2026-11-10T10:00:00Z"),             # id > 64
        _st("c-1", "2026-11-10T10:00:00Z", name=""),
        _st("c-1", "2026-11-10T10:00:00Z", name="   "),
        _st("c-1", "2026-11-10T10:00:00Z", name="x" * 41),
        _st("c-1", "2026-11-10T10:00:00Z", color="red"),
        _st("c-1", "2026-11-10T10:00:00Z", color="#FF880"),
        _st("c-1", "2026-11-10T10:00:00Z", color=""),
        _st("c-1", "2026-11-10T10:00:00Z", instruction="x" * 4001),
    ]
    for item in bad:
        assert client.post("/v1/vocabulary", headers=h, json={"styles": [item]}).status_code == 422, item
    ok = _st("c-1", "2026-11-10T10:00:00Z", name="x" * 40, instruction="y" * 4000)
    assert client.post("/v1/vocabulary", headers=h, json={"styles": [ok]}).status_code == 200


def test_styles_multi_device_and_since():
    h1 = bearer(auth("st4@example.com").json()["token"])
    h2 = bearer(auth("st4@example.com").json()["token"])
    _push(h1, styles=[_st("c-1", "2026-11-10T10:00:00Z", name="A")])
    body = _push(h2, since=0, styles=[_st("c-2", "2026-11-10T10:05:00Z", name="B")])
    assert sorted(s["id"] for s in body["styles"]) == ["c-1", "c-2"] and body["revision"] == 2
    assert [s["id"] for s in client.get("/v1/vocabulary?since=1", headers=h1).json()["styles"]] == ["c-2"]
    assert client.get("/v1/vocabulary?since=2", headers=h1).json()["styles"] == []
    other = bearer(auth("st5@example.com").json()["token"])
    assert client.get("/v1/vocabulary", headers=other).json()["styles"] == []


def test_usage_idempotent_absolute_values():
    h = bearer(auth("us1@example.com").json()["token"])
    row = _us("2026-11-10", "dev-a", "2026-11-10T10:00:00Z", dictations=5, characters=100, words=20,
              audio=12.5, asr=3.25)
    body = _push(h, usage=[row])
    assert body["revision"] == 1 and body["entries"] == []
    u = body["usage"][0]
    assert (u["day"], u["device"], u["dictations"], u["characters"], u["words"], u["audio_seconds"],
            u["asr_seconds"], u["revision"]) == ("2026-11-10", "dev-a", 5, 100, 20, 12.5, 3.25, 1)
    # Re-pushing the same row changes nothing (no revision bump, no double counting).
    body = _push(h, since=1, usage=[row, row])
    assert body["revision"] == 1 and body["usage"] == []
    # Newer absolute values replace, not add.
    body = _push(h, since=1, usage=[_us("2026-11-10", "dev-a", "2026-11-10T11:00:00Z", dictations=7,
                                         characters=150)])
    assert body["revision"] == 2 and body["usage"][0]["dictations"] == 7 and body["usage"][0]["characters"] == 150
    # Older stamp (clock rollback) loses.
    body = _push(h, since=2, usage=[_us("2026-11-10", "dev-a", "2026-11-10T09:00:00Z", dictations=1)])
    assert body["revision"] == 2 and body["usage"] == []


def test_usage_multiple_devices_and_days():
    h = bearer(auth("us2@example.com").json()["token"])
    other = bearer(auth("us2@example.com").json()["token"])
    _push(h, usage=[_us("2026-11-09", "dev-a", "2026-11-09T20:00:00Z", dictations=3),
                    _us("2026-11-10", "dev-a", "2026-11-10T10:00:00Z", dictations=4)])
    body = _push(other, since=0, usage=[_us("2026-11-10", "dev-b", "2026-11-10T10:00:01Z", dictations=9)])
    rows = {(u["day"], u["device"]): u["dictations"] for u in body["usage"]}
    assert rows == {("2026-11-09", "dev-a"): 3, ("2026-11-10", "dev-a"): 4, ("2026-11-10", "dev-b"): 9}
    assert sum(rows.values()) == 16
    assert body["revision"] == 3
    # Pull only what is above since; another account sees nothing.
    assert [u["device"] for u in client.get("/v1/vocabulary?since=2", headers=h).json()["usage"]] == ["dev-b"]
    stranger = bearer(auth("us3@example.com").json()["token"])
    assert client.get("/v1/vocabulary", headers=stranger).json()["usage"] == []


def test_usage_optional_fields_and_validation():
    h = bearer(auth("us4@example.com").json()["token"])
    # words / asr_seconds may be omitted (platform does not track them).
    row = {"day": "2026-11-10", "device": "d", "dictations": 1, "characters": 5, "audio_seconds": 2.0,
           "updated_at": "2026-11-10T10:00:00Z"}
    body = _push(h, usage=[row])
    assert body["usage"][0]["words"] == 0 and body["usage"][0]["asr_seconds"] == 0
    good = _us("2026-11-10", "d", "2026-11-10T11:00:00Z")
    bad = [
        {**good, "day": "10.11.2026"}, {**good, "day": "2026-13-40"}, {**good, "day": "2026-11-1"},
        {**good, "device": ""}, {**good, "device": "d" * 65},
        {**good, "dictations": -1}, {**good, "characters": -5}, {**good, "audio_seconds": -0.1},
        {**good, "dictations": service.MAX_USAGE_COUNT + 1},
        {**good, "audio_seconds": service.MAX_USAGE_SECONDS + 1},
    ]
    for item in bad:
        assert client.post("/v1/vocabulary", headers=h, json={"usage": [item]}).status_code == 422, item


def test_styles_and_usage_share_revision_and_skip_events():
    h = bearer(auth("sh1@example.com").json()["token"])
    body = _push(h, changes=[{"source": "ёж", "replacement": "Ёж", "updated_at": "2026-11-10T10:00:00Z"}],
                 hotwords=[_hw("Слово", "2026-11-10T10:00:00Z")],
                 styles=[_st("c-secret", "2026-11-10T10:00:00Z", name="СекретныйРежим",
                             instruction="СекретнаяИнструкция")],
                 usage=[_us("2026-11-10", "dev-a", "2026-11-10T10:00:00Z")])
    assert body["revision"] == 4
    assert [e["revision"] for e in body["entries"]] == [1]
    assert [e["revision"] for e in body["hotwords"]] == [2]
    assert [e["revision"] for e in body["styles"]] == [3]
    assert [e["revision"] for e in body["usage"]] == [4]
    with service.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events WHERE account_id = (SELECT id FROM accounts"
                            " WHERE email = 'sh1@example.com')").fetchone()[0] == 1


def test_old_client_without_styles_and_usage_is_unaffected():
    h = bearer(auth("old@example.com").json()["token"])
    r = client.post("/v1/vocabulary", headers=h, json={"since": 0, "changes": [
        {"source": "докер", "replacement": "Docker", "updated_at": "2026-11-10T10:00:00Z"}]})
    assert r.status_code == 200 and r.json()["styles"] == [] and r.json()["usage"] == []
    # A new client's data does not leak into an old client's fields.
    _push(h, since=1, styles=[_st("c-1", "2026-11-10T10:00:00Z")], usage=[_us("2026-11-10", "d", "2026-11-10T10:00:00Z")])
    old = client.post("/v1/vocabulary", headers=h, json={"since": 0, "changes": []}).json()
    assert [e["source"] for e in old["entries"]] == ["докер"] and old["revision"] == 3


def test_migration_adds_tables_to_existing_db():
    with service.db() as conn:
        conn.execute("DROP TABLE style_entries")
        conn.execute("DROP TABLE usage_days")
    service.init_db()
    h = bearer(auth("mig@example.com").json()["token"])
    body = _push(h, styles=[_st("c-1", "2026-11-10T10:00:00Z")])
    assert len(body["styles"]) == 1
    service.init_db()  # idempotent

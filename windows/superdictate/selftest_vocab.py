"""Self-tests for ASR hotwords, vocabulary hygiene and the account sync.

Part of ``python main.py --self-test`` (:mod:`superdictate.selftest` runs
:data:`TESTS` and collects :data:`FAILURES`). Kept in a module of its own
because none of it needs Windows: the pure rules run anywhere, which is how
they were checked against the macOS tables on a Mac too
(``python -m superdictate.selftest_vocab``).

* ``test_asr_hotword_selection``: the macOS table of
  ``AsrHotwordSelection`` (asr-hotwords spec §6), case for case.
* ``test_asr_hint_store``: the ``asr_hint`` migration and every write path
  keeping the hint.
* ``test_asr_hotwords_settings_and_ipc``: settings, the TRANSCRIBE options
  (an empty list adds no key) on the wire, and the NPU path sending none.
* ``test_vocabulary_hygiene_review`` / ``..._cleanup``: §1's real-world
  examples and §2's keep-cases; the cleanup plan.
* ``test_vocabulary_edits_and_tombstones``: list saves write only the diff;
  every delete leaves a tombstone.
* ``test_vocabulary_sync_server``: two simulated machines against a local
  ``server/vocab-sync`` (skipped where the server or FastAPI is missing).
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import paths

FAILURES: list[str] = []


def _check(name: str, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{name}\n    expected: {expected!r}\n    actual:   {actual!r}")


def _temp_db() -> str:
    handle, path = tempfile.mkstemp(suffix=".sqlite", prefix="sd-vocab-selftest-")
    os.close(handle)
    os.unlink(path)
    return path


def _remove_db(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


class _Rec:
    """A stand-in record for the pure rules."""

    def __init__(self, id, source, replacement, origin="learned", asr_hint=None,
                 updated_at="2026-01-01T00:00:00Z"):
        self.id, self.source, self.replacement = id, source, replacement
        self.origin, self.asr_hint, self.updated_at = origin, asr_hint, updated_at


# -- ASR hotwords ----------------------------------------------------------

def test_asr_hotword_selection() -> None:
    from . import asr_hotwords as hw

    # (source, replacement, origin, hint, expected phrase or None): the
    # macOS self-test table (SelfTest.testAsrHotwords), unchanged.
    cases = [
        ("DR4 DM", "DDR4 DIMM", "learned", None, "DDR4 DIMM"),
        ("ЕСА", "ЕСИА", "learned", None, "ЕСИА"),
        ("Gm, вотчер,", "Gmail watcher,", "learned", None, "Gmail watcher"),
        ("Пони Чепуренко", "По Ничипуренко", "learned", None, "По Ничипуренко"),
        ("Егр", "ЕГРЮЛ", "learned", None, "ЕГРЮЛ"),
        ("TicTic,", "TickTick,", "learned", None, "TickTick"),
        ("тридцать семь. А", "37А", "learned", None, "37А"),
        ("1.", "1mm.", "learned", None, "1mm"),
        ("Аллес Скарш—", "Alien_skaarj —", "learned", None, "Alien_skaarj"),
        ("хаггинг фейс", "Hugging Face", "manual", None, "Hugging Face"),
        ("Смотри.", "Задайте вопрос ChatGPT", "learned", None, "Задайте вопрос ChatGPT"),
        ("Запомню", "Запомни", "learned", None, None),
        ("сторониной", "стороной", "learned", None, None),
        ("красненькову", "Красникову", "learned", None, None),
        ("Нечепуренко", "Ничипуренко", "learned", None, None),
        ("Нечепуренко", "Ничипуренко", "learned", True, "Ничипуренко"),
        ("красненькову", "Красникову", "learned", True, "Красникову"),
        ("докер", "Docker", "manual", False, None),
        ("Эмсипи", "MCP", "learned", False, None),
        ("сторониной", "стороной", "manual", None, "стороной"),
        ("оплатил", "оплатил.", "learned", True, None),
        ("ознакомления", "ознакомления.", "manual", None, None),
        ("Амирханян Ц", "АмирханянЦ", "learned", True, None),
        ("Х 99", "Х99", "manual", None, None),
        ("Инструменты.", "инструменты?", "manual", None, None),
        ("интернейшнл.", ".", "learned", True, None),
        ("S.", "1", "manual", None, None),
        ("икс", "X", "manual", True, None),
        ("12", "42!", "manual", True, None),
        ("длинно", "раз два три четыре пять", "manual", True, None),
        ("коротко", "раз два три QQ", "learned", None, "раз два три QQ"),
        ("кавычки", "«Ответ налоговая»", "manual", None, "Ответ налоговая"),
        ("тире", "— TDT –", "learned", None, "TDT"),
        ("ssh", "Ssh", "manual", None, None),
    ]
    for index, (source, replacement, origin, hint, expected) in enumerate(cases):
        record = _Rec(index, source, replacement, origin, hint)
        _check(f"hotwords: effective {source} -> {replacement} ({origin}, hint {hint})",
               hw.is_effective(source, replacement, origin, hint), expected is not None)
        _check(f"hotwords: phrase for {source} -> {replacement}",
               hw.phrases([record]), [expected] if expected else [])
    _check("hotwords: one uppercase Cyrillic letter is not term-like", hw.is_term_like("Ёлка"), False)
    _check("hotwords: two uppercase letters are term-like", hw.is_term_like("ЁЖ"), True)
    _check("hotwords: Latin-1 letters count as Latin", hw.is_term_like("café"), True)

    duplicates = [_Rec(i, s, r, "manual") for i, (s, r) in enumerate(
        [("гитхаб", "GitHub"), ("гит хаб", "GitHub"), ("Гетхаб.", "Github."),
         ("зип", "ZIP"), ("Зип,", "Zip,")])]
    _check("hotwords: exact duplicates merged, case variants kept, order kept",
           hw.phrases(duplicates), ["GitHub", "Github", "ZIP", "Zip"])
    many = [_Rec(i, f"s{i}", f"Term{i}", "manual") for i in range(1200)]
    capped = hw.phrases(many)
    _check("hotwords: capped at 1000", len(capped), hw.MAX_PHRASES)
    _check("hotwords: the cap keeps the first 1000 in order", capped[-1], "Term999")


def test_asr_hint_store() -> None:
    import sqlite3

    from .vocabulary import DraftEntry, Origin, VocabularyStore

    path = _temp_db()
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL COLLATE NOCASE,
            replacement TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL);
        CREATE UNIQUE INDEX idx_corrections_source_nocase ON corrections (source);
        INSERT INTO corrections (source, replacement, origin, created_at, updated_at) VALUES
            ('Нечепуренко', 'Ничипуренко', 'learned', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
            ('DR4 DM', 'DDR4 DIMM', 'learned', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
            ('докер', 'Docker', 'manual', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
    """)
    legacy.commit()
    legacy.close()

    store = VocabularyStore(path)
    reopened = None
    try:
        migrated = store.all()
        _check("asr_hint: rows survive the migration", len(migrated), 3)
        _check("asr_hint: migrated rows start automatic",
               all(r.asr_hint is None for r in migrated), True)
        _check("asr_hint: automatic phrases after migration",
               store.asr_hotword_phrases(), ["DDR4 DIMM", "Docker"])
        surname = next(r for r in migrated if r.replacement == "Ничипуренко")
        docker = next(r for r in migrated if r.replacement == "Docker")
        store.set_asr_hint(surname.id, True)
        store.set_asr_hint(docker.id, False)
        _check("asr_hint: explicit hints applied",
               store.asr_hotword_phrases(), ["DDR4 DIMM", "Ничипуренко"])

        reopened = VocabularyStore(path)  # the migration again: idempotent
        _check("asr_hint: persists across connections", reopened.get(surname.id).asr_hint, True)
        _check("asr_hint: explicit off persists", reopened.get(docker.id).asr_hint, False)

        store.upsert("нечепуренко", "Ничипуренко", Origin.MANUAL)
        _check("asr_hint: upsert keeps the hint", store.get(surname.id).asr_hint, True)
        store.learn([("Нечепуренко", "Ничипуренко")])
        _check("asr_hint: learning a known source keeps the hint",
               store.get(surname.id).asr_hint, True)
        _check("asr_hint: learning over a manual rule keeps it manual",
               store.get(surname.id).origin, Origin.MANUAL)
        store.replace_all([("Нечепуренко", "Ничипуренко"), ("докер", "Docker"), ("ЕСА", "ЕСИА")])
        after = {r.source: r for r in store.all()}
        _check("asr_hint: replace_all keeps the hint", after["Нечепуренко"].asr_hint, True)
        _check("asr_hint: replace_all keeps explicit off", after["докер"].asr_hint, False)
        _check("asr_hint: new rows start automatic", after["ЕСА"].asr_hint, None)
        _check("asr_hint: phrases after replace_all",
               store.asr_hotword_phrases(), ["ЕСИА", "Ничипуренко"])
        store.set_asr_hint(surname.id, None)
        _check("asr_hint: None resets", store.get(surname.id).asr_hint, None)
        learned = store.learn([("Клод", "Claude")])
        _check("asr_hint: a learned row starts automatic", learned[0].asr_hint, None)

        # The list window's save carries the hint column.
        baseline = store.all()
        edited = [DraftEntry(r.source, r.replacement, True if r.source == "Клод" else r.asr_hint,
                             r.origin) for r in baseline]
        store.apply_edits(baseline, edited)
        _check("asr_hint: the list save writes a changed hint", store.find("Клод").asr_hint, True)
        _check("asr_hint: the list save keeps the origin", store.find("Клод").origin, Origin.LEARNED)
    finally:
        store.close()
        if reopened is not None:
            reopened.close()
        _remove_db(path)

    fresh = _temp_db()
    store = VocabularyStore(fresh)
    try:
        record = store.upsert("кью 8", "Q8", Origin.LEARNED)
        _check("asr_hint: a brand-new database has the column", record.asr_hint, None)
        _check("asr_hint: a brand-new database selects", store.asr_hotword_phrases(), ["Q8"])
    finally:
        store.close()
        _remove_db(fresh)


_ECHO_HOST = r"""
import json, struct, sys
REQ = struct.Struct("<4sHHQIQ"); RES = struct.Struct("<4sHHQI")
inp, out = sys.stdin.buffer, sys.stdout.buffer
def send(status, rid, body):
    data = json.dumps(body).encode()
    out.write(RES.pack(b"SDAR", 1, status, rid, len(data)) + data); out.flush()
def read(n):
    buf = b""
    while len(buf) < n:
        chunk = inp.read(n - len(buf))
        if not chunk: sys.exit(0)
        buf += chunk
    return buf
while True:
    magic, version, kind, rid, jlen, plen = REQ.unpack(read(REQ.size))
    raw = read(jlen); read(plen)
    if kind == 1:
        send(0, rid, {"provider_actual": "cpu", "model_id": "fake"})
    elif kind == 2:
        body = json.loads(raw or b"{}")
        result = {"text": raw.decode("utf-8"), "processing_seconds": 0.0}
        if body.get("hotwords"):
            result["hotwords_used"] = len(body["hotwords"]) - 1
            result["hotwords_skipped"] = body["hotwords"][-1:]
        send(0, rid, result)
    elif kind == 5:
        sys.exit(0)
"""


def test_asr_hotwords_settings_and_ipc() -> None:
    import numpy as np

    from . import asr_hotwords, onnx_host
    from .settings import Settings

    settings_path = Path(tempfile.mkdtemp()) / "Settings.json"
    settings = Settings(path=settings_path)
    _check("hotwords: on by default", settings.asr_hotwords_enabled, True)
    _check("hotwords: normal strength by default", settings.asr_hotwords_strength, "normal")
    _check("hotwords: default configuration",
           settings.asr_hotwords_configuration(["DDR4 DIMM"]),
           asr_hotwords.HotwordsConfiguration(("DDR4 DIMM",), 2.0))
    settings.apply({"asr_hotwords_strength": "strong"})
    _check("hotwords: strong = 3.0", settings.asr_hotwords_configuration(["x"]).score, 3.0)
    settings.apply({"asr_hotwords_strength": "bogus"})
    _check("hotwords: an unknown strength reads as normal", settings.asr_hotwords_strength, "normal")
    settings.apply({"asr_hotwords_enabled": False})
    _check("hotwords: disabled means no phrases",
           settings.asr_hotwords_configuration(["DDR4 DIMM"]), asr_hotwords.DISABLED)
    _check("hotwords: the switch round-trips", Settings(path=settings_path).asr_hotwords_enabled, False)

    for timestamps in (False, True):
        _check(f"hotwords: an empty list adds no key (timestamps={timestamps})",
               onnx_host.transcribe_options(timestamps=timestamps, hotwords=[], hotwords_score=3.0),
               {"timestamps": timestamps, "sample_rate": 16000})
    biased = onnx_host.transcribe_options(timestamps=False, hotwords=["DDR4 DIMM", "ЕСИА"],
                                          hotwords_score=3.0)
    _check("hotwords: the list and score are sent as given", biased,
           {"timestamps": False, "sample_rate": 16000,
            "hotwords": ["DDR4 DIMM", "ЕСИА"], "hotwords_score": 3.0})

    # On the wire, through a stand-in host that echoes the options back.
    script = Path(tempfile.mkdtemp()) / "echo_host.py"
    script.write_text(_ECHO_HOST, encoding="utf-8")
    host = onnx_host.OnnxHost([sys.executable, "-I", str(script)])
    try:
        host.create(model_directory=Path("m"), assets_directory=Path("a"), threads=1)
        plain = host.transcribe(np.zeros(400, dtype=np.float32))
        _check("hotwords: no list, the pre-hotwords request exactly",
               json.loads(plain.text), {"timestamps": False, "sample_rate": 16000})
        _check("hotwords: no list, no report", plain.hotwords_used, None)
        biased = host.transcribe(np.zeros(400, dtype=np.float32), timestamps=True,
                                 hotwords=("DDR4 DIMM", "ЕСИА", "Ω"), hotwords_score=2.0)
        _check("hotwords: the list reaches the host", json.loads(biased.text),
               {"timestamps": True, "sample_rate": 16000,
                "hotwords": ["DDR4 DIMM", "ЕСИА", "Ω"], "hotwords_score": 2.0})
        _check("hotwords: the host's report is read",
               (biased.hotwords_used, biased.hotwords_skipped), (2, ("Ω",)))
    finally:
        host.shutdown()

    # The NPU (OpenVINO) host has no hotwords: nothing is sent there.
    from . import asr

    configuration = asr_hotwords.HotwordsConfiguration(("DDR4 DIMM",), 2.0)
    cpu = asr.SpeechModel(threads=1)
    cpu.set_hotwords(configuration)
    _check("hotwords: the CPU path sends the list", cpu._request_hotwords(), configuration)
    npu = asr.SpeechModel(threads=1, backend=asr.BACKEND_NPU)
    npu.set_hotwords(configuration)
    _check("hotwords: the NPU path sends none", npu._request_hotwords(), asr_hotwords.DISABLED)


# -- hygiene ---------------------------------------------------------------

def _verdict(source, replacement, existing=()):
    from . import vocabulary_hygiene as h

    verdict = h.review(source, replacement, list(existing))
    if isinstance(verdict, h.Accept):
        return ("accept", verdict.source, verdict.replacement) + (
            (verdict.chain_rewrites,) if verdict.chain_rewrites else ())
    if isinstance(verdict, h.Reject):
        return ("reject", verdict.reason)
    return ("undo", verdict.existing_id)


def test_vocabulary_hygiene_review() -> None:
    from . import vocabulary_hygiene as h

    # §1, the real dictionary's garbage: rejected.
    rejected = [
        ("оплатил", "оплатил.", "punctuation"),
        ("соусом.", "соусом!!", "punctuation"),
        ("инструменты.", "инструменты?", "punctuation"),
        ("интернейшнл.", ".", "no-letters"),
        ("S.", "1", "no-letters"),
        ("Запомню", "Запомни", "inflection"),
        ("дополню,", "дополни,", "inflection"),
        ("пробиваю.", "пробивает.", "inflection"),
        ("капюшонном,", "капюшоном,", "inflection"),
        ("погонял", "погоняло", "inflection"),
        ("сторониной", "стороной", "inflection"),
        ("черноиск", "черновик", "inflection"),
        ("финансовая управляющая", "финансового управляющего", "inflection"),
        ("обжалуемым судебным актом", "обжалуемыми судебными актами", "inflection"),
        ("договор суда", "договор суду", "inflection"),
        ("Санкт-Петербурга", "Санкт-Петербургу", "inflection"),
        ("отец", "отца", "inflection"),
        ("день", "дня", "inflection"),
        ("лёд", "льда", "inflection"),
        ("бой", "боя", "inflection"),
        ("сделал работу", "сделала работы", "inflection"),
        ("ёлка", "елки", "inflection"),
        ("Смотри.", "Задайте вопрос ChatGPT", "rewrite"),
        ("тридцать семь. А", "37А", "rewrite"),
    ]
    for source, replacement, reason in rejected:
        _check(f"hygiene: {source} -> {replacement} rejected",
               _verdict(source, replacement), ("reject", reason))

    # §2's keep-cases: accepted unchanged.
    kept = [
        ("кто", "кот"), ("Бюллеттени Нилова", "Бюллетени Нилова"), ("Биллюте Николашникова", "Биллютени Калашникова"),
        ("докс-документа", "DOCX-документа"),
        ("IS60", "IS-60"), ("Metal Fish", "MetalFish"), ("NH C14S", "NH-C14S"),
        ("Амирханян Ц", "АмирханянЦ"), ("Х 99", "Х99"), ("Егр", "ЕГРЮЛ"),
        ("Нечепуренко", "Ничипуренко"), ("красненькову", "Красникову"),
        ("паникший", "поникший"), ("снуху", "слуху"), ("Эмсипи", "MCP"),
        ("Эс эйч", "ssh"), ("Comment", "Command"), ("Юзу ВМ", "УВМ"),
        ("Кад Сендер", "kad sender"), ("DR4 DM", "DDR4 DIMM"), ("ЕСА", "ЕСИА"),
        ("1", "1mm"), ("хаггинг фейс", "Hugging Face"), ("Гетхаб", "Github"),
    ]
    for source, replacement in kept:
        _check(f"hygiene: {source} -> {replacement} kept",
               _verdict(source, replacement), ("accept", source, replacement))

    # Rule 1: edge punctuation goes from both sides.
    _check("hygiene: shared edge punctuation trimmed",
           _verdict("Pipline.", "Pipeline."), ("accept", "Pipline", "Pipeline"))
    _check("hygiene: one-sided edge punctuation trimmed",
           _verdict("Гетхаб.", "Github"), ("accept", "Гетхаб", "Github"))
    _check("hygiene: dashes and spaces at the edges",
           _verdict("Аллес Скарш—", "Alien_skaarj —"), ("accept", "Аллес Скарш", "Alien_skaarj"))
    _check("hygiene: a term's case fix is kept", _verdict("Github", "GitHub"),
           ("accept", "Github", "GitHub"))

    # Several sources for one target are correct.
    docx = [_Rec(1, "докx", "docx"), _Rec(2, "DogX", "docx")]
    _check("hygiene: another source for a known target is kept",
           _verdict("док икс", "docx", docx), ("accept", "док икс", "docx"))

    # Rule 6: undo.
    _check("hygiene: reverting a rule undoes it",
           _verdict("GitHub", "гитхаб", [_Rec(7, "гитхаб", "GitHub", "manual")]), ("undo", 7))
    _check("hygiene: reverting a pre-hygiene rule still undoes it",
           _verdict("Запомни", "Запомню", [_Rec(8, "Запомню", "Запомни")]), ("undo", 8))

    # Rule 7: chains.
    _check("hygiene: a typo of a typo follows the chain",
           _verdict("Pypline.", "Pipline.", [_Rec(3, "Pipline.", "Pipeline.")]),
           ("accept", "Pypline", "Pipeline"))
    _check("hygiene: chains ending at the source collapse onto the new target",
           _verdict("Гитхаб", "GitHub", [_Rec(4, "гит хаб", "Гитхаб")]),
           ("accept", "Гитхаб", "GitHub", ((4, "GitHub"),)))

    # Rule 8: one casing per target.
    _check("hygiene: a manual entry's casing wins",
           _verdict("Гетхаб", "Github", [_Rec(5, "гит хаб", "GitHub", "manual"),
                                         _Rec(6, "гитхабе", "Github", "learned",
                                              updated_at="2026-09-01T00:00:00Z")]),
           ("accept", "Гетхаб", "GitHub"))
    _check("hygiene: otherwise the newest entry's casing",
           _verdict("интернешнл", "international",
                    [_Rec(9, "интернейшенал", "International", updated_at="2026-09-01T00:00:00Z"),
                     _Rec(10, "интер", "INTERNATIONAL", updated_at="2026-01-01T00:00:00Z")]),
           ("accept", "интернешнл", "International"))
    _check("hygiene: Zip follows the manual ZIP",
           _verdict("зип", "Zip", [_Rec(11, "зипка", "ZIP", "manual")]), ("accept", "зип", "ZIP"))

    # The manual editor: rules 1 and 3 only.
    _check("hygiene: manual entries skip the inflection filter",
           h.review_manual("Запомню.", "Запомни."), h.Accept("Запомню", "Запомни"))
    _check("hygiene: manual entries still need letters",
           h.review_manual("S.", "1"), h.Reject("no-letters"))
    _check("hygiene: is_term_like is the hotword predicate", h.is_term_like("ЕГРЮЛ"), True)


def test_vocabulary_hygiene_cleanup() -> None:
    from . import vocabulary_hygiene as h
    from .vocabulary import Origin, VocabularyStore

    path = _temp_db()
    store = VocabularyStore(path)
    try:
        rows = [
            ("оплатил", "оплатил.", "learned"),
            ("интернейшнл.", ".", "learned"),
            ("Запомню", "Запомни", "learned"),
            ("Смотри.", "Задайте вопрос ChatGPT", "learned"),
            ("Pipline.", "Pipeline.", "learned"),
            ("Pypline.", "Pipline.", "learned"),
            ("гитхаб", "GitHub", "manual"),
            ("Гетхаб.", "Github.", "learned"),
            ("зип", "ZIP", "manual"),
            ("Зип,", "Zip,", "learned"),
            ("Гетхаб", "Гитхаб", "learned"),
            ("гитхабе", "Github", "learned"),
            ("зипы", "Zip", "learned"),
            ("докx", "docx", "learned"),
            ("DogX", "docx", "learned"),
            ("Нечепуренко", "Ничипуренко", "learned"),
            ("сторониной", "стороной", "manual"),
        ]
        for source, replacement, origin in rows:
            store.upsert(source, replacement, Origin(origin))
        with store._lock:  # «Гетхаб.» is the older of the two that collapse
            store._db.execute("UPDATE corrections SET updated_at = '2026-01-01T00:00:00Z' "
                              "WHERE source = 'Гетхаб.';")
            store._db.commit()
        plan = store.cleanup_plan()
        deleted = sorted((d.record.source, d.reason) for d in plan.deletions)
        rewritten = sorted((r.record.source, r.source, r.replacement, r.reasons) for r in plan.rewrites)
        _check("cleanup: deletions with reasons", deleted, sorted([
            ("оплатил", "punctuation"),
            ("интернейшнл.", "no-letters"),
            ("Запомню", "inflection"),
            ("Смотри.", "rewrite"),
            ("Гетхаб.", "duplicate"),      # trims onto the newer «Гетхаб»
            ("Зип,", "duplicate"),         # trims onto the manual «зип»
        ]))
        _check("cleanup: rewrites", rewritten, sorted([
            ("Pipline.", "Pipline", "Pipeline", ("trim",)),
            ("Pypline.", "Pypline", "Pipeline", ("trim", "chain")),
            ("Гетхаб", "Гетхаб", "GitHub", ("chain",)),   # Гитхаб → GitHub (manual)
            ("гитхабе", "гитхабе", "GitHub", ("case",)),
            ("зипы", "зипы", "ZIP", ("case",)),
        ]))
        _check("cleanup: duplicates listed",
               sorted(d.record.source for d in plan.duplicates), ["Гетхаб.", "Зип,"])

        store.apply_cleanup(plan)
        after = {r.source: r.replacement for r in store.all()}
        _check("cleanup: manual entries untouched",
               (after.get("гитхаб"), after.get("зип"), after.get("сторониной")),
               ("GitHub", "ZIP", "стороной"))
        _check("cleanup: several sources for one target stay",
               (after.get("докx"), after.get("DogX")), ("docx", "docx"))
        _check("cleanup: the applied result",
               (after.get("Pypline"), after.get("Гетхаб"), "Запомню" in after),
               ("Pipeline", "GitHub", False))
        tomb_keys = {t.key for t in store.tombstones()}
        _check("cleanup: deletions and re-keyed rows leave tombstones",
               {"оплатил", "запомню", "pypline.", "гетхаб.", "зип,"} <= tomb_keys, True)
        _check("cleanup: the re-used key has no tombstone", "гетхаб" in tomb_keys, False)
        _check("cleanup: a second run finds nothing", store.cleanup_plan().is_empty, True)
        _check("cleanup: an empty plan", h.cleanup_plan([]).is_empty, True)
    finally:
        store.close()
        _remove_db(path)


def test_vocabulary_learn_reviewed() -> None:
    from .vocabulary import Origin, VocabularyStore

    path = _temp_db()
    store = VocabularyStore(path)
    try:
        events = []
        store.add_listener(events.append)
        outcome = store.learn_reviewed("оплатил", "оплатил.")
        _check("learn: a rejected candidate writes nothing",
               (outcome.rejected, store.count(), events), ("punctuation", 0, []))
        store.upsert("гит хаб", "Гитхаб", Origin.LEARNED)
        outcome = store.learn_reviewed("Гитхаб.", "GitHub.")
        _check("learn: stored trimmed", [(r.source, r.replacement) for r in outcome.written],
               [("Гитхаб", "GitHub")])
        _check("learn: the chain collapsed", store.find("гит хаб").replacement, "GitHub")
        outcome = store.learn_reviewed("GitHub", "Гитхаб")
        _check("learn: a revert removes the rule",
               (outcome.undone_id is not None, store.find("Гитхаб")), (True, None))
        _check("learn: the revert leaves a tombstone",
               "гитхаб" in {t.key for t in store.tombstones()}, True)
        _check("learn: every write notified", set(events), {"local"})
    finally:
        store.close()
        _remove_db(path)


def test_learn_hygiene_in_edit_watch() -> None:
    """A rejected candidate never reaches the pill; a rewritten one does."""
    import time as _time

    from . import edit_watch
    from . import vocabulary_hygiene as h
    from .focus_target import FieldSnapshot
    from .vocabulary import LearnCandidate

    def run(dictated, edited):
        clock = {"t": 0.0}
        field = dictated + " конец"
        states = [(0, field), (1, edited + " конец")]
        pending, learned = [], []

        def read():
            text = [t for at, t in states if clock["t"] >= at][-1]
            return FieldSnapshot(element=1, pid=1, text=text, caret=None, secure=False)

        def review(candidate):
            verdict = h.review(candidate.source, candidate.replacement, [])
            if isinstance(verdict, h.Accept):
                return LearnCandidate(verdict.source, verdict.replacement)
            return None

        def sleep(seconds):
            clock["t"] += seconds

        watcher = edit_watch.EditWatcher(
            read, lambda c: learned.append((c.source, c.replacement)) or True,
            review=review, on_pending=lambda c, b: pending.append((c.source, c.replacement)),
            clock=lambda: clock["t"], sleep=sleep)
        watcher.begin(dictated)
        deadline = _time.monotonic() + 10
        while watcher._thread is not None and watcher._thread.is_alive() \
                and _time.monotonic() < deadline:
            _time.sleep(0.01)
        watcher.stop()
        return pending, learned

    _check("edit watch: an inflection edit gets no pill",
           run("я Запомню это", "я Запомни это"), ([], []))
    _check("edit watch: a punctuation edit gets no pill",
           run("он оплатил вчера", "он оплатил. вчера"), ([], []))
    _check("edit watch: a real correction is offered trimmed",
           run("залей на гитхаб.", "залей на GitHub."),
           ([("гитхаб", "GitHub")], [("гитхаб", "GitHub")]))


def test_vocabulary_edits_and_tombstones() -> None:
    from .vocabulary import DraftEntry, Origin, VocabularyStore

    path = _temp_db()
    store = VocabularyStore(path)
    try:
        store.upsert("гитхаб", "GitHub", Origin.LEARNED)
        store.upsert("дебиан", "Debian")
        store.upsert("зип", "ZIP")
        with store._lock:  # pretend these are old, so a rewrite would show
            store._db.execute("UPDATE corrections SET updated_at = '2026-01-01T00:00:00Z';")
            store._db.commit()
        baseline = store.all()
        # Meanwhile the sync changes «зип» on the store.
        store.apply_remote([{"source": "зип", "replacement": "ZIP archive", "origin": "manual",
                             "asr_hint": None, "deleted": False,
                             "updated_at": "2026-05-01T00:00:00Z"}])
        edited = [DraftEntry(r.source, r.replacement, r.asr_hint, r.origin)
                  for r in baseline if r.source != "дебиан"]
        edited.append(DraftEntry("кубер", "Kubernetes"))
        store.apply_edits(baseline, edited)
        after = {r.source: r for r in store.all()}
        _check("edits: the unchanged row keeps its stamp and origin",
               (after["гитхаб"].updated_at, after["гитхаб"].origin),
               ("2026-01-01T00:00:00Z", Origin.LEARNED))
        _check("edits: a row the sync changed meanwhile is not reverted",
               after["зип"].replacement, "ZIP archive")
        _check("edits: a removed row is deleted", "дебиан" in after, False)
        _check("edits: an added row is manual", after["кубер"].origin, Origin.MANUAL)
        _check("edits: the removal left a tombstone",
               [t.key for t in store.tombstones()], ["дебиан"])
        store.upsert("Дебиан", "Debian")
        _check("edits: re-adding the key removes the tombstone", store.tombstones(), [])
        store.delete_source("кубер")
        _check("delete: a tombstone", [t.source for t in store.tombstones()], ["кубер"])
        records, tombs = store.local_changes_since("2026-02-01T00:00:00Z")
        _check("changes since: the edited rows and the tombstone",
               (sorted(r.source for r in records), [t.key for t in tombs]),
               (["Дебиан", "зип"], ["кубер"]))
    finally:
        store.close()
        _remove_db(path)


# -- sync against a local server -----------------------------------------------

def _server_directory() -> Path | None:
    here = Path(__file__).resolve().parent.parent  # windows/
    candidate = here.parent / "server" / "vocab-sync"
    return candidate if (candidate / "app.py").is_file() else None


def _server_python() -> str | None:
    """An interpreter with FastAPI and uvicorn: ``LEXOMORPH_SYNC_TEST_PYTHON``
    or this one."""
    python = paths.env("SYNC_TEST_PYTHON") or sys.executable
    try:
        probe = subprocess.run([python, "-c", "import fastapi, uvicorn"],
                               capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return python if probe.returncode == 0 else None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_vocabulary_sync_server() -> None:
    import urllib.request

    server_dir = _server_directory()
    python = _server_python() if server_dir is not None else None
    if server_dir is None or python is None:
        print("  (skipped test_vocabulary_sync_server: server/vocab-sync or FastAPI not available)")
        return

    from . import vocabulary_sync as vs
    from .settings import Settings
    from .vocabulary import Origin, VocabularyStore

    work = Path(tempfile.mkdtemp(prefix="sd-sync-selftest-"))
    port = _free_port()
    env = dict(os.environ, VOCAB_SYNC_DB=str(work / "server.sqlite"))
    server = subprocess.Popen(
        [python, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port),
         "--app-dir", str(server_dir), "--log-level", "warning"],
        cwd=str(work), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    stores: list = []
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(150):
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                        url + "/healthz", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            _check("sync: the local server starts", server.poll(), None)
            return

        def device(name):
            store = VocabularyStore(str(work / f"{name}.sqlite"))
            stores.append(store)
            settings = Settings(path=work / f"{name}.json")
            settings.update_runtime({"vocabulary_sync_server_url": url})
            tokens = vs.MemoryTokenStore()
            return store, settings, tokens, vs.VocabularySync(store, settings, tokens=tokens)

        a_store, a_settings, a_tokens, a = device("a")
        b_store, b_settings, b_tokens, b = device("b")

        a_store.upsert("гитхаб", "GitHub")
        b_store.upsert("дебиан", "Debian", Origin.LEARNED)   # B's own, before sign-in
        _check("sync: a short password is refused",
               _sync_error(lambda: a.sign_in("user@example.com", "short")), vs.ERROR_INVALID)
        _check("sync: the first sign-in creates the account",
               a.sign_in("User@Example.com", "correct horse"), True)
        _check("sync: the server's e-mail is kept", a_settings.vocabulary_sync_email,
               "user@example.com")
        _check("sync: a wrong password", _sync_error(lambda: b.sign_in("user@example.com", "wrong pass")),
               vs.ERROR_WRONG_PASSWORD)
        _check("sync: the second machine joins", b.sign_in("user@example.com", "correct horse"), False)
        _check("sync: the first sync merged both dictionaries (B)",
               sorted(r.source for r in b_store.all()), ["гитхаб", "дебиан"])
        a.sync_now()
        _check("sync: the first sync merged both dictionaries (A)",
               sorted(r.source for r in a_store.all()), ["гитхаб", "дебиан"])
        _check("sync: the origin travels", a_store.find("дебиан").origin, Origin.LEARNED)
        _check("sync: status after a pass", (a.status.state, a.status.signed_in), (vs.STATE_OK, True))

        # An add on A appears on B, with its hint.
        record = a_store.upsert("кубер", "Kubernetes")
        a_store.set_asr_hint(record.id, False)
        a.sync_now()
        b.sync_now()
        added = b_store.find("кубер")
        _check("sync: an add on A appears on B",
               (added.replacement, added.asr_hint) if added else None, ("Kubernetes", False))
        _check("sync: a remote entry keeps its stamp",
               added.updated_at if added else None, a_store.find("кубер").updated_at)

        # A delete on B removes the entry on A.
        b_store.delete_source("дебиан")
        b.sync_now()
        a.sync_now()
        _check("sync: a delete on B removes it on A", a_store.find("дебиан"), None)
        _check("sync: and records the tombstone on A",
               "дебиан" in {t.key for t in a_store.tombstones()}, True)

        # A conflict: the newer updated_at wins on both machines.
        for store, replacement, stamp in ((a_store, "GitHub Enterprise", "2030-01-01T00:00:00Z"),
                                          (b_store, "GitHub.com", "2031-01-01T00:00:00Z")):
            with store._lock:
                store._db.execute("UPDATE corrections SET replacement = ?, updated_at = ? "
                                  "WHERE source = 'гитхаб';", (replacement, stamp))
                store._db.commit()
        a.sync_now()
        b.sync_now()
        a.sync_now()
        _check("sync: the newer edit wins on both",
               (a_store.find("гитхаб").replacement, b_store.find("гитхаб").replacement),
               ("GitHub.com", "GitHub.com"))

        # The hint travels on its own change too.
        surname = b_store.upsert("нечепуренко", "Ничипуренко", Origin.LEARNED)
        b.sync_now()
        a.sync_now()
        a_store.set_asr_hint(a_store.find("нечепуренко").id, True)
        with a_store._lock:  # one-second stamps: make the hint change strictly newer
            a_store._db.execute("UPDATE corrections SET updated_at = '2032-01-01T00:00:00Z' "
                                "WHERE source = 'нечепуренко';")
            a_store._db.commit()
        a.sync_now()
        b.sync_now()
        _check("sync: asr_hint travels with the entry", b_store.get(surname.id).asr_hint, True)
        _check("sync: and makes it a hotword there",
               "Ничипуренко" in b_store.asr_hotword_phrases(), True)

        # The user's own terms travel through the real server.
        term = a_store.add_hotword_phrase("Дунималова Анаида Георгиевна")
        a.sync_now()
        b.sync_now()
        _check("sync: A's term reaches B",
               [r.phrase for r in b_store.hotword_phrases()], ["Дунималова Анаида Георгиевна"])
        _check("sync: a synced term reaches the ASR list",
               "Дунималова Анаида Георгиевна" in b_store.asr_hotword_phrases(), True)
        _check("sync: a synced term creates no replacement rule",
               any("Дунималова" in r.replacement for r in b_store.all()), False)
        a_store.set_hotword_phrase_enabled(term.id, False)
        a.sync_now()
        b.sync_now()
        _check("sync: disabling a term travels", b_store.hotword_phrases()[0].enabled, False)
        _check("sync: a disabled term leaves the ASR list",
               "Дунималова Анаида Георгиевна" in b_store.asr_hotword_phrases(), False)
        b_store.delete_hotword_phrase(b_store.hotword_phrases()[0].id)
        b.sync_now()
        a.sync_now()
        _check("sync: deleting a term travels", a_store.hotword_phrases(), [])
        _check("sync: and leaves a tombstone",
               [t.key for t in a_store.hotword_tombstones()], ["дунималова анаида георгиевна"])
        readded = a_store.add_hotword_phrase("Дунималова Анаида Георгиевна")
        a.sync_now()
        b.sync_now()
        _check("sync: a re-added term comes back", [r.phrase for r in b_store.hotword_phrases()],
               [readded.phrase])

        # A pass with nothing new changes nothing.
        _check("sync: an idle pass applies nothing", (a.sync_now(), b.sync_now()), (0, 0))

        # 401: the token is dropped and the user is asked to sign in again.
        b_tokens.save("not-a-real-token")
        _check("sync: a refused token raises unauthorized", _sync_error(b.sync_now),
               vs.ERROR_UNAUTHORIZED)
        _check("sync: and is dropped", b_tokens.load(), None)
        _check("sync: the status asks to sign in again", b.status.state, vs.STATE_REAUTH)
        _check("sync: signed out after a 401", b.signed_in, False)

        a.sign_out()
        _check("sync: signing out drops the token", (a_tokens.load(), a.signed_in), (None, False))
        _check("sync: signing out resets the cursors",
               (a_settings.vocabulary_sync_last_server_revision,
                a_settings.vocabulary_sync_last_pushed_local_stamp), (0, ""))
    finally:
        for store in stores:
            store.close()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def test_custom_hotwords_store() -> None:
    """user-hotword-vocabulary spec: the same answers as the macOS suites
    ``asr-hotwords`` and ``hotword-sync``."""
    from . import asr_hotwords
    from .vocabulary import DuplicateHotwordPhrase, InvalidHotwordPhrase, Origin, VocabularyStore

    work = Path(tempfile.mkdtemp(prefix="sd-hotwords-selftest-"))
    path = work / "corrections.sqlite"
    # A database from before this table: the store creates it on open.
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                      "source TEXT NOT NULL COLLATE NOCASE, replacement TEXT NOT NULL, "
                      "origin TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL, "
                      "updated_at TEXT NOT NULL);")
    old.commit()
    old.close()
    store = VocabularyStore(str(path))
    events = []
    store.add_listener(events.append)
    try:
        _check("terms: an old database opens empty", store.hotword_phrases(), [])
        _check("terms: nothing to send means the unbiased path", store.asr_hotword_phrases(), [])

        record = store.add_hotword_phrase("  Дунималова Анаида Георгиевна ")
        _check("terms: edges trimmed", record.phrase, "Дунималова Анаида Георгиевна")
        _check("terms: an add is a local change", events, ["local"])
        _check("terms: the phrase reaches the ASR list unchanged",
               store.asr_hotword_phrases(), ["Дунималова Анаида Георгиевна"])
        _check("terms: no replacement rule", store.count(), 0)
        for bad in ("", "  ", "...", "один два три четыре пять"):
            try:
                store.add_hotword_phrase(bad)
                _check(f"terms: {bad!r} refused", False, True)
            except InvalidHotwordPhrase:
                pass
        try:
            store.add_hotword_phrase("дунималова   анаида ГЕОРГИЕВНА")
            _check("terms: a case and spacing variant is a duplicate", False, True)
        except DuplicateHotwordPhrase:
            pass

        store.set_hotword_phrase_enabled(record.id, False)
        _check("terms: a disabled phrase is kept", len(store.hotword_phrases()), 1)
        _check("terms: and leaves the ASR list", store.asr_hotword_phrases(), [])
        _check("terms: a toggle moves the stamp",
               store.hotword_phrases()[0].updated_at > record.updated_at, True)
        store.set_hotword_phrase_enabled(record.id, True)

        renamed = store.update_hotword_phrase(record.id, "Дунималова Анаида", True)
        _check("terms: a rename tombstones the old key",
               [t.key for t in store.hotword_tombstones()], ["дунималова анаида георгиевна"])
        _check("terms: a rename keeps the row", renamed.id, record.id)

        # Priority and dedup against corrections; custom spelling wins.
        store.upsert("сервак", "Дунималова анаида", Origin.MANUAL)
        store.upsert("гитхаб", "GitHub", Origin.MANUAL)
        _check("terms: the user's spelling wins, then corrections",
               store.asr_hotword_phrases(), ["Дунималова Анаида", "GitHub"])
        many = [type("R", (), {"phrase": f"термин {i}", "enabled": True})() for i in range(1200)]
        capped = asr_hotwords.combined_phrases(store.all(), many)
        _check("terms: at most 1000 phrases", len(capped), asr_hotwords.MAX_PHRASES)
        _check("terms: the cap evicts learned data first", capped[-1], "термин 999")

        # Import.
        events.clear()
        added, invalid = store.import_hotword_phrases(
            "\ufeff# комментарий\r\nАрбитражный суд\r\n\r\nарбитражный СУД\r\n"
            "один два три четыре пять\r\nДунималова Анаида\r\nЕФРСБ\r\n")
        _check("terms: import counts", (added, invalid), (2, 1))
        _check("terms: import notifies once", events, ["local"])
        _check("terms: imported in file order",
               [r.phrase for r in store.hotword_phrases()][-2:], ["Арбитражный суд", "ЕФРСБ"])

        # Delete, then remote changes.
        events.clear()
        efrsb = store.hotword_phrases()[-1]
        store.delete_hotword_phrase(efrsb.id)
        _check("terms: a delete leaves a tombstone",
               "ефрсб" in {t.key for t in store.hotword_tombstones()}, True)
        stale = {"phrase": "ЕФРСБ", "enabled": True, "deleted": False, "updated_at": "2020-01-01T00:00:00Z"}
        _check("terms: a tombstone blocks an older live entry", store.apply_remote_hotwords([stale]), 0)
        fresh = dict(stale, updated_at="2099-01-01T00:00:00Z", enabled=False)
        events.clear()
        _check("terms: a newer entry beats the tombstone", store.apply_remote_hotwords([fresh]), 1)
        _check("terms: a remote change is not a local one", events, ["sync"])
        row = next(r for r in store.hotword_phrases() if r.phrase == "ЕФРСБ")
        _check("terms: the remote stamp and state are kept",
               (row.updated_at, row.enabled), ("2099-01-01T00:00:00Z", False))
        _check("terms: a tie keeps the local copy", store.apply_remote_hotwords([fresh]), 0)
        gone = dict(fresh, deleted=True, updated_at="2099-02-01T00:00:00Z")
        _check("terms: a newer delete removes it", store.apply_remote_hotwords([gone]), 1)
        _check("terms: and is gone",
               "ЕФРСБ" in [r.phrase for r in store.hotword_phrases()], False)
        _check("terms: a malformed remote entry is skipped",
               store.apply_remote_hotwords([{"phrase": "...", "updated_at": "2099-03-01T00:00:00Z"}, "x"]), 0)

        changes, tombstones = store.hotword_changes_since("2099-01-15T00:00:00Z")
        _check("terms: changes since a stamp", (changes, [t.key for t in tombstones]), ([], ["ефрсб"]))
    finally:
        store.close()


def _FakeController(settings, saved: list):
    """The slice of the app controller the settings window touches."""
    from PySide6.QtCore import QObject, Signal

    from .rewrite_styles import StyleStore

    class Listener:
        paused = False

        def reset_state(self) -> None:
            pass

    class Controller(QObject):
        custom_styles_changed = Signal(str)

        def __init__(self) -> None:
            super().__init__()
            self.styles = StyleStore(settings)
            self.styles.add_listener(self.custom_styles_changed.emit)
            self.listener = Listener()

        def apply_settings(self) -> None:
            saved.append(True)

        def reload_model(self) -> None:
            saved.append(True)

    return Controller()


def test_custom_styles_window() -> None:
    """The mode list, the editor dialog and the stats caption, by their widgets."""
    from PySide6.QtWidgets import QApplication

    from .hotkeys import HotkeyChoice
    from .settings import Settings
    from .ui.settings_window import SettingsWindow
    from .ui.stats import StatsPanel
    from .ui.style_editor import StyleEditorDialog
    from .vocabulary import VocabularyStore

    app = QApplication.instance() or QApplication([])
    work = Path(tempfile.mkdtemp(prefix="sd-styles-ui-"))
    store = VocabularyStore(str(work / "d.sqlite"))
    settings = Settings(path=work / "s.json")
    controller = _FakeController(settings, [])
    window = SettingsWindow(settings, store, controller)
    combo = window._rewrite_style
    try:
        _check("modes UI: the built-ins are listed",
               [combo.itemData(i) for i in range(combo.count())],
               ["polish", "structured_task", "official"])
        dialog = StyleEditorDialog(controller.styles, settings, controller, None, window)
        dialog._name.setText("Мой режим")
        dialog._instruction.setPlainText("Сделай коротко.")
        dialog._pick("#bf5af2")
        dialog._hotkey = HotkeyChoice(0x31, 0x3)
        dialog._accept()
        created = dialog.result_style
        _check("modes UI: the dialog creates the mode",
               (created.name, created.color, created.hotkey, created.id.startswith("c-")),
               ("Мой режим", "#BF5AF2", HotkeyChoice(0x31, 0x3), True))
        app.processEvents()
        _check("modes UI: the drop-down lists built-ins + custom",
               [combo.itemData(i) for i in range(combo.count())][-2:], ["official", created.id])
        from PySide6.QtWidgets import QLabel, QPushButton

        shown = [w.text() for w in window._custom_styles.findChildren(QLabel)]
        _check("modes UI: the block shows the mode and its hotkey",
               ("Мой режим" in shown, "Ctrl + Alt + 1" in shown or any("1" in t for t in shown)),
               (True, True))
        _check("modes UI: Edit, Delete and New buttons are there",
               sorted(w.text() for w in window._custom_styles.findChildren(QPushButton)),
               sorted(["＋ Новый режим", "Изменить", "Удалить"]))

        combo.setCurrentIndex(combo.findData(created.id))
        _check("modes UI: choosing a custom mode fills the draft",
               window._draft["rewrite_custom_style_id_v1"], created.id)
        combo.setCurrentIndex(combo.findData("official"))
        _check("modes UI: choosing a built-in clears it",
               (window._draft["rewrite_custom_style_id_v1"], window._draft["rewrite_style_v1"]),
               ("", "official"))

        # A clash with another shortcut is explained, nothing is saved.
        other = StyleEditorDialog(controller.styles, settings, controller, None, window)
        other._name.setText("Второй")
        other._instruction.setPlainText("x")
        other._hotkey = HotkeyChoice(0x31, 0x3)
        other._accept()
        _check("modes UI: a taken hotkey is refused",
               (other.result_style, other._error.isHidden(), len(controller.styles.all())),
               (None, False, 1))
        other._hotkey = settings.rewrite_style_hotkey
        other._accept()
        _check("modes UI: a built-in shortcut is refused too",
               (other.result_style, len(controller.styles.all())), (None, 1))
        other._name.setText("")
        other._hotkey = None
        other._accept()
        _check("modes UI: an empty name is refused", len(controller.styles.all()), 1)

        # Deleting the selected mode (here or from the sync) falls back to polish.
        combo.setCurrentIndex(combo.findData(created.id))
        controller.styles.delete(created.id)
        app.processEvents()
        _check("modes UI: the deleted mode leaves the drop-down",
               combo.findData(created.id), -1)
        _check("modes UI: ...and the selection falls back to polish",
               (combo.currentData(), window._draft["rewrite_custom_style_id_v1"],
                window._draft["rewrite_style_v1"]), ("polish", "", "polish"))
        controller.styles.apply_remote([{
            "id": "c-remote", "name": "С сервера", "color": "#00C7BE", "instruction": "i",
            "deleted": False, "updated_at": "2099-01-01T00:00:00Z"}])
        app.processEvents()
        _check("modes UI: a synced mode appears in the open window",
               combo.findData("c-remote") >= 0, True)

        # The statistics say which scope they show.
        from . import history, paths

        saved = (paths.USAGE_FILE, paths.ensure_directories)
        try:
            usage = _usage_stats(work, "ui")
            on = [False]
            panel = StatsPanel(usage, lambda: on[0])
            panel.show()
            _check("stats UI: no caption without sync", panel._scope.isVisible(), False)
            on[0] = True
            panel.refresh()
            _check("stats UI: the all-devices caption with sync", panel._scope.isVisible(), True)
            panel.close()
        finally:
            paths.USAGE_FILE, paths.ensure_directories = saved
    finally:
        window.hide()
        window.deleteLater()
        store.close()


def test_custom_hotwords_window() -> None:
    """The «ASR-термины» section of the real settings window, by its widgets."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from .settings import Settings
    from .ui.settings_window import SettingsWindow
    from .vocabulary import VocabularyStore

    app = QApplication.instance() or QApplication([])
    work = Path(tempfile.mkdtemp(prefix="sd-hotwords-ui-"))
    store = VocabularyStore(str(work / "d.sqlite"))
    saved: list[bool] = []

    settings = Settings(path=work / "s.json")
    controller = _FakeController(settings, saved)
    window = SettingsWindow(settings, store, controller)
    messages: list[str] = []
    window._warn = messages.append
    field, listing = window._custom_hotword_field, window._custom_hotwords_list
    try:
        window.show()
        window._tabs.setCurrentIndex(3)
        app.processEvents()
        field.setFocus()
        field.setText("Дунималова Анаида Георгиевна")
        QTest.keyClick(field, Qt.Key.Key_Return)
        app.processEvents()
        _check("terms UI: Return adds the phrase", [r.phrase for r in store.hotword_phrases()],
               ["Дунималова Анаида Георгиевна"])
        _check("terms UI: Return does not save or close the settings",
               (saved, window.isVisible()), ([], True))
        _check("terms UI: the field is cleared", field.text(), "")
        field.setText("ДУНИМАЛОВА анаида георгиевна")
        window._add_custom_hotword()
        _check("terms UI: a duplicate is explained and kept in the field",
               (len(messages), field.text()), (1, "ДУНИМАЛОВА анаида георгиевна"))
        field.clear()
        source = work / "terms.txt"
        source.write_bytes("\ufeff# суд\r\nАрбитражный суд города Москвы\r\nЕФРСБ\r\n".encode("utf-8"))
        window._import_custom_hotwords_file(str(source))
        _check("terms UI: import fills the list", listing.count(), 3)
        broken = work / "utf16.txt"
        broken.write_bytes("Тест".encode("utf-16"))
        window._import_custom_hotwords_file(str(broken))
        _check("terms UI: a non-UTF-8 file is refused", listing.count(), 3)
        listing.item(1).setCheckState(Qt.CheckState.Unchecked)
        _check("terms UI: the checkbox reaches the ASR list",
               "Арбитражный суд города Москвы" in store.asr_hotword_phrases(), False)
        listing.setCurrentRow(2)
        window._remove_custom_hotword()
        _check("terms UI: delete", [listing.item(i).text() for i in range(listing.count())],
               ["Дунималова Анаида Георгиевна", "Арбитражный суд города Москвы"])
        store.apply_remote_hotwords([{"phrase": "С сервера", "enabled": True, "deleted": False,
                                      "updated_at": "2099-01-01T00:00:00Z"}])
        window._on_vocabulary_changed("sync")
        _check("terms UI: a synced term appears", listing.item(2).text(), "С сервера")
        _check("terms UI: a reload keeps the unchecked state",
               listing.item(1).checkState(), Qt.CheckState.Unchecked)
    finally:
        window.hide()
        window.deleteLater()
        store.close()


def _sync_error(call) -> str:
    from .vocabulary_sync import SyncError

    try:
        call()
    except SyncError as exc:
        return exc.kind
    return "no error"


def test_sync_settings_and_token() -> None:
    from . import vocabulary_sync as vs
    from .settings import Settings

    work = Path(tempfile.mkdtemp(prefix="sd-sync-token-"))
    settings = Settings(path=work / "Settings.json")
    _check("sync: off by default", settings.vocabulary_sync_enabled, False)
    _check("sync: the default server", settings.vocabulary_sync_server_url,
           "https://superdictate.bykovlegal.ru")
    settings.update_runtime({"vocabulary_sync_enabled": True,
                             "vocabulary_sync_last_server_revision": 42})
    # The settings window's draft is a snapshot from before the sign-in.
    settings.apply({"vocabulary_sync_enabled": False,
                    "vocabulary_sync_last_server_revision": 0, "play_feedback_sounds": False})
    _check("sync: a stale settings draft does not undo the sign-in",
           (settings.vocabulary_sync_enabled, settings.vocabulary_sync_last_server_revision,
            settings.play_feedback_sounds), (True, 42, False))

    path = work / "VocabularySync.token"
    tokens = vs.DpapiTokenStore(path)
    _check("token: none at first", tokens.load(), None)
    tokens.save("secret-token-value")
    _check("token: round-trips", vs.DpapiTokenStore(path).load(), "secret-token-value")
    if sys.platform == "win32":
        _check("token: not stored in the clear", b"secret-token-value" in path.read_bytes(), False)
    tokens.clear()
    _check("token: cleared", (tokens.load(), path.exists()), (None, False))



# -- custom rewrite modes and usage statistics (modes-and-usage-sync spec) ----

def _style_settings(work: Path, name: str = "s"):
    from .settings import Settings

    return Settings(path=work / f"{name}.json")


def test_custom_styles_store() -> None:
    """Create / edit / delete, the saved shape, the fallback, the draft rule."""
    from .hotkeys import HotkeyChoice
    from .rewrite_styles import MAX_INSTRUCTION, MAX_NAME, StyleStore, valid_id

    work = Path(tempfile.mkdtemp(prefix="sd-styles-selftest-"))
    settings = _style_settings(work)
    store = StyleStore(settings)
    kinds: list[str] = []
    store.add_listener(kinds.append)

    key = HotkeyChoice(0x31, 0x2 | 0x1)  # Ctrl+Alt+1 (modifier values do not matter here)
    first = store.create("  Деловой   тон ", "Перепиши строго.", "#ff8800", key)
    _check("styles: id is c-<uuid>", (valid_id(first.id), first.id.startswith("c-"), len(first.id)),
           (True, True, 38))
    _check("styles: name is trimmed and squeezed", first.name, "Деловой тон")
    _check("styles: colour is normalised", first.color, "#FF8800")
    _check("styles: updated_at is ISO UTC",
           bool(__import__("re").match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", first.updated_at)), True)
    _check("styles: a local create notifies as local", kinds, ["local"])

    for bad, which in (("", "name"), ("x" * (MAX_NAME + 1), "name")):
        try:
            store.create(bad, "ok")
            outcome = "accepted"
        except ValueError as exc:
            outcome = str(exc)
        _check(f"styles: name {bad[:5]!r} refused", outcome, which)
    for bad in ("", "   ", "y" * (MAX_INSTRUCTION + 1)):
        try:
            store.create("ok", bad)
            outcome = "accepted"
        except ValueError as exc:
            outcome = str(exc)
        _check("styles: instruction refused", outcome, "instruction")
    _check("styles: a refused create leaves the list alone", len(store.all()), 1)

    # Persisted, hotkey included, and visible to the rewrite pipeline.
    reloaded = StyleStore(_style_settings(work))
    _check("styles: the list survives a restart",
           [(s.name, s.hotkey) for s in reloaded.all()], [("Деловой тон", key)])
    config = settings.rewrite_config()
    _check("styles: the pipeline sees the mode",
           config.custom_styles[first.id]["instruction"], "Перепиши строго.")

    # Unlimited count.
    many = [store.create(f"m{i}", "i").id for i in range(60)]
    _check("styles: no cap on the number", len(store.all()), 61)
    for style_id in many:
        store.delete(style_id)

    # Edit keeps the id, moves updated_at forward even within a second.
    before = first.updated_at
    edited = store.update(first.id, "Деловой 2", "Новая инструкция", "#34C759", None)
    _check("styles: edit keeps the id", edited.id, first.id)
    _check("styles: edit moves updated_at forward", edited.updated_at > before, True)
    _check("styles: edit can clear the hotkey", store.get(first.id).hotkey, None)
    same = store.update(first.id, "Деловой 2", "Новая инструкция", "#34C759", key)
    _check("styles: a hotkey-only edit is local and keeps updated_at",
           same.updated_at, edited.updated_at)
    _check("styles: hotkey clash is found",
           store.hotkey_taken(key).id, first.id)
    _check("styles: ...but not for the owner", store.hotkey_taken(key, except_id=first.id), None)

    # The selected mode is local to the device, and deleting it falls back to polish.
    settings.update_runtime({"rewrite_custom_style_id_v1": first.id, "rewrite_style_v1": "official"})
    _check("styles: selected", settings.rewrite_config().custom_style_id, first.id)
    _check("styles: delete reports success", store.delete(first.id), True)
    _check("styles: delete of an unknown id", store.delete(first.id), False)
    config = settings.rewrite_config()
    _check("styles: deleting the selected mode falls back to polish",
           (config.custom_style_id, config.style.value), ("", "polish"))
    _check("styles: the delete leaves a tombstone",
           [t.id for t in store.tombstones()].count(first.id), 1)
    _check("styles: tombstone is after the last edit",
           store.tombstones()[-1].deleted_at > edited.updated_at, True)
    _check("styles: the list is empty again", store.all(), [])

    # A dangling selection (deleted elsewhere) is no selection.
    settings.update_runtime({"rewrite_custom_style_id_v1": "c-gone"})
    _check("styles: a dangling selection is ignored",
           settings.rewrite_config().custom_style_id, "")

    # The settings window's stale draft must not roll the list back.
    keep = store.create("Keep", "k")
    stale = settings.snapshot()
    stale["rewrite_custom_styles_v1"] = []
    stale["rewrite_custom_style_tombstones_v1"] = [{"id": "c-x", "deleted_at": "2030-01-01T00:00:00Z"}]
    settings.apply(stale)
    _check("styles: Settings.apply() never rolls the list back",
           [s.id for s in store.all()], [keep.id])


def test_custom_styles_sync_merge() -> None:
    """Last write wins, tombstones, local fields kept, applying is silent."""
    from .hotkeys import HotkeyChoice
    from .rewrite_styles import StyleStore

    work = Path(tempfile.mkdtemp(prefix="sd-styles-merge-"))
    settings = _style_settings(work)
    store = StyleStore(settings)
    kinds: list[str] = []
    store.add_listener(kinds.append)

    def row(style_id, name="N", stamp="2026-11-10T12:00:00Z", deleted=False,
            color="#112233", instruction="I"):
        return {"id": style_id, "name": name, "color": color, "instruction": instruction,
                "deleted": deleted, "updated_at": stamp}

    _check("merge: a new style is applied", store.apply_remote([row("c-1", "Один")]), 1)
    _check("merge: applying does not look like a local change", kinds, ["sync"])
    _check("merge: it has no hotkey of its own", store.get("c-1").hotkey, None)
    _check("merge: wire fields land", (store.get("c-1").color, store.get("c-1").updated_at),
           ("#112233", "2026-11-10T12:00:00Z"))

    key = HotkeyChoice(0x32, 0x3)
    store.set_hotkey("c-1", key)
    kinds.clear()
    _check("merge: an older copy is ignored",
           store.apply_remote([row("c-1", "Старый", "2026-11-10T11:00:00Z")]), 0)
    _check("merge: nothing notified", kinds, [])
    _check("merge: a newer copy wins", store.apply_remote([row("c-1", "Новый", "2026-11-10T13:00:00Z")]), 1)
    _check("merge: ...and the local hotkey survives it", store.get("c-1").hotkey, key)
    _check("merge: the echo of an identical row changes nothing",
           store.apply_remote([row("c-1", "Новый", "2026-11-10T13:00:00Z")]), 0)
    _check("merge: a tie goes to the server",
           store.apply_remote([row("c-1", "Сервер", "2026-11-10T13:00:00Z")]), 1)
    _check("merge: tie result", store.get("c-1").name, "Сервер")

    # Malformed rows are skipped, not fatal.
    junk = [row("x-1"), row("c-2", name=""), row("c-3", name="n" * 41), row("c-4", color="red"),
            row("c-5", instruction="i" * 4001), {"id": "c-6"}, "nope", row("c-" + "9" * 70)]
    _check("merge: malformed rows are ignored", store.apply_remote(junk), 0)
    _check("merge: and add nothing", [s.id for s in store.all()], ["c-1"])

    # A remote delete of the selected mode: tombstone, fallback to polish.
    settings.update_runtime({"rewrite_custom_style_id_v1": "c-1", "rewrite_style_v1": "official"})
    kinds.clear()
    _check("merge: an older delete does not remove a newer edit",
           store.apply_remote([row("c-1", deleted=True, stamp="2026-11-10T12:30:00Z")]), 0)
    _check("merge: a newer delete removes it",
           store.apply_remote([row("c-1", deleted=True, stamp="2026-11-10T14:00:00Z")]), 1)
    config = settings.rewrite_config()
    _check("merge: the selected mode fell back to polish",
           (config.custom_style_id, config.style.value), ("", "polish"))
    _check("merge: removed", store.get("c-1"), None)
    _check("merge: remembered as a tombstone",
           [(t.id, t.deleted_at) for t in store.tombstones()], [("c-1", "2026-11-10T14:00:00Z")])
    _check("merge: a delete is not a local change", kinds, ["sync"])

    # The tombstone beats an older copy, loses to a newer one.
    _check("merge: an older live copy stays dead",
           store.apply_remote([row("c-1", stamp="2026-11-10T13:59:00Z")]), 0)
    _check("merge: a newer live copy resurrects it",
           store.apply_remote([row("c-1", "Снова", "2026-11-10T15:00:00Z")]), 1)
    _check("merge: tombstone cleared", store.tombstones(), [])

    # A delete of something never seen here is still remembered.
    store.apply_remote([row("c-77", deleted=True, stamp="2026-11-10T16:00:00Z")])
    _check("merge: a delete of an unknown id is remembered",
           [t.id for t in store.tombstones()], ["c-77"])

    # What goes out: live rows and tombstones, filtered by the stamp.
    local = store.create("Локальный", "L")
    wire = store.changes_since("")
    _check("push: live + deleted rows",
           sorted(("local" if r["id"] == local.id else r["id"], r["deleted"]) for r in wire),
           sorted([("local", False), ("c-1", False), ("c-77", True)]))
    _check("push: the rows carry no hotkey",
           any("hotkey" in r for r in wire), False)
    _check("push: only changes since the stamp",
           [r["id"] for r in store.changes_since("2026-11-10T15:30:00Z")
            if r["id"] != local.id], ["c-77"])
    _check("push: the stamp second itself is included",
           "c-77" in [r["id"] for r in store.changes_since("2026-11-10T16:00:00Z")], True)


def _usage_stats(work: Path, name: str):
    """A UsageStats on private files (the module paths are global)."""
    from . import history, paths

    paths.USAGE_FILE = work / f"{name}-usage.json"
    paths.ensure_directories = lambda: None
    return history.UsageStats(sync_path=work / f"{name}-sync.json")


def test_usage_stats_sync() -> None:
    """Own row = absolute values; others kept apart; the sum; no double count."""
    from datetime import datetime

    from . import history, paths

    saved = (paths.USAGE_FILE, paths.ensure_directories)
    work = Path(tempfile.mkdtemp(prefix="sd-usage-selftest-"))
    try:
        usage = _usage_stats(work, "a")
        day = datetime.now().date().isoformat()
        usage.record("привет мир", 2.0)
        usage.record("ещё одна фраза тут", 3.0)
        rows = usage.own_rows_since("")
        device = usage.device_id()
        _check("usage: the device id is a uuid, kept", (len(device), usage.device_id()), (36, device))
        _check("usage: own row is absolute for the day",
               [(r["day"], r["device"], r["dictations"], r["characters"], r["words"], r["audio_seconds"])
                for r in rows],
               [(day, device, 2, 28, 6, 5.0)])
        _check("usage: asr_seconds is sent as 0", rows[0]["asr_seconds"], 0.0)
        before = usage.own_rows_since("")
        _check("usage: sending again is the same absolute row", usage.own_rows_since("") == before, True)

        # The echo of our own row never doubles the count.
        _check("usage: the server's echo of our own row is ignored", usage.apply_remote(rows), 0)
        _check("usage: totals unchanged", usage.totals().dictations, 2)

        other = [{"day": day, "device": "other-device", "dictations": 10, "characters": 300,
                  "words": 50, "audio_seconds": 100.0, "asr_seconds": 4.0,
                  "updated_at": "2026-11-10T12:00:00Z"},
                 {"day": "2026-01-01", "device": "other-device", "dictations": 4, "characters": 80,
                  "words": 0, "audio_seconds": 20.0, "asr_seconds": 0.0,
                  "updated_at": "2026-01-01T09:00:00Z"}]
        _check("usage: another device's rows are kept", usage.apply_remote(other), 2)
        _check("usage: the same rows again change nothing", usage.apply_remote(other), 0)
        _check("usage: the sum over devices (today)",
               (usage.today().dictations, usage.today().characters, usage.today().words,
                usage.today().audio_seconds), (12, 328, 56, 105.0))
        _check("usage: the sum over devices (all time)",
               (usage.totals().dictations, usage.totals().audio_seconds), (16, 125.0))
        _check("usage: days are merged, not duplicated",
               sorted(d.day for d in usage.all_days()), sorted({day, "2026-01-01"}))
        _check("usage: the other device's row is not sent back",
               [r["device"] for r in usage.own_rows_since("")], [device])

        # An older row from that device loses; a newer one replaces (not adds).
        usage.apply_remote([{**other[0], "dictations": 1, "updated_at": "2026-11-10T11:00:00Z"}])
        _check("usage: an older row is ignored", usage.today().dictations, 12)
        usage.apply_remote([{**other[0], "dictations": 11, "updated_at": "2026-11-10T13:00:00Z"}])
        _check("usage: a newer row replaces the old one", usage.today().dictations, 13)

        # It persists, apart from the local counter.
        again = history.UsageStats(sync_path=work / "a-sync.json")
        _check("usage: remote rows and device id survive a restart",
               (again.device_id(), again.totals().dictations), (device, 17))
        local_file = json.loads((work / "a-usage.json").read_text(encoding="utf-8"))
        _check("usage: the local file holds only this device's days",
               sum(item["dictations"] for item in local_file), 2)

        # Only days changed since the cursor go out.
        _check("usage: nothing newer than the cursor goes out",
               usage.own_rows_since("2999-01-01T00:00:00Z"), [])

        # Signing out / another account drops the other devices from the sum.
        usage.forget_remote()
        _check("usage: forgetting the other devices", (usage.has_remote(), usage.totals().dictations), (False, 2))

        # Days counted before the sync existed become rows of this device.
        (work / "old-usage.json").write_text(json.dumps(
            [{"day": "2025-05-05", "dictations": 7, "audio_seconds": 70.0,
              "characters": 700, "words": 70}]), encoding="utf-8")
        paths.USAGE_FILE = work / "old-usage.json"
        legacy = history.UsageStats(sync_path=work / "old-sync.json")
        rows = legacy.own_rows_since("")
        _check("usage: history before the sync is sent too",
               [(r["day"], r["dictations"], r["updated_at"]) for r in rows],
               [("2025-05-05", 7, "2025-05-05T00:00:00Z")])
    finally:
        paths.USAGE_FILE, paths.ensure_directories = saved


class _FakeVocabServer:
    """An in-process stand-in for ``server/vocab-sync``'s ``/v1/vocabulary``.

    ``modern=False`` is a server that predates styles and usage: it ignores
    both request fields and leaves both out of its answer.
    """

    def __init__(self, modern: bool = True) -> None:
        import http.server
        import threading

        self.modern = modern
        self.revision = 0
        self.styles: dict = {}
        self.usage: dict = {}
        self.requests: list[dict] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                since = int(body.get("since", 0))
                if outer.modern:
                    for row in body.get("styles") or []:
                        known = outer.styles.get(row["id"])
                        if known is None or row["updated_at"] > known[0]["updated_at"]:
                            outer.revision += 1
                            outer.styles[row["id"]] = (dict(row), outer.revision)
                    for row in body.get("usage") or []:
                        key = (row["day"], row["device"])
                        known = outer.usage.get(key)
                        if known is None or row["updated_at"] > known[0]["updated_at"]:
                            outer.revision += 1
                            outer.usage[key] = (dict(row), outer.revision)
                answer = {"revision": outer.revision, "entries": [], "hotwords": []}
                if outer.modern:
                    answer["styles"] = [r for r, rev in outer.styles.values() if rev > since]
                    answer["usage"] = [r for r, rev in outer.usage.values() if rev > since]
                data = json.dumps(answer).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def test_styles_and_usage_wire_sync() -> None:
    """Two machines through the wire: styles, tombstones, usage, old servers."""
    from datetime import datetime

    from . import history, paths
    from . import vocabulary_sync as vs
    from .rewrite_styles import StyleStore
    from .vocabulary import VocabularyStore

    saved = (paths.USAGE_FILE, paths.ensure_directories)
    work = Path(tempfile.mkdtemp(prefix="sd-wire-selftest-"))
    server = _FakeVocabServer(modern=False)
    stores: list = []
    try:
        def machine(name):
            settings = _style_settings(work, name)
            settings.update_runtime({"vocabulary_sync_server_url": server.url,
                                     "vocabulary_sync_enabled": True,
                                     "vocabulary_sync_email": "u@example.com"})
            tokens = vs.MemoryTokenStore()
            tokens.save("tok")
            vocab = VocabularyStore(str(work / f"{name}.sqlite"))
            stores.append(vocab)
            styles = StyleStore(settings)
            usage = _usage_stats(work, name)
            client = vs.VocabularySync(vocab, settings, tokens=tokens, styles=styles, usage=usage)
            return settings, styles, usage, client

        a_settings, a_styles, a_usage, a = machine("a")
        b_settings, b_styles, b_usage, b = machine("b")

        made = a_styles.create("Деловой", "Пиши официально.", "#FF8800")
        a_usage.record("раз два три", 4.0)

        # -- an old server: the fields are dropped, the cursor stays ------------
        a.sync_now()
        body = server.requests[-1]
        _check("wire: styles and usage go out in the push",
               (len(body["styles"]), body["styles"][0]["id"], len(body["usage"])),
               (1, made.id, 1))
        _check("wire: an old server's missing fields are noticed (cursor kept)",
               a_settings.vocabulary_sync_last_pushed_local_stamp, "")
        _check("wire: nothing was applied from the old server", b_styles.all(), [])
        b.sync_now()
        _check("wire: the old server leaves the other machine untouched",
               (b_styles.all(), b_usage.has_remote()), ([], False))

        # An empty pass sends neither field, which keeps old clients' bodies the same.
        empty_settings, empty_styles, empty_usage, empty = machine("e")
        empty.sync_now()
        _check("wire: no styles/usage keys when there is nothing to send",
               ("styles" in server.requests[-1], "usage" in server.requests[-1]), (False, False))

        # -- the server is upgraded -----------------------------------------------
        server.modern = True
        a.sync_now()
        _check("wire: after the upgrade the cursor moves",
               a_settings.vocabulary_sync_last_pushed_local_stamp != "", True)
        b.sync_now()
        _check("wire: the mode reaches the other machine",
               [(s.id, s.name, s.color, s.instruction, s.hotkey) for s in b_styles.all()],
               [(made.id, "Деловой", "#FF8800", "Пиши официально.", None)])
        day = datetime.now().date().isoformat()
        b_usage.record("четыре пять", 6.0)
        _check("wire: A's usage arrived as another device's row", b_usage.has_remote(), True)
        _check("wire: B shows the sum (A: 1 + B: 1)", b_usage.today().dictations, 2)
        b.sync_now()
        a.sync_now()
        _check("wire: A shows the same sum", a_usage.today().dictations, 2)
        _check("wire: both agree on audio seconds", (a_usage.today().audio_seconds,
                                                      b_usage.today().audio_seconds), (10.0, 10.0))

        # Repeated passes never inflate the totals.
        for _ in range(3):
            a.sync_now()
            b.sync_now()
        _check("wire: repeated passes do not double count",
               (a_usage.totals().dictations, b_usage.totals().dictations), (2, 2))
        _check("wire: the local counter is untouched by the sum",
               sum(1 for _ in a_usage.own_rows_since("")), 1)

        # -- an edit and a delete travel -------------------------------------------
        a_styles.update(made.id, "Деловой v2", "Ещё строже.", "#34C759", None)
        a.sync_now()
        b.sync_now()
        _check("wire: an edit reaches B", [(s.name, s.color) for s in b_styles.all()],
               [("Деловой v2", "#34C759")])
        b_settings.update_runtime({"rewrite_custom_style_id_v1": made.id,
                                   "rewrite_style_v1": "official"})
        a_styles.delete(made.id)
        a.sync_now()
        b.sync_now()
        config = b_settings.rewrite_config()
        _check("wire: the delete reaches B and the active mode falls back to polish",
               (b_styles.all(), config.custom_style_id, config.style.value), ([], "", "polish"))
        _check("wire: the tombstone is on the server", server.styles[made.id][0]["deleted"], True)

        # Applying the server's rows never schedules another pass.
        due = []
        b.request_sync = lambda delay=0.0: due.append(delay)
        b._thread = object()  # as if running: a local change would now request a pass
        b._styles.apply_remote([{"id": "c-zz", "name": "Z", "color": "#000000", "instruction": "i",
                                 "deleted": False, "updated_at": "2030-01-01T00:00:00Z"}])
        _check("wire: a remote style does not trigger a pass", due, [])
        b_styles.create("local", "i")
        _check("wire: a local style does", due, [vs.DEBOUNCE_SECONDS])
        b._thread = None

        # Sign-out drops the other devices from the totals.
        b.sign_out = vs.VocabularySync.sign_out.__get__(b)
        b._request = lambda *args, **kwargs: {}
        b.sign_out()
        _check("wire: sign-out drops other devices' usage", b_usage.has_remote(), False)
    finally:
        paths.USAGE_FILE, paths.ensure_directories = saved
        server.close()
        for store in stores:
            try:
                store.close()
            except Exception:
                pass


def test_style_hotkeys_state_machine() -> None:
    """A custom mode's chord activates it; it does not disturb the others."""
    from . import hotkeys as hk

    machine = hk.HotkeyStateMachine()
    style_keys = {"c-aaa": hk.HotkeyChoice(0x31, hk.MOD_CTRL | hk.MOD_ALT),
                  "c-bbb": hk.HotkeyChoice(0x32, hk.MOD_CTRL | hk.MOD_ALT)}

    def press(vk, down, modifiers):
        return machine.transition(
            hk._Event(vk=vk, is_down=down, modifiers=modifiers),
            hotkey=hk.DEFAULT_HOTKEY, trigger_mode=hk.TriggerMode.TOGGLE, is_recording=False,
            style_hotkeys=style_keys)

    mods = hk.MOD_CTRL | hk.MOD_ALT
    result = press(0x31, True, mods)
    _check("hotkey: the mode's chord activates it",
           ([a for a in result.actions], result.suppress), ([hk.STYLE_ACTION_PREFIX + "c-aaa"], True))
    press(0x31, False, mods)
    result = press(0x32, True, mods)
    _check("hotkey: the second mode has its own chord",
           result.actions, [hk.STYLE_ACTION_PREFIX + "c-bbb"])
    press(0x32, False, mods)
    _check("hotkey: the built-in cycle chord still works",
           press(hk.VK_S, True, mods).actions, [hk.Action.CYCLE_REWRITE_STYLE])
    press(hk.VK_S, False, mods)
    _check("hotkey: the same key without the modifiers is not the chord",
           press(0x31, True, 0).actions, [])
    style_keys.pop("c-aaa")
    press(0x31, False, 0)
    _check("hotkey: a removed mode's chord is gone",
           press(0x31, True, mods).actions, [])


def test_rewrite_style_activation() -> None:
    """A mode's hotkey (and the cycle) selects it, turns rewrite on, and the
    toast carries the mode's own colour. Driven on the controller's real
    methods with a stand-in ``self``."""
    from types import SimpleNamespace

    from .app import DictationController as Controller
    from .rewrite_styles import StyleStore

    work = Path(tempfile.mkdtemp(prefix="sd-activate-selftest-"))
    settings = _style_settings(work)
    styles = StyleStore(settings)
    toasts: list[tuple[str, str]] = []
    unloads: list[bool] = []
    fake = SimpleNamespace(
        settings=settings, styles=styles,
        postprocessor=SimpleNamespace(cancel_scheduled_unload=lambda: unloads.append(True)),
        state_toast_requested=SimpleNamespace(emit=lambda text, tone: toasts.append((text, tone))),
        settings_applied=SimpleNamespace(emit=lambda: None))
    fake.activate_rewrite_style = lambda style_id: Controller.activate_rewrite_style(fake, style_id)

    mine = styles.create("Протокол", "Оформи как протокол.", "#FF375F")
    settings.update_runtime({"rewrite_enabled_v1": False})
    Controller.activate_rewrite_style(fake, mine.id)
    config = settings.rewrite_config()
    _check("activate: the mode is selected and rewrite is on",
           (config.custom_style_id, settings.rewrite_enabled, unloads), (mine.id, True, [True]))
    _check("activate: the toast carries the mode's colour",
           toasts[-1], ("Режим · Протокол", "#FF375F"))
    Controller.activate_rewrite_style(fake, "structured_task")
    config = settings.rewrite_config()
    _check("activate: a built-in clears the custom selection",
           (config.custom_style_id, config.style.value, toasts[-1][1]), ("", "structured_task", "structured_task"))
    before = len(toasts)
    Controller.activate_rewrite_style(fake, "c-unknown")
    _check("activate: an unknown id does nothing", len(toasts), before)

    # The cycle walks built-ins, then custom modes, then wraps.
    settings.update_runtime({"rewrite_custom_style_id_v1": "", "rewrite_style_v1": "official"})
    Controller.cycle_rewrite_style(fake)
    _check("cycle: after the last built-in comes the first custom mode",
           settings.rewrite_config().custom_style_id, mine.id)
    Controller.cycle_rewrite_style(fake)
    config = settings.rewrite_config()
    _check("cycle: after the last custom mode it wraps to the first built-in",
           (config.custom_style_id, config.style.value), ("", "polish"))



TESTS = [
    test_custom_hotwords_store,
    test_custom_hotwords_window,
    test_custom_styles_window,
    test_asr_hotword_selection,
    test_asr_hint_store,
    test_asr_hotwords_settings_and_ipc,
    test_vocabulary_hygiene_review,
    test_vocabulary_hygiene_cleanup,
    test_vocabulary_learn_reviewed,
    test_learn_hygiene_in_edit_watch,
    test_vocabulary_edits_and_tombstones,
    test_sync_settings_and_token,
    test_vocabulary_sync_server,
    test_custom_styles_store,
    test_custom_styles_sync_merge,
    test_usage_stats_sync,
    test_styles_and_usage_wire_sync,
    test_style_hotkeys_state_machine,
    test_rewrite_style_activation,
]


def run_all() -> bool:
    FAILURES.clear()
    for test in TESTS:
        try:
            test()
        except Exception as exc:
            import traceback

            FAILURES.append(f"{test.__name__} raised {type(exc).__name__}: {exc}\n"
                            + traceback.format_exc())
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} problem(s) in {len(TESTS)} tests\n")
        for failure in FAILURES:
            print(f"  * {failure}")
        return False
    print(f"OK: {len(TESTS)} vocabulary/hotword self-tests passed")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)

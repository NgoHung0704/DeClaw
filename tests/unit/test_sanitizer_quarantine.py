"""Unit tests for the quarantine store + audit sink (DCL-044 / DCL-045)."""

from __future__ import annotations

import hashlib
import io
import json

from declaw.log import configure
from declaw.sanitizer.quarantine import (
    QuarantineEvent,
    QuarantineStore,
    log_audit_sink,
)
from declaw.sanitizer.verdict import SanitizerVerdict


def _unsafe(reason: str = "injection attempt") -> SanitizerVerdict:
    return SanitizerVerdict(verdict="UNSAFE", reason=reason)


def test_add_stores_record_and_returns_id() -> None:
    store = QuarantineStore(audit_sink=lambda e: None)
    qid = store.add(content="payload", source="file:notes.txt", verdict=_unsafe())

    record = store.get(qid)
    assert record.id == qid
    assert record.source == "file:notes.txt"
    assert record.reason == "injection attempt"
    assert record.content == "payload"
    assert len(store) == 1


def test_record_hashes_the_content() -> None:
    store = QuarantineStore(audit_sink=lambda e: None)
    qid = store.add(content="payload", source="s", verdict=_unsafe())

    expected = hashlib.sha256(b"payload").hexdigest()
    assert store.get(qid).content_sha256 == expected


def test_add_emits_audit_event() -> None:
    events: list[QuarantineEvent] = []
    store = QuarantineStore(audit_sink=events.append)

    store.add(content="payload", source="web:http://x", verdict=_unsafe("jailbreak"))

    assert len(events) == 1
    event = events[0]
    assert event.source == "web:http://x"
    assert event.reason == "jailbreak"
    assert event.content_sha256 == hashlib.sha256(b"payload").hexdigest()


def test_audit_event_never_carries_raw_content() -> None:
    # DCL-045: audit records hash + source, not the (possibly sensitive) content.
    assert "content" not in QuarantineEvent.__dataclass_fields__
    assert "content_sha256" in QuarantineEvent.__dataclass_fields__


def test_list_is_newest_first() -> None:
    store = QuarantineStore(audit_sink=lambda e: None)
    first = store.add(content="a", source="s1", verdict=_unsafe())
    second = store.add(content="b", source="s2", verdict=_unsafe())

    ids = [r.id for r in store.list()]
    # second was added later, so it must come first.
    assert ids[0] == second
    assert ids[1] == first


def test_default_log_sink_logs_hash_not_content() -> None:
    stream = io.StringIO()
    configure(force=True, stream=stream, level="DEBUG")

    secret = "TOP-SECRET-CLIENT-DATA-12345"
    store = QuarantineStore(audit_sink=log_audit_sink)
    store.add(content=secret, source="file:secret.txt", verdict=_unsafe("bad"))

    line = stream.getvalue()
    assert line, "expected a log line"
    record = json.loads(line.splitlines()[-1])
    extra = record["extra"]
    assert extra["event"] == "sanitizer.quarantine"
    assert extra["source"] == "file:secret.txt"
    assert extra["content_sha256"] == hashlib.sha256(secret.encode()).hexdigest()
    # The raw content must never appear in the log.
    assert secret not in line

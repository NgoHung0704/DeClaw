"""Change debouncing, driven by an injected clock. No real filesystem timing."""

from __future__ import annotations

from pathlib import Path

from declaw.documents.watcher import ChangeBuffer, DocumentChangeHandler


class Event:
    """Minimal stand-in for a watchdog filesystem event."""

    def __init__(self, path: str, is_directory: bool = False) -> None:
        self.src_path = path
        self.is_directory = is_directory


def _handler(buffer: ChangeBuffer, now: float = 100.0) -> DocumentChangeHandler:
    return DocumentChangeHandler(buffer, clock=lambda: now)


def test_a_noted_change_is_not_due_immediately() -> None:
    buffer = ChangeBuffer(debounce_s=2.0)
    buffer.note(Path("a.txt"), now=100.0)
    assert buffer.due(now=100.5) == []


def test_a_change_becomes_due_after_the_debounce_window() -> None:
    buffer = ChangeBuffer(debounce_s=2.0)
    buffer.note(Path("a.txt"), now=100.0)
    assert buffer.due(now=102.1) == [Path("a.txt")]


def test_repeated_writes_collapse_into_one_change() -> None:
    # A single 'Save' in Word emits several events; indexing once is correct.
    buffer = ChangeBuffer(debounce_s=2.0)
    for moment in (100.0, 100.3, 100.9):
        buffer.note(Path("a.txt"), now=moment)
    assert buffer.pending_count == 1
    assert buffer.due(now=103.0) == [Path("a.txt")]


def test_a_later_write_extends_the_window() -> None:
    # Still being written at 101.5 means it is not settled at 102.1.
    buffer = ChangeBuffer(debounce_s=2.0)
    buffer.note(Path("a.txt"), now=100.0)
    buffer.note(Path("a.txt"), now=101.5)
    assert buffer.due(now=102.1) == []
    assert buffer.due(now=103.6) == [Path("a.txt")]


def test_due_clears_what_it_returned() -> None:
    buffer = ChangeBuffer(debounce_s=1.0)
    buffer.note(Path("a.txt"), now=100.0)
    assert buffer.due(now=102.0) == [Path("a.txt")]
    assert buffer.due(now=103.0) == []
    assert buffer.pending_count == 0


def test_several_files_are_returned_sorted() -> None:
    buffer = ChangeBuffer(debounce_s=1.0)
    for name in ("z.txt", "a.txt", "m.txt"):
        buffer.note(Path(name), now=100.0)
    assert buffer.due(now=102.0) == [Path("a.txt"), Path("m.txt"), Path("z.txt")]


def test_only_settled_files_are_returned() -> None:
    buffer = ChangeBuffer(debounce_s=2.0)
    buffer.note(Path("settled.txt"), now=100.0)
    buffer.note(Path("still-writing.txt"), now=102.0)
    assert buffer.due(now=102.5) == [Path("settled.txt")]


def test_the_handler_ignores_unsupported_extensions() -> None:
    buffer = ChangeBuffer(debounce_s=1.0)
    handler = _handler(buffer)
    handler.on_modified(Event("/w/photo.png"))
    handler.on_modified(Event("/w/notes.txt"))
    assert buffer.pending_count == 1


def test_the_handler_ignores_directory_events() -> None:
    buffer = ChangeBuffer(debounce_s=1.0)
    _handler(buffer).on_modified(Event("/w/dossier", True))
    assert buffer.pending_count == 0


def test_created_and_modified_events_are_both_noted() -> None:
    buffer = ChangeBuffer(debounce_s=1.0)
    handler = _handler(buffer)
    handler.on_created(Event("/w/a.pdf"))
    handler.on_modified(Event("/w/b.docx"))
    assert buffer.pending_count == 2


def test_every_supported_document_type_is_watched() -> None:
    buffer = ChangeBuffer(debounce_s=1.0)
    handler = _handler(buffer)
    for name in ("a.pdf", "b.docx", "c.xlsx", "d.txt", "e.md", "f.markdown"):
        handler.on_modified(Event(f"/w/{name}"))
    assert buffer.pending_count == 6


def test_uppercase_extensions_are_recognised() -> None:
    buffer = ChangeBuffer(debounce_s=1.0)
    _handler(buffer).on_modified(Event("/w/CONTRAT.PDF"))
    assert buffer.pending_count == 1

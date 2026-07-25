"""Integration test: the real sanitizer classifier over a corpus subset (DCL-040+).

Self-skips unless a local Ollama is reachable AND the sanitizer model is pulled.
It proves the live wire works end-to-end (ChatOllama + structured output ->
typed verdict) on a small subset. It deliberately does NOT hard-assert the
detection / FP / latency *targets* (DCL-047/048): those depend on model and
hardware and are measured by ``scripts/sanitizer_benchmark.py``. Hard-asserting
7B accuracy here would be flaky (same reasoning as the brain integration test).
"""

from __future__ import annotations

import pytest

from declaw.brain.ollama_client import OllamaClient
from declaw.config import get_settings
from declaw.sanitizer.benchmark import run_benchmark
from declaw.sanitizer.classifier import build_ollama_classifier
from declaw.sanitizer.corpus import BENIGN_CORPUS, INJECTION_CORPUS
from declaw.sanitizer.verdict import SanitizerVerdict


async def test_live_sanitizer_classifies_a_subset() -> None:
    settings = get_settings()
    health = await OllamaClient().health()
    if not health.reachable:
        pytest.skip("Ollama daemon not reachable")
    if not health.has_model(settings.sanitizer_model):
        pytest.skip(f"sanitizer model {settings.sanitizer_model!r} not pulled")

    classify = build_ollama_classifier()
    injections = INJECTION_CORPUS[:3]
    benign = BENIGN_CORPUS[:3]
    report = await run_benchmark(classify, injections=injections, benign=benign)

    # The live wire returns well-formed typed verdicts for every sample.
    all_results = [*report.injection_results, *report.benign_results]
    assert len(all_results) == 6
    for r in all_results:
        assert isinstance(r.verdict, SanitizerVerdict)
        assert r.verdict.verdict in ("SAFE", "UNSAFE")
        assert r.elapsed_s >= 0

    # Soft signal (printed with -s), not a hard gate on 7B accuracy.
    print(
        f"\n[live sanitizer] detection={report.detection_rate:.0%} "
        f"fp={report.false_positive_rate:.0%} p95={report.latency_p95:.2f}s"
    )

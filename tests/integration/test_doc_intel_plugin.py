"""The real doc-intel plugin, in a real subprocess, through PluginHost."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fpdf import FPDF

from declaw.plugin_host.errors import PluginCapabilityError
from declaw.plugin_host.host import PluginHost
from declaw.plugin_host.permissions import GrantStore
from declaw.plugin_host.state import PluginStateStore

SOURCE = Path(__file__).parent.parent.parent / "plugins" / "builtin" / "doc-intel"


@pytest.fixture
def plugins_dir(tmp_path: Path) -> Path:
    shutil.copytree(SOURCE, tmp_path / "plugins" / "doc-intel")
    return tmp_path / "plugins"


def _host(tmp_path: Path, plugins_dir: Path) -> PluginHost:
    return PluginHost(
        search_dir=plugins_dir,
        state=PluginStateStore(tmp_path / "plugin_state.json"),
        grants=GrantStore(tmp_path / "plugin_grants.json"),
    )


def _make_pdf(path: Path) -> Path:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("helvetica", size=12)
    pdf.add_page()
    pdf.multi_cell(w=180, h=8, text="ARTICLE 3 - OBLIGATIONS DU PRESTATAIRE")
    pdf.multi_cell(w=180, h=8, text="Le prestataire fournit les services decrits.")
    path.write_bytes(bytes(pdf.output()))
    return path


async def test_the_plugin_loads_and_declares_parse(tmp_path: Path, plugins_dir: Path) -> None:
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        assert [p.manifest.name for p in host.loaded()] == ["doc-intel"]
        assert list(host.loaded()[0].capabilities) == ["parse"]
    finally:
        await host.stop()


async def test_parse_is_never_exposed_to_the_model(tmp_path: Path, plugins_dir: Path) -> None:
    # The model must not be able to call the indexer's infrastructure.
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        assert host.model_tools() == []
    finally:
        await host.stop()


async def test_parsing_a_real_pdf_through_the_subprocess(
    tmp_path: Path, plugins_dir: Path
) -> None:
    document = _make_pdf(tmp_path / "contrat.pdf")
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        result = await host.call("doc-intel", "parse", {"path": str(document)})
        assert result["doc_type"] == "pdf"
        assert result["page_count"] == 1
        assert result["truncated"] is False
        assert result["chunks"]
        assert "PRESTATAIRE" in result["chunks"][0]["text"]
        assert result["chunks"][0]["page"] == 1
        assert result["chunks"][0]["ordinal"] == 0
    finally:
        await host.stop()


async def test_parsing_a_markdown_file(tmp_path: Path, plugins_dir: Path) -> None:
    document = tmp_path / "notes.md"
    document.write_text("# Contrat\n\nLe corps du document.\n", encoding="utf-8")
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        result = await host.call("doc-intel", "parse", {"path": str(document)})
        assert result["doc_type"] == "markdown"
        assert result["chunks"][0]["heading"] == "Contrat"
    finally:
        await host.stop()


async def test_an_unsupported_extension_is_reported(tmp_path: Path, plugins_dir: Path) -> None:
    document = tmp_path / "photo.png"
    document.write_bytes(b"\x89PNG\r\n")
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        with pytest.raises(PluginCapabilityError) as excinfo:
            await host.call("doc-intel", "parse", {"path": str(document)})
        assert excinfo.value.code == "capability_failed"
        assert ".png" in str(excinfo.value)
    finally:
        await host.stop()


async def test_a_missing_file_is_reported(tmp_path: Path, plugins_dir: Path) -> None:
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        with pytest.raises(PluginCapabilityError):
            await host.call("doc-intel", "parse", {"path": str(tmp_path / "nope.pdf")})
    finally:
        await host.stop()

from __future__ import annotations

import importlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _reload_bridge():
    sys.modules.pop("services.rust_bridge", None)
    return importlib.import_module("services.rust_bridge")


def test_fallback_backend_when_rust_module_is_missing(monkeypatch):
    original_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "nightpaw_rs":
            raise ImportError("nightpaw_rs intentionally unavailable in fallback test")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    bridge = _reload_bridge()

    assert bridge.HAS_RUST is False
    assert bridge.RUST_BACKEND == "python"


def test_python_fallback_helpers_match_expected_behavior(monkeypatch):
    original_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "nightpaw_rs":
            raise ImportError("nightpaw_rs intentionally unavailable in fallback test")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    bridge = _reload_bridge()

    assert bridge.normalize_message("  Hello\tWORLD  ") == "hello world"
    assert bridge.chunk_text("alpha beta gamma delta", 10) == ["alpha beta", "gamma", "delta"]
    assert bridge.chunk_text("supercalifragilistic", 5) == ["super", "calif", "ragil", "istic"]
    assert bridge.classify_attachment("archive.tar.gz") == "archive"
    assert bridge.classify_attachment("notes.MD") == "text"
    assert bridge.classify_attachment("clip.webm") == "video"


def test_chunk_text_rejects_invalid_limits():
    bridge = _reload_bridge()

    try:
        bridge.chunk_text("hello", 0)
    except ValueError as exc:
        assert "max_chars" in str(exc)
    else:
        raise AssertionError("chunk_text should reject max_chars <= 0")

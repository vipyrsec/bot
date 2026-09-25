"""Exercise the same extension discovery used during bot startup."""

from __future__ import annotations

from importlib import import_module

from pydis_core.utils._extensions import walk_extensions

from bot import exts


def test_discovered_extensions_have_entry_points() -> None:
    extensions = walk_extensions(exts)
    assert "bot.exts.dragonfly.dragonfly" in extensions
    assert "bot.opengrep_view" not in extensions
    for extension in extensions:
        assert callable(getattr(import_module(extension), "setup", None)), extension

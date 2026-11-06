"""Test setup: load the integration package without Home Assistant.

The package ``__init__.py`` imports Home Assistant, which is not a test
dependency. We register a stub package module pointing at the real
directory so submodules (const/client/models/icons) import cleanly with
their normal relative imports.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "koneho_meteoswiss"
)
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if "koneho_meteoswiss" not in sys.modules:
    package = types.ModuleType("koneho_meteoswiss")
    package.__path__ = [str(COMPONENT_DIR)]
    sys.modules["koneho_meteoswiss"] = package


@pytest.fixture(scope="session")
def fixture_bytes():
    def _load(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()

    return _load


@pytest.fixture(scope="session")
def fixture_text():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="latin-1")

    return _load

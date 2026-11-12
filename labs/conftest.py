"""Shared pytest setup for all labs.

- Loads labs/.env so API keys are available to live tests.
- Tests marked @pytest.mark.live call a real API (they cost a few cents).
  They are skipped unless ANTHROPIC_API_KEY is set, so `pytest` works offline.
"""
import os
import pathlib
import sys

import pytest

try:
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).parent / ".env")
except ImportError:  # dotenv is optional
    pass


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model API (skipped without an API key)")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    skip = pytest.mark.skip(reason="set ANTHROPIC_API_KEY in labs/.env to run live tests")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def pytest_collectstart(collector):
    """Every lab has its own `starter.py` and `solution.py`. Before each lab's
    test module is imported, put that lab's folder first on sys.path and forget
    any previously imported `starter`/`solution`, so `pytest studio-1 -q` runs
    each lab against its own code."""
    if isinstance(collector, pytest.Module):
        lab_dir = str(pathlib.Path(collector.path).parent)
        for mod in ("starter", "solution"):
            sys.modules.pop(mod, None)
        if lab_dir in sys.path:
            sys.path.remove(lab_dir)
        sys.path.insert(0, lab_dir)

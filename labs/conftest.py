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


@pytest.fixture(autouse=True)
def _lab_on_path(request):
    """Let each lab's tests `import starter` from their own folder."""
    lab_dir = str(pathlib.Path(request.fspath).parent)
    sys.path.insert(0, lab_dir)
    for mod in ("starter", "solution"):
        sys.modules.pop(mod, None)
    yield
    sys.path.remove(lab_dir)

"""Shared pytest setup for all labs.

- Loads labs/.env so API keys are available to live tests.
- Tests marked @pytest.mark.live call a real API (they cost a few cents).
  They are skipped unless ANTHROPIC_API_KEY is set, so `pytest` works offline.
- Review track: if a lab folder has a `work.py` (your copy of the solution,
  made by `python lab.py review <lab>`), tests import it instead of
  `starter.py`. Delete work.py (or `python lab.py reset <lab>`) to go back.
- Tests marked @pytest.mark.change belong to the lab's CHANGE.md task. They
  run only when you run test_change.py itself, so a full run stays green
  until you choose to take on the change.
"""
import importlib.abc
import importlib.util
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
    config.addinivalue_line("markers", "change: acceptance test for the lab's CHANGE.md task (run test_change.py on its own)")


def pytest_collection_modifyitems(config, items):
    live_skip = pytest.mark.skip(reason="set ANTHROPIC_API_KEY in labs/.env to run live tests")
    change_skip = pytest.mark.skip(reason="CHANGE.md task: run test_change.py on its own once the change is made")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    # The change tests run only when test_change.py (or one of its tests) was asked for by name.
    asked_for_change = any("test_change" in str(a) for a in config.args)
    for item in items:
        if "live" in item.keywords and not has_key:
            item.add_marker(live_skip)
        if "change" in item.keywords and not asked_for_change:
            item.add_marker(change_skip)


class _WorkCopyFinder(importlib.abc.MetaPathFinder):
    """Resolve `import starter` to the current lab's work.py when it exists."""

    lab_dir: pathlib.Path | None = None

    def find_spec(self, name, path=None, target=None):
        if name != "starter" or self.lab_dir is None:
            return None
        work = self.lab_dir / "work.py"
        if not work.exists():
            return None  # fall through to the normal starter.py
        return importlib.util.spec_from_file_location("starter", work)


_finder = _WorkCopyFinder()
sys.meta_path.insert(0, _finder)


def pytest_collectstart(collector):
    """Every lab has its own `starter.py` and `solution.py`. Before each lab's
    test module is imported, put that lab's folder first on sys.path and forget
    any previously imported `starter`/`solution`, so `pytest studio-1 -q` runs
    each lab against its own code."""
    if isinstance(collector, pytest.Module):
        _finder.lab_dir = pathlib.Path(collector.path).parent
        lab_dir = str(_finder.lab_dir)
        for mod in ("starter", "solution"):
            sys.modules.pop(mod, None)
        if lab_dir in sys.path:
            sys.path.remove(lab_dir)
        sys.path.insert(0, lab_dir)

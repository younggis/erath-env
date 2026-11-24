"""Test isolation: every test run gets its own temporary catalog and data root."""
from __future__ import annotations

import pytest

from earthsim.config import Settings, get_settings, set_settings
from earthsim.catalog import repository as repo
from earthsim.ingest import fixtures


@pytest.fixture(scope="session", autouse=True)
def isolated_data(tmp_path_factory):
    root = tmp_path_factory.mktemp("earthsim-data")
    s = get_settings()
    s.data_mode = "fixture"  # tests always exercise the offline deterministic slice
    s.data_root = root
    for sub in ("catalog", "raw", "derived", "fixtures", "tmp"):
        (root / sub).mkdir(exist_ok=True)
    repo.ensure_migrated()
    fixtures.install_all()
    yield s


@pytest.fixture(autouse=True)
def reset_settings(isolated_data):
    set_settings(isolated_data)
    yield

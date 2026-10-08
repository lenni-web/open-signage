"""Gemeinsame Pytest-Fixtures."""

import pytest


@pytest.fixture(autouse=True)
def legacy_test_initial_password(monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_INITIAL_PASSWORD", "open-signage")
    monkeypatch.setenv("OPEN_SIGNAGE_REQUIRE_INITIAL_PASSWORD_CHANGE", "0")

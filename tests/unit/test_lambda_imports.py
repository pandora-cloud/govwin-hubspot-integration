"""Verify all Lambda handler modules import without error."""

from __future__ import annotations

import importlib


def test_import_authenticate():
    mod = importlib.import_module("src.lambdas.authenticate")
    assert hasattr(mod, "handler")


def test_import_discover_changes():
    mod = importlib.import_module("src.lambdas.discover_changes")
    assert hasattr(mod, "handler")


def test_import_fetch_opp_details():
    mod = importlib.import_module("src.lambdas.fetch_opp_details")
    assert hasattr(mod, "handler")


def test_import_sync_to_hubspot():
    mod = importlib.import_module("src.lambdas.sync_to_hubspot")
    assert hasattr(mod, "handler")


def test_import_update_sync_state():
    mod = importlib.import_module("src.lambdas.update_sync_state")
    assert hasattr(mod, "handler")


def test_import_setup_hubspot():
    mod = importlib.import_module("src.lambdas.setup_hubspot")
    assert hasattr(mod, "handler")


def test_import_handle_error():
    mod = importlib.import_module("src.lambdas.handle_error")
    assert hasattr(mod, "handler")

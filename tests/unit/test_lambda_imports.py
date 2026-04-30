"""Verify all Lambda handler modules import without error."""

from __future__ import annotations

import importlib


def test_import_govwin_orchestrator():
    mod = importlib.import_module("src.lambdas.govwin_orchestrator")
    assert hasattr(mod, "handler")


def test_import_govwin_worker():
    mod = importlib.import_module("src.lambdas.govwin_worker")
    assert hasattr(mod, "handler")


def test_import_setup_hubspot():
    mod = importlib.import_module("src.lambdas.setup_hubspot")
    assert hasattr(mod, "handler")


def test_import_setup_hubspot_webhooks():
    mod = importlib.import_module("src.lambdas.setup_hubspot_webhooks")
    assert hasattr(mod, "handler")


def test_import_hubspot_webhook_receiver():
    mod = importlib.import_module("src.lambdas.hubspot_webhook_receiver")
    assert hasattr(mod, "handler")


def test_import_submit_to_ace():
    mod = importlib.import_module("src.lambdas.submit_to_ace")
    assert hasattr(mod, "handler")


def test_import_update_in_ace():
    mod = importlib.import_module("src.lambdas.update_in_ace")
    assert hasattr(mod, "handler")


def test_import_handle_ace_event():
    mod = importlib.import_module("src.lambdas.handle_ace_event")
    assert hasattr(mod, "handler")

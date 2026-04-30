"""Tests for ACE input validators (path-injection / dynamodb pk safety)."""

from __future__ import annotations

import pytest

from src.ace.validators import (
    is_valid_aws_opportunity_id,
    is_valid_govwin_id,
    is_valid_hubspot_object_id,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("123456789", True),
        ("0", True),
        ("", False),
        (None, False),
        ("../etc/passwd", False),
        ("12345; DROP", False),
        ("12345 ", False),
        ("12.34", False),
    ],
)
def test_hubspot_object_id(value, expected) -> None:
    assert is_valid_hubspot_object_id(value) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("OPP263150", True),
        ("BID13141848", True),
        ("TOP1562354", True),
        ("opp-123_X", True),
        ("OPP/etc", False),
        ("OPP#admin", False),
        ("OPP 123", False),
        ("", False),
        (None, False),
    ],
)
def test_govwin_id(value, expected) -> None:
    assert is_valid_govwin_id(value) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("O123456789012345", True),
        ("O-1", True),
        ("../bad", False),
        ("", False),
    ],
)
def test_aws_opportunity_id(value, expected) -> None:
    assert is_valid_aws_opportunity_id(value) is expected

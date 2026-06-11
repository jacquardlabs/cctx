"""Tests for fan_out classifier (M16 #89) and related models."""
from __future__ import annotations


def test_fanout_waste_kind_exists():
    from cctx.models import FindingKind
    assert FindingKind.FANOUT_WASTE == "fanout_waste"


def test_fanout_waste_has_kind_label():
    from cctx.models import KIND_LABEL, FindingKind
    assert KIND_LABEL[FindingKind.FANOUT_WASTE] == "FANOUT WASTE"


def test_fanout_waste_has_managed_heading():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS[FindingKind.FANOUT_WASTE] == "## Fan-out discipline"

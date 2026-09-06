"""
Unit tests for app.core.scoring -- pure functions, no DB needed.

    docker compose exec api pytest tests/test_scoring.py -v
"""
import math
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, "/app")
from app.core import scoring

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_label(
    label_type="CurbRamp",
    severity=None,
    agree_count=5,
    disagree_count=0,
    unsure_count=0,
    label_date=None,
    match_method="nearest_segment",
    match_distance_m=1.0,
    ambiguous_match=False,
):
    return {
        "label_type": label_type,
        "severity": severity,
        "agree_count": agree_count,
        "disagree_count": disagree_count,
        "unsure_count": unsure_count,
        "label_date": label_date if label_date is not None else AS_OF - timedelta(days=30),
        "match_method": match_method,
        "match_distance_m": match_distance_m,
        "ambiguous_match": ambiguous_match,
    }


# ---------------------------------------------------------------------------
# Unknown / no-evidence segments
# ---------------------------------------------------------------------------

def test_no_labels_is_unknown_with_neutral_score_and_zero_confidence():
    result = scoring.score_segment([], AS_OF)
    assert result["coverage_status"] == "unknown"
    assert result["accessibility_score"] == 0.5
    assert result["confidence_score"] == 0.0
    assert result["label_count"] == 0
    assert result["staleness_days"] is None


def test_only_non_informative_labels_is_unknown():
    labels = [make_label(label_type="Occlusion"), make_label(label_type="Other")]
    result = scoring.score_segment(labels, AS_OF)
    assert result["coverage_status"] == "unknown"
    assert result["accessibility_score"] == 0.5
    assert result["confidence_score"] == 0.0


def test_far_nosidewalk_label_excluded_from_scoring_but_within_10m_would_still_be_matched():
    """The label is within the Week 2.5 10m production match threshold (so it
    stays matched in the DB / accessibility_labels.segment_id), but beyond
    scoring's tighter 5m NoSidewalk cutoff -- must not count as evidence."""
    far_label = make_label(label_type="NoSidewalk", match_distance_m=8.0)
    assert far_label["match_distance_m"] <= scoring.PRODUCTION_MATCH_THRESHOLD_M
    assert not scoring.is_informative(far_label)
    result = scoring.score_segment([far_label], AS_OF)
    assert result["coverage_status"] == "unknown"


def test_close_nosidewalk_label_is_informative():
    close_label = make_label(label_type="NoSidewalk", match_distance_m=2.0)
    assert scoring.is_informative(close_label)
    result = scoring.score_segment([close_label], AS_OF)
    assert result["coverage_status"] == "labeled"
    assert result["accessibility_score"] < 0.5  # near-worst, per FIXED_VALUE_LABEL_TYPES


# ---------------------------------------------------------------------------
# Score monotonicity
# ---------------------------------------------------------------------------

def test_accessibility_score_monotonic_in_label_quality():
    """Replacing a CurbRamp (good) with a NoCurbRamp (bad) must lower the score."""
    good = scoring.score_segment([make_label(label_type="CurbRamp")], AS_OF)
    bad = scoring.score_segment([make_label(label_type="NoCurbRamp", severity=3)], AS_OF)
    assert good["accessibility_score"] > bad["accessibility_score"]


def test_confidence_monotonic_in_label_count():
    """More identical, reliable labels must never decrease confidence."""
    scores = []
    for n in (1, 2, 5, 10):
        labels = [make_label() for _ in range(n)]
        scores.append(scoring.score_segment(labels, AS_OF)["confidence_score"])
    assert scores == sorted(scores)
    assert scores[0] < scores[-1]


def test_confidence_saturates_toward_one_with_heavy_evidence():
    labels = [make_label() for _ in range(200)]
    result = scoring.score_segment(labels, AS_OF)
    assert result["confidence_score"] > 0.95


def test_confidence_not_capped_by_average_reliability():
    """Regression test for the rejected volume_factor * avg_reliability design
    (docs/week3_scoring_report.md): confidence must be able to exceed any
    single label's own reliability once enough evidence accumulates."""
    single_reliability = scoring.label_reliability(make_label(), AS_OF)
    labels = [make_label() for _ in range(50)]
    result = scoring.score_segment(labels, AS_OF)
    assert result["confidence_score"] > single_reliability


# ---------------------------------------------------------------------------
# Severity weighting
# ---------------------------------------------------------------------------

def test_severity_weighting_monotonic_for_scaled_types():
    for label_type in scoring.SEVERITY_SCALED_LABEL_TYPES:
        values = [scoring.label_value(label_type, sev) for sev in (1, 2, 3)]
        assert values == sorted(values, reverse=True), f"{label_type} should get worse with higher severity"


def test_missing_severity_defaults_to_midpoint():
    mid = (scoring.SEVERITY_MIN + scoring.SEVERITY_MAX) / 2
    for label_type in scoring.SEVERITY_SCALED_LABEL_TYPES:
        assert scoring.label_value(label_type, None) == scoring.label_value(label_type, mid)


# ---------------------------------------------------------------------------
# Confidence behavior: agreement, recency, match quality, ambiguity
# ---------------------------------------------------------------------------

def test_disagreement_lowers_confidence():
    agreed = scoring.score_segment([make_label(agree_count=5, disagree_count=0)], AS_OF)
    disputed = scoring.score_segment([make_label(agree_count=0, disagree_count=5)], AS_OF)
    assert agreed["confidence_score"] > disputed["confidence_score"]


def test_older_label_has_lower_confidence():
    fresh = scoring.score_segment([make_label(label_date=AS_OF - timedelta(days=30))], AS_OF)
    old = scoring.score_segment([make_label(label_date=AS_OF - timedelta(days=365 * 10))], AS_OF)
    assert fresh["confidence_score"] > old["confidence_score"]


def test_farther_match_has_lower_confidence():
    close = scoring.score_segment([make_label(match_distance_m=0.5)], AS_OF)
    far = scoring.score_segment([make_label(match_distance_m=9.5)], AS_OF)
    assert close["confidence_score"] > far["confidence_score"]


def test_id_match_treated_as_full_match_quality():
    assert scoring.match_quality("ps_osm_way_id", match_distance_m=9999) == 1.0


def test_ambiguous_match_lowers_confidence():
    clear = scoring.score_segment([make_label(ambiguous_match=False)], AS_OF)
    ambiguous = scoring.score_segment([make_label(ambiguous_match=True)], AS_OF)
    assert clear["confidence_score"] > ambiguous["confidence_score"]
    expected = 1 - math.exp(
        -scoring.label_reliability(make_label(ambiguous_match=True), AS_OF) / scoring.CONFIDENCE_EVIDENCE_SCALE
    )
    assert ambiguous["confidence_score"] == pytest.approx(expected)


def test_all_evidence_discounted_to_zero_falls_back_to_neutral():
    """If reliability rounds to exactly 0 for every label (pathological, but
    the code path must not divide by zero), fall back to the unknown-like
    neutral prior rather than crashing or returning NaN."""
    label = make_label(match_method="nearest_segment", match_distance_m=scoring.PRODUCTION_MATCH_THRESHOLD_M)
    result = scoring.score_segment([label], AS_OF)
    assert result["accessibility_score"] == 0.5
    assert result["confidence_score"] == 0.0
    # but coverage_status is still 'labeled': there *is* a label, just no usable weight
    assert result["coverage_status"] == "labeled"

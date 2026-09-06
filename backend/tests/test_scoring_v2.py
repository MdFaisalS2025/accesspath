"""
Week 3.5 unit tests: dominance ceiling, feature-domain scoping, non-
independence discount, and confidence-consistency semantics -- plus the six
adversarial scenarios requested in review. Pure functions, no DB needed.

    docker compose exec api pytest tests/test_scoring_v2.py -v
"""
import sys
from datetime import datetime, timedelta, timezone

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
    pano_id="panoA",
    ps_label_id=1,
):
    return {
        "ps_label_id": ps_label_id,
        "label_type": label_type,
        "severity": severity,
        "agree_count": agree_count,
        "disagree_count": disagree_count,
        "unsure_count": unsure_count,
        "label_date": label_date if label_date is not None else AS_OF - timedelta(days=90),
        "match_method": match_method,
        "match_distance_m": match_distance_m,
        "ambiguous_match": ambiguous_match,
        "pano_id": pano_id,
    }


def unique_panos(label_type, n, **kwargs):
    return [make_label(label_type, pano_id=f"{label_type}_{i}", ps_label_id=i, **kwargs) for i in range(n)]


# ---------------------------------------------------------------------------
# Adversarial scenarios (mirrors scripts/compare_scoring_models.py)
# ---------------------------------------------------------------------------

def test_ten_curbramps_do_not_cancel_reliable_nosidewalk():
    labels = unique_panos("CurbRamp", 10) + [make_label("NoSidewalk", pano_id="NS", ps_label_id=99)]
    result = scoring.score_segment(labels, AS_OF, "footway")
    assert result["accessibility_score"] <= scoring.FIXED_VALUE_LABEL_TYPES["NoSidewalk"] + 1e-9
    assert result["dominant_hazard_type"] == "NoSidewalk"


def test_many_positives_do_not_cancel_severe_obstacle():
    labels = unique_panos("CurbRamp", 6) + unique_panos("Crosswalk", 4)
    labels.append(make_label("Obstacle", severity=3, pano_id="Ob", ps_label_id=99))
    result = scoring.score_segment(labels, AS_OF, "footway")
    expected_ceiling = scoring.label_value("Obstacle", 3)
    assert result["accessibility_score"] <= expected_ceiling + 1e-9
    assert result["dominant_hazard_type"] == "Obstacle"


def test_equal_reliable_positive_and_negative_is_contested_not_confidently_medium():
    labels = [make_label("CurbRamp", pano_id="pos"), make_label("NoCurbRamp", severity=3, pano_id="neg")]
    result = scoring.score_segment(labels, AS_OF, "footway")
    assert 0.3 < result["accessibility_score"] < 0.7  # roughly neutral
    assert result["evidence_consistency"] < 0.1  # but flagged as contested
    # a one-sided equivalent should show much higher consistency
    one_sided = scoring.score_segment([make_label("CurbRamp", pano_id="pos")], AS_OF, "footway")
    assert one_sided["evidence_consistency"] > result["evidence_consistency"]


def test_duplicated_correlated_labels_undercount_vs_independent():
    duplicated = [make_label("CurbRamp", pano_id="same", ps_label_id=i) for i in range(8)]
    independent = unique_panos("CurbRamp", 8)
    dup_result = scoring.score_segment(duplicated, AS_OF, "footway")
    indep_result = scoring.score_segment(independent, AS_OF, "footway")
    assert dup_result["positive_evidence"] < indep_result["positive_evidence"]
    assert dup_result["confidence_score"] < indep_result["confidence_score"]


def test_crossing_evidence_alone_is_discounted_on_a_non_crossing_segment():
    labels = unique_panos("CurbRamp", 3) + [make_label("Crosswalk", pano_id="cw", ps_label_id=99)]
    on_footway = scoring.score_segment(labels, AS_OF, "footway")
    on_crossing = scoring.score_segment(labels, AS_OF, "crossing")
    # same evidence, matched to its own domain, should count for much more
    assert on_crossing["positive_evidence"] > on_footway["positive_evidence"]
    assert on_crossing["confidence_score"] > on_footway["confidence_score"]


def test_unknown_segment_no_evidence():
    result = scoring.score_segment([], AS_OF, "footway")
    assert result["coverage_status"] == "unknown"
    assert result["accessibility_score"] == 0.5
    assert result["confidence_score"] == 0.0


# ---------------------------------------------------------------------------
# Explicit dominance rules (requirement 2)
# ---------------------------------------------------------------------------

def test_reliable_nosidewalk_caps_near_zero_regardless_of_positive_volume():
    for n_positive in (0, 1, 5, 20, 100):
        labels = unique_panos("CurbRamp", n_positive) + [make_label("NoSidewalk", pano_id="NS", ps_label_id=999)]
        result = scoring.score_segment(labels, AS_OF, "footway")
        assert result["accessibility_score"] <= 0.05 + 1e-9, f"failed at n_positive={n_positive}"


def test_severe_hazard_ceiling_is_proportional_to_severity():
    # Each hazard type is evaluated on a segment matching its own evidence
    # domain (NoCurbRamp is crossing-domain; a footway would cross-domain
    # discount it below the dominance cutoff, which is a separate, correct
    # behavior covered by test_domain_discount_applied_cross_domain).
    domain_for = {"NoCurbRamp": "crossing", "Obstacle": "footway", "SurfaceProblem": "footway"}
    for label_type, highway_type in domain_for.items():
        mild = scoring.score_segment([make_label(label_type, severity=1, pano_id="m")], AS_OF, highway_type)
        severe = scoring.score_segment([make_label(label_type, severity=3, pano_id="s")], AS_OF, highway_type)
        assert severe["accessibility_score"] <= mild["accessibility_score"]
        # the ceiling is an upper bound (min(base_score, ceiling)), not a floor --
        # a single reliable hazard with no offsetting positive evidence can push
        # base_score *below* its own ceiling value, which is fine.
        assert severe["accessibility_score"] <= scoring.label_value(label_type, 3) + 1e-9


def test_unreliable_hazard_does_not_set_a_hard_ceiling():
    """An old, heavily-disputed hazard report shouldn't hard-cap the score --
    it still drags the graduated base_score down, just not to its own value."""
    old_disputed = make_label(
        "NoSidewalk", agree_count=0, disagree_count=8,
        label_date=AS_OF - timedelta(days=365 * 12), pano_id="weak",
    )
    labels = unique_panos("CurbRamp", 5) + [old_disputed]
    result = scoring.score_segment(labels, AS_OF, "footway")
    assert result["dominant_hazard_type"] is None
    assert result["accessibility_score"] > 0.05


def test_low_severity_hazard_barely_constrains():
    labels = unique_panos("CurbRamp", 3) + [make_label("SurfaceProblem", severity=1, pano_id="sp")]
    result = scoring.score_segment(labels, AS_OF, "footway")
    # severity-1 SurfaceProblem value is 0.8 -- should not crush an otherwise good segment
    assert result["accessibility_score"] > 0.5


# ---------------------------------------------------------------------------
# Feature domain scoping (requirement 3)
# ---------------------------------------------------------------------------

def test_domain_discount_applied_cross_domain():
    label = make_label("CurbRamp")
    same_domain = scoring.label_reliability(label, AS_OF, segment_highway_type="crossing")
    cross_domain = scoring.label_reliability(label, AS_OF, segment_highway_type="footway")
    assert cross_domain == same_domain * scoring.CROSS_DOMAIN_DISCOUNT


def test_segment_evidence_domain_matches_footway_not_crossing():
    label = make_label("SurfaceProblem", severity=2)
    same_domain = scoring.label_reliability(label, AS_OF, segment_highway_type="footway")
    cross_domain = scoring.label_reliability(label, AS_OF, segment_highway_type="crossing")
    assert same_domain > cross_domain


def test_curbramp_alone_does_not_prove_whole_segment_accessible():
    """A CurbRamp is crossing-domain evidence; on a plain footway it should
    contribute far less than it would on an actual crossing segment, and
    should never by itself imply high confidence about the footway's own
    surface condition."""
    labels = [make_label("CurbRamp", pano_id="cr")]
    on_footway = scoring.score_segment(labels, AS_OF, "footway")
    on_crossing = scoring.score_segment(labels, AS_OF, "crossing")
    assert on_footway["confidence_score"] < on_crossing["confidence_score"]


# ---------------------------------------------------------------------------
# Confidence semantics (requirement 4)
# ---------------------------------------------------------------------------

def test_confidence_reports_quantity_and_consistency_separately():
    result = scoring.score_segment(unique_panos("CurbRamp", 3), AS_OF, "footway")
    assert "positive_evidence" in result
    assert "negative_evidence" in result
    assert "evidence_consistency" in result
    assert result["positive_evidence"] > 0
    assert result["negative_evidence"] == 0
    assert result["evidence_consistency"] == 1.0  # perfectly one-sided


def test_disagreement_penalizes_confidence_beyond_volume_alone():
    one_sided = scoring.score_segment(unique_panos("CurbRamp", 4), AS_OF, "footway")
    contested = scoring.score_segment(
        unique_panos("CurbRamp", 2) + unique_panos("NoCurbRamp", 2, severity=2), AS_OF, "footway"
    )
    # both have similar total evidence quantity, but contested should show lower confidence
    assert contested["confidence_score"] < one_sided["confidence_score"]


def test_non_independence_discount_is_the_documented_value():
    dup = make_label("CurbRamp", pano_id="same", ps_label_id=2)
    ref = make_label("CurbRamp", pano_id="same", ps_label_id=1)
    weighted = scoring.deduplicate_labels([ref, dup], AS_OF, "footway")
    reliabilities = sorted((r for _, r in weighted), reverse=True)
    assert reliabilities[1] == reliabilities[0] * scoring.NON_INDEPENDENCE_DISCOUNT

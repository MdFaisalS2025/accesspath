"""
Accessibility + confidence scoring per segment.

Deliberately pure/DB-free so it's unit-testable without Postgres --
scripts/compute_scores.py does the DB I/O and calls into this module.

## Week 3.5 revision -- read this first

Week 3 shipped a reliability-weighted *average* of all matched labels. That
was rejected in review: a weighted average lets enough positive labels
(CurbRamp, Crosswalk) numerically outvote one reliable, severe hazard
(NoSidewalk, a severe Obstacle) -- unsafe and indefensible for accessibility
routing, where "usually fine but there's a documented barrier" must not
collapse to "moderately accessible." Four models were compared
(docs/week3_5_scoring_review.md has the full writeup and numbers):

  A. score_segment_weighted_average() -- the original Week 3 model, kept
     here only for comparison/regression testing, not used in production.
  B. score_segment_min_aggregation()  -- take the worst value among
     sufficiently-reliable labels, full stop. Maximally conservative; every
     comparison scenario shows why it's *too* conservative (one marginal
     old SurfaceProblem report permanently drags an otherwise-fine segment
     to that report's value, with no room for it to be outweighed by
     everything else known about the segment).
  D. score_segment_risk_only()        -- noisy-OR risk accumulation (below)
     with no hard ceiling. Combines minor evidence gradually as intended,
     but a large-enough pile of positive evidence can still, in the limit,
     pull a segment with one dominant hazard back up -- the same category
     of failure as the weighted average, just requiring more labels to
     trigger it.
  E. score_segment() -- **the production model.** Same risk-accumulation
     base as D, but capped by an explicit dominance ceiling set by the
     single worst *reliable* hazard, which no amount of positive evidence
     can raise. This is the only one of the four where dominance is a hard
     guarantee provable from the formula, not an emergent (and therefore
     eventually violable) property of the weighting -- see "Dominance
     ceiling" below.

## Accessibility score (0 worst - 1 best) -- production model (E)

1. Each informative label gets a reliability r_i in [0, 1] (see
   `label_reliability`): agreement x recency x match-quality x ambiguity
   penalty x domain-discount x non-independence-discount.
2. Labels split into `positive` (CurbRamp, Crosswalk, Signal) and `hazard`
   (NoCurbRamp, NoSidewalk, SurfaceProblem, Obstacle) -- see `label_polarity`.
3. Risk-accumulate the hazards via noisy-OR:
       risk = 1 - product(1 - r_i * hazard_fraction_i) for i in hazards
   (hazard_fraction_i = 1 - value_i). Multiple mild hazards compound
   *gradually*; one hazard with r_i*hazard_fraction_i near 1 alone drives
   risk near 1, regardless of how many other hazards do or don't exist.
4. Symmetrically accumulate positive support:
       support = 1 - product(1 - r_i * value_i) for i in positives
5. base_score = clamp(0.5 + 0.5*support - 0.5*risk, 0, 1) -- an
   explainable, symmetric combination around the neutral 0.5 prior. Pure
   hazard evidence with risk=1 -> 0. Pure positive evidence with support=1
   -> 1. No evidence of either polarity -> 0.5 (matches the neutral prior;
   in practice this segment would have coverage_status='unknown' instead,
   since "no evidence of either polarity" among informative labels means
   there were no informative labels at all).
6. **Dominance ceiling.** For hazards whose reliability clears
   RELIABILITY_DOMINANCE_CUTOFF (weak/old/disputed/ambiguous/cross-domain
   hazards don't count -- they aren't trusted enough to hard-cap anything):
       ceiling_i = value_i
   i.e. clearing the reliability bar is a binary trust decision, not a
   continuous blend -- a *blended* cap like `1 - r_i*(1-value_i)` was tried
   and rejected (docs/week3_5_scoring_review.md): agreement-smoothing,
   recency decay, and match-quality compound multiplicatively, so even a
   fresh, unanimously-agreed, tightly-matched label rarely has r above
   ~0.75, and a blend leaves that "reliable" NoSidewalk capping the score
   at ~0.29 instead of "near zero" as required. Once a hazard clears the
   trust bar, its own value is the cap, full stop; reliability below the
   bar still shapes the graduated `risk` term above, it just can't
   unilaterally cap anything. The segment's ceiling is the *minimum*
   (worst) ceiling_i across all qualifying hazards -- i.e.
   score_segment_min_aggregation()'s philosophy, used here as a floor
   under the graduated model rather than replacing it outright.
7. final_accessibility_score = min(base_score, ceiling)

This is why "numerous CurbRamp/Crosswalk labels" can't cancel a severe,
reliable barrier: they can push `support` (and therefore `base_score`) as
high as they want, but step 7's min() with a ceiling that was computed
*without reference to support at all* still applies. No combination of
positive evidence can widen a ceiling set by a hazard.

## Confidence score (0 no evidence - 1 well-attested)

Week 3.5 also separates *how much* evidence exists from *how much it
agrees*, instead of treating raw evidence volume as confidence outright
(the Week 3 formula did this and made an evenly-contested segment -- equal
strong positive and negative evidence -- look confidently "medium," which
is the wrong read: that segment is not confidently average, it's
genuinely disputed).

    evidence_quantity   = positive_evidence + negative_evidence   (reliability-weighted sums)
    evidence_consistency = |positive_evidence - negative_evidence| / evidence_quantity
                          (1.0 = perfectly one-sided, 0.0 = maximally contested)
    confidence_score = (1 - exp(-evidence_quantity / CONFIDENCE_EVIDENCE_SCALE)) * evidence_consistency

Both positive_evidence, negative_evidence, and evidence_consistency are
returned alongside confidence_score, not collapsed away, so a caller (or
this report) can distinguish "little evidence" from "lots of evidence that
disagrees" -- both depress confidence_score similarly but for different,
separately-actionable reasons.

## Non-independence discount

Project Sidewalk labels aren't always independent observations: the same
audit pass can generate more than one label for what is, physically, the
same feature (re-labeled a few panoramas apart, or by a second validator
covering overlapping ground). Per informative (label_type, pano_id) group
on a segment, only the single most-reliable label counts at full weight;
additional labels in the same group count at NON_INDEPENDENCE_DISCOUNT of
their own reliability (diminishing, not zero -- they're still mildly
corroborating, just not `n` independent votes). See `deduplicate_labels`.
This is intentionally conservative and pano_id-based (the strongest
available proxy for "the same viewpoint"); it does not catch duplicate
coverage across genuinely different audits of the same physical spot --
documented as a follow-up in docs/week3_5_scoring_review.md, not solved
here.

## Feature scope: crossing evidence vs. segment evidence

CurbRamp / NoCurbRamp / Crosswalk / Signal describe a specific crossing
point (a curb ramp is a property of one corner, not of an entire midblock
sidewalk run). NoSidewalk / SurfaceProblem / Obstacle describe the segment
itself. Our graph already distinguishes these physically:
segments.highway_type = 'crossing' for a dedicated street-crossing way,
vs. 'footway'/'path'/'pedestrian'/'steps' for a walking segment. A label
matched to a segment whose highway_type is in its own domain counts at
full reliability; matched *across* domains (about 60% of crossing-type
labels land on a plain footway segment nearest to them, not a crossing
way -- see docs/week3_5_scoring_review.md) it's discounted by
CROSS_DOMAIN_DISCOUNT. This is deliberately not zero: a CurbRamp label
just off a footway's crossing-adjacent end is still informative about
conditions right there, it's just not proof the whole footway run is
accessible, which is exactly the failure mode being guarded against.

## Coverage / unknown state

A segment with zero informative matched labels gets coverage_status =
'unknown', confidence_score = 0.0, and accessibility_score = 0.5 (a
neutral prior, not a claim of "average accessibility" -- callers must
gate on coverage_status/confidence_score before using the score, never
assume 0.5 means "fine").

## NoSidewalk safeguard (Week 3, unchanged)

NoSidewalk marks the *absence* of a sidewalk, so it structurally cannot
sit right next to a correctly-attributed pedestrian segment the way other
label types do. Week 2.5 already excludes anything beyond the 10m
production match threshold, but the 5-10m band for this type alone is
still ~50% of its "matched" labels (docs/week2_graph_report.md) --
comfortably matched by distance, not confidently *about* that specific
segment. So NoSidewalk gets its own, tighter distance cutoff for scoring
purposes only (NO_SIDEWALK_SCORING_MAX_DISTANCE_M); it stays matched in
the DB either way (Week 2.5's rule to preserve matches is not touched
here), it's just excluded from *this segment's* accessibility aggregation
when the extra margin isn't met.
"""
import math

PRODUCTION_MATCH_THRESHOLD_M = 10.0  # app.core.matching.PRODUCTION_MATCH_THRESHOLD_M, duplicated
                                       # here as a literal so this module has no DB-side import

NO_SIDEWALK_SCORING_MAX_DISTANCE_M = 5.0
AMBIGUITY_CONFIDENCE_PENALTY = 0.5
# Sidewalk infrastructure (curb ramps, crossings) is physically durable, so
# labels decay slowly; 6 years matches this dataset's ~2019-2026 label span
# without crushing every pre-2023 label to near-zero weight.
RECENCY_HALF_LIFE_YEARS = 6.0
# effective_evidence (sum of per-label reliabilities) at which confidence
# reaches 1 - e^-1 = 63%; ~2 fully-reliable labels, or more lower-quality ones.
CONFIDENCE_EVIDENCE_SCALE = 2.0

# Week 3.5 additions -----------------------------------------------------

# A hazard's reliability must clear this bar to set a hard dominance
# ceiling. Below it (old/disputed/ambiguous/cross-domain hazards), the
# report still counts toward the graduated `risk` accumulation, it just
# can't unilaterally cap the score -- we don't trust it enough for that.
RELIABILITY_DOMINANCE_CUTOFF = 0.3

# Reliability multiplier for a label matched to a segment outside its own
# evidence domain (e.g. a CurbRamp -- crossing-domain evidence -- matched
# to a plain footway segment, not a dedicated crossing way). Small but
# nonzero: still informative about conditions right there, not proof of
# the whole segment.
CROSS_DOMAIN_DISCOUNT = 0.15

# Reliability multiplier applied to every label beyond the most-reliable
# one in the same (segment, label_type, pano_id) group -- i.e. likely the
# same audit/viewpoint reporting the same physical feature more than once.
NON_INDEPENDENCE_DISCOUNT = 0.2

CROSSING_EVIDENCE_TYPES = {"CurbRamp", "NoCurbRamp", "Crosswalk", "Signal"}
SEGMENT_EVIDENCE_TYPES = {"NoSidewalk", "SurfaceProblem", "Obstacle"}
POSITIVE_LABEL_TYPES = {"CurbRamp", "Crosswalk", "Signal"}
HAZARD_LABEL_TYPES = {"NoCurbRamp", "NoSidewalk", "SurfaceProblem", "Obstacle"}

# Severity is 1-3 in the loaded Project Sidewalk Seattle extract (not 1-5 as
# schema.sql originally, incorrectly, documented -- see docs/week3_scoring_report.md).
SEVERITY_MIN = 1
SEVERITY_MAX = 3

NON_INFORMATIVE_LABEL_TYPES = {"Occlusion", "Other"}

# label_type -> value in [0, 1] for types whose accessibility impact doesn't
# vary by severity (either no severity concept, or PS never populates one).
FIXED_VALUE_LABEL_TYPES = {
    "CurbRamp": 1.0,
    "Crosswalk": 0.85,
    "Signal": 0.9,
    "NoSidewalk": 0.05,  # PS never records severity for this type; treated as near-worst
}

# label_type -> (value at severity=SEVERITY_MIN, value at severity=SEVERITY_MAX)
SEVERITY_SCALED_LABEL_TYPES = {
    "NoCurbRamp": (0.5, 0.0),
    "SurfaceProblem": (0.8, 0.3),
    "Obstacle": (0.7, 0.15),
}


def is_informative(label):
    """Whether a label is usable evidence at all for *any* segment (independent
    of which segment it happens to be nearest to)."""
    if label["label_type"] in NON_INFORMATIVE_LABEL_TYPES:
        return False
    if label["label_type"] == "NoSidewalk" and label["match_distance_m"] is not None:
        if label["match_distance_m"] > NO_SIDEWALK_SCORING_MAX_DISTANCE_M:
            return False
    return True


def label_value(label_type, severity):
    if label_type in FIXED_VALUE_LABEL_TYPES:
        return FIXED_VALUE_LABEL_TYPES[label_type]
    if label_type in SEVERITY_SCALED_LABEL_TYPES:
        best, worst = SEVERITY_SCALED_LABEL_TYPES[label_type]
        sev = severity if severity is not None else (SEVERITY_MIN + SEVERITY_MAX) / 2
        sev = min(max(sev, SEVERITY_MIN), SEVERITY_MAX)
        frac = (sev - SEVERITY_MIN) / (SEVERITY_MAX - SEVERITY_MIN)
        return best + frac * (worst - best)
    raise ValueError(f"non-informative or unrecognized label_type: {label_type!r}")


def label_polarity(label_type):
    if label_type in POSITIVE_LABEL_TYPES:
        return "positive"
    if label_type in HAZARD_LABEL_TYPES:
        return "hazard"
    raise ValueError(f"non-informative or unrecognized label_type: {label_type!r}")


def evidence_domain(label_type):
    if label_type in CROSSING_EVIDENCE_TYPES:
        return "crossing"
    if label_type in SEGMENT_EVIDENCE_TYPES:
        return "segment"
    raise ValueError(f"non-informative or unrecognized label_type: {label_type!r}")


def domain_discount(label_type, segment_highway_type, cross_domain_discount=CROSS_DOMAIN_DISCOUNT):
    """1.0 when the label's evidence domain matches what the segment
    physically is (crossing evidence on a crossing segment, segment
    evidence on a footway/path/pedestrian/steps segment); otherwise
    cross_domain_discount. segment_highway_type=None (unknown) is treated
    as a mismatch -- conservative, not a free pass. cross_domain_discount is
    parameterized (not just a global lookup) so scripts/sensitivity_analysis.py
    can sweep it without mutating module state."""
    domain = evidence_domain(label_type)
    segment_domain = "crossing" if segment_highway_type == "crossing" else "segment"
    return 1.0 if domain == segment_domain else cross_domain_discount


def agreement_weight(agree_count, disagree_count, unsure_count):
    """Laplace-smoothed agreement fraction: never exactly 0 or 1, so a single
    validation doesn't produce an overconfident weight."""
    return (agree_count + 1) / (agree_count + disagree_count + unsure_count + 2)


def recency_weight(label_date, as_of):
    if label_date is None:
        return 0.5  # unknown age: conservative middle ground, not full trust
    age_years = (as_of - label_date).days / 365.25
    age_years = max(age_years, 0.0)
    return 0.5 ** (age_years / RECENCY_HALF_LIFE_YEARS)


def match_quality(match_method, match_distance_m, threshold=PRODUCTION_MATCH_THRESHOLD_M):
    if match_method == "ps_osm_way_id":
        return 1.0  # Project Sidewalk's own authoritative id join
    return max(0.0, 1.0 - (match_distance_m / threshold))


def base_label_reliability(label, as_of, segment_highway_type=None, cross_domain_discount=CROSS_DOMAIN_DISCOUNT):
    """Per-label reliability *before* the non-independence discount (which
    needs to see the whole group of a segment's labels, not just one)."""
    r = agreement_weight(label["agree_count"], label["disagree_count"], label["unsure_count"])
    r *= recency_weight(label["label_date"], as_of)
    r *= match_quality(label["match_method"], label["match_distance_m"])
    if label.get("ambiguous_match"):
        r *= AMBIGUITY_CONFIDENCE_PENALTY
    r *= domain_discount(label["label_type"], segment_highway_type, cross_domain_discount)
    return r


def label_reliability(label, as_of, segment_highway_type=None, cross_domain_discount=CROSS_DOMAIN_DISCOUNT):
    """Public single-label reliability, for callers/tests that don't need
    non-independence grouping (e.g. comparing one label in isolation)."""
    return base_label_reliability(label, as_of, segment_highway_type, cross_domain_discount)


def deduplicate_labels(labels, as_of, segment_highway_type=None, cross_domain_discount=CROSS_DOMAIN_DISCOUNT):
    """Returns [(label, effective_reliability), ...] with reliabilities
    discounted for likely non-independent duplicates: within each
    (label_type, pano_id) group, only the most-reliable label counts in
    full, the rest count at NON_INDEPENDENCE_DISCOUNT of their own
    reliability. Labels with no pano_id (shouldn't happen post-backfill,
    but defensively) are never grouped -- treated as their own group of one."""
    groups = {}
    order = []
    for label in labels:
        pano_id = label.get("pano_id")
        key = (label["label_type"], pano_id) if pano_id else (label["label_type"], id(label))
        groups.setdefault(key, []).append(label)
        order.append(label)

    reliability_by_label_id = {}
    for group in groups.values():
        scored = [
            (label, base_label_reliability(label, as_of, segment_highway_type, cross_domain_discount))
            for label in group
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        for rank, (label, r) in enumerate(scored):
            effective = r if rank == 0 else r * NON_INDEPENDENCE_DISCOUNT
            reliability_by_label_id[id(label)] = effective

    return [(label, reliability_by_label_id[id(label)]) for label in order]


def _neutral_unknown_result():
    return {
        "accessibility_score": 0.5,
        "confidence_score": 0.0,
        "coverage_status": "unknown",
        "label_count": 0,
        "staleness_days": None,
        "positive_evidence": 0.0,
        "negative_evidence": 0.0,
        "evidence_consistency": None,
        "dominant_hazard_type": None,
        "dominant_hazard_ps_label_id": None,
    }


def score_segment(
    labels,
    as_of,
    segment_highway_type=None,
    reliability_dominance_cutoff=RELIABILITY_DOMINANCE_CUTOFF,
    cross_domain_discount=CROSS_DOMAIN_DISCOUNT,
):
    """Production scoring model (E): ceiling-capped risk accumulation.
    See module docstring for the full derivation.

    labels: matched (segment_id is not null) labels for one segment, each a
    dict with label_type, severity, agree_count, disagree_count,
    unsure_count, label_date, match_method, match_distance_m,
    ambiguous_match, pano_id, and optionally ps_label_id (used only to
    report which label set the dominance ceiling, for explainability).

    reliability_dominance_cutoff / cross_domain_discount default to the
    production constants but are accepted as parameters so
    scripts/sensitivity_analysis.py can sweep them without mutating module
    state (docs/week3_5_scoring_review.md's sensitivity-check section).

    Returns accessibility_score, confidence_score, coverage_status,
    label_count, staleness_days, positive_evidence, negative_evidence,
    evidence_consistency, dominant_hazard_type, dominant_hazard_ps_label_id.
    """
    informative = [l for l in labels if is_informative(l)]
    if not informative:
        return _neutral_unknown_result()

    weighted = deduplicate_labels(informative, as_of, segment_highway_type, cross_domain_discount)

    positive_evidence = sum(r for l, r in weighted if label_polarity(l["label_type"]) == "positive")
    negative_evidence = sum(r for l, r in weighted if label_polarity(l["label_type"]) == "hazard")

    risk_product = 1.0
    support_product = 1.0
    ceiling = 1.0
    dominant_hazard_type = None
    dominant_hazard_ps_label_id = None

    for label, r in weighted:
        value = label_value(label["label_type"], label["severity"])
        if label_polarity(label["label_type"]) == "hazard":
            hazard_fraction = 1 - value
            risk_product *= (1 - r * hazard_fraction)
            if r >= reliability_dominance_cutoff:
                # Once a hazard clears the reliability bar, it caps the score
                # at its own value directly -- not a blend that still leaves
                # room above the hazard's value in proportion to r. A blended
                # cap (e.g. 1 - r*hazard_fraction) undershoots "near zero" for
                # a realistic "reliable" label: agreement-smoothing, recency
                # decay and match-quality compound multiplicatively, so even
                # a fresh, unanimously-agreed, tightly-matched label rarely
                # has r above ~0.75 -- a NoSidewalk label at r=0.75 would cap
                # at 1-0.75*0.95=0.29 under a blend, nowhere near zero, and
                # that's the *good* case. Clearing the reliability bar is the
                # trust decision; once trusted, the hazard's own value is the
                # cap, full stop.
                label_ceiling = value
                if label_ceiling < ceiling:
                    ceiling = label_ceiling
                    dominant_hazard_type = label["label_type"]
                    dominant_hazard_ps_label_id = label.get("ps_label_id")
        else:
            support_product *= (1 - r * value)

    risk = 1 - risk_product
    support = 1 - support_product
    base_score = min(max(0.5 + 0.5 * support - 0.5 * risk, 0.0), 1.0)
    accessibility_score = min(base_score, ceiling)

    evidence_quantity = positive_evidence + negative_evidence
    if evidence_quantity > 0:
        evidence_consistency = abs(positive_evidence - negative_evidence) / evidence_quantity
        confidence_score = (1 - math.exp(-evidence_quantity / CONFIDENCE_EVIDENCE_SCALE)) * evidence_consistency
    else:
        # Every label discounted to exactly 0 reliability (pathological).
        evidence_consistency = None
        confidence_score = 0.0

    most_recent = max((l["label_date"] for l in informative if l["label_date"] is not None), default=None)
    staleness_days = (as_of - most_recent).days if most_recent is not None else None

    return {
        "accessibility_score": accessibility_score,
        "confidence_score": confidence_score,
        "coverage_status": "labeled",
        "label_count": len(informative),
        "staleness_days": staleness_days,
        "positive_evidence": positive_evidence,
        "negative_evidence": negative_evidence,
        "evidence_consistency": evidence_consistency,
        "dominant_hazard_type": dominant_hazard_type,
        "dominant_hazard_ps_label_id": dominant_hazard_ps_label_id,
    }


# ---------------------------------------------------------------------------
# Comparison models (Week 3.5 review) -- not used in production, kept for
# scripts/compare_scoring_models.py and regression tests. See
# docs/week3_5_scoring_review.md for the full comparison and why E won.
# ---------------------------------------------------------------------------

def score_segment_weighted_average(labels, as_of, segment_highway_type=None):
    """Model A: the original Week 3 model. A plain reliability-weighted
    average -- kept only for comparison, since this is exactly the "numerous
    positive labels can dilute one severe reliable hazard" behavior that
    Week 3.5 was asked to fix."""
    informative = [l for l in labels if is_informative(l)]
    if not informative:
        return 0.5, 0.0

    weighted = deduplicate_labels(informative, as_of, segment_highway_type)
    total_r = sum(r for _, r in weighted)
    if total_r <= 0:
        return 0.5, 0.0
    weighted_values = sum(r * label_value(l["label_type"], l["severity"]) for l, r in weighted)
    accessibility_score = weighted_values / total_r
    confidence_score = 1 - math.exp(-total_r / CONFIDENCE_EVIDENCE_SCALE)
    return accessibility_score, confidence_score


def score_segment_min_aggregation(labels, as_of, segment_highway_type=None):
    """Model B: worst-reliable-label aggregation. Take the minimum value
    among labels whose reliability clears RELIABILITY_DOMINANCE_CUTOFF; if
    none qualify, fall back to the reliability-weighted average (there's no
    "worst reliable" answer to give, so approximate as best-effort)."""
    informative = [l for l in labels if is_informative(l)]
    if not informative:
        return 0.5

    weighted = deduplicate_labels(informative, as_of, segment_highway_type)
    qualifying = [(l, r) for l, r in weighted if r >= RELIABILITY_DOMINANCE_CUTOFF]
    if not qualifying:
        acc, _ = score_segment_weighted_average(labels, as_of, segment_highway_type)
        return acc
    return min(label_value(l["label_type"], l["severity"]) for l, r in qualifying)


def score_segment_risk_only(labels, as_of, segment_highway_type=None):
    """Model D: same risk-accumulation base_score as the production model,
    but without the hard dominance ceiling -- shows that the graduated
    model alone still lets enough positive evidence claw a score up past
    what one dominant hazard alone would justify."""
    informative = [l for l in labels if is_informative(l)]
    if not informative:
        return 0.5

    weighted = deduplicate_labels(informative, as_of, segment_highway_type)
    risk_product = 1.0
    support_product = 1.0
    for label, r in weighted:
        value = label_value(label["label_type"], label["severity"])
        if label_polarity(label["label_type"]) == "hazard":
            risk_product *= (1 - r * (1 - value))
        else:
            support_product *= (1 - r * value)
    risk = 1 - risk_product
    support = 1 - support_product
    return min(max(0.5 + 0.5 * support - 0.5 * risk, 0.0), 1.0)

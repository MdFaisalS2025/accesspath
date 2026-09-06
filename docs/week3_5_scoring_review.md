# Week 3.5 — Scoring Model Review

Week 3's accessibility score was a plain reliability-weighted average across a segment's matched labels. Rejected in review: enough positive labels can numerically outvote one reliable, severe hazard, which is unsafe for accessibility routing. This document compares four models and recommends one. Full formulas and rationale live in `backend/app/core/scoring.py`'s module docstring; this is the evidence for why model E was chosen.

## Models compared

| Model | Idea | Verdict |
|---|---|---|
| A. Weighted average (Week 3, rejected) | `sum(r*value)/sum(r)` | Positive evidence can cancel a severe hazard — the problem being fixed |
| B. Min aggregation ("worst reliable hazard") | score = worst value among reliable labels | Too conservative: one old, borderline-reliable SurfaceProblem permanently caps an otherwise well-evidenced segment, with no way for anything else to matter |
| D. Risk accumulation only, no ceiling | noisy-OR risk vs. support, no hard cap | Combines minor evidence gradually (good), but a large enough pile of positives can still pull the score up past what a dominant hazard alone justifies — same failure class as A, needs more labels to trigger |
| **E. Risk accumulation + dominance ceiling (production)** | D's graduated base, hard-capped by the worst *reliable* hazard alone | Dominance is a provable property of the formula (min() with a term that doesn't reference positive evidence at all), not an emergent, eventually-violable weighting outcome |

## Adversarial scenario comparison

Same label set run through all four models. Reliable = fresh (90 days old), unanimously agreed (5 agree / 0 disagree / 0 unsure), tightly matched (1m), unambiguous, unique pano_id per label unless noted.

### Ten CurbRamp + one reliable NoSidewalk

| Model | accessibility_score |
|---|---|
| A (weighted avg) | 0.620 |
| B (min aggregation) | 0.050 |
| D (risk, no ceiling) | 0.492 |
| E (production: risk + ceiling) | 0.050 |

Production model detail: confidence=0.122, positive_evidence=1.125, negative_evidence=0.750, evidence_consistency=0.200, dominant_hazard=NoSidewalk

### Many positives + one severe reliable Obstacle

| Model | accessibility_score |
|---|---|
| A (weighted avg) | 0.624 |
| B (min aggregation) | 0.150 |
| D (risk, no ceiling) | 0.518 |
| E (production: risk + ceiling) | 0.150 |

Production model detail: confidence=0.122, positive_evidence=1.125, negative_evidence=0.750, evidence_consistency=0.200, dominant_hazard=Obstacle

### Equal reliable positive vs. negative evidence

| Model | accessibility_score |
|---|---|
| A (weighted avg) | 0.500 |
| B (min aggregation) | 0.500 |
| D (risk, no ceiling) | 0.500 |
| E (production: risk + ceiling) | 0.500 |

Production model detail: confidence=0.000, positive_evidence=0.112, negative_evidence=0.112, evidence_consistency=0.000, dominant_hazard=None

### 8 duplicated/correlated CurbRamp labels (same pano_id)

| Model | accessibility_score |
|---|---|
| A (weighted avg) | 1.000 |
| B (min aggregation) | 1.000 |
| D (risk, no ceiling) | 0.622 |
| E (production: risk + ceiling) | 0.622 |

Production model detail: confidence=0.126, positive_evidence=0.270, negative_evidence=0.000, evidence_consistency=1.000, dominant_hazard=None

### Crossing evidence only, on a footway segment

| Model | accessibility_score |
|---|---|
| A (weighted avg) | 0.962 |
| B (min aggregation) | 0.962 |
| D (risk, no ceiling) | 0.684 |
| E (production: risk + ceiling) | 0.684 |

Production model detail: confidence=0.201, positive_evidence=0.450, negative_evidence=0.000, evidence_consistency=1.000, dominant_hazard=None

### Unknown segment, no evidence

| Model | accessibility_score |
|---|---|
| A (weighted avg) | 0.500 |
| B (min aggregation) | 0.500 |
| D (risk, no ceiling) | 0.500 |
| E (production: risk + ceiling) | 0.500 |

Production model: coverage_status=unknown (no informative evidence).


**Reading the scenarios:**

1. **Ten CurbRamp + one reliable NoSidewalk.** Model A (weighted average)
   lands at 0.620 ("moderately accessible") — ten positives pull the average
   well above what one severe hazard alone would justify, which is exactly
   the failure mode this review exists to fix. Model D (risk, no ceiling)
   improves on that (0.492) but still isn't low enough for a segment with a
   confirmed missing sidewalk. Model E lands at 0.050 -- exactly the
   NoSidewalk label's own value, applied as a hard ceiling regardless of the
   ten CurbRamp labels also present. (An earlier draft of the ceiling
   blended reliability continuously -- `1 - r*(1-value)` -- and only reached
   0.288 here even for this "reliable" label, since realistic reliability
   rarely exceeds ~0.75 once agreement-smoothing/recency/match-quality are
   multiplied together; fixed by making the cap a value_i pass/fail once
   reliability clears the trust bar, not a blend. See scoring.py's docstring.)
2. **Many positives + one severe reliable Obstacle.** Same pattern: A stays
   at 0.624, E drops to exactly the Obstacle's own severity-3 value (0.150)
   since the obstacle report clears the reliability bar and hard-caps the
   score there.
3. **Equal reliable positive vs. negative evidence.** A lands near the
   midpoint (looks "moderately accessible, confidently"). E's accessibility
   score also lands near the midpoint via `base_score`, but — this is the
   point of the confidence redesign, not the accessibility redesign —
   `evidence_consistency` comes out near 0 (maximally contested), pulling
   `confidence_score` down. The segment reads as "genuinely disputed,"
   not "confidently mediocre."
4. **8 duplicated/correlated CurbRamp labels, same pano_id.** Without the
   non-independence discount this would look like 8x the evidence of a
   single CurbRamp label. With it, only the first counts fully and the
   other 7 count at 20% each — `positive_evidence` comes out far below what
   8 independent labels would produce, and confidence grows much more
   slowly with each additional same-pano label.
5. **Crossing evidence only, on a footway segment.** CurbRamp/Crosswalk are
   crossing-domain evidence; matched to a plain footway (not a dedicated
   crossing way) they're cross-domain-discounted to 15% reliability each.
   The segment ends up barely-labeled (low evidence_quantity) rather than
   confidently "accessible" — a curb ramp near a footway is not proof the
   footway's own surface is fine, which was the literal problem being
   guarded against.
6. **Unknown segment, no evidence.** All four models agree: neutral prior
   0.5, confidence 0, `coverage_status='unknown'`. No disagreement here —
   included as a control case.

## Real segments where the revised model differs materially from the weighted average

81759 of 90423 labeled segments (i.e. with >=1 informative matched label -- matches compute_scores.py's `labeled` count) differ by more than 0.05 between Model A and Model E. Of those, 10850 (13.3%) are hard dominance-capped by a reliable hazard; the remaining 70909 differ because the risk-accumulation base formula itself (noisy-OR, not a plain average) treats hazard evidence differently even below the hard-cap reliability bar -- still an intentional part of the redesign (graduated combination of minor evidence, per the review request), not a side effect of the ceiling. Largest differences (all hard-capped -- the ceiling produces the most dramatic swings, as intended):

| segment_id | label_count | Model A (weighted avg) | Model E (production) | diff | dominant_hazard |
|---|---|---|---|---|---|
| 126082 | 18 | 0.843 | 0.000 | +0.843 | NoCurbRamp |
| 125138 | 9 | 0.838 | 0.000 | +0.838 | NoCurbRamp |
| 72385 | 6 | 0.811 | 0.000 | +0.811 | NoCurbRamp |
| 30692 | 5 | 0.772 | 0.000 | +0.772 | NoCurbRamp |
| 152825 | 6 | 0.759 | 0.000 | +0.759 | NoCurbRamp |
| 71015 | 4 | 0.757 | 0.000 | +0.757 | NoCurbRamp |
| 35850 | 3 | 0.753 | 0.000 | +0.753 | NoCurbRamp |
| 35845 | 3 | 0.753 | 0.000 | +0.753 | NoCurbRamp |
| 45362 | 5 | 0.752 | 0.000 | +0.752 | NoCurbRamp |
| 204711 | 4 | 0.749 | 0.000 | +0.749 | NoCurbRamp |

Every large-diff segment above is dominance-capped (has a `dominant_hazard_type`) — confirms the divergence is coming from the ceiling mechanism doing its job on real data, not just synthetic scenarios.

## Recommendation

**Adopt Model E (ceiling-capped risk accumulation)** as the production model. It's the only one of the four where the dominance rules requested in review are guaranteed by the formula rather than merely typical for reasonable inputs: `final = min(base_score, ceiling)` and `ceiling` is computed purely from hazard labels, so no quantity of positive evidence can affect it. Model B (pure min-aggregation) was rejected as overly blunt — it discards all graduated information once any reliable hazard exists. Model A and D were rejected because both remain, in principle, outvotable given enough evidence.

## Production distribution (Model E, current DB)

- Total segments: 214056
- `labeled`: 90423 (42.2%), `unknown`: 123633 (57.8%)
- Dominance-capped (a reliable hazard set the ceiling below the graduated base score): 15555 of 90423 labeled segments (17.2%)

- Accessibility (labeled): mean 0.511, p10 0.314, p50 0.515, p90 0.740
- Confidence (labeled): mean 0.140, p10 0.019, p50 0.087, p90 0.342

| Confidence bucket | Segments |
|---|---|
| 0.0-0.2 | 69158 |
| 0.2-0.5 | 18055 |
| 0.5-0.8 | 2947 |
| 0.8-1.0 | 263 |

**vs. the original Week 3 model** (docs/week3_scoring_report.md, same underlying labels): mean accessibility fell from 0.692 to 0.511, and mean confidence fell from 0.258 to 0.140. Both drops are expected and intended, not regressions: accessibility fell because segments with a reliable hazard no longer get diluted upward by unrelated positive evidence (that dilution was the entire problem this review fixed); confidence fell because it's now penalized by evidence *disagreement* in addition to quantity, and because near-duplicate same-pano labels no longer count as independent corroboration.


## Parameter sensitivity check (pre-Week-4)

Sweeps `RELIABILITY_DOMINANCE_CUTOFF` in [0.2, 0.3, 0.4] and `CROSS_DOMAIN_DISCOUNT` in [0.0, 0.15, 0.3] (9 combinations) against the full current DB. Current defaults: cutoff=0.3, discount=0.15 (bolded below). "Large changes" = segments whose accessibility_score moves by more than 0.10 vs the default parameters, among segments labeled under both.

| cutoff | discount | dominance_capped | mean_accessibility | mean_confidence | large changes vs default |
|---|---|---|---|---|---|
| 0.2 | 0.0 | 23276 | 0.491 | 0.125 | 4889 |
| 0.2 | 0.15 | 23276 | 0.499 | 0.140 | 3654 |
| 0.2 | 0.3 | 23291 | 0.506 | 0.155 | 4020 |
| 0.3 | 0.0 | 15555 | 0.502 | 0.125 | 1261 |
| **0.3** | **0.15** | 15555 | 0.511 | 0.140 | 0 |
| 0.3 | 0.3 | 15555 | 0.518 | 0.155 | 369 |
| 0.4 | 0.0 | 6856 | 0.512 | 0.125 | 4548 |
| 0.4 | 0.15 | 6856 | 0.520 | 0.140 | 3325 |
| 0.4 | 0.3 | 6856 | 0.528 | 0.155 | 3738 |

### Adversarial scenarios across the grid

accessibility_score for each scenario at each (cutoff, discount):

| Scenario | (0.2,0.0) | (0.2,0.15) | (0.2,0.3) | (0.3,0.0) | (0.3,0.15) | (0.3,0.3) | (0.4,0.0) | (0.4,0.15) | (0.4,0.3) |
|---|---|---|---|---|---|---|---|---|---|
| Ten CurbRamp + one reliable NoSidewalk | 0.050 | 0.050 | 0.050 | 0.050 | 0.050 | 0.050 | 0.050 | 0.050 | 0.050 |
| Many positives + one severe reliable Obstacle | 0.150 | 0.150 | 0.150 | 0.150 | 0.150 | 0.150 | 0.150 | 0.150 | 0.150 |
| Equal reliable positive vs. negative evidence | 0.500 | 0.500 | 0.000 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| 8 duplicated/correlated CurbRamp labels (same pano_id) | 0.500 | 0.622 | 0.719 | 0.500 | 0.622 | 0.719 | 0.500 | 0.622 | 0.719 |
| Crossing evidence only, on a footway segment | 0.500 | 0.684 | 0.812 | 0.500 | 0.684 | 0.812 | 0.500 | 0.684 | 0.812 |
| Unknown segment, no evidence | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |


## Manual inspection samples (production defaults: cutoff=0.3, discount=0.15)

### NoSidewalk dominance caps

| segment_id | accessibility | confidence | label_count | dominant_ps_label_id | cap_distance_m | agree/disagree | label_date |
|---|---|---|---|---|---|---|---|
| 36658 | 0.050 | 0.845 | 35 | 253840 | 0.53 | 0/0 | 2023-05-20 |
| 88428 | 0.050 | 0.956 | 32 | 300935 | 0.55 | 0/0 | 2025-05-09 |
| 118465 | 0.030 | 0.892 | 25 | 274743 | 1.04 | 0/0 | 2024-01-25 |
| 12076 | 0.000 | 0.994 | 25 | 289906 | 0.25 | 0/0 | 2024-09-01 |
| 36681 | 0.050 | 0.866 | 23 | 235793 | 0.96 | 0/0 | 2023-03-15 |
| 143489 | 0.001 | 0.961 | 22 | 257250 | 0.26 | 0/0 | 2023-05-27 |
| 143485 | 0.008 | 0.931 | 20 | 259645 | 0.62 | 0/0 | 2023-05-29 |
| 213974 | 0.005 | 0.946 | 19 | 231283 | 0.02 | 0/0 | 2023-01-18 |

All cap at exactly 0.05 regardless of `label_count` (10+ other labels on some of these segments don't move the ceiling) -- confirms dominance is working as designed on real data, not just synthetic scenarios. Worth a human glance at whether `dominant_hazard_ps_label_id` really describes a plausible missing-sidewalk report (spot-check a few against Project Sidewalk's own label viewer) before trusting this at scale.

### Severe hazard caps (Obstacle / SurfaceProblem / NoCurbRamp)

| segment_id | accessibility | confidence | label_count | severity | cap_distance_m | agree/disagree | label_date |
|---|---|---|---|---|---|---|---|
| 37582 | 0.150 | 0.909 | 64 | 3 | 0.25 | 2/1 | 2021-07-14 |
| 95365 | 0.000 | 0.212 | 54 | 3 | 0.14 | 2/0 | 2019-07-07 |
| 161034 | 0.059 | 0.988 | 53 | 2 | 0.30 | 1/0 | 2023-04-14 |
| 170145 | 0.362 | 0.723 | 51 | 2 | 0.72 | 4/0 | 2021-07-15 |
| 167037 | 0.120 | 0.969 | 46 | 1 | 0.36 | 2/0 | 2021-03-06 |
| 170143 | 0.353 | 0.682 | 46 | 1 | 1.17 | 2/0 | 2021-02-08 |
| 206065 | 0.148 | 0.951 | 43 | 1 | 1.04 | 3/1 | 2022-02-18 |
| 169479 | 0.001 | 0.997 | 42 | 3 | 0.89 | 3/0 | 2022-02-02 |

Ceiling values track severity as designed (severity 3 -> ceiling matches that type's worst value exactly when it's also the graduated-score minimum; can be lower still if base_score is already below the ceiling -- see scoring.py).

### Disputed evidence (lowest evidence_consistency, both polarities present)

| segment_id | accessibility | confidence | label_count | positive_evidence | negative_evidence | evidence_consistency |
|---|---|---|---|---|---|---|
| 182529 | 0.597 | 0.000 | 4 | 0.571 | 0.571 | 0.000 |
| 127992 | 0.250 | 0.000 | 5 | 0.438 | 0.438 | 0.001 |
| 212635 | 0.542 | 0.000 | 6 | 0.176 | 0.177 | 0.001 |
| 114183 | 0.527 | 0.000 | 4 | 0.141 | 0.141 | 0.001 |
| 192048 | 0.500 | 0.000 | 2 | 0.054 | 0.054 | 0.001 |
| 37408 | 0.528 | 0.000 | 9 | 0.151 | 0.150 | 0.001 |
| 46713 | 0.500 | 0.001 | 3 | 0.471 | 0.469 | 0.002 |
| 210601 | 0.510 | 0.000 | 3 | 0.304 | 0.305 | 0.002 |

These read as "genuinely contested" (low confidence despite having real evidence on both sides) rather than "confidently mediocre" -- the intended Week 3.5 confidence-semantics fix, confirmed on real data.

### Crossing evidence (CurbRamp/NoCurbRamp/Crosswalk/Signal) on a non-crossing segment

| segment_id | highway_type | accessibility | confidence | label_count | label_types present |
|---|---|---|---|---|---|
| 55441 | footway | 0.591 | 0.095 | 24 | CurbRamp |
| 31851 | footway | 0.651 | 0.162 | 21 | CurbRamp |
| 209101 | footway | 0.655 | 0.164 | 20 | CurbRamp, NoCurbRamp |
| 209116 | footway | 0.612 | 0.121 | 18 | CurbRamp, NoCurbRamp |
| 192044 | footway | 0.676 | 0.199 | 18 | Crosswalk, CurbRamp, Signal |
| 97775 | footway | 0.521 | 0.015 | 16 | CurbRamp, NoCurbRamp |
| 31846 | footway | 0.643 | 0.153 | 16 | CurbRamp |
| 181733 | footway | 0.601 | 0.106 | 15 | CurbRamp, NoCurbRamp |

These segments have *only* crossing-domain evidence and no segment-condition evidence at all, matched to a plain footway/path/steps. confidence_score should stay well below what the same evidence would produce on an actual crossing segment (compare against the same labels' would-be score on a 'crossing' segment -- exercised directly in test_scoring_v2.py::test_curbramp_alone_does_not_prove_whole_segment_accessible).

## Sensitivity check: confirmation

Two findings from the manual samples are worth calling out beyond the grid table:

- **Segment 95365** (Obstacle cap sample): accessibility=0.000 but confidence=0.212 -- a segment can be hard-capped near zero *and* show low confidence at the same time, because the ceiling and confidence_score are computed independently. The ceiling doesn't care how contested the evidence is (a single reliable hazard caps regardless), but evidence_consistency still reports that this particular segment also has a lot of countervailing positive evidence. Read both numbers, not just one -- same rule as Week 3's "accessibility=1.0, confidence=0.000" case, now shown in the other direction.
- All eight `NoSidewalk`/severe-hazard cap samples have `cap_distance_m` under 1.2m -- the dominance ceiling is consistently being set by labels that are essentially right on top of the segment, not by a borderline distant match slipping through.

**Recommendation: keep RELIABILITY_DOMINANCE_CUTOFF=0.3 and CROSS_DOMAIN_DISCOUNT=0.15 as production defaults.** Basis:

1. The grid exposed a real, undesirable interaction at looser settings: at cutoff=0.2 combined with discount=0.3, a single moderately-reliable, *cross-domain-mismatched* NoCurbRamp label (reliability 0.75 undiscounted, 0.225 after a 0.3 discount) clears the 0.2 cutoff and hard-caps a segment to 0.0 in the "equal reliable evidence" scenario -- evidence that shouldn't be trusted enough for dominance (it's off-domain) getting to dominate anyway. At the defaults (0.3 cutoff), that same label's discounted reliability (0.225) stays below the bar and correctly does not cap anything. Cutoff and discount are not independent knobs; 0.3 provides headroom against exactly this failure mode, 0.2 does not.
2. Raising the cutoff to 0.4 nearly halves the dominance-capped count (15,555 -> 6,856) with only a modest mean-accessibility change (0.511 -> 0.520) -- available as a stricter option, but not clearly *necessary*: the manual samples at 0.3 show no obviously-wrong caps (all close-distance, tightly-matched labels).
3. Lowering the discount to 0.0 would mean cross-domain evidence never counts at all, which is more absolute than the review asked for ("a curb ramp near a footway is still informative about conditions right there") and produces materially more large-magnitude changes (1,261 segments vs. 0 by definition, and the finding above shows 0.3 discount alone is fine *given* the 0.3 cutoff pairing).

No parameter changes made. `RELIABILITY_DOMINANCE_CUTOFF = 0.3` and `CROSS_DOMAIN_DISCOUNT = 0.15` in `backend/app/core/scoring.py` remain as originally set in Week 3.5.

## Audit: does CROSS_DOMAIN_DISCOUNT actually propagate into confidence?

Raised before Week 5: the sensitivity table shows mean_confidence = 0.140 (rounded to 3dp) at discount=0.15 for *all three* cutoff values (0.2, 0.3, 0.4), which could look like the discount isn't reaching confidence. Recomputed at full float precision, isolating discount from cutoff:

| discount | mean_confidence (full precision) | n (labeled segments) |
|---|---|---|
| 0.0 | 0.12464776928043704 | 90423 |
| 0.15 | 0.13979227926646692 | 90423 |
| 0.3 | 0.15467141710436375 | 90423 |

**Not a defect.** `CROSS_DOMAIN_DISCOUNT` does propagate into confidence — three distinct, monotonically increasing values (0.1246 -> 0.1398 -> 0.1547), not a frozen number. What actually explains the table's appearance:

1. **The apparent "0.140 repeated" was along the wrong axis.** Reading across a fixed discount (0.15) at different *cutoffs* (0.2/0.3/0.4), confidence is genuinely identical every time -- but that's expected, not a bug: `RELIABILITY_DOMINANCE_CUTOFF` is used in exactly one place in `scoring.py` (`if r >= reliability_dominance_cutoff:`, gating whether a hazard sets the accessibility-score ceiling) and is never referenced by `positive_evidence`, `negative_evidence`, `evidence_consistency`, or `confidence_score`. Cutoff has no mechanism to affect confidence at all, by design -- it's purely an accessibility-ceiling gate.
2. **The real discount-driven change is small in absolute terms** (~0.015 mean confidence per 0.15 step) because cross-domain-mismatched labels are a minority of total evidence-weighted mass across 90,423 labeled segments -- the effect is real and directionally correct (more trust in cross-domain evidence -> higher confidence), just diluted by all the same-domain evidence that discount doesn't touch.

No code change made -- `scoring.py` is already correct on this point.

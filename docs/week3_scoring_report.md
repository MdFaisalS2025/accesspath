# Week 3 — Accessibility & Confidence Scoring Report

Implementation: `backend/app/core/scoring.py` (pure, unit-tested, no DB dependency) + `backend/scripts/compute_scores.py` (DB I/O, run via `docker compose exec api python scripts/compute_scores.py`). Unit tests: `backend/tests/test_scoring.py`. This report documents the formulas and the resulting distribution against the current DB.

## Formulas

### Accessibility score (0 worst – 1 best)

Reliability-weighted average of each matched, informative label's `value` for that segment:

```
accessibility_score = sum(reliability_i * value_i) / sum(reliability_i)
```

`value` by label_type (severity-scaled types interpolate linearly, severity 1–3):

| label_type | value |
|---|---|
| CurbRamp | 1.0 |
| Crosswalk | 0.85 |
| Signal | 0.9 |
| NoSidewalk | 0.05 |
| NoCurbRamp | 0.5 (severity 1) → 0.0 (severity 3) |
| SurfaceProblem | 0.8 (severity 1) → 0.3 (severity 3) |
| Obstacle | 0.7 (severity 1) → 0.15 (severity 3) |

`Occlusion`/`Other` carry no accessibility signal and are excluded entirely. `NoSidewalk` is fixed (Project Sidewalk never records its severity) and deliberately scored near-worst, not zero, since a missing-sidewalk report is severe but not usually literally impassable.

### Per-label reliability (drives both scores)

```
reliability = agreement_weight * recency_weight * match_quality * ambiguity_penalty

agreement_weight = (agree_count + 1) / (agree_count + disagree_count + unsure_count + 2)
recency_weight   = 0.5 ** (age_years / 6.0)
match_quality    = 1.0                          if osm_way_id-matched
                 = max(0, 1 - distance_m / 10)   if nearest-segment-matched
ambiguity_penalty = 0.5 if ambiguous_match else 1.0
```

### Confidence score (0 no evidence – 1 well-attested)

```
effective_evidence = sum(reliability_i) over informative matched labels
confidence_score = 1 - exp(-effective_evidence / 2.0)
```

**Calibration note:** an earlier version computed `volume_factor(effective_evidence) * avg_reliability`, which is wrong — multiplying by the *average* per-label reliability caps confidence at that average forever, no matter how much evidence accumulates. Caught before finalizing because a real segment with 234 matched labels came out at confidence 0.44 under that formula, which is backwards. Summing reliability into one evidence quantity (used above) fixes it: that same segment now scores confidence ≈1.0 (see worked examples below).

### Safeguards carried over from Week 2.5

- **Unmatched labels are never scored** (only `segment_id IS NOT NULL` labels are fetched at all) — the 10m production threshold from Week 2.5 is unchanged here.
- **`NoSidewalk` gets an extra, tighter cutoff**: only counted toward scoring if `match_distance_m <= 5m` (vs the general 10m), since Week 2.5 found ~half of NoSidewalk's 10m-matched labels are still 5-10m out — too far to confidently say *this segment* is the one missing a sidewalk, since by definition there's no sidewalk-shaped feature for it to sit on.
- **`ambiguous_match` is applied**, not ignored: an ambiguous label's reliability is multiplied by 0.5 before it affects either score.
- **`component_id` is untouched by scoring** — it's a routing-time concern (`app.core.graph`), not a scoring input; component 0 means "largest component found," not "the whole Seattle network" (see that module's docstring).
- **Severity range corrected**: `schema.sql` documented severity as 1-5; the loaded Seattle extract only ever has 1-3 (`SEVERITY_MIN`/`SEVERITY_MAX` in `scoring.py`, schema comment fixed).

## Coverage

- Total segments: 214056
- `labeled` (>=1 informative matched label): 90423 (42.2%)
- `unknown` (no informative matched label -> accessibility_score=0.5 neutral prior, confidence_score=0.0): 123633 (57.8%)

## Accessibility score distribution (labeled segments only)

- Mean: 0.692
- p10: 0.050
- p50: 0.886
- p90: 1.000

## Confidence score distribution (labeled segments only)

- Mean: 0.258
- p10: 0.090
- p50: 0.210
- p90: 0.492

| Confidence bucket | Segments |
|---|---|
| 0.0-0.2 | 43368 |
| 0.2-0.5 | 38448 |
| 0.5-0.8 | 7751 |
| 0.8-1.0 | 856 |

**Reading this:** confidence is low for most labeled segments not because the pipeline is broken, but because most segments have only 1-2 matched labels (Project Sidewalk coverage is sparse relative to 214k segments) — `CONFIDENCE_EVIDENCE_SCALE = 2.0` in `scoring.py` means confidence only approaches 1.0 once a segment accumulates evidence equivalent to roughly two-plus reliable, agreeing, on-target labels. A low confidence_score on a `labeled` segment is a real, useful signal ("we have a little evidence, don't fully trust it"), distinct from `unknown` ("we have none") — routing/consumers must treat both as "don't rely on accessibility_score alone" but they are not the same situation.

## Worked examples (real segments from this run)

### Heavily-labeled segments (evidence should saturate confidence)

| segment_id | accessibility_score | confidence_score | label_count | staleness_days |
|---|---|---|---|---|
| 161484 | 0.795 | 1.000 | 234 | 1263 |
| 35587 | 0.771 | 0.825 | 102 | 1208 |
| 63637 | 0.509 | 0.933 | 74 | 1212 |

These are why the earlier `volume_factor * avg_reliability` formula was rejected: segment 161484's 234 labels now correctly reach confidence ≈1.0 instead of being capped at its average per-label reliability (~0.44).

### Single-label segments, best vs. worst case

| segment_id | accessibility_score | confidence_score | staleness_days |
|---|---|---|---|
| 192574 | 1.000 | 0.302 | 106 |
| 193536 | 1.000 | 0.300 | 163 |
| 27099 | 1.000 | 0.299 | 165 |
| 57451 | 0.300 | 0.000 | 502 |
| 49469 | 1.000 | 0.000 | 2041 |
| 198980 | 0.425 | 0.001 | 2146 |

First 3 rows: the best-case single label (fresh, unanimously agreed, tightly matched, unambiguous). Last 3: the worst-case single label (old, disputed, distant, and/or ambiguous). Both are `label_count = 1` with visibly different confidence — recency/agreement/match-quality/ambiguity all move the number even at the same label count, as intended.

Note row 49469: accessibility_score = 1.000 with confidence_score = 0.000 is not a bug. accessibility_score is *conditional on the evidence being trustworthy* (here, a single ~5.6-year-old CurbRamp label whose reliability has decayed to nearly nothing still divides out to its own value, 1.0, since it's the only vote); confidence_score is the separate, honest answer to "how much should you trust that number" — here, barely at all. Consumers must always read the two together, never accessibility_score alone.

import { GeoJSONFeatureCollection } from "../api/types";

// Mirrors backend/app/core/routing.py's thresholds exactly, so the map's
// "low confidence" / "disputed" layers agree with what a route explanation
// would call low-confidence/disputed for the same segment.
export const LOW_CONFIDENCE_THRESHOLD = 0.3;
export const DISPUTED_CONSISTENCY_THRESHOLD = 0.3;

/** Adds derived boolean `low_confidence` / `disputed` properties to each
 * segment feature from /segments, computed client-side from
 * confidence_score / evidence_consistency, so MapLibre's filter
 * expressions don't need null-safe numeric comparisons. */
export function annotateCoverageFeatures(collection: GeoJSONFeatureCollection): GeoJSONFeatureCollection {
  return {
    ...collection,
    features: collection.features.map((feature) => {
      const props = feature.properties;
      const confidence = props.confidence_score as number | null;
      const consistency = props.evidence_consistency as number | null;
      const isLabeled = props.coverage_status === "labeled";
      return {
        ...feature,
        properties: {
          ...props,
          low_confidence: isLabeled && confidence !== null && confidence < LOW_CONFIDENCE_THRESHOLD,
          disputed: consistency !== null && consistency !== undefined && consistency < DISPUTED_CONSISTENCY_THRESHOLD,
        },
      };
    }),
  };
}

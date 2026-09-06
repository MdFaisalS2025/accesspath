// Mirrors backend/app/core/route_service.py's response shapes exactly
// (see docs/week5_api_report.md for the authoritative examples this was
// written against).

export type RouteMode = "shortest" | "accessible" | "confidence_aware";

export const ROUTE_MODES: RouteMode[] = ["shortest", "accessible", "confidence_aware"];

export interface Coordinate {
  lat: number;
  lon: number;
}

export interface SnapInfo {
  node_id: number;
  snapped_lat: number;
  snapped_lon: number;
  snap_distance_m: number;
  component_id: number;
  adjusted_for_connectivity: boolean;
  nearest_unconstrained_node_id: number;
  nearest_unconstrained_distance_m: number;
}

export interface EndpointInfo {
  requested: Coordinate;
  snap: SnapInfo;
}

export interface HazardRef {
  segment_id: number;
  hazard_type: string;
}

export interface GeoJSONLineString {
  type: "LineString";
  coordinates: [number, number][];
}

export interface RouteCoverage {
  total_segments: number;
  labeled_segments: number;
  unknown_segments: number;
}

export interface RouteResult {
  mode: RouteMode;
  geometry: GeoJSONLineString;
  distance_m: number;
  estimated_travel_time_s: number;
  accessibility_score: number | null;
  min_accessibility_score: number | null;
  confidence_score: number | null;
  min_confidence_score: number | null;
  coverage: RouteCoverage;
  hazards: HazardRef[];
  unknown_segment_ids: number[];
  low_confidence_segment_ids: number[];
  disputed_segment_ids: number[];
  explanation: string;
}

export interface RouteCompareOk {
  status: "ok";
  origin: EndpointInfo;
  destination: EndpointInfo;
  disclaimer: string;
  routes: Record<RouteMode, RouteResult>;
  comparison_notes: string[];
}

export interface RouteCompareNoConnection {
  status: "no_connected_route";
  reason: string;
  origin: EndpointInfo;
  destination: EndpointInfo;
  disclaimer: string;
  origin_component_id: number;
  destination_component_id: number;
}

export type RouteCompareResponse = RouteCompareOk | RouteCompareNoConnection;

export interface ApiErrorBody {
  error: string;
  message: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;

  constructor(status: number, body: ApiErrorBody | null, message: string) {
    super(message);
    this.status = status;
    this.body = body;
    this.name = "ApiError";
  }
}

export interface GeoJSONFeatureCollection {
  type: "FeatureCollection";
  features: GeoJSONFeature[];
  count: number;
  truncated: boolean;
}

export interface GeoJSONFeature {
  type: "Feature";
  geometry: GeoJSONLineString | { type: "Point"; coordinates: [number, number] };
  properties: Record<string, unknown>;
}

export interface CoverageSummaryEntry {
  segment_count: number;
  mean_accessibility_score: number | null;
  mean_confidence_score: number | null;
  dominance_capped_count: number;
}

export interface CoverageSummary {
  bbox: { min_lon: number; min_lat: number; max_lon: number; max_lat: number };
  total_segments: number;
  dominance_capped_segments: number;
  by_coverage_status: Record<string, CoverageSummaryEntry>;
}

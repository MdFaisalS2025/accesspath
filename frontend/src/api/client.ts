import {
  ApiError,
  ApiErrorBody,
  CoverageSummary,
  DeploymentInfo,
  GeoJSONFeature,
  GeoJSONFeatureCollection,
  RouteCompareResponse,
} from "./types";

// Configurable per Week 6's requirement to keep the API base URL an env var,
// not hardcoded -- set at build time by Vite, overridden per-deployment via
// docker-compose.yml / .env (local) or the hosting platform's project
// settings (e.g. Vercel's VITE_API_BASE_URL, see docs/deployment.md).
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// A production build (import.meta.env.PROD, set by Vite's build command)
// that never had VITE_API_BASE_URL set at build time silently falls back to
// localhost:8000 above -- in a real deployment that's not "the backend is
// down," it's "this deployment was never configured," and a visitor's
// browser has no localhost:8000 to reach. Distinguishing the two here
// means the UI can show a clear configuration message instead of a
// misleading "server unavailable" one (see StatusMessage's status === -1
// branch). Local dev and the Docker Compose setup both set the env var
// (see docker-compose.yml's frontend.environment), so this is false there.
export const API_BASE_URL_MISCONFIGURED = import.meta.env.PROD && !import.meta.env.VITE_API_BASE_URL;

async function parseErrorBody(response: Response): Promise<ApiErrorBody | null> {
  try {
    const body = await response.json();
    if (body && typeof body === "object" && "error" in body) {
      return body as ApiErrorBody;
    }
    return null;
  } catch {
    return null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (API_BASE_URL_MISCONFIGURED) {
    // Fail before ever attempting a request to an unreachable localhost --
    // status -1 is a sentinel distinct from 0 (a real, reachable-in-theory
    // backend that didn't respond) so the UI can tell "misconfigured
    // deployment" apart from "backend is temporarily down."
    throw new ApiError(
      -1,
      null,
      "This deployment is missing its backend configuration (VITE_API_BASE_URL was not set at build time).",
    );
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch (networkError) {
    // fetch itself throws for DNS/connection failures -- this is the
    // "API unavailable" case the UI needs to distinguish from a 4xx/5xx.
    throw new ApiError(0, null, "Could not reach the AccessPath server.");
  }

  if (!response.ok) {
    const body = await parseErrorBody(response);
    throw new ApiError(response.status, body, body?.message ?? `Request failed (${response.status})`);
  }

  return (await response.json()) as T;
}

export function compareRoutes(
  originLat: number,
  originLon: number,
  destinationLat: number,
  destinationLon: number,
): Promise<RouteCompareResponse> {
  return request<RouteCompareResponse>("/route/compare", {
    method: "POST",
    body: JSON.stringify({
      origin_lat: originLat,
      origin_lon: originLon,
      destination_lat: destinationLat,
      destination_lon: destinationLon,
    }),
  });
}

function bboxParam(bbox: [number, number, number, number]): string {
  return bbox.join(",");
}

export function fetchSegments(bbox: [number, number, number, number]): Promise<GeoJSONFeatureCollection> {
  return request<GeoJSONFeatureCollection>(`/segments?bbox=${bboxParam(bbox)}`);
}

export function fetchLabels(bbox: [number, number, number, number]): Promise<GeoJSONFeatureCollection> {
  return request<GeoJSONFeatureCollection>(`/labels?bbox=${bboxParam(bbox)}`);
}

export function fetchCoverageSummary(bbox: [number, number, number, number]): Promise<CoverageSummary> {
  return request<CoverageSummary>(`/coverage-summary?bbox=${bboxParam(bbox)}`);
}

export function fetchSegmentGeometry(segmentId: number): Promise<GeoJSONFeature> {
  return request<GeoJSONFeature>(`/segments/${segmentId}`);
}

export function fetchDeploymentInfo(): Promise<DeploymentInfo> {
  return request<DeploymentInfo>("/deployment-info");
}

export { ApiError };

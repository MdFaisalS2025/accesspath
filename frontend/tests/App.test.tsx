import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/types";

vi.mock("maplibre-gl", async () => {
  const { MockMap, MockMarker } = await import("./maplibreMock");
  return {
    default: { Map: MockMap, Marker: MockMarker, NavigationControl: vi.fn(), AttributionControl: vi.fn() },
  };
});

vi.mock("../src/api/client", () => ({
  compareRoutes: vi.fn(),
  fetchSegments: vi.fn(),
  fetchLabels: vi.fn(),
  fetchSegmentGeometry: vi.fn(),
  fetchCoverageSummary: vi.fn(),
  ApiError,
}));

import { MockMap } from "./maplibreMock";
import App from "../src/App";
import * as client from "../src/api/client";

function clickMap(lat: number, lon: number) {
  const instance = MockMap.instances[MockMap.instances.length - 1];
  act(() => {
    instance.triggerClick({ lat, lng: lon });
  });
}

const SUCCESS_RESPONSE = {
  status: "ok" as const,
  origin: {
    requested: { lat: 47.6, lon: -122.33 },
    snap: {
      node_id: 1, snapped_lat: 47.6, snapped_lon: -122.33, snap_distance_m: 0,
      component_id: 0, adjusted_for_connectivity: false,
      nearest_unconstrained_node_id: 1, nearest_unconstrained_distance_m: 0,
    },
  },
  destination: {
    requested: { lat: 47.61, lon: -122.32 },
    snap: {
      node_id: 2, snapped_lat: 47.61, snapped_lon: -122.32, snap_distance_m: 40,
      component_id: 0, adjusted_for_connectivity: true,
      nearest_unconstrained_node_id: 3, nearest_unconstrained_distance_m: 12,
    },
  },
  disclaimer: "test disclaimer",
  comparison_notes: ["confidence_aware passes through more segments with a known issue than shortest"],
  routes: {
    shortest: {
      mode: "shortest" as const,
      geometry: { type: "LineString" as const, coordinates: [[-122.33, 47.6], [-122.32, 47.61]] as [number, number][] },
      distance_m: 420, estimated_travel_time_s: 350,
      accessibility_score: 0.53, min_accessibility_score: 0, confidence_score: 0.14, min_confidence_score: 0,
      coverage: { total_segments: 12, labeled_segments: 5, unknown_segments: 7 },
      hazards: [], unknown_segment_ids: [1, 2], low_confidence_segment_ids: [], disputed_segment_ids: [],
      explanation: "shortest route explanation",
    },
    accessible: {
      mode: "accessible" as const,
      geometry: { type: "LineString" as const, coordinates: [[-122.33, 47.6], [-122.325, 47.605], [-122.32, 47.61]] as [number, number][] },
      distance_m: 460, estimated_travel_time_s: 380,
      accessibility_score: 0.71, min_accessibility_score: 0.2, confidence_score: 0.18, min_confidence_score: 0,
      coverage: { total_segments: 14, labeled_segments: 8, unknown_segments: 6 },
      hazards: [{ segment_id: 55, hazard_type: "Obstacle" }], unknown_segment_ids: [], low_confidence_segment_ids: [3], disputed_segment_ids: [],
      explanation: "accessible route explanation",
    },
    confidence_aware: {
      mode: "confidence_aware" as const,
      geometry: { type: "LineString" as const, coordinates: [[-122.33, 47.6], [-122.325, 47.605], [-122.32, 47.61]] as [number, number][] },
      distance_m: 460, estimated_travel_time_s: 380,
      accessibility_score: 0.71, min_accessibility_score: 0.2, confidence_score: 0.3, min_confidence_score: 0.1,
      coverage: { total_segments: 14, labeled_segments: 9, unknown_segments: 5 },
      hazards: [{ segment_id: 55, hazard_type: "Obstacle" }], unknown_segment_ids: [], low_confidence_segment_ids: [], disputed_segment_ids: [],
      explanation: "confidence-aware route explanation",
    },
  },
};

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the initial idle state before any coordinates are selected", () => {
    render(<App />);
    expect(screen.getByText(/Click the map to place your origin/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /compare routes/i })).toBeDisabled();
  });

  it("shows the origin-selected state after one click", () => {
    render(<App />);
    clickMap(47.6, -122.33);
    expect(screen.getByText(/Origin placed/)).toBeInTheDocument();
  });

  it("enables Compare routes once both points are selected", () => {
    render(<App />);
    clickMap(47.6, -122.33);
    clickMap(47.61, -122.32);
    expect(screen.getByText(/Both points placed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /compare routes/i })).toBeEnabled();
  });

  it("shows a loading state while comparison is in flight", async () => {
    let resolvePromise: (v: Awaited<ReturnType<typeof client.compareRoutes>>) => void = () => {};
    vi.mocked(client.compareRoutes).mockReturnValue(new Promise((resolve) => (resolvePromise = resolve)));
    render(<App />);
    clickMap(47.6, -122.33);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));
    expect(await screen.findByText(/Comparing shortest, accessibility-optimized/)).toBeInTheDocument();

    // Resolve and wait for the resulting state update to fully settle before
    // the test ends -- otherwise React applies it after teardown, outside
    // any act() scope, which is what produced the "not wrapped in act"
    // warning here previously.
    resolvePromise(SUCCESS_RESPONSE);
    await waitFor(() => expect(screen.getByText(/Route comparison/)).toBeInTheDocument());
  });

  it("shows all three routes with distinguishing details on success", async () => {
    vi.mocked(client.compareRoutes).mockResolvedValue(SUCCESS_RESPONSE);
    render(<App />);
    clickMap(47.6, -122.33);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));

    await waitFor(() => expect(screen.getByText(/Route comparison/)).toBeInTheDocument());
    expect(screen.getByText(/solid line/)).toBeInTheDocument();
    expect(screen.getByText(/dashed line/)).toBeInTheDocument();
    expect(screen.getByText(/dotted line/)).toBeInTheDocument();
    expect(screen.getByText(/No known hazards documented/)).toBeInTheDocument(); // shortest has none
  });

  it("discloses a connectivity snap adjustment with distance and unconstrained comparison", async () => {
    vi.mocked(client.compareRoutes).mockResolvedValue(SUCCESS_RESPONSE);
    render(<App />);
    clickMap(47.6, -122.33);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));

    await waitFor(() => expect(screen.getByText(/Route comparison/)).toBeInTheDocument());
    expect(screen.getByText(/40 m away/)).toBeInTheDocument();
    expect(screen.getByText(/12 m away.*not part of the same connected network/)).toBeInTheDocument();
  });

  it("flags identical route geometry between accessible and confidence_aware", async () => {
    vi.mocked(client.compareRoutes).mockResolvedValue(SUCCESS_RESPONSE);
    render(<App />);
    clickMap(47.6, -122.33);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));
    await waitFor(() => expect(screen.getByText(/Route comparison/)).toBeInTheDocument());
    expect(screen.getByText(/Identical to the Accessibility-optimized route/)).toBeInTheDocument();
  });

  it("shows an explicit no-connected-route state, not a generic error", async () => {
    vi.mocked(client.compareRoutes).mockResolvedValue({
      status: "no_connected_route",
      reason: "origin_and_destination_in_different_connected_components",
      origin: SUCCESS_RESPONSE.origin,
      destination: SUCCESS_RESPONSE.destination,
      disclaimer: "test",
      origin_component_id: 0,
      destination_component_id: 3,
    });
    render(<App />);
    clickMap(47.6, -122.33);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));
    expect(await screen.findByText(/No connected route found/)).toBeInTheDocument();
    expect(screen.getByText(/component 0 vs\. component 3/)).toBeInTheDocument();
  });

  it("shows a clear message for a point outside the service area", async () => {
    vi.mocked(client.compareRoutes).mockRejectedValue(
      new ApiError(400, { error: "out_of_service_area", message: "nope" }, "nope"),
    );
    render(<App />);
    clickMap(48.05, -122.3);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));
    expect(await screen.findByText(/Outside the supported area/)).toBeInTheDocument();
  });

  it("shows a clear message when no routable network is nearby", async () => {
    vi.mocked(client.compareRoutes).mockRejectedValue(
      new ApiError(400, { error: "no_routable_network", message: "nope", max_snap_distance_m: 75 }, "nope"),
    );
    render(<App />);
    clickMap(47.6, -122.4);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));
    expect(await screen.findByText(/No nearby routable path/)).toBeInTheDocument();
  });

  it("shows a server-unavailable message distinct from other errors", async () => {
    vi.mocked(client.compareRoutes).mockRejectedValue(new ApiError(0, null, "Could not reach the AccessPath server."));
    render(<App />);
    clickMap(47.6, -122.33);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));
    expect(await screen.findByText(/AccessPath server unavailable/)).toBeInTheDocument();
  });

  it("retrying a recoverable failure re-issues the same comparison request", async () => {
    vi.mocked(client.compareRoutes).mockRejectedValueOnce(new ApiError(0, null, "Could not reach the AccessPath server."));
    render(<App />);
    clickMap(47.6, -122.33);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));
    expect(await screen.findByText(/AccessPath server unavailable/)).toBeInTheDocument();
    expect(client.compareRoutes).toHaveBeenCalledTimes(1);

    vi.mocked(client.compareRoutes).mockResolvedValueOnce(SUCCESS_RESPONSE);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByText(/Route comparison/)).toBeInTheDocument());
    expect(client.compareRoutes).toHaveBeenCalledTimes(2);
  });

  it("resets selection and results on Clear selection", async () => {
    vi.mocked(client.compareRoutes).mockResolvedValue(SUCCESS_RESPONSE);
    render(<App />);
    clickMap(47.6, -122.33);
    clickMap(47.61, -122.32);
    fireEvent.click(screen.getByRole("button", { name: /compare routes/i }));
    await waitFor(() => expect(screen.getByText(/Route comparison/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /clear selection/i }));
    expect(screen.queryByText(/Route comparison/)).not.toBeInTheDocument();
    expect(screen.getByText(/Click the map to place your origin/)).toBeInTheDocument();
  });
});

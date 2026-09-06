// jsdom has no WebGL, so real maplibre-gl can't run in component tests.
// This mock provides just enough surface for MapView/App to mount and for
// tests to assert on marker/layer calls without a real map.
import { vi } from "vitest";

export class MockMap {
  static instances: MockMap[] = [];

  private handlers: Record<string, (() => void)[]> = {};

  constructor() {
    MockMap.instances.push(this);
  }

  on = vi.fn((event: string, handler: () => void) => {
    this.handlers[event] = this.handlers[event] ?? [];
    this.handlers[event].push(handler);
  });
  once = vi.fn((event: string, handler: () => void) => {
    handler();
  });
  off = vi.fn();
  addControl = vi.fn();
  addSource = vi.fn();
  removeSource = vi.fn();
  addLayer = vi.fn();
  removeLayer = vi.fn();
  getLayer = vi.fn(() => undefined);
  getSource = vi.fn(() => undefined);
  isStyleLoaded = vi.fn(() => true);
  getZoom = vi.fn(() => 12);
  flyTo = vi.fn();
  getBounds = vi.fn(() => ({
    getWest: () => -122.35,
    getSouth: () => 47.6,
    getEast: () => -122.33,
    getNorth: () => 47.62,
  }));
  remove = vi.fn();

  triggerClick(lngLat: { lng: number; lat: number }) {
    (this.handlers["click"] ?? []).forEach((h) => (h as (e: unknown) => void)({ lngLat }));
  }
}

export class MockMarker {
  setLngLat = vi.fn(() => this);
  addTo = vi.fn(() => this);
  remove = vi.fn();
}

// Usage in a test file (vi.mock is hoisted, so it must be called directly
// in the test file, not through this helper -- see RouteMap.test.tsx):
//
//   vi.mock("maplibre-gl", async () => {
//     const { MockMap, MockMarker } = await import("./maplibreMock");
//     return { default: { Map: MockMap, Marker: MockMarker, NavigationControl: vi.fn(), AttributionControl: vi.fn() } };
//   });

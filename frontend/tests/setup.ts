import "@testing-library/jest-dom/vitest";
import { toHaveNoViolations } from "jest-axe";
import { expect } from "vitest";

expect.extend(toHaveNoViolations);

// MapLibre GL requires a WebGL-capable canvas, which jsdom doesn't provide.
// Component tests that render <App> or <MapView> mock this module instead
// of trying to polyfill WebGL (see tests/mapMock.ts).

// jsdom doesn't implement ResizeObserver (used by MapView to keep the map
// canvas sized correctly -- see docs/week7_hardening_report.md). Real
// browsers all support it; this is a test-environment shim only.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

import { RouteMode } from "../api/types";

export interface RouteStyle {
  label: string;
  color: string;
  patternName: string;
  dashArray: number[] | null;
  lineCap: "round" | "butt";
  width: number;
}

// Okabe-Ito colorblind-safe triad, each also given a distinct line pattern
// and width so mode is never encoded by color alone (docs/week6_visual_system.md).
export const ROUTE_STYLES: Record<RouteMode, RouteStyle> = {
  shortest: {
    label: "Shortest",
    color: "var(--route-shortest)",
    patternName: "solid",
    dashArray: null,
    lineCap: "butt",
    width: 4,
  },
  accessible: {
    label: "Accessibility-optimized",
    color: "var(--route-accessible)",
    patternName: "dashed",
    dashArray: [10, 6],
    lineCap: "butt",
    width: 5,
  },
  confidence_aware: {
    label: "Confidence-aware",
    color: "var(--route-confidence-aware)",
    patternName: "dotted",
    dashArray: [2, 6],
    lineCap: "round",
    width: 5,
  },
};

// MapLibre wants hex/rgb, not CSS custom properties -- resolved copies for
// use as paint-property values.
export const ROUTE_COLORS_RESOLVED: Record<RouteMode, string> = {
  shortest: "#000000",
  accessible: "#0072B2",
  confidence_aware: "#D55E00",
};

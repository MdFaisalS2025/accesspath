import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./MapView.css";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { Coordinate, GeoJSONFeatureCollection, RouteCompareOk, RouteMode } from "../api/types";
import { ROUTE_COLORS_RESOLVED, ROUTE_STYLES } from "../lib/routeStyle";

// Free, key-less OSM raster tiles -- permitted for light development/demo
// use under OSMF's tile usage policy, with attribution (see the map's
// built-in AttributionControl, always on). See docs/week6_frontend_report.md
// for the basemap-choice rationale (no paid service, no API key).
const OSM_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

const SEATTLE_CENTER: [number, number] = [-122.3321, 47.6062];

export interface MapViewHandle {
  focusOnFeature: (feature: GeoJSONFeatureCollection["features"][number]) => void;
  getBounds: () => [number, number, number, number] | null;
}

interface MapViewProps {
  origin: Coordinate | null;
  destination: Coordinate | null;
  onMapClick: (coordinate: Coordinate) => void;
  routeResult: RouteCompareOk | null;
  selectedMode: RouteMode | null;
  coverageSegments: GeoJSONFeatureCollection | null;
  coverageLabels: GeoJSONFeatureCollection | null;
  coverageVisible: {
    labeled: boolean;
    unknown: boolean;
    lowConfidence: boolean;
    disputed: boolean;
    labels: boolean;
  };
}

const ROUTE_LAYER_ORDER: RouteMode[] = ["shortest", "accessible", "confidence_aware"];

export const MapView = forwardRef<MapViewHandle, MapViewProps>(function MapView(
  { origin, destination, onMapClick, routeResult, selectedMode, coverageSegments, coverageLabels, coverageVisible },
  ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const originMarkerRef = useRef<maplibregl.Marker | null>(null);
  const destinationMarkerRef = useRef<maplibregl.Marker | null>(null);
  const focusMarkerRef = useRef<maplibregl.Marker | null>(null);
  const onMapClickRef = useRef(onMapClick);
  onMapClickRef.current = onMapClick;

  useImperativeHandle(ref, () => ({
    focusOnFeature(feature) {
      const map = mapRef.current;
      if (!map || feature.geometry.type !== "LineString") return;
      const coords = feature.geometry.coordinates;
      const mid = coords[Math.floor(coords.length / 2)];
      if (focusMarkerRef.current) focusMarkerRef.current.remove();
      const el = document.createElement("div");
      el.className = "map-focus-marker";
      focusMarkerRef.current = new maplibregl.Marker({ element: el }).setLngLat(mid as [number, number]).addTo(map);
      map.flyTo({ center: mid as [number, number], zoom: Math.max(map.getZoom(), 17), essential: true });
    },
    getBounds() {
      const map = mapRef.current;
      if (!map) return null;
      const bounds = map.getBounds();
      return [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];
    },
  }));

  // Map init -- once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_STYLE,
      center: SEATTLE_CENTER,
      zoom: 12,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: false }));

    map.on("click", (event) => {
      onMapClickRef.current({ lat: event.lngLat.lat, lon: event.lngLat.lng });
    });

    // Week 7: reduces the blank/split-tile first-paint quirk observed
    // during Week 6 verification (docs/week6_frontend_report.md's
    // "remaining issues"). MapLibre sizes its canvas from the container's
    // dimensions *at construction time*; if the container's final layout
    // (flex/media-query) hadn't settled yet on that first paint, the
    // canvas could end up the wrong size until something else triggered a
    // resize. A ResizeObserver calls map.resize() whenever the container's
    // actual size changes -- covering both that initial-layout race and,
    // as a real secondary bug this incidentally fixes, the map never
    // resizing at all on a browser window resize or phone rotation
    // (MapLibre does not do this on its own).
    const resizeObserver = new ResizeObserver(() => map.resize());
    resizeObserver.observe(containerRef.current);

    mapRef.current = map;
    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Origin/destination markers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (originMarkerRef.current) {
      originMarkerRef.current.remove();
      originMarkerRef.current = null;
    }
    if (origin) {
      const el = document.createElement("div");
      el.className = "map-marker map-marker--origin";
      el.setAttribute("role", "img");
      el.setAttribute("aria-label", "Origin");
      el.textContent = "A";
      originMarkerRef.current = new maplibregl.Marker({ element: el }).setLngLat([origin.lon, origin.lat]).addTo(map);
    }

    if (destinationMarkerRef.current) {
      destinationMarkerRef.current.remove();
      destinationMarkerRef.current = null;
    }
    if (destination) {
      const el = document.createElement("div");
      el.className = "map-marker map-marker--destination";
      el.setAttribute("role", "img");
      el.setAttribute("aria-label", "Destination");
      el.textContent = "B";
      destinationMarkerRef.current = new maplibregl.Marker({ element: el })
        .setLngLat([destination.lon, destination.lat])
        .addTo(map);
    }
  }, [origin, destination]);

  // Route line layers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyLayers = () => {
      for (const mode of ROUTE_LAYER_ORDER) {
        const sourceId = `route-${mode}`;
        const casingId = `${sourceId}-casing`;
        const lineId = `${sourceId}-line`;

        if (map.getLayer(lineId)) map.removeLayer(lineId);
        if (map.getLayer(casingId)) map.removeLayer(casingId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);

        if (!routeResult) continue;

        const result = routeResult.routes[mode];
        const style = ROUTE_STYLES[mode];
        const isDimmed = selectedMode !== null && selectedMode !== mode;

        map.addSource(sourceId, {
          type: "geojson",
          data: { type: "Feature", geometry: result.geometry, properties: {} },
        });
        map.addLayer({
          id: casingId,
          type: "line",
          source: sourceId,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": "#ffffff",
            "line-width": style.width + 2,
            "line-opacity": isDimmed ? 0.25 : 0.9,
          },
        });
        map.addLayer({
          id: lineId,
          type: "line",
          source: sourceId,
          layout: { "line-cap": style.lineCap, "line-join": "round" },
          paint: {
            "line-color": ROUTE_COLORS_RESOLVED[mode],
            "line-width": style.width,
            "line-opacity": isDimmed ? 0.35 : 1,
            ...(style.dashArray ? { "line-dasharray": style.dashArray } : {}),
          },
        });
      }
    };

    if (map.isStyleLoaded()) {
      applyLayers();
    } else {
      map.once("load", applyLayers);
    }
  }, [routeResult, selectedMode]);

  // Coverage layers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const sourceId = "coverage-segments";
    const labelSourceId = "coverage-labels";

    const applyCoverage = () => {
      for (const id of ["coverage-labeled", "coverage-unknown", "coverage-low-confidence", "coverage-disputed"]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      if (map.getLayer("coverage-label-points")) map.removeLayer("coverage-label-points");
      if (map.getSource(sourceId)) map.removeSource(sourceId);
      if (map.getSource(labelSourceId)) map.removeSource(labelSourceId);

      if (!coverageSegments && !coverageLabels) return;

      map.addSource(sourceId, {
        type: "geojson",
        data: coverageSegments ?? { type: "FeatureCollection", features: [] },
      });
      map.addSource(labelSourceId, {
        type: "geojson",
        data: coverageLabels ?? { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "coverage-labeled",
        type: "line",
        source: sourceId,
        filter: ["==", ["get", "coverage_status"], "labeled"],
        layout: { visibility: coverageVisible.labeled ? "visible" : "none" },
        paint: { "line-color": "#2E7D32", "line-width": 3, "line-opacity": 0.55 },
      });
      map.addLayer({
        id: "coverage-unknown",
        type: "line",
        source: sourceId,
        filter: ["==", ["get", "coverage_status"], "unknown"],
        layout: { visibility: coverageVisible.unknown ? "visible" : "none" },
        paint: { "line-color": "#757575", "line-width": 3, "line-dasharray": [1, 2], "line-opacity": 0.6 },
      });
      map.addLayer({
        id: "coverage-low-confidence",
        type: "line",
        source: sourceId,
        filter: ["==", ["get", "low_confidence"], true],
        layout: { visibility: coverageVisible.lowConfidence ? "visible" : "none" },
        paint: { "line-color": "#6B4400", "line-width": 3, "line-dasharray": [4, 2], "line-opacity": 0.6 },
      });
      map.addLayer({
        id: "coverage-disputed",
        type: "circle",
        source: sourceId,
        filter: ["==", ["get", "disputed"], true],
        layout: { visibility: coverageVisible.disputed ? "visible" : "none" },
        paint: { "circle-color": "#8A1300", "circle-radius": 5, "circle-opacity": 0.7 },
      });
      map.addLayer({
        id: "coverage-label-points",
        type: "circle",
        source: labelSourceId,
        layout: { visibility: coverageVisible.labels ? "visible" : "none" },
        paint: { "circle-color": "#0B5FA5", "circle-radius": 3, "circle-opacity": 0.7 },
      });
    };

    if (map.isStyleLoaded()) {
      applyCoverage();
    } else {
      map.once("load", applyCoverage);
    }
  }, [coverageSegments, coverageLabels, coverageVisible]);

  return <div ref={containerRef} className="map-view" role="application" aria-label="Route map. Click to place origin and destination points." />;
});

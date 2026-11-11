import { useEffect, useRef, useState } from "react";
import maplibregl, {
  type GeoJSONSource,
  type Map as MapLibreMap,
  type StyleSpecification,
} from "maplibre-gl";
import type { EventFeatureCollection } from "../api/types";

export type MapLayer = {
  url: string;
  coordinates: [number, number][];
  name: string;
};

type MapViewProps = {
  events?: EventFeatureCollection | null;
  layer?: MapLayer | null;
  selectedEventId?: string | null;
  onSelectEvent?: (eventId: string) => void;
  height?: number | string;
  interactive?: boolean;
};

const DEFAULT_BOUNDS: [number, number, number, number] = [91.48, 25.98, 92.02, 26.4];

const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    {
      id: "background",
      type: "background",
      paint: { "background-color": "#071018" },
    },
    {
      id: "osm",
      type: "raster",
      source: "osm",
      paint: {
        "raster-opacity": 0.5,
        "raster-saturation": -0.72,
        "raster-contrast": 0.08,
        "raster-brightness-min": 0.02,
        "raster-brightness-max": 0.6,
      },
    },
  ],
};

const STAGE_COLORS: Record<string, string> = {
  CONFIRMED: "#8ee6a8",
  CLASSIFIED: "#f0c674",
  HYPOTHESIZED: "#c59bff",
  DETECTED: "#f08a5d",
  OBSERVED: "#79c9ff",
};

function withEventIds(collection: EventFeatureCollection): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: collection.features.map((feature) => ({
      type: "Feature",
      geometry: feature.geometry,
      properties: {
        ...feature.properties,
        event_id: feature.id,
        stage_color:
          STAGE_COLORS[String(feature.properties.taxonomy_stage).toUpperCase()] ||
          STAGE_COLORS.DETECTED,
      },
    })),
  };
}

function removeIfPresent(map: MapLibreMap, id: string, kind: "layer" | "source") {
  if (kind === "layer" && map.getLayer(id)) map.removeLayer(id);
  if (kind === "source" && map.getSource(id)) map.removeSource(id);
}

export function MapView({
  events,
  layer,
  selectedEventId,
  onSelectEvent,
  height = 460,
  interactive = true,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const selectRef = useRef(onSelectEvent);
  selectRef.current = onSelectEvent;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: [91.75, 26.19],
      zoom: 9.3,
      attributionControl: false,
      interactive,
    });
    mapRef.current = map;
    map.fitBounds(DEFAULT_BOUNDS, { padding: 40, duration: 0 });
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    if (interactive) {
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    }

    map.on("load", () => setReady(true));

    const handleClick = (event: maplibregl.MapMouseEvent) => {
      const layers = ["events-fill", "events-point"].filter((id) => map.getLayer(id));
      if (!layers.length) return;
      const [feature] = map.queryRenderedFeatures(event.point, { layers });
      const eventId = feature?.properties?.event_id;
      if (typeof eventId === "string") selectRef.current?.(eventId);
    };
    const handleMove = (event: maplibregl.MapMouseEvent) => {
      const layers = ["events-fill", "events-point"].filter((id) => map.getLayer(id));
      if (!layers.length) return;
      const features = map.queryRenderedFeatures(event.point, { layers });
      map.getCanvas().style.cursor = features.length ? "pointer" : "";
    };
    map.on("click", handleClick);
    map.on("mousemove", handleMove);

    const observer = new ResizeObserver(() => map.resize());
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      map.off("click", handleClick);
      map.off("mousemove", handleMove);
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, [interactive]);

  // Event source and layers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    if (!events || !events.features.length) {
      removeIfPresent(map, "events-point", "layer");
      removeIfPresent(map, "events-line", "layer");
      removeIfPresent(map, "events-fill", "layer");
      removeIfPresent(map, "events", "source");
      return;
    }

    const data = withEventIds(events);
    const source = map.getSource("events") as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.addSource("events", { type: "geojson", data });
      map.addLayer({
        id: "events-fill",
        type: "fill",
        source: "events",
        paint: {
          "fill-color": ["get", "stage_color"],
          "fill-opacity": [
            "case",
            ["boolean", ["feature-state", "hover"], false],
            0.4,
            0.18,
          ],
        },
      });
      map.addLayer({
        id: "events-line",
        type: "line",
        source: "events",
        paint: {
          "line-color": ["get", "stage_color"],
          "line-width": 2,
          "line-opacity": 0.9,
        },
      });
      map.addLayer({
        id: "events-point",
        type: "circle",
        source: "events",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-color": ["get", "stage_color"],
          "circle-radius": 5,
          "circle-stroke-color": "#071018",
          "circle-stroke-width": 2,
        },
      });
    }
  }, [events, ready]);

  // Selection emphasis.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const filter = selectedEventId
      ? (["==", ["get", "event_id"], selectedEventId] as maplibregl.FilterSpecification)
      : null;
    if (map.getLayer("events-fill")) map.setFilter("events-fill", filter);
    if (map.getLayer("events-line")) {
      map.setFilter("events-line", filter);
      map.setPaintProperty("events-line", "line-width", selectedEventId ? 3.2 : 2);
    }
  }, [selectedEventId, ready]);

  // Raster overlay.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    removeIfPresent(map, "active-image-layer", "layer");
    removeIfPresent(map, "active-image", "source");
    if (!layer) return;
    const before = map.getLayer("events-fill") ? "events-fill" : undefined;
    map.addSource("active-image", {
      type: "image",
      url: layer.url,
      coordinates: layer.coordinates as [[number, number], [number, number], [number, number], [number, number]],
    });
    map.addLayer(
      {
        id: "active-image-layer",
        type: "raster",
        source: "active-image",
        paint: { "raster-opacity": 0.82, "raster-fade-duration": 0 },
      },
      before,
    );
  }, [layer, ready]);

  return (
    <div className="map-shell" style={{ height }}>
      <div ref={containerRef} className="map-canvas" />
      {!ready ? <div className="map-loading">Initializing map…</div> : null}
      <div className="map-legend-stage" aria-hidden="true">
        {Object.entries(STAGE_COLORS).map(([stage, color]) => (
          <span key={stage}>
            <i style={{ background: color }} />
            {stage}
          </span>
        ))}
      </div>
    </div>
  );
}

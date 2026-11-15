import { useEffect, useRef, useState, type PointerEvent } from 'react';
import * as maplibregl from 'maplibre-gl';
import type { LayerSpecification, Map as MlMap, MapMouseEvent } from 'maplibre-gl';
import { loadContext, tileTemplate } from './api';
import { displayRasterHref, featureCollection, type ContextLayer, type Region, type StacItem } from './lib';

const STYLE = 'https://tiles.openfreemap.org/styles/liberty';
const FALLBACK_STYLE = { version: 8 as const, sources: {}, layers: [{ id: 'background', type: 'background' as const, paint: { 'background-color': '#14201e' } }] };
const RESULT_SOURCE = 'nisar-results';
const POINT_SOURCE = 'inspect-point';
const RASTER_SOURCE = 'active-raster';
const RASTER_LAYER = 'active-raster-layer';

type Props = {
  items: StacItem[];
  selected?: StacItem;
  compare?: StacItem;
  focus?: Region;
  projection: 'globe' | 'mercator';
  homeKey: number;
  reducedMotion: boolean;
  pointMode: boolean;
  point?: [number, number];
  contexts: ContextLayer[];
  onSelect: (id: string) => void;
  onBoundsChange: (bounds: [number, number, number, number]) => void;
  onInspect: (point: [number, number]) => void;
  onMapError: (message: string) => void;
};

function firstLabelLayer(map: MlMap) {
  return map.getStyle().layers?.find((layer) => layer.type === 'symbol')?.id;
}

function addRaster(map: MlMap, item?: StacItem, prefix = '') {
  const href = displayRasterHref(item);
  if (!href || !map.isStyleLoaded()) return;
  const sourceId = `${prefix}${RASTER_SOURCE}`;
  const layerId = `${prefix}${RASTER_LAYER}`;
  if (map.getLayer(layerId)) map.removeLayer(layerId);
  if (map.getSource(sourceId)) map.removeSource(sourceId);
  map.addSource(sourceId, { type: 'raster', tiles: [tileTemplate(href, item)], tileSize: 256, attribution: 'NASA / ASF DAAC — NISAR' });
  map.addLayer({ id: layerId, type: 'raster', source: sourceId, paint: { 'raster-opacity': 0.88 } }, firstLabelLayer(map));
}

function removeContext(map: MlMap, count: number) {
  for (let index = 0; index < count; index += 1) {
    for (const suffix of ['fill', 'line', 'raster']) {
      const id = `context-${index}-${suffix}`;
      if (map.getLayer(id)) map.removeLayer(id);
    }
    const id = `context-${index}`;
    if (map.getSource(id)) map.removeSource(id);
  }
}

export default function MapView(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  const compareContainer = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | undefined>(undefined);
  const compareMap = useRef<MlMap | undefined>(undefined);
  const loaded = useRef(false);
  const latest = useRef(props);
  const popup = useRef<maplibregl.Popup | undefined>(undefined);
  const contextAbort = useRef<AbortController | undefined>(undefined);
  const contextCount = useRef(0);
  const fallbackUsed = useRef(false);
  const [swipe, setSwipe] = useState(50);
  latest.current = props;

  useEffect(() => {
    if (!container.current) return;
    const instance = new maplibregl.Map({
      container: container.current,
      style: STYLE,
      center: [0, 18],
      zoom: 1.45,
      minZoom: 0.4,
      maxZoom: 17,
      cooperativeGestures: true,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
    instance.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');
    instance.on('moveend', () => {
      const bounds = instance.getBounds();
      latest.current.onBoundsChange([bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]);
    });
    instance.on('error', () => {
      latest.current.onMapError('Map tiles or the basemap could not be loaded. You can still use the result list and source records.');
      if (!loaded.current && !fallbackUsed.current && !instance.isStyleLoaded()) {
        fallbackUsed.current = true;
        instance.setStyle(FALLBACK_STYLE);
      }
    });
    const installLayers = () => {
      if (instance.getSource(RESULT_SOURCE)) return;
      instance.setProjection({ type: latest.current.projection });
      instance.addSource(RESULT_SOURCE, { type: 'geojson', data: featureCollection(latest.current.items, latest.current.selected?.id) });
      instance.addLayer({ id: 'results-fill', type: 'fill', source: RESULT_SOURCE,
        paint: { 'fill-color': ['case', ['get', 'selected'], '#ffd166', ['==', ['get', 'catalog'], 'eligible_for_pilot_review'], '#42cbb4', ['==', ['get', 'catalog'], 'segregated'], '#e58a59', '#9daaaa'],
          'fill-opacity': ['case', ['get', 'selected'], 0.34, 0.12] } } as LayerSpecification, firstLabelLayer(instance));
      instance.addLayer({ id: 'results-line', type: 'line', source: RESULT_SOURCE,
        paint: { 'line-color': ['case', ['get', 'selected'], '#ffe3a0', '#b7e5dc'],
          'line-width': ['case', ['get', 'selected'], 2.6, 1.1], 'line-dasharray': [2, 1.5] } } as LayerSpecification, firstLabelLayer(instance));
      instance.addSource(POINT_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      instance.addLayer({ id: 'inspect-point-dot', type: 'circle', source: POINT_SOURCE,
        paint: { 'circle-radius': 6, 'circle-color': '#ffd166', 'circle-stroke-color': '#0b1112', 'circle-stroke-width': 2 } });
      instance.on('click', (event: MapMouseEvent) => {
        if (latest.current.pointMode) latest.current.onInspect([event.lngLat.lng, event.lngLat.lat]);
      });
      instance.on('click', 'results-fill', (event) => {
        if (latest.current.pointMode) return;
        const id = event.features?.[0]?.properties?.id;
        if (id) latest.current.onSelect(String(id));
      });
      instance.on('mouseenter', 'results-fill', (event) => {
        if (latest.current.pointMode) return;
        instance.getCanvas().style.cursor = 'pointer';
        const properties = event.features?.[0]?.properties;
        if (!properties) return;
        const card = document.createElement('div');
        card.className = 'map-popup';
        const title = document.createElement('strong'); title.textContent = String(properties.product);
        const label = document.createElement('span'); label.textContent = String(properties.parameter);
        const date = document.createElement('span'); date.textContent = String(properties.date);
        card.append(title, label, date);
        popup.current?.remove();
        popup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '220px' })
          .setLngLat(event.lngLat).setDOMContent(card).addTo(instance);
      });
      instance.on('mouseleave', 'results-fill', () => {
        instance.getCanvas().style.cursor = latest.current.pointMode ? 'crosshair' : '';
        popup.current?.remove();
      });
      loaded.current = true;
      syncMap(instance, latest.current);
    };
    instance.on('load', installLayers);
    instance.on('style.load', installLayers);
    return () => {
      popup.current?.remove();
      contextAbort.current?.abort();
      instance.remove();
      map.current = undefined;
      loaded.current = false;
    };
  }, []);

  useEffect(() => {
    if (loaded.current && map.current) syncMap(map.current, props);
  }, [props.items, props.selected]);

  useEffect(() => {
    if (!loaded.current || !map.current) return;
    const source = map.current.getSource(POINT_SOURCE) as maplibregl.GeoJSONSource | undefined;
    source?.setData({ type: 'FeatureCollection', features: props.point ? [{
      type: 'Feature', geometry: { type: 'Point', coordinates: props.point }, properties: {},
    }] : [] });
  }, [props.point]);

  useEffect(() => {
    if (loaded.current && map.current) void setContexts(map.current, props.contexts);
  }, [props.contexts, props.focus]);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    if (instance.isStyleLoaded()) instance.setProjection({ type: props.projection });
    else instance.once('load', () => instance.setProjection({ type: latest.current.projection }));
  }, [props.projection]);

  useEffect(() => {
    const instance = map.current;
    const focus = props.focus;
    if (!focus || !instance) return;
    requestAnimationFrame(() => {
      instance.resize();
      const latestFocus = latest.current.focus;
      if (latestFocus) {
        const camera = instance.cameraForBounds(latestFocus.bounds_wgs84, { padding: 62, maxZoom: 12 });
        if (camera) instance.jumpTo(camera);
      }
    });
  }, [props.focus?.id]);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !props.homeKey) return;
    requestAnimationFrame(() => {
      const home = { center: [0, 18] as [number, number], zoom: 1.45, bearing: 0, pitch: 0 };
      if (props.reducedMotion) instance.jumpTo(home);
      else instance.flyTo({ ...home, duration: 850 });
    });
  }, [props.homeKey, props.reducedMotion]);

  const compareHref = displayRasterHref(props.compare);
  useEffect(() => {
    if (!compareHref || !compareContainer.current) {
      compareMap.current?.remove(); compareMap.current = undefined; return;
    }
    const options = map.current?.getCenter();
    const secondary = new maplibregl.Map({
      container: compareContainer.current, style: STYLE,
      center: options ? [options.lng, options.lat] : [0, 18],
      zoom: map.current?.getZoom() ?? 1.45,
      attributionControl: false,
      interactive: false, fadeDuration: 0,
    });
    compareMap.current = secondary;
    secondary.on('load', () => addRaster(secondary, props.compare, 'compare-'));
    secondary.on('load', () => secondary.setProjection({ type: props.projection }));
    let compareFallback = false;
    secondary.on('error', () => {
      if (!compareFallback && !secondary.isStyleLoaded()) {
        compareFallback = true;
        secondary.setStyle(FALLBACK_STYLE);
      }
    });
    const primary = map.current;
    const sync = () => {
      if (!primary || !compareMap.current) return;
      const center = primary.getCenter();
      compareMap.current.jumpTo({ center: [center.lng, center.lat], zoom: primary.getZoom(), bearing: primary.getBearing(), pitch: primary.getPitch() });
    };
    primary?.on('move', sync);
    return () => {
      primary?.off('move', sync);
      secondary.remove();
      compareMap.current = undefined;
    };
  }, [compareHref, props.projection]);

  function syncMap(instance: MlMap, state: Props) {
    const source = instance.getSource(RESULT_SOURCE) as maplibregl.GeoJSONSource | undefined;
    source?.setData(featureCollection(state.items, state.selected?.id));
    const href = displayRasterHref(state.selected);
    if (instance.isStyleLoaded()) {
      if (href) addRaster(instance, state.selected);
      else {
        if (instance.getLayer(RASTER_LAYER)) instance.removeLayer(RASTER_LAYER);
        if (instance.getSource(RASTER_SOURCE)) instance.removeSource(RASTER_SOURCE);
      }
    }
    instance.getCanvas().style.cursor = state.pointMode ? 'crosshair' : '';
  }

  async function setContexts(instance: MlMap, layers: ContextLayer[]) {
    contextAbort.current?.abort();
    const controller = new AbortController();
    contextAbort.current = controller;
    removeContext(instance, contextCount.current);
    contextCount.current = layers.length;
    for (const [index, layer] of layers.entries()) {
      try {
        if (layer.asset_url.endsWith('.geojson')) {
          const response = await loadContext(layer.asset_url, controller.signal);
          const data = await response.json() as import('geojson').FeatureCollection;
          if (controller.signal.aborted || !instance.isStyleLoaded()) return;
          const source = `context-${index}`;
          instance.addSource(source, { type: 'geojson', data });
          instance.addLayer({ id: `${source}-fill`, type: 'fill', source,
            paint: { 'fill-color': '#e3b85b', 'fill-opacity': 0.18 } }, 'results-fill');
          instance.addLayer({ id: `${source}-line`, type: 'line', source,
            paint: { 'line-color': '#f4c96f', 'line-width': 1.3 } }, 'results-line');
        } else {
          const region = latest.current.focus;
          if (!region) continue;
          const [west, south, east, north] = region.bounds_wgs84;
          const source = `context-${index}`;
          instance.addSource(source, { type: 'image', url: `${(import.meta.env.VITE_PROJECT_API || '/api')}${layer.asset_url.replace(/^\/api/, '')}`,
            coordinates: [[west, north], [east, north], [east, south], [west, south]] });
          instance.addLayer({ id: `${source}-raster`, type: 'raster', source,
            paint: { 'raster-opacity': 0.52 } }, 'results-fill');
        }
      } catch {
        if (!controller.signal.aborted) latest.current.onMapError(`Reference layer “${layer.label}” could not be loaded.`);
      }
    }
  }

  function moveSwipe(event: PointerEvent<HTMLDivElement>) {
    if (!(event.currentTarget as HTMLDivElement).hasPointerCapture(event.pointerId)) return;
    const rect = event.currentTarget.parentElement!.getBoundingClientRect();
    setSwipe(Math.min(96, Math.max(4, ((event.clientX - rect.left) / rect.width) * 100)));
  }

  const compareActive = Boolean(compareHref);
  return <div className={`map-stage ${props.pointMode ? 'point-mode' : ''}`}>
    <div ref={container} className="map-canvas" aria-label="Interactive NISAR observation map" />
    {props.pointMode && <button type="button" className="inspect-center" onClick={() => {
      const center = map.current?.getCenter();
      if (center) props.onInspect([center.lng, center.lat]);
    }}>Sample map center</button>}
    {compareActive && <>
      <div ref={compareContainer} className="compare-canvas" style={{ clipPath: `inset(0 ${100 - swipe}% 0 0)` }} aria-hidden="true" />
      <span className="compare-badge compare-before">Earlier</span><span className="compare-badge compare-after">Selected</span>
      <div className="swipe-rail" style={{ left: `${swipe}%` }} role="slider" aria-label="Swipe comparison divider"
        aria-valuemin={4} aria-valuemax={96} aria-valuenow={Math.round(swipe)} tabIndex={0}
        onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); moveSwipe(event); }}
        onPointerMove={moveSwipe}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') setSwipe((value) => Math.max(4, value - 2));
          if (event.key === 'ArrowRight') setSwipe((value) => Math.min(96, value + 2));
        }}><span /></div>
    </>}
    {props.pointMode && <div className="map-instruction" role="status">Click a location to sample its selected raster and time series.</div>}
    {!displayRasterHref(props.selected) && <div className="map-layer-note">{props.selected?.properties['readiness:visual'] === 'ready' ? 'This categorical or encoded quality layer is kept off the continuous color map until its legend is reviewed.' : 'Select a prepared result to load its raster. Footprints remain visible for archive-only scenes.'}</div>}
  </div>;
}


import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import { inspectPoint, loadNextPage, loadProducts, loadRegions, searchCatalog } from './api';
import { canCompare, displayRasterHref, itemTime, rasterHref, rasterScale, rasterVisualization, readableDate, sameSeriesStratum, type Product, type Region, type StacItem } from './lib';

const MapView = lazy(() => import('./MapView'));

type Filters = { product: string; parameter: string; maturity: string; readiness: string; review: string; polarization: string; frequency: string; region: string; start: string; end: string };
const INITIAL_FILTERS: Filters = { product: '', parameter: '', maturity: '', readiness: '', review: '', polarization: '', frequency: '', region: '', start: '2026-05-01', end: new Date().toISOString().slice(0, 10) };
const STORIES = [
  { region: 'Santa Rosa', label: 'Wildfire context', tone: 'fire' },
  { region: 'Barataria', label: 'Wetland inventory', tone: 'water' },
  { region: 'Colusa', label: 'Working lands', tone: 'land' },
  { region: 'Antarctica', label: 'Ice sheet offsets', tone: 'ice' },
];

function parametersFor(product?: Product): Array<[string, string, string?]> {
  if (!product) return [];
  if (product.id === 'nisar-gcov') return [
    ['hh-backscatter', 'HH backscatter'], ['hv-backscatter', 'HV backscatter'],
    ['hh-backscatter-difference', 'HH pair difference'], ['hv-backscatter-difference', 'HV pair difference'],
  ];
  return Object.entries(product.parameters || {}).map(([id, value]) => [id, id.replaceAll('_', ' '),
    typeof value === 'object' ? value.unit || '' : value]);
}

function itemSource(item?: StacItem) {
  return item?.assets['source-data']?.href || item?.links?.find((link) => link.rel === 'via')?.href;
}

function caveat(item?: StacItem) {
  if (!item) return 'A radar observation records a surface response. It does not, by itself, establish the cause of a change.';
  const warning = item.properties['nisar:display_warning'];
  if (warning) return String(warning);
  if (/categorical|bit field|integer label/i.test(String(item.properties.unit || ''))) return 'This is an encoded quality or category layer. Its values are preserved as delivered; the map does not assign meanings to codes or interpolate them.';
  if (item.properties['readiness:reviewed_change'] !== 'reviewed') return 'This footprint shows archive coverage, not a confirmed change. Interpretation needs quality checks and independent evidence.';
  return 'This result has a reviewed interpretation. Review its source and method before comparing it.';
}

function statusLabel(item?: StacItem) {
  if (!item) return 'No selection';
  if (item.properties['readiness:catalog'] === 'segregated') return 'Segregated from default results';
  if (item.properties['readiness:catalog'] === 'withheld') return 'Withheld by QA';
  const visual = item.properties['readiness:visual'] || 'not_prepared';
  const reviewed = item.properties['readiness:reviewed_change'] === 'reviewed';
  if (reviewed) return 'Reviewed analysis';
  if (visual === 'ready') return item.properties.product === 'nisar-sme2' ? 'Experimental layer' : 'Layer ready';
  if (visual === 'withheld') return 'Layer withheld';
  return 'Archive only';
}

export default function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [includeUnqualified, setIncludeUnqualified] = useState(false);
  const [viewport, setViewport] = useState<[number, number, number, number]>([-180, -80, 180, 80]);
  const [items, setItems] = useState<StacItem[]>([]);
  const [total, setTotal] = useState<number>();
  const [next, setNext] = useState<NonNullable<StacItem['links']>[number] | undefined>();
  const [selectedId, setSelectedId] = useState('');
  const [focus, setFocus] = useState<Region>();
  const [loading, setLoading] = useState(true);
  const [moreLoading, setMoreLoading] = useState(false);
  const [error, setError] = useState('');
  const [projection, setProjection] = useState<'globe' | 'mercator'>('globe');
  const [pointMode, setPointMode] = useState(false);
  const [point, setPoint] = useState<[number, number]>();
  const [series, setSeries] = useState<Array<{ item: StacItem; value?: number; error?: string }>>([]);
  const [contextIds, setContextIds] = useState<string[]>([]);
  const [playing, setPlaying] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [searchVersion, setSearchVersion] = useState(0);
  const [mapHomeKey, setMapHomeKey] = useState(0);
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([loadProducts(controller.signal), loadRegions(controller.signal)])
      .then(([productRows, regionRows]) => { setProducts(productRows); setRegions(regionRows); setError(''); })
      .catch((reason: Error) => { if (reason.name !== 'AbortError') setError(`Project API unavailable: ${reason.message}. Start the local data services and refresh.`); })
      .finally(() => setLoading(false));
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(motion.matches);
    const update = () => setReducedMotion(motion.matches);
    motion.addEventListener('change', update);
    return () => { controller.abort(); motion.removeEventListener('change', update); };
  }, []);

  useEffect(() => {
    if (!products.length || !regions.length) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setLoading(true); setError(''); setNext(undefined);
      searchCatalog({
        bbox: viewport,
        start: filters.start ? `${filters.start}T00:00:00Z` : '',
        end: filters.end ? `${filters.end}T23:59:59Z` : '',
        product: filters.product || undefined,
        parameter: filters.parameter || undefined,
        maturity: filters.maturity || undefined,
        readiness: filters.readiness || undefined,
        review: filters.review || undefined,
        polarization: filters.polarization || undefined,
        frequency: filters.frequency || undefined,
        limit: 100,
      }, controller.signal).then((result) => {
        if (controller.signal.aborted) return;
        const sorted = result.items.slice().sort((a, b) => itemTime(a).localeCompare(itemTime(b)));
        const eligible = sorted.filter((item) => item.properties['readiness:catalog'] === 'eligible_for_pilot_review');
        setItems(sorted); setTotal(result.total); setNext(result.next); setSelectedId((current) =>
          sorted.some((item) => item.id === current) ? current : (eligible[0] || (includeUnqualified ? sorted[0] : undefined))?.id || '');
      }).catch((reason: Error) => { if (reason.name !== 'AbortError') setError(`Catalog search failed: ${reason.message}.`); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, searchVersion ? 0 : 400);
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [filters, viewport, products.length, regions.length, searchVersion, includeUnqualified]);

  const visibleItems = useMemo(() => includeUnqualified ? items : items.filter((item) => item.properties['readiness:catalog'] === 'eligible_for_pilot_review'), [items, includeUnqualified]);
  const selected = visibleItems.find((item) => item.id === selectedId);
  const timelineItems = useMemo(() => selected ? visibleItems.filter((item) => sameSeriesStratum(item, selected)) : [], [visibleItems, selected]);
  const index = Math.max(0, timelineItems.findIndex((item) => item.id === selectedId));
  const prior = useMemo(() => {
    if (!selected) return undefined;
    const before = visibleItems.filter((item) => item.id !== selected.id && itemTime(item) < itemTime(selected) && canCompare(selected, item));
    return before.at(-1);
  }, [visibleItems, selected]);
  const currentProduct = products.find((product) => product.id === filters.product);
  const parameters = parametersFor(currentProduct);
  const currentRegion = regions.find((region) => region.id === filters.region);
  const selectedContexts = (currentRegion?.context_layers || []).filter((layer) => contextIds.includes(layer.asset_url));
  const seriesItems = useMemo(() => selected ? timelineItems.filter((item) => Boolean(rasterHref(item))).slice(-24) : [], [timelineItems, selected]);

  useEffect(() => {
    if (selectedId && !visibleItems.some((item) => item.id === selectedId)) setSelectedId(visibleItems[0]?.id || '');
  }, [visibleItems, selectedId]);

  useEffect(() => {
    setContextIds([]); setPoint(undefined); setPointMode(false);
  }, [filters.region]);

  useEffect(() => {
    if (!point || !seriesItems.length) { setSeries([]); return; }
    const controller = new AbortController();
    Promise.all(seriesItems.map(async (item) => {
      try { return { item, value: await inspectPoint(rasterHref(item)!, point[0], point[1], controller.signal) }; }
      catch (reason) {
        if ((reason as Error).name === 'AbortError') throw reason;
        return { item, error: (reason as Error).message };
      }
    })).then(setSeries).catch((reason: Error) => { if (reason.name !== 'AbortError') setError(`Point series unavailable: ${reason.message}.`); });
    return () => controller.abort();
  }, [point, seriesItems]);

  useEffect(() => {
    if (!playing || reducedMotion || timelineItems.length < 2) { setPlaying(false); return; }
    const timer = window.setInterval(() => setSelectedId((current) => {
      const currentIndex = timelineItems.findIndex((item) => item.id === current);
      if (currentIndex >= timelineItems.length - 1) return current;
      return timelineItems[currentIndex + 1].id;
    }), 1700);
    return () => window.clearInterval(timer);
  }, [playing, reducedMotion, timelineItems]);

  useEffect(() => {
    if (playing && index === timelineItems.length - 1) setPlaying(false);
  }, [playing, index, timelineItems.length]);

  function updateFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((current) => ({ ...current, [key]: value, ...(key === 'product' ? { parameter: '' } : {}) }));
    setPlaying(false);
  }

  function chooseStory(regionName: string) {
    const region = regions.find((entry) => entry.id === regionName);
    if (!region) return;
    setFocus(region); setViewport(region.bounds_wgs84); setProjection('mercator'); setFilters((current) => ({ ...current, region: region.id })); setPlaying(false);
  }

  async function loadMore() {
    if (!next || moreLoading) return;
    setMoreLoading(true);
    try {
      const page = await loadNextPage(next);
      setItems((current) => [...current, ...page.items].filter((item, index, rows) => rows.findIndex((other) => other.id === item.id) === index)
        .sort((a, b) => itemTime(a).localeCompare(itemTime(b))));
      setTotal(page.total); setNext(page.next);
    } catch (reason) { setError(`Could not load the next catalog page: ${(reason as Error).message}.`); }
    finally { setMoreLoading(false); }
  }

  function changeFrame(direction: -1 | 1) {
    if (!timelineItems.length) return;
    const nextIndex = (index + direction + timelineItems.length) % timelineItems.length;
    setSelectedId(timelineItems[nextIndex].id);
  }

  const visibleDates = timelineItems.map(itemTime).filter(Boolean);
  const minDate = visibleDates[0] ? new Date(visibleDates[0]).getTime() : 0;
  const maxDate = visibleDates.at(-1) ? new Date(visibleDates.at(-1)!).getTime() : minDate + 1;
  const seriesMinDate = series[0] ? new Date(itemTime(series[0].item)).getTime() : minDate;
  const seriesMaxDate = series.at(-1) ? new Date(itemTime(series.at(-1)!.item)).getTime() : seriesMinDate + 1;
  const values = series.map((entry) => entry.value).filter((value): value is number => typeof value === 'number');
  const minValue = values.length ? Math.min(...values) : 0;
  const maxValue = values.length ? Math.max(...values) : 1;
  const valueRange = maxValue - minValue || 1;
  const selectedScale = rasterScale(selected);
  const selectedVisualization = rasterVisualization(selected);

  return <main className="app-shell">
    <header className="topbar">
      <a className="brand" href="#top" aria-label="EarthBeat Atlas home"><span className="brand-mark">e</span><span>EarthBeat <b>Atlas</b></span></a>
      <div className="topbar-center"><span className="eyebrow">NISAR SURFACE OBSERVATIONS</span><span className="online-dot" /> <span>Archive explorer</span></div>
      <a className="mission-link" href="https://nisar.jpl.nasa.gov/" target="_blank" rel="noreferrer">About the mission <span aria-hidden="true">↗</span></a>
    </header>

    <section className="workspace" id="top">
      <aside className="sidebar" aria-label="Explore observations">
        <div className="sidebar-heading"><div><p className="eyebrow">EXPLORE</p><h1>Earth in motion</h1></div><span className="orbital-icon" aria-hidden="true">◌</span></div>
        <p className="intro">Find radar observations, follow their real acquisition dates, and inspect prepared layers.</p>
        <details className="reading-guide"><summary>How to read the radar layers</summary><div>
          <p>NISAR measures returned L-band microwave energy. A bright or dark return can have several causes; it does not identify an event by itself. In HH, HV, VH or VV, the first letter is the transmitted polarization and the second is the received polarization.</p>
          <p>GCOV shows calibrated radar backscatter in dB; a difference is later minus earlier over shared valid pixels. GUNW phase is in radians and is not displacement here. GOFF offsets are unfiltered and are not velocity. SME2 is provisional and not fully calibrated.</p>
          <p>Timeline positions are actual acquisitions. A gap means no displayed measurement, not an interpolated one. Fire, wetland, crop and ice overlays are independent context with their own dates; wind and pressure are not measured by this dashboard.</p>
          <a href="https://science.nasa.gov/mission/nisar/polarimetry/" target="_blank" rel="noreferrer">NASA guide to NISAR polarimetry ↗</a>
        </div></details>

        <div className="story-block"><div className="section-heading"><span>START WITH A STORY</span><span className="small-count">04 AREAS</span></div>
          <div className="story-grid">{STORIES.map((story) => <button key={story.region} type="button" className={`story-card story-${story.tone} ${filters.region === story.region ? 'active' : ''}`} onClick={() => chooseStory(story.region)}>
            <span className="story-glyph" aria-hidden="true">{story.tone === 'fire' ? '✳' : story.tone === 'water' ? '≈' : story.tone === 'land' ? '⌁' : '❄'}</span>
            <span><b>{story.label}</b><small>{story.region}</small></span><span className="story-arrow" aria-hidden="true">↗</span>
          </button>)}</div>
        </div>

        <div className="filters-block"><div className="section-heading"><span>DATA FILTERS</span><button type="button" className="text-button" onClick={() => { setFilters(INITIAL_FILTERS); setFocus(undefined); setIncludeUnqualified(false); setProjection('globe'); setMapHomeKey((key) => key + 1); setSearchVersion((v) => v + 1); }}>Reset to world</button></div>
          <label>Region<select value={filters.region} onChange={(event) => {
            const id = event.target.value; updateFilter('region', id);
            const region = regions.find((entry) => entry.id === id); setFocus(region); setProjection(region ? 'mercator' : 'globe');
            if (region) setViewport(region.bounds_wgs84);
            if (!region) setMapHomeKey((key) => key + 1);
          }}><option value="">Anywhere on Earth</option>{regions.map((region) => <option key={region.id} value={region.id}>{region.name}</option>)}</select></label>
          <label>Product<select value={filters.product} onChange={(event) => updateFilter('product', event.target.value)}><option value="">All NISAR products</option>{products.map((product) => <option key={product.id} value={product.id}>{product.id.replace('nisar-', '').toUpperCase()} · {product.maturity}</option>)}</select></label>
          <div className="filter-row"><label>Parameter<select value={filters.parameter} disabled={!currentProduct} onChange={(event) => updateFilter('parameter', event.target.value)}><option value="">All parameters</option>{parameters.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
            <label>Maturity<select value={filters.maturity} onChange={(event) => updateFilter('maturity', event.target.value)}><option value="">All</option><option>PROVISIONAL</option><option>VALIDATED</option><option>BETA</option></select></label></div>
          <div className="filter-row"><label>Polarization<select value={filters.polarization} onChange={(event) => updateFilter('polarization', event.target.value)}><option value="">All</option><option value="HH">HH</option><option value="HV">HV</option><option value="VH">VH</option><option value="VV">VV</option></select></label>
            <label>Frequency<select value={filters.frequency} onChange={(event) => updateFilter('frequency', event.target.value)}><option value="">All</option><option value="A">A</option><option value="B">B</option></select></label></div>
          <label>Layer readiness<select value={filters.readiness} onChange={(event) => updateFilter('readiness', event.target.value)}><option value="">All archive records</option><option value="ready">Visual layer ready</option><option value="not_prepared">Archive only</option><option value="withheld">Layer withheld</option></select></label>
          <label>Interpretation<select value={filters.review} onChange={(event) => updateFilter('review', event.target.value)}><option value="">All review states</option><option value="reviewed">Expert reviewed</option><option value="not_reviewed">Not reviewed</option></select></label>
          <label className="unqualified-toggle"><input type="checkbox" checked={includeUnqualified} onChange={(event) => setIncludeUnqualified(event.target.checked)} /> Include unassessed, segregated, and withheld archive records</label>
          <div className="filter-row dates"><label>From<input type="date" value={filters.start} onChange={(event) => updateFilter('start', event.target.value)} /></label><label>To<input type="date" value={filters.end} onChange={(event) => updateFilter('end', event.target.value)} /></label></div>
          <button type="button" className="search-button" onClick={() => setSearchVersion((version) => version + 1)}><span aria-hidden="true">⌕</span> Update results <span className="button-arrow" aria-hidden="true">→</span></button>
          <p className="filter-hint">Map movement also searches the visible bounds. Results retain the source maturity and date gaps.</p>
        </div>

        <div className="result-list"><div className="section-heading"><span>VISIBLE RECORDS</span><span className="small-count">{total === undefined ? visibleItems.length : `${visibleItems.length} / ${total}`}</span></div>
          {visibleItems.slice(0, 18).map((item) => <button type="button" key={item.id} onClick={() => { setSelectedId(item.id); setPlaying(false); }} className={`result-row ${item.id === selectedId ? 'selected' : ''}`}>
            <span className={`result-status status-${item.properties['readiness:visual'] || 'none'}`} />
            <span className="result-copy"><b>{item.properties.product || 'NISAR'} <small>{item.properties.parameter || 'scene'}</small></b><span>{readableDate(itemTime(item))} · {item.properties['nisar:collection_maturity'] || 'maturity unknown'} · {String(item.properties['readiness:catalog'] || 'not assessed').replaceAll('_', ' ')}</span></span>
          </button>)}
          {!loading && !visibleItems.length && <p className="empty-results">No qualified records on this page. {next ? 'Load the next catalog page to continue this search.' : 'Include unassessed or segregated archive records to inspect excluded coverage.'}</p>}
          {visibleItems.length > 18 && <p className="more-in-map">Showing 18 in the list; all {visibleItems.length} appear in the timeline and map.</p>}
          {next && <button type="button" className="load-more" disabled={moreLoading} onClick={() => void loadMore()}>{moreLoading ? 'Loading…' : 'Load next page'} <span aria-hidden="true">↓</span></button>}
        </div>
      </aside>

      <section className="map-column" aria-label="Map and selected observation">
        <div className="map-toolbar">
          <div className="map-title"><span className="live-kicker"><span className="online-dot" /> INTERACTIVE MAP</span><h2>{focus?.full_name || 'Explore NISAR coverage'}</h2><p>{visibleItems.length} records in this page <span>·</span> {viewport[0].toFixed(2)}°, {viewport[1].toFixed(2)}° to {viewport[2].toFixed(2)}°, {viewport[3].toFixed(2)}°</p></div>
          <div className="map-actions"><div className="segmented" role="group" aria-label="Map projection">
            <button type="button" aria-pressed={projection === 'globe'} className={projection === 'globe' ? 'active' : ''} onClick={() => setProjection('globe')}>◉ Globe</button>
            <button type="button" aria-pressed={projection === 'mercator'} className={projection === 'mercator' ? 'active' : ''} onClick={() => setProjection('mercator')}>▱ Flat</button></div>
            <button type="button" className={`inspect-button ${pointMode ? 'active' : ''}`} onClick={() => setPointMode((mode) => !mode)} disabled={!rasterHref(selected)} title={rasterHref(selected) ? 'Choose a map point to inspect' : 'Point inspection requires a prepared pixel asset'} aria-pressed={pointMode}>＋ Inspect point</button>
          </div>
        </div>

        {error && <div className="notice error-notice" role="alert"><span>!</span><p>{error}</p><button type="button" onClick={() => setSearchVersion((version) => version + 1)}>Retry</button><button className="dismiss" aria-label="Dismiss" onClick={() => setError('')}>×</button></div>}
        <Suspense fallback={<div className="map-stage" role="status">Loading interactive map…</div>}><MapView items={visibleItems} selected={selected} compare={prior} focus={focus} projection={projection} homeKey={mapHomeKey} reducedMotion={reducedMotion} pointMode={pointMode} point={point} contexts={selectedContexts}
          onSelect={setSelectedId} onBoundsChange={setViewport} onInspect={(coordinate) => { setPoint(coordinate); setPointMode(false); }} onMapError={(message) => setError(message)} /></Suspense>

        {currentRegion?.context_layers.length ? <div className="context-switcher"><span className="context-title">REFERENCE LAYERS</span>{currentRegion.context_layers.map((layer) => <label key={layer.asset_url} className="context-toggle"><input type="checkbox" checked={contextIds.includes(layer.asset_url)} onChange={(event) => setContextIds((current) => event.target.checked ? [...current, layer.asset_url] : current.filter((id) => id !== layer.asset_url))} />{layer.label}<a href={layer.source} target="_blank" rel="noreferrer" aria-label={`Source for ${layer.label}`}>↗</a></label>)}</div> : null}

        <section className="timeline-panel" aria-label="Observation timeline">
          <div className="timeline-head"><div><span className="eyebrow">OBSERVED DATES · SAME PRODUCT AND PARAMETER</span><h3>{timelineItems.length ? `${index + 1} of ${timelineItems.length} frames` : 'No timeline frames'}</h3></div>
            <div className="transport"><button aria-label="Previous observed date" title="Previous observed date" disabled={!timelineItems.length} onClick={() => changeFrame(-1)}>‹</button><button className="play-button" aria-label={playing ? 'Pause animation' : 'Play timeline'} disabled={timelineItems.length < 2 || reducedMotion} title={reducedMotion ? 'Animation disabled by reduced motion preference' : 'Play observed dates'} onClick={() => setPlaying((value) => !value)}>{playing ? 'Ⅱ' : '▶'}</button><button aria-label="Next observed date" title="Next observed date" disabled={!timelineItems.length} onClick={() => changeFrame(1)}>›</button></div>
            <div className="frame-date"><b>{selected ? readableDate(itemTime(selected)) : '—'}</b><span>{selected?.properties.parameter || 'Select a result'}</span></div></div>
          <input className="timeline-range" aria-label="Choose an observed date" type="range" min="0" max={Math.max(0, timelineItems.length - 1)} value={index} onChange={(event) => { setSelectedId(timelineItems[Number(event.target.value)]?.id || ''); setPlaying(false); }} disabled={timelineItems.length < 2} />
          <div className="timeline-ticks" role="list" aria-label="Available acquisition dates">{timelineItems.slice(0, 32).map((item, itemIndex) => {
            const time = itemTime(item); const x = maxDate === minDate ? 0 : ((new Date(time).getTime() - minDate) / (maxDate - minDate)) * 100;
            const days = itemIndex ? Math.round((new Date(time).getTime() - new Date(itemTime(timelineItems[itemIndex - 1])).getTime()) / 86400000) : 0;
            return <button role="listitem" type="button" key={item.id} className={item.id === selectedId ? 'active' : ''} style={{ left: `${x}%` }} title={`${readableDate(time)}${days ? ` · ${days} day gap` : ''}`} onClick={() => { setSelectedId(item.id); setPlaying(false); }}><i /><span>{new Date(time).toLocaleDateString('en', { month: 'short', day: 'numeric', timeZone: 'UTC' })}</span></button>;
          })}</div>
          <div className="timeline-foot"><span><i className="legend-dot ready" /> Prepared layer</span><span><i className="legend-dot archive" /> Archive record</span><span>Timeline uses actual source dates; spacing reflects observed gaps.</span></div>
        </section>
      </section>

      <aside className="detail-rail" aria-label="Selected observation details">
        <div className="detail-top"><span className="eyebrow">SELECTED RECORD</span><span className={`readiness-pill ${selected?.properties['readiness:visual'] === 'ready' ? 'good' : ''}`}>{statusLabel(selected)}</span></div>
        {selected ? <>
          <p className="product-overline">{String(selected.properties.product || 'NISAR').toUpperCase()}</p>
          <h2 className="detail-title">{String(selected.properties.parameter || 'Observation').replaceAll('_', ' ')}</h2>
          <div className="detail-date">{readableDate(itemTime(selected))}<span>{selected.properties.unit || 'unit not provided'}</span></div>
          <div className="metric-grid"><div><small>ARCHIVE</small><b>{String(selected.properties['readiness:archive'] || 'Unknown').replaceAll('_', ' ')}</b></div><div><small>CATALOG</small><b>{String(selected.properties['readiness:catalog'] || 'Not assessed').replaceAll('_', ' ')}</b></div><div><small>VISUAL</small><b>{String(selected.properties['readiness:visual'] || 'Unknown').replaceAll('_', ' ')}</b></div><div><small>REVIEW</small><b>{String(selected.properties['readiness:reviewed_change'] || 'Unknown').replaceAll('_', ' ')}</b></div><div><small>QUALITY</small><b>{String(selected.properties['quality:state'] || 'Unknown').replaceAll('_', ' ')}</b></div><div><small>MATURITY</small><b>{String(selected.properties['nisar:collection_maturity'] || 'Unknown')}</b></div><div><small>CRID</small><b>{String(selected.properties['nisar:crid'] || '—')}</b></div><div><small>TRACK</small><b>{String(selected.properties['nisar:track'] || '—')}</b></div><div><small>UNIT</small><b>{String(selected.properties.unit || 'Not provided')}</b></div></div>
          <div className="caveat-card"><span className="caveat-icon">i</span><p>{caveat(selected)}</p></div>
          {selected.properties['readiness:visual'] === 'ready' && displayRasterHref(selected) && <div className="layer-legend"><span className="eyebrow">DISPLAY LAYER · {selectedVisualization === 'diverging' ? 'ZERO-CENTERED DIVERGING' : 'VIRIDIS'}</span><div><i className={`legend-gradient ${selectedVisualization === 'diverging' ? 'diverging' : ''}`} /><span>{selectedScale ? `${selectedScale[0].toPrecision(3)} — ${selectedScale[1].toPrecision(3)} ${selected.properties.unit || ''}` : `Source pixels · ${selected.properties.unit || 'unit unavailable'}`}</span></div><small>Rendered from this COG using its source band range when available. No unreviewed change classification is applied.</small></div>}
          {itemSource(selected) && <a className="source-link" href={itemSource(selected)} target="_blank" rel="noreferrer">Open NASA / ASF source record <span>↗</span></a>}
          <div className="point-card"><div className="section-heading"><span>POINT & TIME SERIES</span><button type="button" className="text-button" disabled={!rasterHref(selected)} title={rasterHref(selected) ? 'Choose another map point' : 'Point inspection requires a prepared pixel asset'} onClick={() => { setPoint(undefined); setPointMode(true); }}>Choose point</button></div>
            {point && rasterHref(selected) ? <><p className="point-coord">{point[1].toFixed(5)}° {point[1] >= 0 ? 'N' : 'S'}, {Math.abs(point[0]).toFixed(5)}° {point[0] >= 0 ? 'E' : 'W'}</p>
              {/categorical|bit field|integer label/i.test(String(selected.properties.unit || '')) && <p className="point-help">Raw encoded values below; no trend is calculated for category or quality codes.</p>}
              {series.length ? <><svg className="series-chart" viewBox="0 0 600 155" role="img" aria-label={`Sampled values over ${series.length} observations at selected point`}>
                <path d="M34 12V126H574" className="chart-axis" />
                <text x="8" y="20" className="chart-label">{maxValue.toPrecision(3)}</text><text x="8" y="126" className="chart-label">{minValue.toPrecision(3)}</text>
                {series.map((entry, itemIndex) => {
                  const date = new Date(itemTime(entry.item)).getTime();
                  const x = seriesMaxDate === seriesMinDate ? 304 : 38 + ((date - seriesMinDate) / (seriesMaxDate - seriesMinDate)) * 530;
                  const y = typeof entry.value === 'number' ? 120 - ((entry.value - minValue) / valueRange) * 94 : 120;
                  const previous = series[itemIndex - 1];
                  const previousDate = previous ? new Date(itemTime(previous.item)).getTime() : date;
                  const previousX = seriesMaxDate === seriesMinDate ? 38 : 38 + ((previousDate - seriesMinDate) / (seriesMaxDate - seriesMinDate)) * 530;
                  return <g key={entry.item.id}>{previous && typeof entry.value === 'number' && typeof previous.value === 'number' && <line x1={previousX} y1={120 - ((previous.value - minValue) / valueRange) * 94} x2={x} y2={y} className="chart-line" />}{typeof entry.value === 'number' && <circle cx={x} cy={y} r={4.3} className="chart-point"><title>{readableDate(itemTime(entry.item))}: {entry.value}</title></circle>}</g>;
                })}</svg>
                <div className="chart-range"><span>{readableDate(itemTime(series[0].item))}</span><span>{readableDate(itemTime(series.at(-1)!.item))}</span></div>
                <p className="chart-caption">{values.length} of {series.length} samples returned. Missing pixels remain gaps; failed requests are marked separately. Units: {selected.properties.unit || 'source unit'}.</p>
                <details className="series-table"><summary>Accessible values table ({series.length})</summary><table><thead><tr><th>Date</th><th>Value</th><th>Unit</th></tr></thead><tbody>{series.map((entry) => <tr key={entry.item.id}><td>{readableDate(itemTime(entry.item))}</td><td>{typeof entry.value === 'number' ? entry.value.toPrecision(5) : entry.error ? `Request failed: ${entry.error}` : 'No sample'}</td><td>{String(entry.item.properties.unit || '—')}</td></tr>)}</tbody></table></details>
              </> : <p className="point-help">Choose a point inside the selected coverage to sample it across the available matching dates.</p>}
            </> : point ? <p className="point-help">Point sampling is unavailable because this record has no prepared pixel asset.</p> : rasterHref(selected) ? <p className="point-help">Select “Inspect point”, then click the map or sample its center to read a pixel and its available time series.</p> : <p className="point-help">This archive record has no prepared pixel asset, so point inspection is unavailable.</p>}
          </div>
        </> : <div className="no-selection"><span>◌</span><h3>Select a footprint</h3><p>Choose a record from the map or list to see source, maturity, quality, assets, and observation dates.</p></div>}
        <div className="rail-footer"><span>DATA SOURCE</span><a href="https://www.earthdata.nasa.gov/data/projects/nisar" target="_blank" rel="noreferrer">NASA Earthdata · NISAR ↗</a><small>Footprint availability and visual readiness are separate states.</small></div>
      </aside>
    </section>
  </main>;
}

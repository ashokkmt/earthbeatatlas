export type Product = {
  id: string;
  short_name: string;
  maturity: string;
  workflow_state: string;
  parameters: Record<string, { unit?: string; visualization?: string } | string>;
  source_guide: string;
};

export type ContextLayer = {
  label: string;
  asset_url: string;
  source: string;
  features?: number;
  year?: number;
};

export type Region = {
  id: string;
  name: string;
  title: string;
  full_name: string;
  bounds_wgs84: [number, number, number, number];
  context_layers: ContextLayer[];
  data_note?: string;
};

export type StacItem = {
  id: string;
  collection: string;
  geometry: import('geojson').Geometry | null;
  bbox: number[];
  properties: Record<string, unknown> & {
    datetime?: string | null;
    start_datetime?: string;
    end_datetime?: string;
    product?: string;
    parameter?: string;
    unit?: string;
    'readiness:visual'?: string;
    'quality:state'?: string;
    'readiness:reviewed_change'?: string;
    'readiness:catalog'?: string;
    'nisar:collection_maturity'?: string;
    'nisar:crid'?: string;
    'nisar:source_granule_id'?: string;
    'nisar:track'?: string | number;
    'nisar:orbit_direction'?: string;
    'nisar:frequency'?: string;
    'nisar:display_warning'?: string;
    'sar:polarizations'?: string[];
  };
  assets: Record<string, { href: string; type?: string; title?: string; roles?: string[]; 'raster:bands'?: Array<{ statistics?: { minimum?: number; maximum?: number } }> }>;
  links?: Array<{ rel: string; href: string; method?: string; body?: unknown }>;
};

export type SearchFilters = {
  bbox: number[];
  start: string;
  end: string;
  product?: string;
  parameter?: string;
  maturity?: string;
  readiness?: string;
  review?: string;
  polarization?: string;
  frequency?: string;
  limit?: number;
};

export function buildSearchBody(filters: SearchFilters) {
  const query: Record<string, unknown> = {};
  if (filters.product) query.product = { eq: filters.product };
  if (filters.parameter) query.parameter = { eq: filters.parameter };
  if (filters.maturity) query['nisar:collection_maturity'] = { eq: filters.maturity };
  if (filters.readiness) query['readiness:visual'] = { eq: filters.readiness };
  if (filters.review) query['readiness:reviewed_change'] = { eq: filters.review };
  const polarizationField = { HH: 'nisar:has_hh', HV: 'nisar:has_hv', VH: 'nisar:has_vh', VV: 'nisar:has_vv' }[filters.polarization || ''];
  if (polarizationField) query[polarizationField] = { eq: true };
  if (filters.frequency) query['nisar:frequency'] = { eq: filters.frequency };
  const body: Record<string, unknown> = { bbox: filters.bbox, limit: filters.limit ?? 100 };
  if (filters.start || filters.end) body.datetime = `${filters.start || '..'}/${filters.end || '..'}`;
  if (Object.keys(query).length) body.query = query;
  return body;
}

export function itemTime(item: StacItem) {
  return item.properties.datetime || item.properties.end_datetime || item.properties.start_datetime || '';
}

export function itemTitle(item: StacItem) {
  return String(item.properties.title || item.id);
}

export function rasterHref(item?: StacItem) {
  if (!item || item.properties['readiness:visual'] !== 'ready') return undefined;
  const asset = Object.values(item.assets).find((candidate) =>
    candidate.href.startsWith('s3://') || /\.tiff?(?:$|\?)/i.test(candidate.href),
  );
  return asset?.href;
}

export function displayRasterHref(item?: StacItem) {
  if (rasterVisualization(item) === 'categorical') return undefined;
  return rasterHref(item);
}

export function rasterVisualization(item?: StacItem): 'sequential' | 'diverging' | 'categorical' {
  const configured = item?.properties['nisar:visualization'];
  if (configured === 'sequential' || configured === 'diverging' || configured === 'categorical') return configured;
  const product = String(item?.properties.product || '');
  const parameter = String(item?.properties.parameter || '').toLowerCase();
  const unit = String(item?.properties.unit || '').toLowerCase();
  if (/categorical|bit field|integer label/.test(unit)) return 'categorical';
  if (parameter.includes('difference') || (product === 'nisar-gunw' && /phase/.test(parameter))
    || (product === 'nisar-goff' && /offset$/.test(parameter))) return 'diverging';
  return 'sequential';
}

export function rasterScale(item?: StacItem): [number, number] | undefined {
  const href = rasterHref(item);
  const band = item && Object.values(item.assets).find((asset) => asset.href === href)?.['raster:bands']?.[0];
  const minimum = band?.statistics?.minimum;
  const maximum = band?.statistics?.maximum;
  if (typeof minimum !== 'number' || typeof maximum !== 'number' || !Number.isFinite(minimum)
    || !Number.isFinite(maximum) || minimum >= maximum) return undefined;
  if (rasterVisualization(item) === 'diverging') {
    const limit = Math.max(Math.abs(minimum), Math.abs(maximum));
    return [-limit, limit];
  }
  return [minimum, maximum];
}

export function canCompare(a?: StacItem, b?: StacItem) {
  if (!a || !b || !displayRasterHref(a) || !displayRasterHref(b)
    || (a.properties.datetime == null) !== (b.properties.datetime == null)) return false;
  if (a.properties.datetime == null && (a.properties.start_datetime !== b.properties.start_datetime
    || a.properties.end_datetime !== b.properties.end_datetime)) return false;
  return a.collection === b.collection
    && a.properties.product === b.properties.product
    && a.properties.parameter === b.properties.parameter
    && a.properties['nisar:collection_maturity'] === b.properties['nisar:collection_maturity']
    && a.properties['nisar:crid'] === b.properties['nisar:crid']
    && a.properties['sar:polarizations']?.join(',') === b.properties['sar:polarizations']?.join(',')
    && a.properties['nisar:frequency'] === b.properties['nisar:frequency']
    && a.properties['nisar:track'] === b.properties['nisar:track']
    && a.properties['nisar:orbit_direction'] === b.properties['nisar:orbit_direction']
    && a.properties.unit === b.properties.unit;
}

export function sameSeriesStratum(a: StacItem, b: StacItem) {
  return a.collection === b.collection
    && a.properties.product === b.properties.product
    && a.properties.parameter === b.properties.parameter
    && a.properties.unit === b.properties.unit
    && a.properties['nisar:collection_maturity'] === b.properties['nisar:collection_maturity']
    && a.properties['nisar:crid'] === b.properties['nisar:crid']
    && a.properties['sar:polarizations']?.join(',') === b.properties['sar:polarizations']?.join(',')
    && a.properties['nisar:frequency'] === b.properties['nisar:frequency']
    && a.properties['nisar:track'] === b.properties['nisar:track']
    && a.properties['nisar:orbit_direction'] === b.properties['nisar:orbit_direction']
    && (a.properties.datetime == null) === (b.properties.datetime == null);
}

export function readableDate(value: string) {
  if (!value) return 'Date unavailable';
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(value));
}

export function featureCollection(items: StacItem[], selected?: string): import('geojson').FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: items.filter((item) => item.geometry).map((item) => ({
      type: 'Feature' as const,
      id: item.id,
      geometry: item.geometry!,
      properties: {
        id: item.id,
        label: itemTitle(item),
        product: item.properties.product || 'NISAR observation',
        parameter: item.properties.parameter || 'parameter unavailable',
        date: readableDate(itemTime(item)),
        visual: item.properties['readiness:visual'] || 'not_prepared',
        catalog: item.properties['readiness:catalog'] || 'not_assessed',
        selected: item.id === selected,
      },
    })),
  };
}

export function pointValue(payload: unknown): number | undefined {
  if (!payload || typeof payload !== 'object') return undefined;
  const values = (payload as { values?: unknown }).values;
  if (!Array.isArray(values)) return undefined;
  const value = values.find((candidate) => typeof candidate === 'number' && Number.isFinite(candidate));
  return typeof value === 'number' ? value : undefined;
}

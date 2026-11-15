import { buildSearchBody, pointValue, rasterScale, rasterVisualization, type Product, type Region, type SearchFilters, type StacItem } from './lib';

const STAC = import.meta.env.VITE_STAC_BASE || '/stac';
const PROJECT = import.meta.env.VITE_PROJECT_API || '/api';
const TILES = import.meta.env.VITE_TILES_BASE || '/tiles';

async function checked<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export async function loadProducts(signal?: AbortSignal) {
  return checked<Product[]>(await fetch(`${PROJECT}/v1/products`, { signal }));
}

export async function loadRegions(signal?: AbortSignal) {
  return checked<Region[]>(await fetch(`${PROJECT}/v1/cases`, { signal }));
}

export async function searchCatalog(filters: SearchFilters, signal?: AbortSignal) {
  const response = await fetch(`${STAC}/search`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildSearchBody(filters)), signal,
  });
  const result = await checked<{ features?: StacItem[]; numberMatched?: number; links?: StacItem['links'] }>(response);
  const next = result.links?.find((link) => link.rel === 'next');
  return { items: result.features || [], total: result.numberMatched, next };
}

function catalogNextHref(href: string) {
  const url = new URL(href, window.location.origin);
  return `${STAC}${url.pathname.replace(/^\/stac/, '')}${url.search}`;
}

export async function loadNextPage(link: NonNullable<StacItem['links']>[number], signal?: AbortSignal) {
  const response = await fetch(catalogNextHref(link.href), {
    method: link.method || 'GET',
    headers: link.method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
    body: link.method === 'POST' && link.body ? JSON.stringify(link.body) : undefined,
    signal,
  });
  const result = await checked<{ features?: StacItem[]; numberMatched?: number; links?: StacItem['links'] }>(response);
  return { items: result.features || [], total: result.numberMatched,
    next: result.links?.find((candidate) => candidate.rel === 'next') };
}

export function tileTemplate(href: string, item?: StacItem) {
  const query = new URLSearchParams({ url: href });
  const scale = rasterScale(item);
  query.set('colormap_name', rasterVisualization(item) === 'diverging' ? 'rdbu' : 'viridis');
  if (scale) query.set('rescale', `${scale[0]},${scale[1]}`);
  return `${TILES}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?${query}`;
}

export async function inspectPoint(href: string, longitude: number, latitude: number, signal?: AbortSignal) {
  const query = new URLSearchParams({ url: href });
  const response = await fetch(`${TILES}/cog/point/${longitude},${latitude}?${query}`, { signal });
  return pointValue(await checked<unknown>(response));
}

export async function loadContext(layerUrl: string, signal?: AbortSignal) {
  const response = await fetch(`${PROJECT}${layerUrl.replace(/^\/api/, '')}`, { signal });
  if (!response.ok) throw new Error(`Context layer unavailable (${response.status})`);
  return response;
}

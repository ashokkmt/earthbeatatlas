import { describe, expect, it } from 'vitest';
import { buildSearchBody, canCompare, displayRasterHref, featureCollection, pointValue, rasterHref, rasterScale, rasterVisualization, sameSeriesStratum, type StacItem } from './lib';
import { tileTemplate } from './api';

const item = (id: string, changes: Partial<StacItem['properties']> = {}, assets: StacItem['assets'] = {}) => ({
  id, collection: 'nisar', geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, bbox: [0, 0, 1, 1],
  properties: { product: 'nisar-gcov', parameter: 'hh-backscatter', unit: 'dB', datetime: '2026-05-05T00:00:00Z',
    'readiness:visual': 'ready', 'nisar:collection_maturity': 'PROVISIONAL', ...changes }, assets,
}) as StacItem;

describe('catalog and display helpers', () => {
  it('builds a bounded STAC search from viewport, UTC dates, and selected filters', () => {
    const body = buildSearchBody({ bbox: [-120, 33, -119, 34], start: '2026-05-01T00:00:00Z', end: '2026-05-31T23:59:59Z',
      product: 'nisar-gcov', parameter: 'hh-backscatter', polarization: 'HH', readiness: 'ready', limit: 100 });
    expect(body.bbox).toEqual([-120, 33, -119, 34]);
    expect(body.datetime).toBe('2026-05-01T00:00:00Z/2026-05-31T23:59:59Z');
    expect(body.query).toEqual({ product: { eq: 'nisar-gcov' }, parameter: { eq: 'hh-backscatter' },
      'readiness:visual': { eq: 'ready' }, 'nisar:has_hh': { eq: true } });
    for (const [polarization, property] of [['HV', 'nisar:has_hv'], ['VH', 'nisar:has_vh'], ['VV', 'nisar:has_vv']]) {
      expect(buildSearchBody({ bbox: [], start: '', end: '', polarization }).query).toEqual({ [property]: { eq: true } });
    }
  });

  it('keeps archive-only records off the raster map', () => {
    const row = item('archive', { 'readiness:visual': 'not_prepared' }, { data: { href: 's3://bucket/scene.tif' } });
    expect(rasterHref(row)).toBeUndefined();
    expect(featureCollection([row]).features).toHaveLength(1);
  });

  it('allows swipe only when product, parameter, maturity, and units match', () => {
    const asset = { data: { href: 's3://bucket/scene.tif' } };
    expect(canCompare(item('a', {}, asset), item('b', {}, asset))).toBe(true);
    expect(canCompare(item('a', {}, asset), item('b', { unit: 'radians' }, asset))).toBe(false);
    expect(canCompare(item('a', {}, asset), item('b', { 'nisar:collection_maturity': 'VALIDATED' }, asset))).toBe(false);
    expect(canCompare(item('a', {}, asset), { ...item('b', {}, asset), collection: 'other' })).toBe(false);
    expect(canCompare(item('a', {}, asset), item('b', { 'nisar:track': 12 }, asset))).toBe(false);
  });

  it('keeps timeline series in one provenance stratum and prevents mismatched pair swipes', () => {
    const acquisition = item('a');
    const otherTrack = item('b', { 'nisar:track': 12 });
    expect(sameSeriesStratum(acquisition, item('c'))).toBe(true);
    expect(sameSeriesStratum(acquisition, otherTrack)).toBe(false);
    const pairA = item('pair-a', { datetime: null, start_datetime: '2026-05-01', end_datetime: '2026-05-05' }, { data: { href: 's3://bucket/a.tif' } });
    const pairB = item('pair-b', { datetime: null, start_datetime: '2026-05-02', end_datetime: '2026-05-05' }, { data: { href: 's3://bucket/b.tif' } });
    expect(canCompare(pairA, pairB)).toBe(false);
    expect(canCompare(pairA, item('single', {}, { data: { href: 's3://bucket/c.tif' } }))).toBe(false);
  });

  it('reads only finite sampled values from the point response', () => {
    expect(pointValue({ values: [null, NaN, 0.42] })).toBe(0.42);
    expect(pointValue({ values: [null, 'no data'] })).toBeUndefined();
  });

  it('uses categorical hiding and a symmetric zero-centered scale for signed offsets', () => {
    const asset = { data: { href: 's3://bucket/scene.tif', 'raster:bands': [{ statistics: { minimum: -3, maximum: 11 } }] } };
    const offset = item('offset', { product: 'nisar-goff', parameter: 'along_track_offset', unit: 'm' }, asset);
    expect(rasterVisualization(offset)).toBe('diverging');
    expect(rasterScale(offset)).toEqual([-11, 11]);
    const flags = item('flags', { 'nisar:visualization': 'categorical' }, { data: { href: 's3://bucket/flags.tif' } });
    expect(rasterVisualization(flags)).toBe('categorical');
    expect(rasterHref(flags)).toBeDefined();
    expect(displayRasterHref(flags)).toBeUndefined();
  });

  it('builds the configured TiTiler tile path and signed color scale', () => {
    const row = item('difference', { parameter: 'hh-backscatter-difference' }, {
      data: { href: 's3://bucket/change.tif', 'raster:bands': [{ statistics: { minimum: -2, maximum: 5 } }] },
    });
    const template = tileTemplate(rasterHref(row)!, row);
    expect(template).toContain('/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?');
    const query = new URLSearchParams(template.split('?')[1]);
    expect(query.get('colormap_name')).toBe('rdbu');
    expect(query.get('rescale')).toBe('-5,5');
  });
});

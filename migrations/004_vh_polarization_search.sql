INSERT INTO pgstac.queryables(name, definition, property_wrapper, property_index_type)
SELECT 'nisar:has_vh', '{"title":"Contains VH polarization","type":"boolean"}'::jsonb, 'to_text', 'BTREE'
WHERE NOT EXISTS (
    SELECT 1 FROM pgstac.queryables q
    WHERE q.name='nisar:has_vh' AND q.collection_ids IS NULL
);

UPDATE pgstac.items
SET content = jsonb_set(content, '{properties,nisar:has_vh}', to_jsonb(
    COALESCE((content #> '{properties,sar:polarizations}') ? 'VH',
             upper(content #>> '{properties,parameter}') ~ '(^|[^A-Z])VH([^A-Z]|$)', false)), true)
WHERE content #> '{properties}' IS NOT NULL
  AND NOT ((content #> '{properties}') ? 'nisar:has_vh');

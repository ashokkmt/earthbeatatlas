INSERT INTO pgstac.queryables(name, definition, property_wrapper, property_index_type)
SELECT name, definition::jsonb, 'to_text', 'BTREE'
FROM (VALUES
    ('nisar:has_hh', '{"title":"Contains HH polarization","type":"boolean"}'),
    ('nisar:has_hv', '{"title":"Contains HV polarization","type":"boolean"}'),
    ('nisar:has_vv', '{"title":"Contains VV polarization","type":"boolean"}')
) AS fields(name, definition)
WHERE NOT EXISTS (
    SELECT 1 FROM pgstac.queryables q
    WHERE q.name=fields.name AND q.collection_ids IS NULL
);

UPDATE pgstac.items
SET content = jsonb_set(
    jsonb_set(
        jsonb_set(content, '{properties,nisar:has_hh}', to_jsonb(
            COALESCE((content #> '{properties,sar:polarizations}') ? 'HH',
                     upper(content #>> '{properties,parameter}') ~ '(^|[^A-Z])HH([^A-Z]|$)', false)), true),
        '{properties,nisar:has_hv}', to_jsonb(
            COALESCE((content #> '{properties,sar:polarizations}') ? 'HV',
                     upper(content #>> '{properties,parameter}') ~ '(^|[^A-Z])HV([^A-Z]|$)', false)), true),
    '{properties,nisar:has_vv}', to_jsonb(
        COALESCE((content #> '{properties,sar:polarizations}') ? 'VV',
                 upper(content #>> '{properties,parameter}') ~ '(^|[^A-Z])VV([^A-Z]|$)', false)), true)
WHERE content #> '{properties}' IS NOT NULL
  AND NOT (content #> '{properties}') ? 'nisar:has_hh';

UPDATE pgstac.items
SET content = jsonb_set(
    jsonb_set(
        jsonb_set(
            jsonb_set(content, '{properties,nisar:has_hh}', to_jsonb(
                COALESCE((content #> '{properties,sar:polarizations}') ? 'HH',
                         upper(content #>> '{properties,parameter}') ~ '(^|[^A-Z])HH([^A-Z]|$)', false)), true),
            '{properties,nisar:has_hv}', to_jsonb(
                COALESCE((content #> '{properties,sar:polarizations}') ? 'HV',
                         upper(content #>> '{properties,parameter}') ~ '(^|[^A-Z])HV([^A-Z]|$)', false)), true),
        '{properties,nisar:has_vh}', to_jsonb(
            COALESCE((content #> '{properties,sar:polarizations}') ? 'VH',
                     upper(content #>> '{properties,parameter}') ~ '(^|[^A-Z])VH([^A-Z]|$)', false)), true),
    '{properties,nisar:has_vv}', to_jsonb(
        COALESCE((content #> '{properties,sar:polarizations}') ? 'VV',
                 upper(content #>> '{properties,parameter}') ~ '(^|[^A-Z])VV([^A-Z]|$)', false)), true)
WHERE content #> '{properties}' IS NOT NULL
  AND (
      NOT ((content #> '{properties}') ? 'nisar:has_hh')
      OR NOT ((content #> '{properties}') ? 'nisar:has_hv')
      OR NOT ((content #> '{properties}') ? 'nisar:has_vh')
      OR NOT ((content #> '{properties}') ? 'nisar:has_vv')
  );

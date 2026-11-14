CREATE SCHEMA IF NOT EXISTS nasa_explorer;
CREATE TABLE IF NOT EXISTS nasa_explorer.schema_migrations (
    version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS nasa_explorer.source_revisions (
    collection_id text NOT NULL, item_id text NOT NULL, revision_id text NOT NULL,
    revision_date timestamptz, payload_sha256 text NOT NULL, payload jsonb NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (collection_id, item_id, revision_id, payload_sha256)
);
CREATE TABLE IF NOT EXISTS nasa_explorer.sync_state (
    source text PRIMARY KEY, next_url text, last_success timestamptz, last_error text,
    cursor text, expected_records bigint, pages bigint NOT NULL DEFAULT 0,
    records bigint NOT NULL DEFAULT 0
);
ALTER TABLE nasa_explorer.sync_state ADD COLUMN IF NOT EXISTS cursor text;
ALTER TABLE nasa_explorer.sync_state ADD COLUMN IF NOT EXISTS expected_records bigint;
CREATE TABLE IF NOT EXISTS nasa_explorer.sync_runs (
    id bigserial PRIMARY KEY, source text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz, status text NOT NULL, pages bigint NOT NULL DEFAULT 0,
    records bigint NOT NULL DEFAULT 0, error text
);
CREATE TABLE IF NOT EXISTS nasa_explorer.jobs (
    id text PRIMARY KEY, kind text NOT NULL, status text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}', updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS source_revisions_item_idx
    ON nasa_explorer.source_revisions (collection_id, item_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS sync_runs_started_idx ON nasa_explorer.sync_runs (started_at DESC);
INSERT INTO pgstac.queryables(name, definition, property_wrapper, property_index_type)
SELECT name, definition::jsonb, 'to_text', 'BTREE'
FROM (VALUES
    ('product', '{"title":"Product family","type":"string"}'),
    ('parameter', '{"title":"Measured parameter","type":"string"}'),
    ('nisar:collection_maturity', '{"title":"NISAR collection maturity","type":"string"}'),
    ('readiness:archive', '{"title":"Archive availability","type":"string"}'),
    ('quality:state', '{"title":"Project quality state","type":"string"}'),
    ('readiness:visual', '{"title":"Prepared visual asset state","type":"string"}'),
    ('readiness:reviewed_change', '{"title":"Reviewed change state","type":"string"}')
) AS fields(name, definition)
WHERE NOT EXISTS (SELECT 1 FROM pgstac.queryables q WHERE q.name=fields.name AND q.collection_ids IS NULL);

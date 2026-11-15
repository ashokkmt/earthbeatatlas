ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS request jsonb;
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS request_sha256 text;
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS idempotency_sha256 text;
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS progress smallint NOT NULL DEFAULT 0;
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 3;
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS available_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false;
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS error jsonb;
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE nasa_explorer.jobs ADD COLUMN IF NOT EXISTS expires_at timestamptz NOT NULL DEFAULT (now() + interval '7 days');
CREATE UNIQUE INDEX IF NOT EXISTS jobs_idempotency_sha_idx
    ON nasa_explorer.jobs(idempotency_sha256) WHERE idempotency_sha256 IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_queue_claim_idx
    ON nasa_explorer.jobs(available_at, created_at) WHERE status IN ('queued', 'running');

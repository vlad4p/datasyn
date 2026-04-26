-- OpenMetadata-inspired dataset entity: JSONB payload + FQN hash + full-text search.
-- https://docs.open-metadata.org/v1.12.x/api-reference/main-concepts/backend-db

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE dataset_entity (
    id BIGSERIAL PRIMARY KEY,
    fqn_hash TEXT NOT NULL UNIQUE,
    fully_qualified_name TEXT NOT NULL UNIQUE,
    entity_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'simple',
            coalesce(fully_qualified_name, '') || ' ' ||
            coalesce(entity_json->>'name', '') || ' ' ||
            coalesce(entity_json->>'displayName', '') || ' ' ||
            coalesce(entity_json->>'description', '')
        )
    ) STORED
);

CREATE INDEX dataset_entity_updated_at_idx ON dataset_entity (updated_at DESC);
CREATE INDEX dataset_entity_search_idx ON dataset_entity USING GIN (search_tsv);
CREATE INDEX dataset_entity_entity_json_gin ON dataset_entity USING GIN (entity_json jsonb_path_ops);

CREATE OR REPLACE FUNCTION dataset_entity_set_fqn_hash() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.fqn_hash := encode(digest(lower(trim(NEW.fully_qualified_name)), 'sha256'), 'hex');
    RETURN NEW;
END;
$$;

CREATE TRIGGER dataset_entity_fqn_hash_trg
    BEFORE INSERT OR UPDATE OF fully_qualified_name ON dataset_entity
    FOR EACH ROW
    EXECUTE FUNCTION dataset_entity_set_fqn_hash();

CREATE OR REPLACE FUNCTION dataset_entity_touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER dataset_entity_updated_at_trg
    BEFORE UPDATE ON dataset_entity
    FOR EACH ROW
    EXECUTE FUNCTION dataset_entity_touch_updated_at();

COMMENT ON TABLE dataset_entity IS 'Minimal table_entity analogue: flexible metadata in entity_json; FQN columns for indexing.';

-- Relationship edges (lineage) and denormalized tag usage; OM-style separation from entity JSON.

CREATE TABLE entity_relationship (
    id BIGSERIAL PRIMARY KEY,
    from_id BIGINT NOT NULL REFERENCES dataset_entity (id) ON DELETE CASCADE,
    to_id BIGINT NOT NULL REFERENCES dataset_entity (id) ON DELETE CASCADE,
    from_entity TEXT NOT NULL DEFAULT 'dataset',
    to_entity TEXT NOT NULL DEFAULT 'dataset',
    relation TEXT NOT NULL CHECK (relation IN ('upstream', 'downstream')),
    CONSTRAINT entity_relationship_no_self CHECK (from_id <> to_id)
);

CREATE INDEX entity_relationship_from_idx ON entity_relationship (from_id);
CREATE INDEX entity_relationship_to_idx ON entity_relationship (to_id);
CREATE UNIQUE INDEX entity_relationship_edge_uniq
    ON entity_relationship (from_id, to_id, relation);

CREATE TABLE tag_usage (
    id BIGSERIAL PRIMARY KEY,
    target_id BIGINT NOT NULL REFERENCES dataset_entity (id) ON DELETE CASCADE,
    tag_fqn TEXT NOT NULL,
    source SMALLINT NOT NULL DEFAULT 0,
    UNIQUE (target_id, tag_fqn)
);

CREATE INDEX tag_usage_tag_fqn_idx ON tag_usage (tag_fqn);

COMMENT ON TABLE entity_relationship IS 'Lineage only when both endpoints exist as dataset_entity rows; JSON on entity remains full source of truth.';
COMMENT ON TABLE tag_usage IS 'Denormalized from entity_json.tags; source 0=classification, 1=glossary (OpenMetadata tag_usage).';

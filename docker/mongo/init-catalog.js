// Runs once on first MongoDB startup (empty data volume).
// Compose sets MONGO_INITDB_DATABASE=datacyber_catalog so `db` is that database.

db.createCollection("datasets");

db.datasets.createIndex({ fullyQualifiedName: 1 }, { unique: true });
db.datasets.createIndex(
  { "service.name": 1, "database.name": 1, "schema.name": 1, name: 1 },
  { name: "service_db_schema_name" }
);
db.datasets.createIndex({ updatedAt: -1 });
db.datasets.createIndex({
  name: "text",
  description: "text",
  displayName: "text",
  fullyQualifiedName: "text",
});

db.metadata.insertOne({
  _id: "catalog_bootstrap",
  version: 1,
  reference: "OpenMetadata-style table/dataset entities (v1.12.x concepts: FQN, service, schema, columns, tags, owners, lineage)",
  createdAt: new Date(),
});

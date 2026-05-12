---
name: upload_files_storage
description: Upload files from local filesystem or data-local mount to object storage (MinIO/S3) using the storage-mcp tools.
---

# Upload Files to Object Storage

This skill uploads files from the local filesystem (typically the `/data-local` mount) to object storage (MinIO/S3) via the `storage-mcp` server.

## Prerequisites

- The file must already exist on the local filesystem (typically under `/data-local/`).
- The `storage-mcp` server must be running and reachable (configured in `mcp.json` as the `storage` server).

## Tools Used

All tools are from the **`storage-mcp`** server (prefixed `storage_` in the runtime):

| Tool | Purpose |
|------|---------|
| `storage_list_buckets` | Verify the target bucket exists |
| `storage_list_objects` | Check existing objects in the target prefix |
| `storage_put_object_text` | Upload a file's content as a text object |

## Workflow

### 1. Verify the source file exists

Locate the file under `/data-local/` (or another local path). Use `duckdb_list_data_mount` or `glob` to confirm.

### 2. Read the file content

Read the file into a string variable.

### 3. Upload to object storage

Call `storage_put_object_text` with:
- `key`: the destination key (e.g., `landing/indec/indec.csv`)
- `text`: the file content
- `bucket`: (optional) target bucket, defaults to `data-local`
- `content_type`: (optional) MIME type, defaults to `text/plain; charset=utf-8`

## Example: Upload `data-local/indec.csv` to `landing/indec/indec.csv`

```python
# 1. Verify source exists
# Use duckdb_list_data_mount or glob to check /data-local/indec.csv

# 2. Read file content
with open("/data-local/indec.csv", "r") as f:
    content = f.read()

# 3. Upload to storage
storage_put_object_text(
    key="landing/indec/indec.csv",
    text=content,
    bucket="data-local",
)
```

## Example: Upload all TXT files from a directory

```python
import os

source_dir = "/data-local/indec/mercado_laboral/EPH/2024/Q1"

for fname in sorted(os.listdir(source_dir)):
    if fname.endswith(".txt"):
        src_path = os.path.join(source_dir, fname)
        with open(src_path, "r") as f:
            content = f.read()
        dest_key = f"landing/indec/eph/{fname}"
        storage_put_object_text(
            key=dest_key,
            text=content,
        )
```

## Notes

- `storage_put_object_text` accepts **text only** (string content). For binary files, the `put_object_text` tool in `server.py` encodes to UTF-8.
- The default bucket is `data-local`. Pass a different `bucket` argument to use another bucket.
- The tool auto-creates the bucket if it does not exist (when `create_bucket_if_missing=True`, which is the default).
- The storage endpoint is `http://datacyber-object-minio:9000` (see `infra/object-storage/.env`).
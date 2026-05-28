---
name: upload-files-object-storage
description: Upload local text files to Datasyn object storage through the Kilo Code `storage` MCP server. Use when the user asks to upload, copy, put, or publish files into MinIO/S3 object storage with storage-mcp.
---

# Upload Files To Object Storage

Use the `storage` MCP server from `.kilo/kilo.jsonc`. Do not use `curl`, `aws`, `mc`, or ad-hoc shell uploads when the storage MCP tools are available.

## Storage MCP tools

The storage MCP server is `storage-mcp`. Depending on the host, tools may appear as either `storage_<tool>` or as unprefixed tools under the `storage` server. Use the tool schema exposed by Kilo, with these server-side contracts:

- `list_buckets()`
- `list_objects(bucket: str = "", prefix: str = "", max_keys: int = 200)`
- `get_object_text(bucket: str = "", key: str = "", encoding: str = "utf-8")`
- `put_object_text(key: str, text: str, bucket: str = "", content_type: str = "text/plain; charset=utf-8", create_bucket_if_missing: bool = true)`
- `delete_object(bucket: str = "", key: str = "")`

An empty `bucket` uses the server default bucket, normally `data-local`.

## Upload workflow

1. Resolve the source path or paths requested by the user.
   - For a file, upload that file.
   - For a directory, enumerate files recursively and preserve relative paths below the destination prefix.
   - Skip directories and hidden system artifacts unless the user explicitly asks for them.
2. Confirm the destination.
   - Default bucket: `data-local`.
   - Object keys must use `/` separators and must not start with `/`.
   - If the user gives a prefix, append the file basename or relative path under that prefix.
3. Before writing, call `list_objects` with the destination key as `prefix`.
   - If an exact key already exists and the user did not explicitly allow overwrite, ask before replacing it.
4. Read each source file as UTF-8 text.
   - `put_object_text` only uploads text content.
   - If a file is binary or cannot decode as UTF-8, stop and report that the current storage MCP upload tool is text-only for that file.
5. Upload each file with `put_object_text`.
   - Use `bucket` only when the user specifies a non-default bucket.
   - Set `content_type` from the file type when obvious; otherwise use `text/plain; charset=utf-8`.
   - Keep `create_bucket_if_missing=true` unless the user asks not to create buckets.
6. Verify the upload with `list_objects` on the destination prefix.
7. Report the result with bucket, object key, bytes written, content type, and any failures.

## Key mapping

Use deterministic key mapping:

```text
single file + no prefix:        <basename>
single file + prefix:           <prefix>/<basename>
directory + no prefix:          <relative/path/from/source/root>
directory + prefix:             <prefix>/<relative/path/from/source/root>
```

Normalize duplicate slashes. Never include local absolute path components such as `/Users/...` in object keys unless the user explicitly asks for that layout.

## Example

User asks: "Upload `reports/summary.md` to storage under `reports/latest/`."

Use:

```json
{
  "bucket": "",
  "key": "reports/latest/summary.md",
  "text": "<contents of reports/summary.md>",
  "content_type": "text/markdown; charset=utf-8",
  "create_bucket_if_missing": true
}
```

Then verify with:

```json
{
  "bucket": "",
  "prefix": "reports/latest/summary.md",
  "max_keys": 10
}
```

## Failure handling

- If an MCP call returns `"ok": false`, report the error verbatim and do not claim success.
- If `list_objects` returns `is_truncated: true`, narrow the prefix before deciding whether a key exists.
- If only some files upload, report the successful keys and the failed files separately.

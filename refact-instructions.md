in the follow strucrture the folder is:
(datacyber) ➜  datacyber git:(first-commit) ✗ ls -l  
total 1336
-rw-r--r--@  1 vlad  staff   28908 Apr 29 14:48 AGENTS.md
-rw-r--r--   1 vlad  staff     867 Apr 26 21:04 Dockerfile
drwxr-xr-x   9 vlad  staff     288 Apr 29 15:20 agent
-rw-r--r--   1 vlad  staff    1946 Apr 25 22:30 compose.env
-rw-r--r--   1 vlad  staff     697 Apr 27 12:26 deepagents.toml
-rw-r--r--   1 vlad  staff    1356 Apr 29 15:43 docker-compose.yaml
drwxr-xr-x   2 vlad  staff      64 Apr 29 15:31 docs
drwxr-xr-x   8 vlad  staff     256 Apr 29 15:24 infra
-rw-r--r--   1 vlad  staff     307 Apr 25 22:29 mcp.json
drwxr-xr-x   8 vlad  staff     256 Apr 27 15:03 mcp_servers
-rw-r--r--@  1 vlad  staff     952 Apr 28 20:37 pyproject.toml
-rw-r--r--@  1 vlad  staff    2436 Apr 21 23:44 requirements.txt
drwxr-xr-x  10 vlad  staff     320 Apr 29 14:28 skills
drwxr-xr-x  15 vlad  staff     480 Apr 29 15:42 ui
-rw-r--r--@  1 vlad  staff  619247 Apr 21 23:38 uv.lock

**agent**
the Agent is the main deep agent for this repository. The *Dockerfile* and *docker-compose.yaml* describe the *agent* and *ui*
**ui**
The ui is a react app, add a Dockerfile

**mcp_servers**
Improve the mcp servers, all mcp server, share the docker-compose
(datacyber) ➜  datacyber git:(first-commit) ✗ ls -l mcp_servers
total 16
drwxr-xr-x  15 vlad  staff   480 Apr 27 15:03 dagster-mcp
-rw-r--r--   1 vlad  staff  7318 Apr 29 14:47 docker-compose.yaml
drwxr-xr-x   8 vlad  staff   256 Apr 29 15:51 duckdb-mcp
drwxr-xr-x   6 vlad  staff   192 Apr 23 12:30 duckdb-ui
drwxr-xr-x   9 vlad  staff   288 Apr 29 14:48 scrapper-mcp

- update the duckdb-mcp, now, the "data" is in the infra volume **duckdb_data** defined in the infra/duckdb/docker-compose.yaml
- update the mcp_servers/docker-compose.yaml, add the volume "storage" from

**infra**
has the different parts of the infra, every part, should be have a docker-compose, and share the networking called "infra-datasynk"

(datacyber) ➜  infra git:(first-commit) ✗ ls -l
total 0
drwxr-xr-x  12 vlad  staff   384 Apr 29 15:12 dagster
drwxr-xr-x   6 vlad  staff   192 Apr 29 15:33 duckdb
drwxr-xr-x  48 vlad  staff  1536 Apr 29 15:10 langfuse
drwxr-xr-x  12 vlad  staff   384 Apr 29 15:17 litellm
drwxr-xr-x   6 vlad  staff   192 Apr 29 15:29 object-storage


**dagster**
Dagster is the central catalog and orchestrate of the datasynk system, the damon, to run the jobs, read the data and write, should be attached and permission to the "duckdb" and "storage" volumes
**duckdb**
is the analytics layer
**langfuse**
observability  and monitoring
**litellm**
the gateway
**object-storage**
is the central object storage, is a minio with a volume called "storage", validate and fix if necessary


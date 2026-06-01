# Publishing checklist

Use this list before making **datasyn** public on GitHub.

## Completed in repo

- [x] Remove internal IPs and personal filesystem paths from tracked files
- [x] Add `SECURITY.md`
- [x] Generalize legacy **Ubika** deployment docs
- [x] Align `AGENTS.md` / README with in-repo skills and `mcp.json`
- [x] Fix auth test env isolation; narrow public routes when OAuth is on
- [x] Add `data-local/.gitkeep` for empty clone ergonomics
- [x] Split Makefiles: root = brain + UI; each `infra/<stack>/Makefile` owns deploy

## Before first public push

1. **History scan** — run [gitleaks](https://github.com/gitleaks/gitleaks) or [trufflehog](https://github.com/trufflesecurity/trufflehog) on full git history.
2. **Registry URL** — set `DATASYN_IMAGE_REGISTRY` / `REGISTRY_HTTP_URL` (see `make -C infra/distribution print-env`, `INSTALL.md`).
3. **Dagster run launcher** — edit `infra/dagster/runtime/dagster.yaml` volume path to your clone’s absolute `data-local` path (DockerRunLauncher does not support env interpolation there).
4. **Sibling repo** — publish [`datasyn-code`](https://github.com/YOUR_ORG/datasyn-code) or replace placeholder URLs in README.
5. **IDE config** — review `.cursor/` and `.kilo/`; remove or sanitize machine-specific MCP URLs if needed.
6. **OAuth** — create Google/GitHub OAuth apps with production redirect URLs; set strong `OAUTH_SESSION_SECRET` (≥ 32 bytes).

## Optional follow-ups

- Add GitHub Actions CI (`uv run pytest`, UI build)
- Add `CODE_OF_CONDUCT.md` if you expect external contributors
- Expand in-repo skills or move agent playbooks from `AGENTS.md` into `skills/`

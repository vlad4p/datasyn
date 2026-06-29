# Gitflow reference

## Branch naming

| Valid | Invalid |
|-------|---------|
| `feature/ui-build-fix` | `feature_ui` (no underscore) |
| `release/1.2.0` | `release-v1.2.0` (use slash) |
| `hotfix/fix-null-count` | `hotfix` (missing name) |

Use lowercase kebab-case after the prefix.

## Versioning (semver)

- **release/** — bump MINOR or MAJOR: `1.1.0` → `1.2.0` or `2.0.0`
- **hotfix/** — bump PATCH only: `1.2.0` → `1.2.1`

Tag format: `v<major>.<minor>.<patch>` (e.g. `v1.2.0`).

## Merge strategies

| Scenario | Strategy | Why |
|----------|----------|-----|
| Feature → develop | Squash or merge commit (team preference) | Clean history on develop |
| Release → main | `--no-ff` merge commit | Preserves release boundary |
| Hotfix → main | `--no-ff` merge commit | Traceable hotfix lineage |
| Back-merge to develop | `--no-ff` | develop stays aware of main fixes |

Squash-merge on GitHub is acceptable for feature PRs if the team prefers linear history on `develop`.

## Common commands

```bash
# List branches by type
git branch | grep '^  feature/'
git branch | grep '^  release/'
git branch | grep '^  hotfix/'

# See commits on feature not in develop
git log develop..feature/<name> --oneline

# See commits on develop not in main
git log main..develop --oneline

# Abort a merge in progress
git merge --abort

# Update feature branch with latest develop
git checkout feature/<name>
git fetch origin
git merge origin/develop
# or: git rebase origin/develop  (only if user approves rebase)
```

## Edge cases

### No `develop` branch yet

Bootstrap once (see SKILL.md). Until then, use `main` as integration — document the exception.

### Feature branch is stale

```bash
git checkout feature/<name>
git fetch origin
git merge origin/develop
# resolve conflicts, test, push
```

Prefer merge over rebase unless the user explicitly wants rebase.

### Release branch needs a fix found on develop

Cherry-pick or merge the specific commit onto `release/<version>` — never merge all of `develop` into a release branch.

### Hotfix while a release branch is open

Finish the hotfix first (merge to `main` + `develop`), then merge `main` or `develop` into the open `release/` branch to pick up the fix.

### Accidental commit on wrong branch

If not pushed: `git stash`, checkout correct branch, `git stash pop`.
If pushed: ask user before any history rewrite.

## GitHub settings (recommended)

- Default branch: `main`
- Branch protection on `main` and `develop`: require PR, no force push
- Delete head branches after merge: enabled

## datasyn specifics

| Path | Branch typical scope |
|------|---------------------|
| `agent/` | feature / fix |
| `ui/` | feature / fix |
| `skills/` | feature or docs |
| `mcp/` | feature / chore |
| `docker-compose.yaml`, `Makefile` | feature / deploy |
| `AGENTS.md`, `README.md` | docs or chore |

Never commit: `data-local/**` (real data), `reports/**`, `inbox/**`, `tmp/**`, `.cache/skills/**`, `.env` or env variants, secrets, `warehouse.duckdb`, API keys. See **`.cursorrules`** and **`AGENTS.md`** security section.

Pipeline ingest code lives in sibling **`datasyn-code`** — use gitflow there for Dagster assets; this repo uses gitflow for brain, UI, MCP, and skills.

---
name: gitflow
description: >-
  Implement and operate Gitflow branching (main, develop, feature, release,
  hotfix). Use when the user asks for gitflow, branch strategy, feature branches,
  releases, hotfixes, merging to main/develop, or version tagging.
---

# Gitflow

Branching model for datasyn. Long-lived `main` + `develop`; short-lived
`feature/`, `release/`, and `hotfix/` branches.

```
main     ●─────────●─────────────────●─────────●  (tags: v1.0.0, v1.1.0)
          \       /                 ↑         /
develop    ●──●──●──●──●──●──●──●──●──●──●──●
                \    /  \        /    /
feature          ●──●    ●──────●
release                    ●────●
hotfix                              ●──●
```

| Branch | Prefix | Base | Merge into | Purpose |
|--------|--------|------|------------|---------|
| **main** | — | — | — | Production-ready; every merge is releasable |
| **develop** | — | `main` (bootstrap) | — | Integration; latest completed work |
| **feature** | `feature/` | `develop` | `develop` | New work (agent, UI, skills, MCP, deploy) |
| **release** | `release/` | `develop` | `main` + `develop` | Stabilize, version bump, pre-release QA |
| **hotfix** | `hotfix/` | `main` | `main` + `develop` | Urgent production fix |

## Before any gitflow operation

1. **Inspect state** (run in parallel when possible):

```bash
git status
git branch -a
git log --oneline -5
git remote -v
```

2. **Confirm** the operation type (feature / release / hotfix / finish) with the user.
3. **Never** run destructive commands (`push --force`, `reset --hard`) on `main` or
   `develop` unless the user explicitly requests it.
4. **Never** update git config, skip hooks, or commit unless the user asks.

Optional helper: `scripts/sh/gitflow.sh status` — branch model check.

## Bootstrap (first time)

Only when the repo has no `develop` yet:

```bash
git checkout main
git pull origin main
git checkout -b develop
git push -u origin develop
```

Set default PR base to `develop` for features; to `main` for hotfixes.

## Feature workflow

**Start** (from latest `develop`):

```bash
git checkout develop
git pull origin develop
git checkout -b feature/<short-kebab-name>
```

Naming: `feature/ui-build-fix`, `feature/gitflow-skill`, `feature/brain-oauth`.

**Work**: commit only when the user requests. Prefer small, focused commits.

**Finish** (via PR — preferred):

```bash
git push -u origin HEAD
gh pr create --base develop --title "feat(<scope>): <summary>" --body "$(cat <<'EOF'
## Summary
- ...

## Test plan
- [ ] ...

EOF
)"
```

After merge: delete remote and local feature branch.

```bash
git checkout develop
git pull origin develop
git branch -d feature/<short-kebab-name>
git push origin --delete feature/<short-kebab-name>  # if remote still exists
```

## Release workflow

**Start** when `develop` is ready for a version:

```bash
git checkout develop
git pull origin develop
git checkout -b release/<version>   # e.g. release/1.2.0
```

On the release branch only: version bumps, changelog, final QA fixes — **no new features**.

**Finish**:

```bash
# merge to main
git checkout main
git pull origin main
git merge --no-ff release/<version> -m "release: v<version>"
git tag -a v<version> -m "Release v<version>"
git push origin main --tags

# back-merge to develop
git checkout develop
git pull origin develop
git merge --no-ff release/<version> -m "merge release/<version> into develop"
git push origin develop

git branch -d release/<version>
git push origin --delete release/<version>
```

Use `gh pr create --base main` instead of direct merges when the team requires PR review.

## Hotfix workflow

**Start** from `main` (production bug):

```bash
git checkout main
git pull origin main
git checkout -b hotfix/<short-kebab-name>
```

**Finish** (same dual-merge as release):

```bash
git checkout main
git pull origin main
git merge --no-ff hotfix/<name> -m "hotfix: <summary>"
git tag -a v<version> -m "Hotfix v<version>"   # bump PATCH
git push origin main --tags

git checkout develop
git pull origin develop
git merge --no-ff hotfix/<name> -m "merge hotfix/<name> into develop"
git push origin develop

git branch -d hotfix/<name>
```

## Commit message convention

Align with existing repo style (`git log -5`). Default format:

```
<type>(<scope>): <imperative summary>

Optional body — why, not what.
```

| Type | Use |
|------|-----|
| `feat` | New capability (agent, UI, skill, deploy) |
| `fix` | Bug fix |
| `docs` | README, AGENTS, skills only |
| `chore` | Tooling, deps, bootstrap |
| `refactor` | Structure change, no behavior change |
| `release` | Version cut |

Scopes: `agent`, `ui`, `brain`, `mcp`, `skills`, `scripts`, `deploy`, `docker`.

## Pull request rules

Follow the project PR workflow (`gh` CLI):

1. `git status`, `git diff`, `git log` vs base branch — in parallel before creating PR.
2. Base branch: `develop` (features) · `main` (hotfixes, releases).
3. PR body: Summary + Test plan checklist.
4. Return the PR URL to the user.
5. Do not push unless the user asks.

## Decision flow

| User says | Action |
|-----------|--------|
| "New feature / agent / UI work" | `feature/` from `develop` |
| "Ship version X" / "cut a release" | `release/<version>` |
| "Production is broken" | `hotfix/` from `main` |
| "Merge my branch" | PR → correct base (`develop` or `main`) |
| "What branch am I on?" | `scripts/sh/gitflow.sh status` |

## Safety checklist

- [ ] Correct base branch checked out and pulled
- [ ] Branch name matches prefix (`feature/`, `release/`, `hotfix/`)
- [ ] `git diff --cached` has no data under `data-local/`, `reports/`, `inbox/`, `tmp/`, `.cache/skills/`
- [ ] No secrets, `.env`, credentials, `warehouse.duckdb`, or private MCP config in commits
- [ ] Commit message has no PII or raw data excerpts
- [ ] `main` never receives direct feature merges
- [ ] Hotfixes and releases merged to **both** `main` and `develop`
- [ ] Tags annotated on `main` for releases and hotfixes

## Additional resources

- Command cheat sheet and edge cases: [reference.md](reference.md)

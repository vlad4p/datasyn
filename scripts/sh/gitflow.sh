#!/usr/bin/env bash
# Gitflow helper — inspect branch state (no destructive operations).
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
  cat <<'EOF'
Usage: scripts/sh/gitflow.sh <command>

Commands:
  status    Show current branch, gitflow type, and divergence from main/develop
  check     Validate branch name against gitflow prefixes (exit 1 if invalid)

Examples:
  ./scripts/sh/gitflow.sh status
  ./scripts/sh/gitflow.sh check
EOF
}

current_branch() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown"
}

branch_type() {
  local branch="$1"
  case "$branch" in
    main|master) echo "main" ;;
    develop) echo "develop" ;;
    feature/*) echo "feature" ;;
    release/*) echo "release" ;;
    hotfix/*) echo "hotfix" ;;
    *) echo "other" ;;
  esac
}

count_ahead_behind() {
  local base="$1"
  if ! git rev-parse --verify "$base" >/dev/null 2>&1; then
    echo "n/a"
    return
  fi
  local ahead behind
  ahead=$(git rev-list --count "$base..HEAD" 2>/dev/null || echo "?")
  behind=$(git rev-list --count "HEAD..$base" 2>/dev/null || echo "?")
  echo "+${ahead}/-${behind}"
}

cmd_status() {
  local branch type
  branch=$(current_branch)
  type=$(branch_type "$branch")

  echo "=== Gitflow status ==="
  echo "Branch:  $branch"
  echo "Type:    $type"

  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    echo "vs origin/main:    $(count_ahead_behind origin/main)"
  elif git rev-parse --verify main >/dev/null 2>&1; then
    echo "vs main:           $(count_ahead_behind main)"
  fi

  if git rev-parse --verify origin/develop >/dev/null 2>&1; then
    echo "vs origin/develop: $(count_ahead_behind origin/develop)"
  elif git rev-parse --verify develop >/dev/null 2>&1; then
    echo "vs develop:        $(count_ahead_behind develop)"
  else
    echo -e "${YELLOW}develop branch not found — run gitflow bootstrap (see skills/gitflow/SKILL.md)${NC}"
  fi

  echo ""
  echo "Recent commits:"
  git log --oneline -3 2>/dev/null || true

  case "$type" in
    feature)
      echo -e "${GREEN}Expected merge target: develop${NC}"
      ;;
    release|hotfix)
      echo -e "${GREEN}Expected merge targets: main + develop${NC}"
      ;;
    other)
      echo -e "${YELLOW}Not a standard gitflow branch name${NC}"
      ;;
  esac
}

cmd_check() {
  local branch type
  branch=$(current_branch)
  type=$(branch_type "$branch")

  case "$type" in
    main|develop|feature|release|hotfix)
      echo -e "${GREEN}OK${NC}: $branch ($type)"
      exit 0
      ;;
    *)
      echo -e "${RED}INVALID${NC}: $branch is not a gitflow branch"
      echo "Use: main, develop, feature/<name>, release/<version>, hotfix/<name>"
      exit 1
      ;;
  esac
}

main() {
  local cmd="${1:-status}"
  case "$cmd" in
    status) cmd_status ;;
    check) cmd_check ;;
    -h|--help|help) usage ;;
    *)
      echo "Unknown command: $cmd" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "${1:-status}"

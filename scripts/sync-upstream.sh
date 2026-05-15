#!/usr/bin/env bash
# Sync upstream into the fork: fast-forward `main`, then merge into
# `personal`. See FORK.md for the branch model.
#
# Remote convention (standard):
#   origin   = your fork (push target)
#   upstream = the parent repo (read-only)
# Adjust the variables below if your remotes use different names.
#
# Usage:
#   ./scripts/sync-upstream.sh
#
# Idempotent. Refuses to run with a dirty working tree.

set -euo pipefail

UPSTREAM_REMOTE="upstream"
FORK_REMOTE="origin"
MAIN_BRANCH="main"
PERSONAL_BRANCH="personal"

# One-time: register the `ours` merge driver so .gitattributes works.
git config --local merge.ours.driver true

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is dirty. Commit or stash before syncing." >&2
  exit 1
fi

start_branch="$(git rev-parse --abbrev-ref HEAD)"

echo "[1/4] Fetching ${UPSTREAM_REMOTE}..."
git fetch "${UPSTREAM_REMOTE}"

echo "[2/4] Fast-forwarding ${MAIN_BRANCH} to ${UPSTREAM_REMOTE}/${MAIN_BRANCH}..."
git checkout "${MAIN_BRANCH}"
git merge --ff-only "${UPSTREAM_REMOTE}/${MAIN_BRANCH}"
git push "${FORK_REMOTE}" "${MAIN_BRANCH}"

echo "[3/4] Merging ${MAIN_BRANCH} into ${PERSONAL_BRANCH}..."
git checkout "${PERSONAL_BRANCH}"
git merge --no-edit "${MAIN_BRANCH}"
git push "${FORK_REMOTE}" "${PERSONAL_BRANCH}"

if [[ "${start_branch}" != "${MAIN_BRANCH}" && "${start_branch}" != "${PERSONAL_BRANCH}" ]]; then
  echo "[4/4] Returning to ${start_branch}..."
  git checkout "${start_branch}"
else
  echo "[4/4] Staying on ${start_branch}."
fi

echo "Sync complete."

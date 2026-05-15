#!/usr/bin/env bash
set -euo pipefail

# Provisions branch and tag rulesets + repo settings for this personal fork.
# Modeled on pedropaulovc/typescript-project/scripts/provision-repo.sh, with
# adaptations for the fork's branch model (main tracks upstream; the
# auto-sync workflow needs to push, so the Actions integration gets an
# unconditional bypass on main).
#
# Idempotent: existing rulesets are updated in place. Safe to re-run.
#
# Usage:
#   scripts/provision-fork.sh                  # auto-detects repo from git remote
#   scripts/provision-fork.sh owner/repo       # explicit repo

REPO="${1:-}"

if [[ -z "$REPO" ]]; then
  REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null) || {
    echo "Error: could not detect repo. Pass owner/repo as argument." >&2
    exit 1
  }
fi

echo "Provisioning $REPO ..."

# ── Helpers ────────────────────────────────────────────────────────────────────

ruleset_id_by_name() {
  gh api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$1\") | .id" 2>/dev/null || true
}

upsert_ruleset() {
  local name="$1"
  local body
  body=$(cat)

  local existing_id
  existing_id=$(ruleset_id_by_name "$name")

  if [[ -n "$existing_id" ]]; then
    echo "  Updating ruleset: $name (id $existing_id) ..."
    echo "$body" | gh api "repos/$REPO/rulesets/$existing_id" -X PUT --silent --input -
  else
    echo "  Creating ruleset: $name ..."
    echo "$body" | gh api "repos/$REPO/rulesets" -X POST --silent --input -
  fi
}

# ── Drop legacy branch protection (if present) before applying rulesets ─────
echo "  Removing legacy branch protection on main (if any) ..."
gh api "repos/$REPO/branches/main/protection" -X DELETE --silent 2>/dev/null || true

# ── Repo settings — merge-only, like typescript-project ─────────────────────
echo "  Setting merge strategy (merge-only) and auto-merge ..."
gh api "repos/$REPO" -X PATCH --silent \
  -F allow_merge_commit=true \
  -F allow_squash_merge=false \
  -F allow_rebase_merge=false \
  -F allow_auto_merge=true \
  -f merge_commit_title=PR_TITLE \
  -f merge_commit_message=PR_BODY \
  -F delete_branch_on_merge=true

# ── Branch ruleset: Protect main ───────────────────────────────────────────
# Adaptations vs typescript-project:
#  - No required_status_checks (upstream's ci.yml is conda-based and we
#    don't want to gate fork sync on it; pedro-ci runs on personal).
#  - No pull_request rule. The auto-sync workflow needs to push to main,
#    and GitHub does not allow Integration-actor bypass on personal-account
#    repos (orgs only). Without a PR rule, the workflow can push directly;
#    with one, we'd need a PAT or PR-based sync workflow.
#  - Admin bypass is `always` — emergency manual fixes (e.g., reset main
#    after upstream history rewrite) shouldn't be blocked.
#  - Footgun coverage: deletion, force push, and merge commits on main are
#    all blocked. Direct fast-forward of unrelated commits is NOT blocked
#    (relies on convention "never commit on main"). To close that gap,
#    convert pedro-sync-upstream.yml to open+auto-merge a PR and add the
#    pull_request rule back.
upsert_ruleset "Protect main" <<'JSON'
{
  "name": "Protect main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main"],
      "exclude": []
    }
  },
  "bypass_actors": [
    {
      "actor_id": 5,
      "actor_type": "RepositoryRole",
      "bypass_mode": "always"
    }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" }
  ]
}
JSON

# ── Branch ruleset: Protect personal (light) ────────────────────────────────
# Personal is the daily working branch — no PR requirement, just no
# accidental deletion or force-push.
upsert_ruleset "Protect personal" <<'JSON'
{
  "name": "Protect personal",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/personal"],
      "exclude": []
    }
  },
  "bypass_actors": [
    {
      "actor_id": 5,
      "actor_type": "RepositoryRole",
      "bypass_mode": "always"
    }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" }
  ]
}
JSON

# ── Tag ruleset: Immutable v* tags ──────────────────────────────────────────
upsert_ruleset "Immutable tags" <<'JSON'
{
  "name": "Immutable tags",
  "target": "tag",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/tags/v*"],
      "exclude": []
    }
  },
  "bypass_actors": [],
  "rules": [
    { "type": "update" },
    { "type": "deletion" }
  ]
}
JSON

echo "Done. Rulesets applied to $REPO."

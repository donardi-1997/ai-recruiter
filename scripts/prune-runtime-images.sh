#!/usr/bin/env bash
# Remove stale AI Recruiter image refs while preserving the active SHA and one rollback.
set -euo pipefail

if [[ $# -ne 6 ]]; then
  echo "usage: $0 <registry> <backend-repo> <frontend-repo> <current-sha> <backend-rollback-tag> <frontend-rollback-tag>" >&2
  exit 2
fi

REGISTRY="$1"
BACKEND_REPO="$2"
FRONTEND_REPO="$3"
CURRENT_SHA="$4"
BACKEND_ROLLBACK_TAG="$5"
FRONTEND_ROLLBACK_TAG="$6"

prune_repo_refs() {
  local repo="$1"
  local rollback_tag="$2"
  local image_repo="${REGISTRY}/${repo}"

  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    local tag="${ref##*:}"
    if [[ "$tag" == "$CURRENT_SHA" || "$tag" == "$rollback_tag" ]]; then
      continue
    fi
    docker rmi "$ref" >/dev/null 2>&1 || true
  done < <(docker images "$image_repo" --format '{{.Repository}}:{{.Tag}}')
}

prune_repo_refs "$BACKEND_REPO" "$BACKEND_ROLLBACK_TAG"
prune_repo_refs "$FRONTEND_REPO" "$FRONTEND_ROLLBACK_TAG"

# Any layers made dangling by removing stale SHA/latest tags are now safe to delete.
docker image prune -f

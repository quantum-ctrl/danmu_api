#!/usr/bin/env bash
set -euo pipefail

upstream_repository="${UPSTREAM_REPOSITORY:-https://github.com/huangxd-/danmu_api.git}"
target_branch="${TARGET_BRANCH:-main}"

summary() {
    echo "$1"
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        echo "$1" >> "$GITHUB_STEP_SUMMARY"
    fi
}

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
before=$(git rev-parse HEAD)
git fetch --no-tags "$upstream_repository" "refs/heads/main"
upstream=$(git rev-parse FETCH_HEAD)

if git merge-base --is-ancestor "$upstream" HEAD; then
    summary 'Already up to date with upstream.'
    exit 0
fi

# Record upstream ancestry even when workflow changes are excluded, so future
# syncs merge only new changes. --no-ff also prevents an early fast-forward.
if ! git merge --no-ff --no-commit "$upstream"; then
    if ! git rev-parse --verify -q MERGE_HEAD >/dev/null; then
        echo '::error::Could not start the upstream merge.'
        exit 1
    fi
fi

# Restore additions, deletions and conflicts in workflows to the target tree.
# contents:write does not grant GITHUB_TOKEN permission to update workflows.
git restore --source="$before" --staged --worktree -- .github/workflows

conflicts=$(git diff --name-only --diff-filter=U)
if [[ -n "$conflicts" ]]; then
    summary "Merge conflicts require manual resolution: $conflicts"
    git merge --abort
    echo '::error::Upstream sync stopped because application files have merge conflicts.'
    exit 1
fi

if ! git diff --cached --quiet "$upstream" -- .github/workflows; then
    summary 'Upstream workflows differ from local workflows. Local workflows were preserved; review upstream workflow changes separately.'
fi

git diff --cached --exit-code "$before" -- .github/workflows
git commit -m 'Sync upstream code while preserving local workflows'
# No force push: concurrent changes must never be overwritten.
git push origin "HEAD:refs/heads/$target_branch"
summary "Synced upstream $upstream; local workflows were preserved."

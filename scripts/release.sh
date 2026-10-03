#!/usr/bin/env bash
# Maintainer: make a Bron release.  Usage: scripts/release.sh <version>   (for example 0.5.0)
# Checks, bumps the version everywhere, runs the tests, commits "Release <version>" and tags v<version>.
# It never pushes. Afterwards: git push origin main && git push origin v<version>
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
VERSION="${1:-}"
FILES="core/VERSION core/Engine/pyproject.toml core/Engine/bron/__init__.py"

stop() { printf '%s\n' "$*" >&2; exit 1; }
order() { sort -t. -k1,1n -k2,2n -k3,3n; }

printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || stop "The version must look like 0.5.0."
[ -z "$(git status --porcelain --untracked-files=no)" ] || stop "Commit or stash your changes first."
latest="$(git tag -l 'v*' | sed 's/^v//' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | order | tail -n 1 || true)"
if [ -n "$latest" ]; then
  top="$(printf '%s\n%s\n' "$latest" "$VERSION" | order | tail -n 1)"
  if [ "$top" != "$VERSION" ] || [ "$latest" = "$VERSION" ]; then
    stop "Version $VERSION isn't newer than the latest release ($latest)."
  fi
fi
grep -Eq "^## $VERSION( |$)" CHANGELOG.md || stop "CHANGELOG.md has no section '## $VERSION'. Add one first."

printf '%s\n' "$VERSION" > core/VERSION
sed -i '' -E "s/^version = \"[0-9]+\.[0-9]+\.[0-9]+\"/version = \"$VERSION\"/" core/Engine/pyproject.toml
sed -i '' -E "s/^__version__ = \"[0-9]+\.[0-9]+\.[0-9]+\"/__version__ = \"$VERSION\"/" core/Engine/bron/__init__.py
if [ -f core/Engine/uv.lock ]; then
  uv lock --quiet --project core/Engine
  FILES="$FILES core/Engine/uv.lock"
fi

if ! bash -c "${BRON_RELEASE_TEST_CMD:-uv run --project core/Engine pytest tests -q}"; then
  # shellcheck disable=SC2086
  git checkout -q -- $FILES
  stop "The tests failed, so nothing was released."
fi

MESSAGE="Release $VERSION"
if [ -n "${BRON_COMMIT_TRAILER:-}" ]; then
  MESSAGE="$(printf '%s\n\n%s' "$MESSAGE" "$BRON_COMMIT_TRAILER")"
fi
# shellcheck disable=SC2086
git add $FILES
git commit -q -m "$MESSAGE"
git tag -a "v$VERSION" -m "Bron $VERSION"
echo "Released $VERSION (tag v$VERSION). Publish it with: git push origin main && git push origin v$VERSION"

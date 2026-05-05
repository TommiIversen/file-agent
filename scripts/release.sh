#!/bin/bash
# Finds the latest tag and pushes the next logical patch version to trigger a build.
# Usage: bash scripts/release.sh

set -e

LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null)

if [ -z "$LATEST_TAG" ]; then
  echo "No existing tags found. Starting at v0.1.0"
  NEXT_TAG="v0.1.0"
else
  # Strip 'v' prefix, split into parts
  VERSION="${LATEST_TAG#v}"
  IFS='.' read -r MAJOR MINOR PATCH <<< "$VERSION"
  NEXT_PATCH=$((PATCH + 1))
  NEXT_TAG="v${MAJOR}.${MINOR}.${NEXT_PATCH}"
fi

echo "Latest tag: ${LATEST_TAG:-none}"
echo "Next tag:   $NEXT_TAG"
echo ""
read -p "Push $NEXT_TAG to trigger build? [y/N] " CONFIRM

if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
  echo "$NEXT_TAG" > VERSION
  git add VERSION
  git commit -m "Release $NEXT_TAG"
  git tag "$NEXT_TAG"
  git push origin main
  git push origin "$NEXT_TAG"
  echo ""
  echo "Done! $NEXT_TAG pushed — build will start shortly."
else
  echo "Aborted."
fi

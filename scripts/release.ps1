# Finds the latest tag and pushes the next logical patch version to trigger a build.
# Usage: .\scripts\release.ps1

$ErrorActionPreference = "Stop"

# Find latest semver tag (vX.Y.Z) sorted by version
$latestTag = git tag --sort=-v:refname | Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } | Select-Object -First 1

if (-not $latestTag) {
    Write-Host "No existing semver tags found. Starting at v0.1.0"
    $nextTag = "v0.1.0"
} else {
    $version = $latestTag -replace '^v', ''
    $parts = $version -split '\.'
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    $patch = [int]$parts[2] + 1
    $nextTag = "v$major.$minor.$patch"
}

Write-Host "Latest tag: $($latestTag ?? 'none')"
Write-Host "Next tag:   $nextTag"
Write-Host ""

$confirm = Read-Host "Push $nextTag to trigger build? [y/N]"

if ($confirm -match '^[Yy]$') {
    $nextTag | Set-Content -NoNewline VERSION
    git add VERSION
    git commit -m "Release $nextTag"
    git tag $nextTag
    git push origin main
    git push origin $nextTag
    Write-Host ""
    Write-Host "Done! $nextTag pushed - build will start shortly."
} else {
    Write-Host "Aborted."
}

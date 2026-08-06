---
name: cut-release
description: Cut a new sbomify release. Bumps version in pyproject.toml and package.json, refreshes both lockfiles, opens a chore(release) PR, waits for CI to go green, merges, waits for master CI, tags the merge commit, then creates a GitHub release with auto-generated notes that you then amend before publishing. Use whenever the user says "cut a release", "ship a release", "tag a release", or "make a new release".
---

# Cut a release

sbomify releases are **CalVer** in the form **`YY.MM.MICRO`** (per [ADR-0002](https://github.com/sbomify/adr/blob/master/0002-adopt-calver-versioning.md)):

- **YY**: two-digit calendar year (`26`, `27`, ...).
- **MM**: month of release, `1` to `12`, **not zero-padded** (`26.7.0`, never `26.07.0`). Leading zeros are invalid SemVer (npm rejects them) and PEP 440 normalises `26.07` to `26.7`.
- **MICRO**: release counter within the month, starting at `0`. First release in the month is `.0`; each subsequent release that month increments it.

A skipped month simply leaves a gap in the sequence. That is expected.

## Determining the next version

Check the manifests first, then the tag list. The manifests can be ahead of the tags if a prior release bumped versions but never got tagged: in that case, do not bump again; just tag the current version.

```bash
grep '^version = ' pyproject.toml            # current manifest version
git fetch --tags
git tag -l 'v*' --sort=-v:refname | head -5  # latest tags
date +'%y.%-m'                                # YY.MM for today (unpadded month)
```

Reconcile:

- Manifest version has no matching tag: skip bumping, just tag the current commit as that version.
- Manifest and latest tag match, same month: bump MICRO (`26.7.1` becomes `26.7.2`).
- Manifest and latest tag match, new month: reset MICRO to `0` (`26.7.3` in July becomes `26.8.0` in August).
- New year in January: `27.1.0`.

If the version you compute is already tagged, stop and ask.

## Steps

Run these in order. Confirm the target version with the user before doing anything that touches git.

### 1. Confirm we're releasable

Working tree clean on `master` and up to date with `origin/master`. No open blocker PRs that were supposed to land first: check with the user if unsure.

```bash
git switch master
git pull --ff-only
git status
```

If the tree has unrelated dirty files or untracked work, stop and confirm with the user. If they say to proceed, stash with `git stash push -u -m "..." -- <paths>` (not silent, not global) and restore after tagging.

### 2. Bump versions and refresh both lockfiles

Skip this step entirely if the manifest is already at the target version (a prior release PR merged but was never tagged). Jump to step 6.

Otherwise, edit the `version` field in **both** manifests to the new version (keep them in sync), then refresh both lockfiles:

- `pyproject.toml` at `[project] version = "..."`
- `package.json` at `"version": "..."`

```bash
uv lock              # updates the sbomify entry in uv.lock
bun install          # updates bun.lock (frontend package version bump)
```

Sanity-check exactly four files changed and nothing else:

```bash
git status --porcelain
# Expect: pyproject.toml, package.json, uv.lock, bun.lock
```

If any other file is dirty, stop and figure out why before continuing.

### 3. Branch, commit, push, open PR

Branch name and commit subject follow the established convention exactly. The merge commit and the auto-tag paperwork downstream depend on them looking familiar:

```bash
VERSION=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)
git switch -c "chore/release-${VERSION}"
git add pyproject.toml package.json uv.lock bun.lock
git commit -m "$(cat <<EOF
chore(release): ${VERSION} (YY.MM.MICRO CalVer)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin "chore/release-${VERSION}"
gh pr create \
  --title "chore(release): ${VERSION}" \
  --body "Bumps version to \`${VERSION}\` and refreshes lockfiles. CalVer per ADR-0002."
```

### 4. Wait for CI green on the PR, then merge

Trust CI. No need to run ruff, pytest, or coverage locally first; that is what the PR pipeline is for.

```bash
gh pr checks --watch                # blocks until all checks resolve
gh pr merge --squash --auto         # or --merge, match the repo's usual pattern
```

If checks fail, **do not force through**. Investigate, push fixes to the release branch, wait again. Never skip hooks or bypass required checks.

### 5. Automated QA on master after merge

Once the PR is merged, wait for the CI pipeline on `master` to go green before tagging. This is the automated QA gate. A red master run means the release must not be tagged.

```bash
git switch master
git pull --ff-only
gh run watch $(gh run list --branch master --limit 1 --json databaseId --jq '.[0].databaseId')
```

If master CI is red: stop, surface the failure to the user, and only tag once it is resolved.

### 6. Tag the merge commit

Annotated tag on the merge commit, using the `v` prefix (matches all historical tags and the CI trigger in `.github/workflows/ci-cd.yml`, which builds and publishes images on `refs/tags/v*`):

```bash
git tag -a "v${VERSION}" -m "Release version ${VERSION}"
git push origin "v${VERSION}"
```

Pushing the tag kicks off the release image build in CI.

### 7. Create the GitHub release with auto-generated notes

Let GitHub generate the initial notes from PRs merged since the previous tag. Do **not** try to write the final notes yourself before this step; they will be overwritten.

```bash
gh release create "v${VERSION}" \
  --title "v${VERSION}" \
  --generate-notes \
  --verify-tag
```

### 8. Amend the release notes

Fetch the auto-generated body, rewrite it into a themed, human-readable changelog, and push the amended version back. This is done together with the user, not by the skill alone.

```bash
gh release view "v${VERSION}" --json body -q '.body' > /tmp/${VERSION}-raw.md
# Draft amended notes, propose to the user, iterate, save final to /tmp/${VERSION}-notes.md.
gh release edit "v${VERSION}" --notes-file /tmp/${VERSION}-notes.md
```

Suggested structure when drafting:

- **Highlights**: user-visible features and design changes, one bullet per theme, PR numbers in parens.
- **Fixes and performance**: bug fixes, perf work, back-end correctness.
- **API and security**: API surface changes, security posture, dependency security bumps.
- **Infrastructure**: CI, tooling, analytics, dependency upgrades that are worth naming.
- **New contributors**: verbatim from the auto-generated section.

Collapse dependabot noise into single lines or drop it. Group related PRs into one bullet. Match the tone of prior release notes in the same repo if you can see them (`gh release view <prev-tag>`).

After the amended notes are pushed, show the user the release URL (`gh release view v${VERSION} --web` opens it) so they can eyeball the final result.

## Guardrails

- **Never** amend or force-push a release commit or tag. If something is wrong, cut the next MICRO.
- **Never** skip CI (`--no-verify`, `-c commit.gpgsign=false`, bypassing required checks). Release integrity depends on it.
- If the working tree has unrelated dirty files at step 1, stop and confirm with the user rather than stashing silently.
- If `uv lock` or `bun install` touches more than the version-related entries (e.g. transitive upgrades), stop and ask. That belongs in a separate PR, not a release bump.
- The release PR contains **only** the version and lockfile bumps. Nothing else.
- No em-dashes in the amended release notes. Use colons, commas, parentheses, or a new sentence.

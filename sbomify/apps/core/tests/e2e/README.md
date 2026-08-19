
## The product-releases baselines come from CI, not from here

`test_product_releases_private_snapshot[*]` renders differently in this
environment than in CI. Locally the page reliably fails to load its releases
and shows a "Failed to load releases" toast over a "No releases yet" empty
state, under a badge that still reads "4 Releases". In CI the same page renders
the table with its four releases, which is the page the test means to pin.

So those four baselines are copied from the CI run's `e2e-test-diffs` artifact,
not generated here:

```bash
gh run download <run-id> -R sbomify/sbomify -n e2e-test-diffs -D /tmp/diffs
cp "/tmp/diffs/core/tests/e2e/__diffs__/test_product_releases_private_snapshot[1920].jpg" \
   "sbomify/apps/core/tests/e2e/__snapshots__/"
```

**A local regeneration sweep silently overwrites them with the broken render.**
Deleting a baseline and re-running writes whatever this machine produces, which
for this page is the error state, and CI then fails on a diff that looks like a
real regression. If you regenerate baselines in bulk, restore these four from a
CI artifact afterwards, or check them before committing.

The underlying local failure is worth fixing on its own; until it is, this is
the workaround.

# Upgrade notes

Steps an operator has to take when upgrading, beyond pulling the new image. Each
entry names the pull request it belongs to. When a release is cut, every entry
whose pull request is in that release goes into its release notes under
**Upgrade notes** (see `.claude/skills/cut-release/SKILL.md`, step 8).

Newest first. An entry stays here after its release, so anyone upgrading across
several releases can read every step in between.

## Scan results stored once (#1893, #1901)

**What changed.** Scanners, Dependency Track above all, rescan every SBOM on a
schedule and used to store the full list of findings again on every run, even
when nothing had changed. Two releases fix that:

- **#1893** stores each finding once in the findings table, and drops the old
  `vulnerability_scanning_findings` table.
- **#1901** stores each distinct findings list once, in object storage. Only a
  run that is still the current result for its SBOM keeps its findings in
  Postgres. Superseded runs point at the shared copy. EPSS scores, which
  Dependency Track refreshes daily, stay with each run, so an unchanged SBOM
  keeps one copy however often it is scanned. A nightly task
  (`offload_assessment_results_task`, 03:45 UTC) moves superseded runs, and the
  daily prune removes shared copies no run uses any more.

On an install with scheduled Dependency Track scans, this is most of the
database.

**What to do after upgrading.**

1. **Check that the old findings table is gone.** Migration
   `vulnerability_scanning.0017` drops it, but gives up and leaves it in place
   if running scans hold the locks it needs. While it is there, the nightly
   retention prune skips.

   ```sql
   SELECT to_regclass('vulnerability_scanning_findings');  -- NULL means it is gone
   ```

   If it is still there, drop it. Nothing reads it any more. If this times out, a
   scan is holding the lock; run it again.

   ```sql
   SET lock_timeout = '5s';
   DROP TABLE vulnerability_scanning_findings;
   ```

2. **Clear the backlog of superseded results in one go**, rather than waiting
   for the nightly task, which works for 3.5 hours a night:

   ```bash
   docker compose exec sbomify-backend python manage.py offload_assessment_results --dry-run
   docker compose exec sbomify-backend python manage.py offload_assessment_results
   ```

   It can be stopped and run again at any point, and it carries on from where it
   stopped.

3. **Give the space back to the disk.** Moving rows out frees space inside
   Postgres, which it reuses, but the files on disk do not shrink until the table
   is rewritten:

   ```bash
   pg_repack --table=plugins_assessment_runs <database>
   ```

   `VACUUM FULL plugins_assessment_runs;` works too, but it locks the table for
   the whole run and needs free disk space for a full copy, so run it in a quiet
   window.

**How to check it worked.**

```sql
SELECT pg_size_pretty(pg_total_relation_size('plugins_assessment_runs'));

SELECT count(*) FILTER (WHERE result IS NOT NULL) AS inline,
       count(*) FILTER (WHERE result_object_key <> '') AS moved,
       count(DISTINCT result_findings_key) FILTER (WHERE result_findings_key <> '') AS shared_copies
FROM plugins_assessment_runs;
```

After the backlog is cleared, `inline` is a few runs per SBOM and scanner (the current ones),
and `shared_copies` is far below `moved`.

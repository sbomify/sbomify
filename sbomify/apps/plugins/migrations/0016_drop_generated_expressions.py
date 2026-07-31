from django.db import migrations

_COLUMNS = ("result_summary", "result_skipped")


def _drop_generated_expressions(apps, schema_editor):
    """Convert leftover generated columns to plain columns, in place.

    Only environments that ran the earlier table-rewriting revision of 0015
    have these as STORED generated columns. DROP EXPRESSION is a catalog-only
    change that keeps every already-computed value, so it is instant and
    loses nothing. Environments that ran the current 0015 created the columns
    plain — no-op there.
    """
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for column in _COLUMNS:
            cursor.execute(
                "SELECT is_generated FROM information_schema.columns "
                "WHERE table_name = 'plugins_assessment_runs' AND column_name = %s",
                [column],
            )
            row = cursor.fetchone()
            if row and row[0] == "ALWAYS":
                schema_editor.execute(f"ALTER TABLE plugins_assessment_runs ALTER COLUMN {column} DROP EXPRESSION")


class Migration(migrations.Migration):
    dependencies = [
        ("plugins", "0015_assessmentrun_result_skipped_and_more"),
    ]

    operations = [
        migrations.RunPython(_drop_generated_expressions, migrations.RunPython.noop),
    ]

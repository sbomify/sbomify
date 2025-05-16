from django.db import migrations, connection

# SQL to create the table and its FKs. Assumes PKs in referenced tables are BIGINT.
SQL_CREATE_TABLE_IF_NOT_EXISTS = """
CREATE TABLE IF NOT EXISTS "socialaccount_socialapp_sites" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "socialapp_id" BIGINT NOT NULL,
    "site_id" BIGINT NOT NULL,
    CONSTRAINT "socialaccount_socialapp_sites_socialapp_id_fk_socialaccount_socialapp_id"
        FOREIGN KEY ("socialapp_id") REFERENCES "socialaccount_socialapp" ("id") DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "socialaccount_socialapp_sites_site_id_fk_django_site_id"
        FOREIGN KEY ("site_id") REFERENCES "django_site" ("id") DEFERRABLE INITIALLY DEFERRED,
    UNIQUE ("socialapp_id", "site_id")
);
"""

# SQL to create indexes idempotently (PostgreSQL specific)
SQL_CREATE_INDEXES_IF_NOT_EXISTS = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'socialaccount_socialapp_sites_socialapp_id_idx' AND n.nspname = 'public'
    ) THEN
        CREATE INDEX "socialaccount_socialapp_sites_socialapp_id_idx" ON "socialaccount_socialapp_sites" ("socialapp_id");
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'socialaccount_socialapp_sites_site_id_idx' AND n.nspname = 'public'
    ) THEN
        CREATE INDEX "socialaccount_socialapp_sites_site_id_idx" ON "socialaccount_socialapp_sites" ("site_id");
    END IF;
END
$$;
"""

# SQL to drop the table (for reverse operation)
SQL_DROP_TABLE = 'DROP TABLE IF EXISTS "socialaccount_socialapp_sites";'

class Migration(migrations.Migration):
    dependencies = [
        ('core', '0005_alter_user_options_user_email_verified_and_more'),
        # Ensure socialaccount_socialapp and django_site tables exist for FK constraints
        ('socialaccount', '0001_initial'), # Provides socialaccount_socialapp table
        ('sites', '0001_initial'),       # Provides django_site table
    ]

    operations = [
        migrations.RunSQL(
            sql=SQL_CREATE_TABLE_IF_NOT_EXISTS,
            reverse_sql=SQL_DROP_TABLE,
        ),
        # Only run the index creation on Postgres
        migrations.RunSQL(
            sql=SQL_CREATE_INDEXES_IF_NOT_EXISTS if connection.vendor == 'postgresql' else '',
            reverse_sql='',
        ),
    ]
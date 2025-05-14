from django.db import migrations

SQL_CREATE_TABLE_IF_NOT_EXISTS = """
CREATE TABLE IF NOT EXISTS "socialaccount_socialapp_sites" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "socialapp_id" BIGINT NOT NULL,
    "site_id" BIGINT NOT NULL,
    CONSTRAINT "socialaccount_socialapp_sites_socialapp_id_fk_socialaccoun_socialapp_id"
        FOREIGN KEY ("socialapp_id") REFERENCES "socialaccount_socialapp" ("id") DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "socialaccount_socialapp_sites_site_id_fk_django_site_id"
        FOREIGN KEY ("site_id") REFERENCES "django_site" ("id") DEFERRABLE INITIALLY DEFERRED,
    UNIQUE ("socialapp_id", "site_id")
);
"""

SQL_CREATE_INDEXES_IF_NOT_EXISTS = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   pg_class c
        JOIN   pg_namespace n ON n.oid = c.relnamespace
        WHERE  c.relname = 'socialaccount_socialapp_sites_socialapp_id_idx'
        AND    n.nspname = 'public' -- or your specific schema
    ) THEN
        CREATE INDEX "socialaccount_socialapp_sites_socialapp_id_idx" ON "socialaccount_socialapp_sites" ("socialapp_id");
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM   pg_class c
        JOIN   pg_namespace n ON n.oid = c.relnamespace
        WHERE  c.relname = 'socialaccount_socialapp_sites_site_id_idx'
        AND    n.nspname = 'public' -- or your specific schema
    ) THEN
        CREATE INDEX "socialaccount_socialapp_sites_site_id_idx" ON "socialaccount_socialapp_sites" ("site_id");
    END IF;
END
$$;
"""

SQL_DROP_TABLE = 'DROP TABLE IF EXISTS "socialaccount_socialapp_sites";'

class Migration(migrations.Migration):

    dependencies = [
        ('socialaccount', '0006_alter_socialaccount_extra_data'),
        ('sites', '0002_alter_domain_unique'), # Ensures the sites table (django_site) exists
    ]

    operations = [
        migrations.RunSQL(
            sql=SQL_CREATE_TABLE_IF_NOT_EXISTS,
            reverse_sql=SQL_DROP_TABLE,
        ),
        migrations.RunSQL(
            sql=SQL_CREATE_INDEXES_IF_NOT_EXISTS,
            reverse_sql="", # Indexes are dropped with the table if it's dropped
        )
    ]
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0005_alter_user_options_user_email_verified_and_more'),
        ('sites', '0002_alter_domain_unique'),
        ('socialaccount', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SocialAppSites',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('socialapp', models.ForeignKey(on_delete=models.CASCADE, to='socialaccount.socialapp')),
                ('site', models.ForeignKey(on_delete=models.CASCADE, to='sites.site')),
            ],
            options={
                'verbose_name': 'social application site',
                'verbose_name_plural': 'social application sites',
                'db_table': 'socialaccount_socialapp_sites',
            },
        ),
        migrations.AlterUniqueTogether(
            name='socialappsites',
            unique_together={('socialapp', 'site')},
        ),
    ]
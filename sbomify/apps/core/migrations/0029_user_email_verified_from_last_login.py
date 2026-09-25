from django.db import migrations

BATCH_SIZE = 2000


def record_email_verified_from_last_login(apps, schema_editor):
    """Set email_verified from the claims each user's last Keycloak login stored.

    Logins recorded False whatever the provider said: they looked for the claim
    at the top of extra_data, and since allauth 65.11 it sits under userinfo and
    id_token. The claims themselves were stored as sent. Only a confirmation of
    the address the user still holds turns the flag on.
    """
    SocialAccount = apps.get_model("socialaccount", "SocialAccount")
    User = apps.get_model("core", "User")

    confirmed = []
    accounts = SocialAccount.objects.filter(provider="keycloak").values_list("user_id", "user__email", "extra_data")
    for user_id, email, extra_data in accounts.iterator(chunk_size=BATCH_SIZE):
        data = extra_data or {}
        claims = data.get("userinfo") or data.get("id_token") or {}
        if email and claims.get("email_verified") is True and (claims.get("email") or "").lower() == email.lower():
            confirmed.append(user_id)
        if len(confirmed) >= BATCH_SIZE:
            User.objects.filter(pk__in=confirmed, email_verified=False).update(email_verified=True)
            confirmed = []

    User.objects.filter(pk__in=confirmed, email_verified=False).update(email_verified=True)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0028_user_newsletter_opt_in"),
        ("socialaccount", "0006_alter_socialaccount_extra_data"),
    ]

    operations = [
        migrations.RunPython(record_email_verified_from_last_login, migrations.RunPython.noop),
    ]

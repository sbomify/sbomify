"""Keep a SHA-256 of each access token instead of the token.

The OIDC scope check decoded the stored JWT for its token_type claim, so the
claim moves into a column of its own. A hash can't be turned back into the
token, so this migration can't be reversed.

Every request that authenticates with a token waits on the table lock until
this commits. Python only reads each JWT's claim, and one UPDATE then hashes
every row and sets its type. Writing a row twice here would also queue foreign
key checks, and PostgreSQL refuses the ALTER TABLE that follows.
"""

import jwt
from django.conf import settings
from django.db import migrations, models

# token_hash is hash_token in SQL: the SHA-256 of the token's UTF-8 bytes, in lowercase hex.
HASH_AND_TYPE_EVERY_ROW = """
    UPDATE access_tokens
    SET token_hash = encode(sha256(convert_to(encoded_token, 'UTF8')), 'hex'), token_type = claimed.token_type
    FROM unnest(%s::bigint[], %s::text[]) AS claimed(id, token_type)
    WHERE access_tokens.id = claimed.id
"""


def token_type_of(encoded_token: str) -> str:
    """The token_type claim a token was signed with: oidc, or pat for anything else."""
    try:
        claims = jwt.decode(
            encoded_token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False, "verify_aud": False, "verify_sub": False},
        )
    except jwt.InvalidTokenError:
        # Not signed by this deployment, so it can never authenticate and its type does not matter.
        return "pat"
    return "oidc" if claims.get("token_type") == "oidc" else "pat"


def hash_stored_tokens(apps, schema_editor):
    AccessToken = apps.get_model("access_tokens", "AccessToken")
    ids, token_types = [], []
    for pk, encoded_token in AccessToken.objects.values_list("pk", "encoded_token").iterator(chunk_size=1000):
        ids.append(pk)
        token_types.append(token_type_of(encoded_token))
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(HASH_AND_TYPE_EVERY_ROW, [ids, token_types])


class Migration(migrations.Migration):
    dependencies = [
        ("access_tokens", "0011_rename_access_toke_team_id_56c481_idx_access_toke_workspa_298f40_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="accesstoken",
            name="token_hash",
            field=models.CharField(editable=False, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="accesstoken",
            name="token_type",
            field=models.CharField(
                default="pat",
                editable=False,
                help_text=(
                    "The token_type claim of the JWT, pat or oidc. Authentication refuses a token whose claim differs."
                ),
                max_length=4,
            ),
        ),
        migrations.RunPython(hash_stored_tokens),
        migrations.RemoveField(
            model_name="accesstoken",
            name="encoded_token",
        ),
        migrations.AlterField(
            model_name="accesstoken",
            name="token_hash",
            field=models.CharField(editable=False, max_length=64, unique=True),
        ),
        migrations.AddConstraint(
            model_name="accesstoken",
            constraint=models.CheckConstraint(
                condition=models.Q(("token_hash__regex", "^[0-9a-f]{64}$")),
                name="access_token_stores_a_hash",
            ),
        ),
    ]

#!/bin/sh
set -e

KC_URL="${KEYCLOAK_SERVER_URL}"
REALM="${KEYCLOAK_REALM}"
CLIENT_ID="${KEYCLOAK_CLIENT_ID}"
ADMIN_USER="${KC_BOOTSTRAP_ADMIN_USERNAME}"
ADMIN_PASS="${KC_BOOTSTRAP_ADMIN_PASSWORD}"
CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET}"
APP_BASE_URL="${APP_BASE_URL:-http://127.0.0.1:8000}"

# Wait for Keycloak REST API to be ready
until /opt/keycloak/bin/kcadm.sh config credentials --server "$KC_URL" --realm master --user "$ADMIN_USER" --password "$ADMIN_PASS"; do
  echo "Waiting for Keycloak to be ready for admin CLI..."
  sleep 3
done

# Create realm if it doesn't exist
if ! /opt/keycloak/bin/kcadm.sh get "realms/$REALM" > /dev/null 2>&1; then
  /opt/keycloak/bin/kcadm.sh create realms \
    -s "realm=$REALM" \
    -s enabled=true
fi

# Disable SSL requirement for development (only in dev mode)
if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
  /opt/keycloak/bin/kcadm.sh update "realms/$REALM" -s sslRequired=NONE
  echo "SSL requirement disabled for development"
fi

# Ensure the realm uses the bundled sbomify themes for branding.
/opt/keycloak/bin/kcadm.sh update "realms/$REALM" -s "loginTheme=sbomify" -s "emailTheme=sbomify"

# Create client if it doesn't exist
if ! /opt/keycloak/bin/kcadm.sh get clients -r "$REALM" -q "clientId=$CLIENT_ID" | grep -q '"id"'; then
  # In dev mode, allow all redirect URIs and web origins for flexibility
  if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
    /opt/keycloak/bin/kcadm.sh create clients -r "$REALM" \
      -s "clientId=$CLIENT_ID" \
      -s enabled=true \
      -s protocol=openid-connect \
      -s publicClient=false \
      -s 'redirectUris=["*"]' \
      -s 'webOrigins=["*"]' \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=true \
      -s serviceAccountsEnabled=true \
      -s "baseUrl=$APP_BASE_URL" \
      -s "rootUrl=$APP_BASE_URL" \
      -s "secret=$CLIENT_SECRET"
  else
    /opt/keycloak/bin/kcadm.sh create clients -r "$REALM" \
      -s "clientId=$CLIENT_ID" \
      -s enabled=true \
      -s protocol=openid-connect \
      -s publicClient=false \
      -s 'redirectUris=["http://localhost:8000/*","http://127.0.0.1:8000/*"]' \
      -s 'webOrigins=["http://localhost:8000","http://127.0.0.1:8000"]' \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=true \
      -s serviceAccountsEnabled=true \
      -s "baseUrl=$APP_BASE_URL" \
      -s "rootUrl=$APP_BASE_URL" \
      -s "secret=$CLIENT_SECRET"
  fi
else
  CLIENT_UUID=$(/opt/keycloak/bin/kcadm.sh get clients -r "$REALM" -q clientId="$CLIENT_ID" --fields id --format csv | tail -n1 | tr -d '"')
  /opt/keycloak/bin/kcadm.sh update "clients/$CLIENT_UUID" -r "$REALM" -s secret="$CLIENT_SECRET"

  # In dev mode, also update redirect URIs to allow all
  if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
    /opt/keycloak/bin/kcadm.sh update "clients/$CLIENT_UUID" -r "$REALM" \
      -s 'redirectUris=["*"]' \
      -s 'webOrigins=["*"]'
  fi
fi

# Always enable user registration after all other steps. Mirror production's
# registration exactly so local runs predict it: the email address is the
# username, the form collects no password, and the account is activated by
# verifying the email first and setting a password right after.
/opt/keycloak/bin/kcadm.sh update "realms/$REALM" \
  -s registrationAllowed=true \
  -s registrationEmailAsUsername=true \
  -s verifyEmail=true

# Email action links must survive real-world mailbox delays: verification
# links live 3 days, credential resets 1 hour (the Keycloak default of
# 5 minutes locks out anyone behind a slow corporate mail gateway).
/opt/keycloak/bin/kcadm.sh update "realms/$REALM" \
  -s 'attributes."actionTokenGeneratedByUserLifespan.verify-email"=259200' \
  -s 'attributes."actionTokenGeneratedByUserLifespan.reset-credentials"=3600'

# Registration flow without the password step (production behaviour): copy
# the built-in flow, disable Password Validation, and bind the copy.
if ! /opt/keycloak/bin/kcadm.sh get authentication/flows -r "$REALM" | grep -q 'registration-email-first'; then
  /opt/keycloak/bin/kcadm.sh create "authentication/flows/registration/copy" -r "$REALM" -s newName=registration-email-first
fi
PASSWORD_EXEC_ID=$(/opt/keycloak/bin/kcadm.sh get "authentication/flows/registration-email-first/executions" -r "$REALM" \
  | tr -d '\n ' \
  | sed 's/.*"id":"\([^"]*\)"[^{]*"providerId":"registration-password-action".*/\1/')
if [ -n "$PASSWORD_EXEC_ID" ]; then
  /opt/keycloak/bin/kcadm.sh update "authentication/flows/registration-email-first/executions" -r "$REALM" \
    -b "{\"id\":\"$PASSWORD_EXEC_ID\",\"requirement\":\"DISABLED\"}"
fi
/opt/keycloak/bin/kcadm.sh update "realms/$REALM" -s registrationFlow=registration-email-first

# The password is set right after email verification: Verify Email runs
# first, then Update Password.
/opt/keycloak/bin/kcadm.sh update "authentication/required-actions/VERIFY_EMAIL" -r "$REALM" -s priority=20
/opt/keycloak/bin/kcadm.sh update "authentication/required-actions/UPDATE_PASSWORD" -r "$REALM" -s defaultAction=true -s priority=30

# Create test users for development (only in dev mode). The realm uses the
# email address as the username, so these sign in with their full address
# and skip the verification and password steps a real signup goes through.
if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
  create_test_user() {
    email="$1"
    first="$2"
    last="$3"

    if ! /opt/keycloak/bin/kcadm.sh get users -r "$REALM" -q "username=$email" | grep -q '"id"'; then
      /opt/keycloak/bin/kcadm.sh create users -r "$REALM" \
        -s "username=$email" \
        -s "firstName=$first" \
        -s "lastName=$last" \
        -s "email=$email" \
        -s emailVerified=true \
        -s enabled=true
      echo "Created test user: $email"
    fi

    user_id=$(/opt/keycloak/bin/kcadm.sh get users -r "$REALM" -q "username=$email" --fields id --format csv | tail -n1 | tr -d '"')
    /opt/keycloak/bin/kcadm.sh update "users/$user_id" -r "$REALM" -s emailVerified=true -s 'requiredActions=[]'
    /opt/keycloak/bin/kcadm.sh update "users/$user_id/reset-password" -r "$REALM" \
      -s type=password -s value=foobar123 -s temporary=false -n
  }

  create_test_user jdoe@example.com John Doe
  create_test_user ssmith@example.com Steve Smith
fi

echo "Keycloak client secret for $CLIENT_ID: $CLIENT_SECRET"

if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
  echo "Development test users created:"
  echo "  - jdoe@example.com / foobar123 (John Doe)"
  echo "  - ssmith@example.com / foobar123 (Steve Smith)"
fi

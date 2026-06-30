# API access tokens

Personal access tokens (PATs) authenticate programmatic API requests. This is the
operator and contributor reference for using them safely and for rotating the legacy
unscoped tokens. The authoritative field semantics live in the `AccessToken` model
`help_text` (`sbomify/apps/access_tokens/models.py`); this page does not duplicate them.

## The model

A token carries workspace scoping, optional action scopes, and an optional expiry:

- **Workspace** (`team`): the token acts only within that workspace. Legacy tokens
  predating workspace scoping have `team = NULL` and are **not** restricted to one
  workspace; they work across every workspace the user belongs to. Rotate these (see
  below) so each token is pinned to a single workspace.
- **Action scopes** (`scopes`): a list of `can()` actions the token may perform. A scope
  only narrows access; the user's workspace role and the resource's attributes still
  apply. `NULL` means unscoped (full capability).
- **Expiry** (`expires_at`): new PATs default to 90 days. `NULL` means never expires.
- **Last seen** (`last_used_at`): stamped on use, throttled (accurate to within a few minutes), for
  spotting stale or leaked tokens.

New PATs created in the UI are workspace-scoped and 90-day-expiring by default, but the
access-scope selector defaults to **full** (unscoped) access. Narrow the action scope
explicitly to limit what the token can do.

## Best practices

1. **Least privilege.** Scope every token to one workspace and the smallest set of
   action scopes the integration needs. Over-scoping is the only risk; a scope can never
   grant more than the user already has.
2. **Always set an expiry.** Keep the 90-day default. A never-expiring token is a
   deliberate, monitored exception, not a default.
3. **Rotate on a schedule and on suspected leak.** For machine credentials, rotate
   regularly so a stolen token works only briefly. (NIST SP 800-63B drops periodic
   rotation for human passwords; that ruling does not cover API tokens.)
4. **One token per consumer.** A separate token per CI pipeline or integration shrinks
   the blast radius of a leak and makes `last_used_at` attributable to a single consumer.
5. **Store securely, never in version control.** Treat tokens like passwords. Keep them
   in the CI secret store or a secret manager, gitignore env files, and enable secret
   scanning.
6. **Revoke by deleting.** sbomify has no separate revoke step; deleting a token revokes
   it. Delete immediately on suspected compromise.
7. **Watch `last_used_at`.** Use it to find unused or leaked tokens and delete them.
8. **Prefer OIDC trusted publishing for CI.** sbomify's OIDC-issued tokens are
   short-lived (about 15 minutes), which removes the long-lived secret entirely. Use a
   long-lived PAT only when OIDC is not available.

On IP allow-listing: org-level IP restrictions break with CI runners on rotating IP
pools (GitHub advises against allow-listing hosted runners), so do not rely on them for
CI tokens. sbomify has no per-token IP restriction; scoping, expiry, and OIDC are the
durable controls.

## Rotating a legacy token

Tokens created before token scoping shipped have `scopes = NULL`, `expires_at = NULL`,
and often `team = NULL` (full, never-expiring access that is also not pinned to a single
workspace, so it reaches every workspace the holder belongs to). They stay valid until
you rotate them; there is no forced cutover or auto-expiry, since that would break
existing CI. Rotate at your convenience:

1. Create a new token scoped to the specific workspace, with only the action scopes the
   integration needs, and an expiry (the 90-day default is fine).
2. Update the CI job or integration to use the new token (via the secret store, never
   committed).
3. Confirm the new token's `last_used_at` starts advancing.
4. Confirm the old token's `last_used_at` has stopped advancing. This is how you find
   which integration still depends on a legacy token.
5. Delete the old token.

The token list flags unscoped tokens and surfaces `last_used_at` for self-service
rotation.

## References

- GitHub, [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- GitHub, [Introducing fine-grained personal access tokens](https://github.blog/security/application-security/introducing-fine-grained-personal-access-tokens-for-github/)
- GitLab, [Personal access tokens](https://docs.gitlab.com/user/profile/personal_access_tokens/)
- OWASP, [Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

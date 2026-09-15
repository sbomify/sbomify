# Integrations

A workspace's compliance programme usually already lives in a dedicated tool.
Integrations read that programme and republish the part of it the workspace
chooses, so the trust center can be true without anyone retyping it.

Vanta is the first provider. This page is the operator reference: how to
register the OAuth client, what the sync writes, and what to check when it
stops.

## What a connection does

A connection is read-only. sbomify never writes back to the provider.

Each framework the provider tracks becomes a `controls.ControlCatalog` with
`source` set to the provider key, its controls become `controls.Control` rows,
and each control's state becomes a workspace-scope `controls.ControlStatus`.
Nothing downstream knows a provider exists: the trust center, the product
pages and the scoring in `controls.services.status_service` treat a synced
framework exactly like one somebody activated by hand.

Two consequences worth knowing:

- **A synced framework arrives unpublished.** Connecting reads data. Putting a
  framework on a page the workspace's customers read is a second, deliberate
  act, the same way `product:set_visibility` sits above the tier that creates
  products. Settings → Integrations is where someone chooses.
- **Product-scope statuses are never touched.** The provider describes the
  organisation, so a status somebody set on one product stays theirs.

## Setting up the Vanta OAuth client

Vanta issues one credential per connected customer through the OAuth
authorization-code flow, so every workspace that connects gets its own token
against its own Vanta account.

1. Register an app in the Vanta developer portal with the scope
   `vanta-api.all:read`.
2. Register the redirect URI. It is one fixed URL per provider, with no
   workspace in it:

   ```text
   https://<your-host>/integrations/oauth/vanta/callback
   ```

   The workspace being connected travels in the session, not the path, because
   providers refuse any redirect URI they were not given.
3. Set the credentials:

   | Variable | Default | What it is |
   | --- | --- | --- |
   | `VANTA_CLIENT_ID` | empty | The app's client id (`vci_...`) |
   | `VANTA_CLIENT_SECRET` | empty | The app's client secret (`vcs_...`) |
   | `VANTA_OAUTH_AUTHORIZE_URL` | `https://app.vanta.com/oauth/authorize` | Where the customer consents |
   | `VANTA_OAUTH_TOKEN_URL` | `https://api.vanta.com/oauth/token` | Where codes and refreshes are exchanged |
   | `VANTA_API_BASE_URL` | `https://api.vanta.com` | Where the read calls go |

Without both halves of the credential the provider's tile renders disabled
rather than hidden, so a self-hoster can see the feature exists and what it
wants.

**Regions.** Vanta serves its API from one host worldwide, but customers
consent on their own regional app host: `app.eu.vanta.com` for EU accounts and
`app.aus.vanta.com` for AU. A deployment whose customers are not all in the US
overrides `VANTA_OAUTH_AUTHORIZE_URL`.

## Syncing

`integrations.cron.periodic_integration_sync` runs every six hours and queues
any connection that has not synced inside that window. Compliance state moves
in days, so this is well inside what a trust center needs and well outside
anything a provider would call chatty. Admins can also queue one from the
Integrations tab.

A sync is never run in the request cycle. Vanta exposes a control's status only
on the single-control endpoint, so a framework costs one request per control;
control details are cached across frameworks within a run, because the same
control is usually mapped into several of them.

### Status mapping

| Vanta | sbomify |
| --- | --- |
| `COMPLETED` | `compliant` |
| `IN_PROGRESS` | `partial` |
| `NOT_STARTED` | `not_implemented` |
| `NO_EVIDENCE_MAPPED` | `not_implemented` |
| anything else | `not_implemented` |

Nothing maps to `not_applicable`. Vanta expresses "does not apply" by leaving
the control out of the framework, so a control that reaches the mapper applies
by definition, and inventing an N/A would quietly remove it from the
denominator of a published score.

## When something goes wrong

The Integrations tab shows the last sync and its error. Two states are
different on purpose:

- **Failed** is a bad day at the provider. The next scheduled run tries again,
  and nothing about the connection has changed.
- **Needs reconnecting** means the refresh token was rejected. No retry can fix
  that, so the scheduler skips the connection entirely and someone has to go
  through the consent screen again.

Vanta rotates the refresh token on every use. sbomify saves the new one before
using the access token, so a process that dies mid-sync leaves the workspace
connected.

## Disconnecting

Disconnecting deletes the credential and takes every framework the provider
published off the trust center. The synced frameworks and their controls are
kept, so reconnecting is not a re-import, but nothing stays public: a trust
center must not go on claiming a control is met from a source nobody is reading
any more.

## Adding a provider

1. A `ProviderSpec` in `sbomify/apps/integrations/providers/`, added to
   `PROVIDERS`.
2. A `sync(integration) -> ServiceResult[dict]` function named by the spec's
   `sync_path`.
3. A `ControlCatalog.Source` member whose value is the provider key, so a
   disconnect can find what it published.

The OAuth module, the views and the templates are provider-agnostic and should
not need changing.

# Integrations

A workspace's compliance programme usually already lives in a dedicated tool.
Integrations read that programme and republish the part of it the workspace
chooses, so the trust center can be true without anyone retyping it.

Vanta is the first compliance provider. Slack is the first notification
provider: it reads nothing, and posts the VEX approval queue and vulnerability
news to the channels a workspace picks (see [Slack](#slack)). This page is the
operator reference: how to register each OAuth client, what each connection
writes, and what to check when it stops.

## What a connection does

A connection is read-only. sbomify never writes back to the provider.

Each framework the provider tracks becomes a `controls.ControlCatalog` with
`source` set to the provider key, its controls become `controls.Control` rows,
and each control's state becomes a workspace-scope `controls.ControlStatus`.
Nothing downstream knows a provider exists: the trust center, the product
pages and the scoring in `controls.services.status_service` treat a synced
framework exactly like one somebody activated by hand.

Four consequences worth knowing:

- **Tracking a framework and publishing it are two flags.** `is_active` means
  the workspace tracks the framework: it appears in settings, and plugin
  assessments may promote its controls. `is_published` means it appears on the
  public trust center, and it defaults to off. They used to be one flag, which
  would have meant every workspace already tracking SOC 2 internally started
  publishing a compliance score to its customers the moment the trust center
  learned to render one.
- **A synced framework arrives active but unpublished.** Connecting reads data.
  Putting a framework on a page the workspace's customers read is a second,
  deliberate act, the same way `product:set_visibility` sits above the tier
  that creates products. Settings → Integrations is where someone chooses.
- **Nothing else writes into a synced catalogue.** `controls.INTEGRATION_SOURCES`
  names the sources an external system owns, and `automation_service` skips
  them: promoting one of their controls from a plugin result would overwrite
  the answer the workspace's own compliance tool gave, and be undone by the
  next sync a few hours later. The SOC 2 codes in `PLUGIN_CONTROL_MAP` are
  exactly the ones a synced SOC 2 catalogue uses, so this is not hypothetical.
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

Which one you get is decided by what the provider actually said, and the line
matters: a connection wrongly marked as needing a reconnect is skipped by the
scheduler forever, so one timeout would end syncing until a human noticed. A
**4xx at the token endpoint is the provider refusing the grant** and is
terminal (`ProviderAuthError`). **Everything else is transient**
(`ProviderUnavailable`): 5xx, timeouts, DNS failures, an unreadable body.

Vanta rotates the refresh token on every use, which makes a concurrent refresh
worse than a wasted request: two callers read the same token, both spend it,
and the loser's 401 looks exactly like a dead credential. `access_token` takes
a row lock before refreshing and re-reads under it, so a "Sync now" landing on
top of the scheduled run waits and then finds the token already fresh. The new
refresh token is saved before the access token is used, so a process that dies
mid-sync leaves the workspace connected.

### Nothing empty is treated as an instruction

The client is deliberately tolerant of a response it cannot parse, which means
"this framework has no controls" and "a shape we did not recognise" arrive as
the same empty list. Pruning against that would delete a whole framework and
record the run as a success, so a sync only removes controls when the framework
actually returned some, and only retires catalogues when the account returned
at least one framework. Running past the pagination ceiling fails the sync
rather than returning a partial list for the same reason.

## Disconnecting

Disconnecting deletes the credential and takes every framework the provider
published off the trust center. The synced frameworks and their controls are
kept, so reconnecting is not a re-import, but nothing stays public: a trust
center must not go on claiming a control is met from a source nobody is reading
any more.

## Slack

Slack is the first provider sbomify writes to rather than reads from. A
workspace installs the sbomify app into its Slack workspace, then picks a
channel for each kind of message on the Integrations tab. Each message can go
to a different channel, or be turned off.

| Message | When it is posted |
| --- | --- |
| VEX approval queue | Each time a VEX ruling is submitted for approval |
| Daily vulnerability digest | Every day at 08:00 UTC: open totals by severity, known exploited, past fix-by date, what opened and closed in the last 24 hours, rulings waiting, and the top five priorities |
| New vulnerabilities | When a scan finds a vulnerability a component did not have before, at or above the severity the route asks for (high and above by default) |

"New" is decided by `plugins.lifecycle.record_run`, the one place that knows a
vulnerability is new to a component rather than new to a scan: a rescan, a
second scanner or a fresh SBOM of the same component reports it again and
opens nothing. A new vulnerability a published VEX already covers is not
posted.

### Setting up the Slack app

1. Create an app at <https://api.slack.com/apps> and add the bot token scopes
   `chat:write`, `chat:write.public`, `channels:read` and `groups:read`.
2. Add the redirect URL:

   ```text
   https://<your-host>/integrations/oauth/slack/callback
   ```

3. Turn on public distribution if workspaces other than your own will connect.
4. Set the credentials:

   | Variable | Default | What it is |
   | --- | --- | --- |
   | `SLACK_CLIENT_ID` | empty | The app's client id |
   | `SLACK_CLIENT_SECRET` | empty | The app's client secret |
   | `SLACK_OAUTH_AUTHORIZE_URL` | `https://slack.com/oauth/v2/authorize` | Where the customer consents |
   | `SLACK_OAUTH_TOKEN_URL` | `https://slack.com/api/oauth.v2.access` | Where codes are exchanged |
   | `SLACK_API_BASE_URL` | `https://slack.com/api` | Where the Web API calls go |

`chat:write.public` lets the bot post to any public channel without being
invited. A private channel is only listed once the app has been invited to it.

### How delivery behaves

Messages are posted by dramatiq tasks queued after the change that caused them
commits, so a Slack outage delays a message and never fails a scan or a
submission. Slack answers almost every call with a 200 and reports failure in
the body, so the client sorts errors by what Slack said:

- **A dead token** (`invalid_auth`, `token_revoked`, `account_inactive`,
  `missing_scope`) marks the connection as needing a reconnect.
- **A refused channel** (`channel_not_found`, `not_in_channel`, `is_archived`)
  is recorded on that message's row, and every other message keeps working.
- **Anything else** (rate limits, 5xx, timeouts) is retried by dramatiq.

Bot tokens do not expire, so a Slack connection has no refresh and nothing to
sync, and the scheduler never queues one.

## Adding a provider

1. A `ProviderSpec` in `sbomify/apps/integrations/providers/`, added to
   `PROVIDERS`.
2. For a compliance provider, a `sync(integration) -> ServiceResult[dict]`
   function named by the spec's `sync_path`, and a `ControlCatalog.Source`
   member whose value is the provider key, so a disconnect can find what it
   published.
3. For a notification provider, `kind="notifications"` on the spec. The routes,
   the tasks and the tab are shared, but the client is Slack's today, so a
   second one needs `services.notifications` to pick a client by provider.

The OAuth module, the views and the templates are provider-agnostic. Where a
provider departs from the OAuth spec (Slack's form-encoded token endpoint,
comma-separated scopes, tokens that never expire) it says so on its spec.

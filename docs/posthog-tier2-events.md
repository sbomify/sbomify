# PostHog Tier 2 Events — Implementation Plan

Events to instrument after the Tier 1 AARRR core events are validated in production.

## Event Naming Convention

Format: `category:object_action` in snake_case, past tense.

Examples: `sbom:uploaded`, `billing:checkout_completed`, `team:member_invited`

## Tier 2 Events

### Engagement & Feature Adoption

| Event | Where to Hook | Properties | AARRR Stage |
|-------|--------------|------------|-------------|
| `api_token:created` | `sbomify/apps/teams/views/team_tokens.py` → `TeamTokensView.post()` | `token_name` | Retention |
| `api_token:deleted` | `sbomify/apps/core/views/__init__.py` → `delete_access_token()` | — | Retention |
| `search:performed` | `sbomify/apps/core/views/search.py` → `SearchView.get()` | `query_length`, `result_count` | Retention |
| `item:visibility_toggled` | `sbomify/apps/core/views/toggle_public_status.py` → `TogglePublicStatusView.post()` | `visibility`, `item_type`, `item_id` | Retention |

### Collaboration

| Event | Where to Hook | Properties | AARRR Stage |
|-------|--------------|------------|-------------|
| `team:member_invited` | `sbomify/apps/teams/views/__init__.py` → `invite()` | `role`, `invited_email_domain` | Collaboration |
| `team:member_invitation_accepted` | `sbomify/apps/teams/views/__init__.py` → `accept_invite()` | — | Collaboration |
| `team:member_removed` | `sbomify/apps/teams/views/__init__.py` → `delete_member()` | `role` | Collaboration |
| `team:branding_updated` | `sbomify/apps/teams/views/team_branding.py` → `TeamBrandingView.post()` | — | Feature Adoption |
| `team:custom_domain_added` | `sbomify/apps/teams/views/team_custom_domain.py` → `TeamCustomDomainView.post()` | — | Feature Adoption |

### Trust Center & Document Access

| Event | Where to Hook | Properties | AARRR Stage |
|-------|--------------|------------|-------------|
| `document:access_requested` | `sbomify/apps/documents/views/access_requests.py` → `AccessRequestView.post()` | `component_id` | External Engagement |
| `document:access_approved` | `sbomify/apps/documents/views/access_requests.py` → approval flow | — | External Engagement |
| `nda:signed` | `sbomify/apps/documents/views/access_requests.py` → `NDASigningView.post()` | — | External Engagement |

### Entity CRUD

| Event | Where to Hook | Properties | AARRR Stage |
|-------|--------------|------------|-------------|
| `product:created` | `sbomify/apps/core/apis.py` → `create_product()` | — | Retention |
| `component:created` | `sbomify/apps/core/apis.py` → `create_component()` | `component_type` | Retention |
| `release:created` | `sbomify/apps/core/apis.py` → `create_release()` | `product_id` | Retention |

### Churn Signals

| Event | Where to Hook | Properties | AARRR Stage |
|-------|--------------|------------|-------------|
| `user:account_deleted` | `sbomify/apps/core/apis.py` → `delete_account()` | — | Churn |
| `billing:trial_expired` | `sbomify/apps/billing/billing_processing.py` → `handle_trial_period()` | `team_key` | Revenue |

## Implementation Notes

- All view-based events should pass `request=request` to `capture()` for session correlation.
- Signal-based events should use `transaction.on_commit()`.
- Use `groups={"workspace": team_key}` for all workspace-scoped events.
- Use `str(request.user.pk)` as `distinct_id` for authenticated user actions.
- Use `"system"` as `distinct_id` only for events with no user context (webhooks, cron).

## Priority Order

1. `team:member_invited` + `team:member_invitation_accepted` — collaboration funnel
2. `api_token:created` — API adoption signal
3. `item:visibility_toggled` — trust center usage
4. `document:access_requested` + `nda:signed` — external engagement
5. `search:performed` — feature usage pattern
6. `product:created`, `component:created`, `release:created` — entity lifecycle
7. `user:account_deleted`, `billing:trial_expired` — churn signals
8. Remaining team/branding events — feature adoption depth

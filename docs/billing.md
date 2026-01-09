# Billing

This document covers the billing system for sbomify, including Stripe integration, subscription management, and trial handling.

## Overview

sbomify uses Stripe for payment processing and subscription management. The billing system supports:

- **Free Community plan** - Limited features, no payment required
- **Business plan** - Full features with a 14-day trial period
- **Enterprise plan** - Custom pricing and features

## Architecture

```text
┌─────────────────┐     Webhooks      ┌──────────────────┐
│                 │ ────────────────> │                  │
│     Stripe      │                   │  /billing/       │
│                 │ <──────────────── │  webhook/        │
└─────────────────┘     API calls     └──────────────────┘
                                              │
                                              ▼
                                      ┌──────────────────┐
                                      │  billing_        │
                                      │  processing.py   │
                                      └──────────────────┘
                                              │
                              ┌───────────────┼───────────────┐
                              ▼               ▼               ▼
                        ┌──────────┐   ┌──────────┐   ┌──────────┐
                        │  Team    │   │  Email   │   │  Logs    │
                        │  Model   │   │  Notifs  │   │          │
                        └──────────┘   └──────────┘   └──────────┘
```

## Module Structure

| File                        | Responsibility                                         |
| --------------------------- | ------------------------------------------------------ |
| `models.py`                 | BillingPlan model, feature flags, price calculations   |
| `views.py`                  | HTTP endpoints (plan selection, checkout, portal)      |
| `billing_processing.py`     | Webhook event handlers, check_billing_limits decorator |
| `stripe_client.py`          | Stripe API wrapper with error handling                 |
| `stripe_pricing_service.py` | Fetches/caches pricing from Stripe                     |
| `team_pricing_service.py`   | Calculates team-specific pricing display               |
| `stripe_sync.py`            | Syncs subscription/price data from Stripe              |
| `stripe_cache.py`           | Subscription data caching layer                        |
| `notifications.py`          | In-app billing alerts/warnings                         |
| `tasks.py`                  | Async Dramatiq tasks (emails, stale trial checks)      |
| `webhook_handler.py`        | Webhook signature verification                         |

## Service Architecture

```text
┌────────────────────────────────────────────────────────────────┐
│                         Views Layer                            │
│  (select_plan, billing_redirect, create_portal_session, etc.)  │
└───────────────────────┬────────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────────┐
│                     Service Layer                               │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐ │
│  │ TeamPricingService  │  │ StripePricingService             │ │
│  │ (team-specific      │  │ (all plans pricing,              │ │
│  │  pricing display)   │  │  checkout session creation)      │ │
│  └─────────────────────┘  └──────────────────────────────────┘ │
└───────────────────────┬────────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────────┐
│                     StripeClient                                │
│  (Stripe API wrapper with error handling and rate limit mgmt)   │
└────────────────────────────────────────────────────────────────┘
```

## User Flows

### Plan Selection & Checkout

1. User visits `/billing/select-plan/<team_key>/` → `select_plan()` view
2. User selects plan → redirected to `/billing/redirect/<team_key>/`
3. `billing_redirect()` creates Stripe checkout session
4. User completes payment on Stripe
5. Stripe sends `checkout.session.completed` webhook (see [Webhook Events](#required-webhook-events))
6. `handle_checkout_completed()` updates Team billing state
7. User redirected to `/billing/return/` → `billing_return()` shows success

### Billing Portal Access

1. User clicks "Manage Billing" → `/billing/portal/<team_key>/`
2. `create_portal_session()` creates Stripe portal session
3. User redirected to Stripe Billing Portal

### Downgrade/Cancellation

1. User schedules downgrade (sets `cancel_at_period_end`)
2. At period end, Stripe sends `customer.subscription.deleted` webhook
3. `handle_subscription_deleted()` downgrades to Community

## Billing Limits Enforcement

Use the `check_billing_limits` decorator to enforce plan limits:

```python
from sbomify.apps.billing.billing_processing import check_billing_limits

class MyCreateView(View):
    @check_billing_limits('product')  # or 'project', 'component'
    def post(self, request, *args, **kwargs):
        # Create logic here
```

Limits are stored in `Team.billing_plan_limits` JSONField:

- `max_products`, `max_projects`, `max_components`
- When billing is disabled (`BILLING=FALSE`), all teams get unlimited access

## Async Tasks & Cron Jobs

| Task/Cron                       | Schedule          | Purpose                                         |
| ------------------------------- | ----------------- | ----------------------------------------------- |
| `check_stale_trials_task`       | Daily 2:00 AM UTC | Safety net for missed trial expiration webhooks |
| `send_enterprise_inquiry_email` | On-demand         | Async email sending for enterprise inquiries    |

## In-App Notifications

The `notifications.py` module provides billing alerts:

- Missing billing plan selection
- Missing payment information for Business plan
- Payment failures (past_due, unpaid states)
- Downgrade would exceed target plan limits
- Community plan upgrade suggestions

## API Endpoints

| URL Pattern                        | View                    | Purpose                  |
| ---------------------------------- | ----------------------- | ------------------------ |
| `/billing/select-plan/<team_key>/` | `select_plan`           | Plan selection page      |
| `/billing/redirect/<team_key>/`    | `billing_redirect`      | Stripe checkout redirect |
| `/billing/portal/<team_key>/`      | `create_portal_session` | Stripe portal redirect   |
| `/billing/enterprise-contact/`     | `enterprise_contact`    | Enterprise inquiry form  |
| `/billing/return/`                 | `billing_return`        | Checkout return handler  |

## Environment Variables

| Variable                         | Description                                                                                                                                               |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BILLING`                        | For local/self-hosted: set `BILLING=TRUE` to enable billing or `BILLING=FALSE` to disable billing for unlimited access; only `TRUE`/`FALSE` are supported |
| `STRIPE_SECRET_KEY`              | Stripe secret API key                                                                                                                                     |
| `STRIPE_WEBHOOK_SECRET`          | Webhook signing secret from Stripe Dashboard                                                                                                              |
| `STRIPE_PUBLISHABLE_KEY`         | Stripe publishable key (for frontend)                                                                                                                     |
| `TRIAL_PERIOD_DAYS`              | Number of days for trial period (default: 14)                                                                                                             |
| `TRIAL_ENDING_NOTIFICATION_DAYS` | Days before trial end to send notification (default: 3)                                                                                                   |

## Trial Management

### How Trials Work

1. When a user creates a workspace, they automatically start a trial on the Business plan
2. Trial duration is configured via `TRIAL_PERIOD_DAYS` (default: 14 days)
3. Users receive a notification `TRIAL_ENDING_NOTIFICATION_DAYS` before the trial ends
4. When the trial ends, if no payment method is added, the subscription is canceled

### Trial Status Fields

The `Team.billing_plan_limits` JSON field contains:

```json
{
  "is_trial": true,
  "trial_end": 1765264023,
  "trial_days_remaining": 7,
  "subscription_status": "trialing",
  "stripe_subscription_id": "sub_xxx",
  "stripe_customer_id": "cus_xxx",
  "last_updated": "2025-12-01T10:00:00+00:00"
}
```

### Safety Net: Stale Trial Check

A daily cron job (`check_stale_trials_task`) runs at 2:00 AM UTC to catch any trials that may have expired but weren't updated due to missed webhooks.

## Stripe Webhook Configuration

### Webhook URL

The Stripe webhook endpoint must be configured with the correct URL:

```text
https://<your-domain>/billing/webhook/
```

**Example for production:**

```text
https://app.sbomify.com/billing/webhook/
```

> **Important:** The webhook path is `/billing/webhook/` (not `/webhook/`). The billing app is mounted at `/billing/` in the main URL configuration.

### Required Webhook Events

Configure Stripe to send the following events:

| Event                           | Description                                                  | Handler Action                                                               |
| ------------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `checkout.session.completed`    | Customer completes checkout                                  | Creates/updates team billing plan, sets subscription status                  |
| `customer.subscription.updated` | Subscription status changes (trial ends, plan changes, etc.) | Updates `subscription_status`, handles trial expiration, sends notifications |
| `customer.subscription.deleted` | Subscription is canceled                                     | Sets status to `canceled`, notifies team owners                              |
| `invoice.payment_succeeded`     | Payment succeeds                                             | Sets status to `active`, sends payment confirmation                          |
| `invoice.payment_failed`        | Payment fails                                                | Sets status to `past_due`, sends payment failure notification                |

#### Event Details

**`checkout.session.completed`**

- Triggered when a customer successfully completes the Stripe Checkout flow
- Creates the initial subscription record in the team's `billing_plan_limits`
- Sets up trial period if applicable

**`customer.subscription.updated`**

- Most important event for subscription lifecycle management
- Handles trial-to-active transitions
- Handles trial expiration (when payment fails after trial)
- Updates plan limits if subscription plan changes

**`customer.subscription.deleted`**

- Triggered when subscription is fully canceled
- Updates team status to `canceled`
- Sends subscription ended notification to team owners

**`invoice.payment_succeeded`**

- Confirms successful recurring payments
- Reactivates subscriptions that were `past_due`

**`invoice.payment_failed`**

- Handles failed payment attempts
- Sets subscription to `past_due` status
- Triggers payment failure notifications to team owners

### Setting Up Webhooks in Stripe Dashboard

1. Go to **Developers → Webhooks** in your Stripe Dashboard
2. Click **Add endpoint**
3. Enter your webhook URL: `https://<your-domain>/billing/webhook/`
4. Select the events listed above
5. Click **Add endpoint**
6. Copy the **Signing secret** and set it as `STRIPE_WEBHOOK_SECRET`

### Testing Webhooks Locally

Use the Stripe CLI to forward webhooks:

```bash
stripe listen --forward-to localhost:8000/billing/webhook/
```

## Troubleshooting

### Webhook Returns 404

**Cause:** Incorrect webhook URL configured in Stripe.

**Fix:** Ensure the URL is `https://<domain>/billing/webhook/` (with the `/billing/` prefix).

### Webhook Returns 403 "No Stripe signature found"

**Cause:** Missing or invalid `Stripe-Signature` header.

**Fix:** This is expected for non-Stripe requests. Real Stripe webhooks include this header.

### Webhook Returns 403 "Invalid signature"

**Cause:** `STRIPE_WEBHOOK_SECRET` doesn't match the signing secret in Stripe Dashboard.

**Fix:**

1. Go to Stripe Dashboard → Developers → Webhooks
2. Click on your endpoint
3. Copy the "Signing secret"
4. Update `STRIPE_WEBHOOK_SECRET` in your environment

### Trial Not Expiring

**Possible causes:**

1. Webhook wasn't received (check Stripe Dashboard → Webhooks → Recent deliveries)
2. Webhook failed to process (check application logs)
3. `STRIPE_WEBHOOK_SECRET` mismatch

**Fix:**

1. Verify webhook configuration in Stripe Dashboard
2. Check webhook delivery logs in Stripe
3. Run the sync command with `--stale-trials-only` (see [Subscription Status Out of Sync](#subscription-status-out-of-sync) below)

### Subscription Status Out of Sync

**Cause:** Missed webhooks due to server downtime, network issues, or configuration problems.

**Fix:** Use the `sync_stripe_subscriptions` command to sync subscription data from Stripe:

```bash
# Dry run - see what would change
python manage.py sync_stripe_subscriptions --dry-run

# Sync all teams with subscriptions
python manage.py sync_stripe_subscriptions

# Sync only teams with stale trials
python manage.py sync_stripe_subscriptions --stale-trials-only

# Sync a specific team
python manage.py sync_stripe_subscriptions --team-key=ABC123
```

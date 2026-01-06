# Billing App

This app handles Stripe-based billing, subscriptions, and trial management for sbomify.

## Documentation

- [Billing Documentation](/docs/billing.md) - Stripe setup, webhooks, trials, and troubleshooting

## Key Files

| File                     | Purpose                           |
| ------------------------ | --------------------------------- |
| `billing_processing.py`  | Core webhook event handlers       |
| `stripe_client.py`       | Stripe API wrapper                |
| `webhook_handler.py`     | Webhook verification and routing  |
| `views.py`               | HTTP endpoints including webhook  |
| `tasks.py`               | Async tasks (email, trial checks) |
| `cron.py`                | Scheduled cron jobs               |
| `email_notifications.py` | Email notification helpers        |
| `models.py`              | BillingPlan model                 |

## Management Commands

### sync_stripe_subscriptions

Sync subscription status from Stripe for teams whose local data may be out of sync:

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

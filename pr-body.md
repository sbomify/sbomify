## What is wrong today

One failed Stripe pricing refresh writes three error-level log lines:

1. `stripe_client.py` — `"Stripe API connection error"`, from the wrapper that classifies the Stripe exception.
2. `stripe_pricing_service._refresh_pricing_from_stripe` — `"Failed to fetch Stripe products: {e}"`, logged and immediately re-raised.
3. `stripe_pricing_service.get_all_plans_pricing` — `"Failed to fetch Stripe products: {e}. Returning cached data."`, from the handler that catches the re-raise.

Sentry's logging integration is wired with `event_level=logging.ERROR` (`settings.py`), so those are three separate Sentry issues, three alerts, for one request. The third line says what actually happened: the fallback returned the cached prices and the pricing page rendered. Nobody needed waking.

Meanwhile the branch that *is* worth an alert — the cached prices being more than 24 hours old, so what the page shows may no longer be what Stripe would charge — logged at `warning`, which is the one level that never reaches Sentry.

## What changed

- `_refresh_pricing_from_stripe` no longer logs before re-raising. The line restated what the client had already written and what its own caller writes next; the `try`/`except` existed only to hold it.
- The fallback in `get_all_plans_pricing` logs at `warning`. Serving a few-minute-old price during a Stripe blip is the cache doing its job.
- The stale-cache branch logs at `error`. That is the condition where the fallback has stopped covering for the outage.

Net effect: a transient Stripe outage produces one Sentry issue (from the client, where the failure is not yet known to be recoverable) instead of three, and a genuinely stale price cache produces one that previously could not be raised at all.

## How I know it is right

Three tests in `test_stripe_pricing_service.py` pin the levels and the count: a fresh-cache failure logs exactly one warning and no error, the module writes exactly one "Failed to fetch Stripe products" line per failure, and a cache older than 24 hours logs exactly one error naming the stale plan. The existing test that the fallback still returns cached data is unchanged and still passes.

The tests assert against a patched module logger rather than `caplog`, because the `sbomify` logger does not propagate to root — the same approach `test_stripe_timeout.py` already uses and documents.

`sbomify/apps/billing` suite: 380 passed. The 17 failures in that directory are all `DjangoViteAssetNotFoundError` from an unbuilt frontend manifest, present before this change and unrelated to it. `ruff check`, `ruff format` and `mypy` are clean — the type-checker's remaining findings in the test file are the pre-existing unannotated tests, unchanged in number.

## Where it came from

Found while auditing unresolved error-tracker alerts for this service. The three issues there are titled "Stripe API connection error", "Failed to fetch Stripe products: Could not connect to payment provider." and "…Returning cached data." — roughly 100 events each in production over six weeks, and the same trio again on staging, all from the same handful of Stripe blips.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

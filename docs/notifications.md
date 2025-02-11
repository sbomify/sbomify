# Notifications

## Overview

The notifications system provides a flexible way to display notifications to users across the application. The system uses a simple, function-based approach where each notification provider is a Python function that returns notification data.

## Architecture

### Provider Functions

Each notification provider is a simple Python function that:

- Takes a `request` parameter
- Returns notification data or None
- Is configured in Django settings
- Lives in a `notifications.py` module within its app

### Configuration

Providers are configured in Django settings:

```python
NOTIFICATION_PROVIDERS = [
    "billing.notifications.check_subscription_status",
    "teams.notifications.check_billing_plan",
]

# Frontend refresh interval (milliseconds)
NOTIFICATION_REFRESH_INTERVAL = 5 * 60 * 1000  # 5 minutes
```

### Notification Schema

Each notification must include:

```python
{
    "id": str,          # Unique identifier
    "type": str,        # Type identifier
    "message": str,     # Display message
    "severity": str,    # One of: "info", "warning", "error"
    "created_at": str,  # ISO format timestamp
    "action_url": str,  # Optional: URL for action button
}
```

## Implementation Guide

### 1. Create Provider Function

Add a `notifications.py` file in your app:

```python
from datetime import datetime
from django.urls import reverse

def your_notification_provider(request):
    """Check for and return notifications"""
    # Example notification
    return {
        "id": "unique_notification_id",
        "type": "notification_type",
        "message": "Your notification message",
        "severity": "info",
        "created_at": datetime.utcnow().isoformat(),
        "action_url": reverse("your:view-name")  # Optional
    }
```

### 2. Enable Provider

Add your provider to `NOTIFICATION_PROVIDERS` in settings:

```python
NOTIFICATION_PROVIDERS = [
    "your_app.notifications.your_notification_provider",
]
```

## Examples

### Team Billing Check

```python
def check_billing_plan(request):
    """Check if team has a billing plan selected"""
    if "current_team" in request.session:
        team_key = request.session["current_team"]["key"]
        try:
            team = Team.objects.get(key=team_key)
            if not team.billing_plan:
                if team.members.filter(
                    member__user=request.user,
                    member__role="owner"
                ).exists():
                    return {
                        "id": f"team_billing_required_{team.key}",
                        "type": "team_billing_required",
                        "message": "Please add billing information",
                        "severity": "warning",
                        "created_at": datetime.utcnow().isoformat(),
                        "action_url": reverse(
                            "billing:select_plan",
                            kwargs={"team_key": team_key}
                        )
                    }
        except Team.DoesNotExist:
            pass
    return None
```

### Subscription Status Check

```python
def check_subscription_status(request):
    """Check subscription status"""
    notifications = []
    if "current_team" in request.session:
        team = get_team(request)
        if team and team.billing_plan == "business":
            if team.billing_plan_limits.get("subscription_status") == "past_due":
                notifications.append({
                    "id": f"billing_past_due_{team.key}",
                    "type": "billing_past_due",
                    "message": "Payment is past due",
                    "severity": "error",
                    "created_at": datetime.utcnow().isoformat(),
                    "action_url": reverse("billing:select_plan",
                                       kwargs={"team_key": team.key})
                })
    return notifications
```

## Best Practices

1. **Single Responsibility**: Each provider should check for one specific type of notification
2. **Error Handling**: Always handle exceptions gracefully
3. **Return Values**: Return `None` or empty list when no notifications
4. **Unique IDs**: Use clear, unique IDs that include context (e.g., `billing_past_due_${team_id}`)
5. **Action URLs**: Include action URLs when there's a specific action to take
6. **Logging**: Log errors and important state changes
7. **Performance**: Keep checks lightweight and cache where appropriate

## Testing

Providers should be tested for:

- Correct notification format
- Proper handling of edge cases
- Error conditions
- Permission checks
- Empty/None returns

See `notifications/tests.py` for examples.

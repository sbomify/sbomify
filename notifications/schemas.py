from ninja import Schema


class NotificationSchema(Schema):
    """Schema for notifications"""
    id: str
    type: str
    message: str
    action_url: str | None = None
    severity: str = "warning"  # info, warning, error
    created_at: str
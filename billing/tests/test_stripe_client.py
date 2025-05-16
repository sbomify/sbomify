from unittest.mock import patch

from django.conf import settings

from billing.stripe_client import StripeClient


@patch("stripe.Webhook.construct_event")
def test_construct_webhook_event_with_default_secret(mock_construct):
    """Test webhook event construction with default secret."""
    client = StripeClient()
    payload = b"test_payload"
    sig_header = "test_sig"

    mock_construct.return_value = "test_event"
    result = client.construct_webhook_event(payload, sig_header)

    assert result == "test_event"
    mock_construct.assert_called_once_with(
        payload,
        sig_header,
        settings.STRIPE_WEBHOOK_SECRET
    )

@patch("stripe.Webhook.construct_event")
def test_construct_webhook_event_with_custom_secret(mock_construct):
    """Test webhook event construction with custom secret."""
    client = StripeClient()
    payload = b"test_payload"
    sig_header = "test_sig"
    custom_secret = "custom_secret"

    mock_construct.return_value = "test_event"
    result = client.construct_webhook_event(payload, sig_header, custom_secret)

    assert result == "test_event"
    mock_construct.assert_called_once_with(
        payload,
        sig_header,
        custom_secret
    )
from random import randint
import pytest
from django.template import Context, Template
from django.http import HttpRequest
from sbomify.apps.billing.services import get_stripe_prices

from sbomify.apps.core.utils import generate_id, number_to_random_token, token_to_number, get_client_ip

import json
import re


def test_id_token_conversion():
    for _ in range(100):
        num = randint(0, 10000)  # nosec: B311
        tok = number_to_random_token(num)
        assert isinstance(tok, str)
        assert len(tok) > 6
        assert num == token_to_number(tok)

def test_generate_id():
    id1 = generate_id()
    assert len(id1) == 12
    assert id1[0].isalpha()
    assert id1.isalnum()
    ids = {generate_id() for _ in range(1000)}
    assert len(ids) == 1000

@pytest.mark.django_db
def test_schema_org_metadata_tag(mocker):
    """
    Test that the schema_org_metadata template tag outputs correct schema.org JSON-LD and valid syntax.
    """
    # Mock the Stripe prices service
    mocker.patch(
        'sbomify.apps.billing.services.get_stripe_prices',
        return_value={
            'business': {'monthly': 199.0, 'annual': 1908.0},
            'starter': {'monthly': 49.0, 'annual': 499.0},
        }
    )
    # Create a BillingPlan for each plan
    from sbomify.apps.billing.models import BillingPlan
    BillingPlan.objects.create(key='business', name='Business')
    BillingPlan.objects.create(key='starter', name='Starter')

    template = Template("""
    {% load schema_tags %}
    {% schema_org_metadata %}
    """)
    rendered = template.render(Context({}))

    assert 'application/ld+json' in rendered
    assert 'SBOMify' in rendered
    assert 'Business - Monthly' in rendered
    assert '199.0' in rendered
    assert 'Business - Annual' in rendered
    assert '1908.0' in rendered
    assert 'Starter - Monthly' in rendered
    assert '49.0' in rendered
    assert 'Starter - Annual' in rendered
    assert '499.0' in rendered
    # Check JSON structure
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', rendered, re.DOTALL)
    assert match, 'No JSON-LD script found'
    data = json.loads(match.group(1))
    assert data['@type'] == 'SoftwareApplication'
    assert any(o['name'] == 'Business - Monthly' for o in data['offers'])
    assert any(o['name'] == 'Starter - Annual' for o in data['offers'])
    # Validate required schema.org fields
    required_fields = ["@context", "@type", "name", "description", "applicationCategory", "operatingSystem", "offers"]
    for field in required_fields:
        assert field in data, f"Missing required schema.org field: {field}"
    # Validate offers structure
    for offer in data["offers"]:
        assert offer["@type"] == "Offer"
        assert "name" in offer
        assert "price" in offer
        assert "priceCurrency" in offer
        assert "priceSpecification" in offer
        ps = offer["priceSpecification"]
        assert ps["@type"] == "UnitPriceSpecification"
        assert "price" in ps
        assert "priceCurrency" in ps
        assert "billingDuration" in ps
        assert "billingIncrement" in ps


def test_get_client_ip_priority():
    """Test get_client_ip prioritizes headers correctly."""
    request = HttpRequest()
    
    # 1. Cloudflare IP should be highest priority
    request.META = {
        "HTTP_CF_CONNECTING_IP": "1.1.1.1",
        "HTTP_X_FORWARDED_FOR": "2.2.2.2",
        "HTTP_X_REAL_IP": "3.3.3.3",
        "REMOTE_ADDR": "4.4.4.4"
    }
    assert get_client_ip(request) == "1.1.1.1"

    # 2. X-Forwarded-For should be second priority
    request.META = {
        "HTTP_X_FORWARDED_FOR": "2.2.2.2",
        "HTTP_X_REAL_IP": "3.3.3.3",
        "REMOTE_ADDR": "4.4.4.4"
    }
    assert get_client_ip(request) == "2.2.2.2"

    # 3. X-Real-IP should be third priority
    request.META = {
        "HTTP_X_REAL_IP": "3.3.3.3",
        "REMOTE_ADDR": "4.4.4.4"
    }
    assert get_client_ip(request) == "3.3.3.3"

    # 4. REMOTE_ADDR is fallback
    request.META = {
        "REMOTE_ADDR": "4.4.4.4"
    }
    assert get_client_ip(request) == "4.4.4.4"

    # 5. None if nothing exists
    request.META = {}
    assert get_client_ip(request) is None


def test_get_client_ip_xff_parsing():
    """Test get_client_ip handles multi-value X-Forwarded-For headers."""
    request = HttpRequest()
    
    # Standard comma-separated list
    request.META = {
        "HTTP_X_FORWARDED_FOR": "203.0.113.195, 70.41.3.18, 150.172.238.178",
        "REMOTE_ADDR": "127.0.0.1"
    }
    assert get_client_ip(request) == "203.0.113.195"

    # With spaces
    request.META = {
        "HTTP_X_FORWARDED_FOR": "10.0.0.1,  10.0.0.2",
        "REMOTE_ADDR": "127.0.0.1"
    }
    assert get_client_ip(request) == "10.0.0.1"

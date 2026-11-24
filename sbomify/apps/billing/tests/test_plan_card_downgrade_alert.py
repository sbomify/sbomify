"""Which downgrade cards carry the cancellation notice.

``plan.downgrade`` is true for every cheaper plan, but only the Community card
leads to a cancellation: ``plan-selection.ts`` sends community to the portal's
``subscription_cancel`` flow and every other plan to ``subscription_update``.
An Enterprise workspace looking at the Business card is downgrading without
cancelling, so it must not be told its subscription ends. Nor is a workspace
with no live subscription, which changes over at once.
"""

import pytest
from django.template.loader import render_to_string

CANCEL_NOTICE = "Your subscription ends with this billing period"
PROBE = "core/cotton_probes/billing_plan_card.html.j2"


def _plan(key: str, name: str, *, downgrade: bool, current: bool = False, ends_subscription: bool = False) -> dict:
    return {
        "key": key,
        "name": name,
        "description": f"{name} plan",
        "features": ("A feature",),
        "current": current,
        "downgrade": downgrade,
        "ends_subscription": ends_subscription,
        "prices": [],
        "limits": [{"label": "member", "count": 1}],
    }


def _card(rendered: str, name: str) -> str:
    """The markup of one card, sliced on its region label."""
    start = rendered.index(f'aria-label="{name} plan"')
    end = rendered.find('role="region"', start)
    return rendered[start:] if end == -1 else rendered[start:end]


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string(
        PROBE,
        {
            "plans": [
                _plan("community", "Community", downgrade=True, ends_subscription=True),
                _plan("business", "Business", downgrade=True),
                _plan("enterprise", "Enterprise", downgrade=False, current=True),
            ]
        },
    )


def test_community_downgrade_says_the_subscription_is_cancelled(rendered: str) -> None:
    assert CANCEL_NOTICE in _card(rendered, "Community")


def test_a_downgrade_that_is_not_a_cancellation_stays_silent(rendered: str) -> None:
    assert CANCEL_NOTICE not in _card(rendered, "Business")


def test_the_current_plan_carries_no_downgrade_notice(rendered: str) -> None:
    assert CANCEL_NOTICE not in _card(rendered, "Enterprise")


def test_a_community_move_with_nothing_to_cancel_stays_silent() -> None:
    rendered = render_to_string(PROBE, {"plans": [_plan("community", "Community", downgrade=True)]})

    assert CANCEL_NOTICE not in _card(rendered, "Community")


def test_the_notice_and_the_lost_features_share_one_alert(rendered: str) -> None:
    """Two alerts saying the subscription ends was the merge of two fixes for
    one finding. The period end leads the alert that lists what is lost."""
    plan = _plan("community", "Community", downgrade=True, ends_subscription=True)
    card = _card(render_to_string(PROBE, {"plans": [{**plan, "lost_features": ["Private products"]}]}), "Community")

    assert card.count("billing period") == 1
    assert card.index("Moving here costs you") < card.index(CANCEL_NOTICE) < card.index("Private products")

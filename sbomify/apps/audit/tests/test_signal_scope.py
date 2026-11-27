"""The audit receivers listen to tracked models only.

A receiver connected without a sender listens to every model, and Django then
refuses its one-statement bulk delete everywhere: a cascade into a large
untracked table loads and signals each row instead.
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.db.models.deletion import Collector
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch.dispatcher import _make_id

from sbomify.apps.audit.signals import TRACKED, tracked_senders

SIGNALS = {
    "audit_pre_save": pre_save,
    "audit_post_save": post_save,
    "audit_pre_delete": pre_delete,
    "audit_post_delete": post_delete,
}


def _audit_sender_ids(signal, uid_prefix: str) -> set:
    return {key[1] for key, *_ in signal.receivers if isinstance(key[0], str) and key[0].startswith(uid_prefix)}


@pytest.mark.parametrize("uid_prefix", SIGNALS)
def test_receivers_are_bound_to_tracked_models_and_their_proxies_only(uid_prefix: str) -> None:
    expected = {_make_id(model) for model in tracked_senders()}

    assert _audit_sender_ids(SIGNALS[uid_prefix], uid_prefix) == expected
    assert _make_id(None) not in expected


def test_every_tracked_entry_and_its_proxies_are_senders() -> None:
    senders = {model._meta.label for model in tracked_senders()}

    assert {tracked.model for tracked in TRACKED} <= senders
    assert {"core.Product", "core.Component"} <= senders


def test_an_untracked_leaf_table_is_deleted_in_bulk() -> None:
    model = apps.get_model("vulnerability_scanning", "ComponentVexDrift")

    assert not pre_delete.has_listeners(model)
    assert not post_delete.has_listeners(model)
    assert Collector("default").can_fast_delete(model.objects.all())

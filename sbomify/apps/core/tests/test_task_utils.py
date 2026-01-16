from types import SimpleNamespace

from sbomify import task_utils


def test_record_task_breadcrumb_no_sentry(monkeypatch):
    monkeypatch.setattr(task_utils, "sentry_sdk", None)
    task_utils.record_task_breadcrumb("sample_task", "start")


def test_record_task_breadcrumb_calls_sentry(monkeypatch):
    calls = []

    def add_breadcrumb(**kwargs):
        calls.append(kwargs)

    dummy_sentry = SimpleNamespace(add_breadcrumb=add_breadcrumb)
    monkeypatch.setattr(task_utils, "sentry_sdk", dummy_sentry)

    task_utils.record_task_breadcrumb("sample_task", "start", data={"id": "123"})

    assert len(calls) == 1
    assert calls[0]["category"] == "tasks"
    assert "sample_task" in calls[0]["message"]

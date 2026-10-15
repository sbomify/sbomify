"""Forms for CRA Article 14 reports. Dates are entered in UTC, as ENISA's portal asks."""

from __future__ import annotations

from typing import Any

from django import forms

from .models import CRAReport, CRAReportFiling
from .reporting import fields_for

_DATETIME_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"]


class CRAReportCreateForm(forms.Form):
    kind = forms.ChoiceField(choices=CRAReport.Kind.choices)
    product_id = forms.CharField(max_length=20)
    advisory_id = forms.CharField(max_length=20, required=False)
    # Empty means now: a report is usually started the moment someone learns of it.
    aware_at = forms.DateTimeField(required=False, input_formats=_DATETIME_FORMATS)


class CRAFilingForm(forms.Form):
    stage = forms.ChoiceField(choices=CRAReportFiling.Stage.choices)
    srp_reference = forms.CharField(max_length=100, required=False)
    filed_at = forms.DateTimeField(required=False, input_formats=_DATETIME_FORMATS)


class CRAReportForm(forms.Form):
    """The report's dates plus one field per entry of the ENISA form for its kind."""

    aware_at = forms.DateTimeField(input_formats=_DATETIME_FORMATS)
    occurred_at = forms.DateTimeField(required=False, input_formats=_DATETIME_FORMATS)
    measure_available_at = forms.DateTimeField(required=False, input_formats=_DATETIME_FORMATS)

    def __init__(self, *args: Any, kind: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if kind != CRAReport.Kind.VULNERABILITY:
            del self.fields["measure_available_at"]
        for field in fields_for(kind):
            if field.column:
                continue
            if field.choices:
                choices = [("", "Not set"), *((choice, choice) for choice in field.choices)]
                self.fields[field.id] = forms.ChoiceField(choices=choices, required=False, label=field.label)
            else:
                self.fields[field.id] = forms.CharField(
                    required=False, max_length=field.max_length, label=field.label, strip=True
                )

    def values(self) -> dict[str, Any]:
        return {name: value for name, value in self.cleaned_data.items() if name not in self._dates()}

    def dates(self) -> dict[str, Any]:
        return {name: self.cleaned_data.get(name) for name in self._dates() if name in self.fields}

    @staticmethod
    def _dates() -> tuple[str, ...]:
        return ("aware_at", "occurred_at", "measure_available_at")

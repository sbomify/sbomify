"""Database expressions shared by CSAF lookup and its index."""

from django.db.models import CharField, F, Func, Value
from django.db.models.functions import Coalesce, Concat, Lower, NullIf


def csaf_filename_expression() -> Concat:
    """CSAF 2.0 section 5.1 normalization, matching csaf_filename()."""
    return Concat(
        Func(
            Lower(Coalesce(NullIf(F("tracking_id"), Value("")), F("id"))),
            Value("[^+a-z0-9-]"),
            Value("_"),
            Value("g"),
            function="REGEXP_REPLACE",
            output_field=CharField(),
        ),
        Value(".json"),
        output_field=CharField(),
    )

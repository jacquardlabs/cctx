"""JSON exporter — full session array as pretty-printed JSON."""
from __future__ import annotations

import json
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from cctx.models import Diagnosis, SessionTrace

from cctx.exporters.jsonl import export_diagnosis


def write(
    diagnoses: list[tuple[Diagnosis, SessionTrace]],
    out: IO[str],
    *,
    include_content: bool = True,
) -> None:
    objects = [
        json.loads(export_diagnosis(diagnosis, trace, include_content=include_content))
        for diagnosis, trace in diagnoses
    ]
    out.write(json.dumps(objects, indent=2) + "\n")

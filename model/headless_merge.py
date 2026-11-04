from __future__ import annotations

from pathlib import Path

import fitz

from model.navigation_graft import NavigationGraft
from model.pdf_model import _guard_foreign_doc
from utils.path_staging import write_via_staging


def headless_merge(inputs: list[str], output: str) -> None:
    if not inputs:
        raise ValueError("headless_merge requires at least one input file")

    resolved_inputs = [Path(path) for path in inputs]
    missing = next((path for path in resolved_inputs if not path.exists()), None)
    if missing is not None:
        raise FileNotFoundError(str(missing))

    output_path = Path(output)
    if not output_path.parent.exists():
        raise FileNotFoundError(str(output_path.parent))

    merged = fitz.open()
    try:
        # insert_pdf alone drops outline, page labels, named destinations and
        # LINK_NAMED links (F16-NAV-3); the graft carries them across.
        graft = NavigationGraft(merged)
        for input_path in resolved_inputs:
            # Inputs are foreign PDFs: apply the size/page/encryption guards.
            src = _guard_foreign_doc(input_path)
            try:
                graft.copy_pages(src)
            finally:
                src.close()
        graft.finish()
        # Stage + atomic replace: a failed write must not truncate an existing output.
        write_via_staging(output_path, merged.save)
    finally:
        merged.close()

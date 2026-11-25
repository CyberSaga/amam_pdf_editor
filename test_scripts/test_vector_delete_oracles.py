"""Card B6 acceptance (design plan Step 5): the PRODUCT delete path judged by the B1 oracles over the builder twins.

vector_select state -> plan_delete -> PDFModel.commit_vector_plan, then O-rebuild, O-struct, O-pixel, O-bytes, O-dict and
rule B (vector_oracles.ORACLES) compare the committed document against the builder's own expected() for the same
operation.  A commit test that only compares the result with the plan checks the plan against itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.pdf_model import PDFModel  # noqa: E402
from model.vector_paths.edit import plan_delete  # noqa: E402
from model.vector_paths.scan import VectorPageRefused, scan_page  # noqa: E402
from test_scripts import vector_fixture_builder as vfb  # noqa: E402
from test_scripts import vector_index_rows as vir  # noqa: E402
from test_scripts import vector_oracles as vo  # noqa: E402

OPS = [
    vfb.Op("delete", 0, (1,)),
    vfb.Op("delete", 0, (1, 2)),
    vfb.Op("delete", 0, (3,)),
    vfb.Op("delete", 0, (0,)),
    vfb.Op("delete", 0, (9,)),
]


def _cases() -> list[tuple[str, vfb.Scene, vfb.Op]]:
    return [(f"{name}/{op.selected}", scene, op) for name, scene in vfb.default_scenes() for op in OPS]


@pytest.mark.parametrize("label,scene,op", _cases(), ids=[c[0] for c in _cases()])
def test_the_product_delete_passes_every_oracle(tmp_path, label, scene, op):
    before = vfb.build(scene)
    path = tmp_path / "twin.pdf"
    path.write_bytes(before)
    model = PDFModel()
    model.open_pdf(str(path))
    page_num = op.page + 1
    try:
        streams, frame = model.vector_page_source(page_num)
    except VectorPageRefused:
        pytest.skip("page refused by the scanner source")
    index = scan_page(list(streams), frame)
    model.install_vector_index(page_num, index)
    rows = sorted(vir.selected_rows(scene.pages[op.page], op.selected))
    mask = np.zeros(len(index.paths), dtype=bool)
    mask[rows] = True
    editable = (index.paths["flags"].astype(int) & 1) != 0
    if not (mask & editable).any():
        pytest.skip("nothing editable in this selection")
    model.__dict__["_vector_selection"] = (page_num, 1, mask, index, model.handle_generation)
    inputs = model.vector_plan_inputs(1)
    assert inputs is not None
    plan = plan_delete(*inputs)
    result = model.commit_vector_plan(plan, 1)
    assert result is not None, model.last_object_op_refusal
    after = bytes(model.serialize_document_bytes(model.doc))
    expected_data, facts = vfb.expected(scene, op)
    kw = {k: v for k, v in facts.context.items() if k != "scenario_op"}
    kw["expected"] = expected_data
    verdicts = {name: fn(op, before, after, **kw) for name, fn in vo.ORACLES.items()}
    assert not any(verdicts.values()), verdicts

from __future__ import annotations

from types import SimpleNamespace

import fitz
import pytest

from model.tools.annotation_tool import AnnotationTool


@pytest.mark.parametrize('with_text', [False, True])
def test_only_pages_with_listable_annotation_types_are_loaded(monkeypatch, with_text):
    with fitz.open() as doc:
        for _ in range(3):
            page = doc.new_page(width=200, height=200)
            page.add_rect_annot(fitz.Rect(10, 10, 40, 40))
        if with_text:
            doc[2].add_text_annot((70, 70), 'keep me')
        original = doc.load_page
        loaded = []

        def observed(index):
            loaded.append(index)
            return original(index)

        monkeypatch.setattr(doc, 'load_page', observed)
        result = AnnotationTool(SimpleNamespace(doc=doc)).get_all_annotations()
        assert [row['text'] for row in result] == (['keep me'] if with_text else [])
        assert loaded == ([2] if with_text else [])

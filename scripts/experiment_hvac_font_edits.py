"""Reproduce ten bounded edits on the HVAC Bb fixture; not a general editor.

Run from the repository root with its virtualenv. All outputs are separate
from the input. This deliberately reuses the project's CID/lexer primitives.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import fitz
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.text_commit.cid_fonts import CidCapabilityFailure
from model.text_commit.dto import StreamReplacement
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.pdf_lexer import encode_hex_string, splice_stream
from model.text_commit.plan import PlanRejection
from model.text_commit.replay import replay_page_streams


# Page indices are zero based; seq identifies the actual show, including twins.
CASES = (
    (4, 11, "空調冰水管線系統圖(1)", "空調冰水管線系統圖(4)"),
    (4, 16, "空調冷卻水管線系統圖(1)", "空調冷卻水管線系統表(1)"),
    (4, 6, "空調系統封面", "空調系統圖說"),
    (4, 7, "Chilled Water Distribution System Diagram(1)", "Chilled Water Distribution System Diagram(4)"),
    (4, 18, "1F Chilled Water System Plan Layout", "2F Chilled Water System Plan Layout"),
    (4, 26, "Drawing List", "Drawing Title"),
    (5, 60, "2026.05.15", "2026.05.16"),
    (5, 58, "空調系統設計圖說A版", "空調系統設計圖說B版"),
    (6, 7, "Buffer Tank", "Tank Buffer"),
    (6, 5, "Buffer Tank", "Tank Buffer"),
)


def shows(doc, page_index):
    page = doc[page_index]
    result = replay_page_streams([(x, doc.xref_stream(x)) for x in page.get_contents()])
    assert not result.malformed and not result.refusal_reason, result
    return result.shows


def verify_text(candidate):
    registry = DocumentFontRegistry(candidate)
    for number, (page_index, seq, _, replacement) in enumerate(CASES, 1):
        show = shows(candidate, page_index)[seq]
        cap = registry.capability(candidate[page_index], show.font_resource)
        assert cap.cid is not None
        actual = cap.cid.decode_show_bytes(show.decoded_bytes)
        assert actual == replacement, f"case {number}: {actual!r} != {replacement!r}"


def trace_for(page, show, text):
    origin = fitz.Point(show.origin_user) * page.transformation_matrix
    matches = []
    for trace in page.get_texttrace():
        full = ''.join(chr(c[0]) for c in trace['chars'])
        start = full.find(text)
        while start >= 0:
            chars = trace['chars'][start:start + len(text)]
            rect = fitz.Rect(chars[0][3])
            for char in chars[1:]:
                rect |= fitz.Rect(char[3])
            matches.append(dict(trace, chars=chars, bbox=tuple(rect)))
            start = full.find(text, start + 1)
    assert matches, text
    match = min(matches, key=lambda t: abs(fitz.Point(t['chars'][0][2]) - origin))
    assert abs(fitz.Point(match['chars'][0][2]) - origin) < 0.02
    return match


def render(page, zoom=2, clip=None):
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)


def verify_images(source, candidate, out):
    """Target ink must change; every pixel outside target rectangles must agree."""
    rows = []
    rectangles = {}
    pairs = []
    for number, (page_index, seq, original, replacement) in enumerate(CASES, 1):
        old_show = shows(source, page_index)[seq]
        new_show = shows(candidate, page_index)[seq]
        old = trace_for(source[page_index], old_show, original)
        new = trace_for(candidate[page_index], new_show, replacement)
        for key in ('font', 'dir', 'size', 'color', 'opacity', 'type'):
            assert old[key] == new[key], (number, key)
        assert old['chars'][0][2] == new['chars'][0][2], number
        for key in ('font_resource', 'font_size', 'tm', 'ctm', 'hscale',
                    'char_spacing', 'word_spacing', 'rise', 'render_mode'):
            assert getattr(old_show, key) == getattr(new_show, key), (number, key)
        rect = fitz.Rect(old['bbox']) | fitz.Rect(new['bbox'])
        rect = rect * source[page_index].rotation_matrix
        rect += (-3, -3, 3, 3)
        rectangles.setdefault(page_index, []).append(rect)
        before = render(source[page_index], 6, rect)
        after = render(candidate[page_index], 6, rect)
        changed = int(np.any(np.array(before) != np.array(after), axis=2).sum())
        assert changed > 0, number
        before.save(out / f'{number:02}-before.png')
        after.save(out / f'{number:02}-after.png')
        rotated = before.height > before.width * 2
        if rotated:
            before = before.transpose(Image.Transpose.ROTATE_270)
            after = after.transpose(Image.Transpose.ROTATE_270)
        pairs.append((number, before, after, rotated))
        rows.append({'case': number, 'page': page_index + 1,
                     'before': original, 'after': replacement,
                     'font': old['font'], 'trace_size': old['size'],
                     'origin': old['chars'][0][2], 'crop_visual': list(rect),
                     'changed_pixels_6x': changed,
                     'same_font_state_and_origin': True})
    page_checks = []
    for page_index, rects in rectangles.items():
        before = np.array(render(source[page_index]))
        after = np.array(render(candidate[page_index]))
        diff = np.any(before != after, axis=2)
        for rect in rects:
            bounds = (rect * fitz.Matrix(2, 2)).irect
            diff[max(0, bounds.y0):bounds.y1, max(0, bounds.x0):bounds.x1] = False
        count = int(diff.sum())
        assert count == 0, (page_index + 1, count)
        page_checks.append({'page': page_index + 1, 'outside_target_changed_pixels_2x': count})
    width = max(max(a.width, b.width) for _, a, b, _ in pairs) + 24
    heights = [max(a.height, b.height) + 38 for _, a, b, _ in pairs]
    sheet = Image.new('RGB', (width * 2, sum(heights) + 34), '#e9edf2')
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), 'BEFORE (6x render)', fill='black')
    draw.text((width + 12, 10), 'AFTER (6x render; original font resource)', fill='black')
    y = 34
    for (number, before, after, rotated), height in zip(pairs, heights):
        label = f'Case {number:02}' + (' - crop rotated 270 degrees; no reflection correction' if rotated else '')
        draw.text((12, y), label, fill='black')
        sheet.paste(before, (12, y + 20))
        sheet.paste(after, (width + 12, y + 20))
        y += height
    sheet.save(out / 'comparison-10.png')
    return rows, page_checks


def write_candidate(source, output):
    registry = DocumentFontRegistry(source)
    patches = {}
    records = []
    engine = TieredCommitEngine(source, max_tier=1)
    for number, (page_index, seq, original, replacement) in enumerate(CASES, 1):
        page = source[page_index]
        show = shows(source, page_index)[seq]
        assert show.operator == 'Tj' and show.string_kind == 'hex'
        assert show.origin_reliable and show.render_mode == 0
        cap = registry.capability(page, show.font_resource)
        assert cap is not None and cap.cid is not None
        cid = cap.cid
        assert cid.decode_show_bytes(show.decoded_bytes) == original
        old_cids = tuple(int.from_bytes(show.decoded_bytes[i:i + 2], 'big')
                         for i in range(0, len(show.decoded_bytes), 2))
        new_cids = cid.encode_strict(replacement)
        assert not isinstance(new_cids, CidCapabilityFailure), new_cids
        assert cid.glyph_gate(new_cids, replacement) is None
        delta = (cid.advance_points(new_cids, show.font_size, show.char_spacing)
                 - cid.advance_points(old_cids, show.font_size, show.char_spacing))
        kern = delta * 1000 / show.font_size
        encoded = encode_hex_string(cid.encode_cids(new_cids))
        if abs(kern) < 1e-8:
            start, end = show.string_start, show.string_end
            payload = encoded
        else:
            start, end = show.op_start, show.op_end
            payload = b'[' + encoded + f' {kern:.10f}'.encode('ascii') + b'] TJ'
        stream = source.xref_stream(show.stream_xref)
        patches.setdefault(show.stream_xref, []).append(StreamReplacement(
            show.stream_xref, start, end, stream[start:end], payload,
            hashlib.sha256(stream).hexdigest()))
        trace = trace_for(page, show, original)
        visual_origin = fitz.Point(trace['chars'][0][2]) * page.rotation_matrix
        visual_bbox = fitz.Rect(trace['bbox']) * page.rotation_matrix
        plan = engine.prepare(page, target_text=original, replacement_text=replacement,
                              expected_origin=tuple(visual_origin), target_bbox=tuple(visual_bbox))
        probe = ({'prepared': False, 'reason': plan.reason, 'detail': plan.detail}
                 if isinstance(plan, PlanRejection) else
                 {'prepared': True, 'tier': int(plan.tier)})
        records.append({'case': number, 'font_xref': cap.font_xref,
                        'font_resource': show.font_resource, 'Tf': show.font_size,
                        'Tm': show.tm, 'CTM': show.ctm, 'Tz_percent': show.hscale,
                        'Tc': show.char_spacing, 'Tw': show.word_spacing,
                        'TJ_compensation': kern, 'engine_max_tier_1_probe': probe,
                        'stream_xref': show.stream_xref, 'byte_start': start, 'byte_end': end,
                        'before_operator': stream[show.op_start:show.op_end].decode('ascii'),
                        'replacement_bytes': payload.decode('ascii')})
        print(f'Prepared case {number}: {probe}', flush=True)
    # Extra negative control: never silently invent a CID for a missing character.
    cap = registry.capability(source[4], shows(source, 4)[11].font_resource)
    missing = cap.cid.encode_strict('空調冰水管路系統圖(1)')
    assert isinstance(missing, CidCapabilityFailure)
    shutil.copyfile(source.name, output)
    with fitz.open(output) as candidate:
        for xref, replacements in patches.items():
            original = candidate.xref_stream(xref)
            candidate.update_stream(xref, splice_stream(original, replacements), compress=True)
        candidate.saveIncr()
    return records, {'replacement': '空調冰水管路系統圖(1)', 'reason': missing.reason}


def verify_resources(source, candidate):
    affected = {p for p, _, _, _ in CASES}
    stream_xrefs = {x for p in affected for x in source[p].get_contents()}
    assert source.page_count == candidate.page_count
    # Incremental save of this cross-reference-stream PDF adds a new /XRef.
    assert candidate.xref_length() >= source.xref_length()
    for xref in range(source.xref_length(), candidate.xref_length()):
        assert candidate.xref_get_key(xref, 'Type') == ('name', '/XRef'), xref
    # Only declared page content streams may change, including font objects,
    # embedded font programs, ToUnicode maps, images and other page streams.
    checked = 0
    for xref in range(1, source.xref_length()):
        if xref in stream_xrefs:
            continue
        # Save may change compression dictionaries, but decoded bytes must agree.
        if source.xref_is_stream(xref):
            assert source.xref_stream(xref) == candidate.xref_stream(xref), xref
        else:
            assert source.xref_object(xref) == candidate.xref_object(xref), xref
        checked += 1
    return {'unchanged_non_target_xrefs': checked,
            'modified_content_xrefs': sorted(stream_xrefs),
            'added_xref_streams': candidate.xref_length() - source.xref_length()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path('output/pdf/manual-font-study'))
    parser.add_argument('--verify-only', type=Path, help='Check a saved candidate; original must fail.')
    args = parser.parse_args()
    with fitz.open(args.verify_only or args.source) as candidate:
        if args.verify_only:
            verify_text(candidate)
            print('All 10 replacements present.')
            return
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / 'hvac-pymupdf-10.pdf'
    assert output.resolve() != args.source.resolve(), 'Never overwrite the source.'
    original_digest = hashlib.sha256(args.source.read_bytes()).hexdigest()
    with fitz.open(args.source) as source:
        records, negative = write_candidate(source, output)
        with fitz.open(output) as candidate:
            verify_text(candidate)
            resources = verify_resources(source, candidate)
            rows, page_checks = verify_images(source, candidate, args.output)
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == original_digest
    report = {'pymupdf_version': fitz.VersionBind, 'source_name': args.source.name,
              'source_sha256': original_digest, 'output_name': output.name,
              'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'edits': [dict(row, **record) for row, record in zip(rows, records)],
              'page_checks': page_checks, 'resources': resources,
              'missing_glyph_negative_control': negative}
    (args.output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'success': True, 'edits': len(rows), **resources,
                      'page_checks': page_checks}, ensure_ascii=False))


if __name__ == '__main__':
    main()

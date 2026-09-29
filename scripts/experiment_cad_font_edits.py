"""Bounded source-glyph experiments for three CAD fixtures; not a general editor."""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import shutil
import subprocess
import sys

import fitz
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.cid_fonts import CidCapabilityFailure
from model.text_commit.dto import StreamReplacement
from model.text_commit.pdf_lexer import TokenKind, encode_hex_string, lex_content_stream, splice_stream
from scripts.experiment_hvac_font_edits import render, shows, trace_for


FILES = {
    'chb': 'vector-chb.pdf',
    'ecc': 'ecc-dwg.pdf',
    'taoyuan': 'vector-airport.pdf',
}
SOURCE_HASHES = {
    'chb': '1580cbc98bc4506d6c8ea73b732eb91267468f4311a4ed21e943ac4f89c2024d',
    'ecc': '0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853',
    'taoyuan': 'c994e9f888588a6684cd64bdff8e4b0ea6c85fc46eed3b4d0c8cd8120c0494f7',
}
TEXT_CASES = (
    (31, '專案名稱', '專案圖名'),
    (38, '平面配置圖', '機房配置圖'),
    (57, '113.05.03', '113.05.05'),
    (60, None, 'ECC-3'),
)
# A None original is read from the hash-pinned fixture and checked against this
# digest, so the drawing's identifying text stays out of git.
TEXT_CASE_SHA256 = {60: '306a3a57a5bfe7d06316a66c06f4adde43b9d4a647266cabcebc412485bd0660'}
# Visual page coordinates. Each donor is from the same source lettering/size.
# Translation is rigid: no scaling, stretching, raster replacement or new font.
VECTOR_CASES = {
    'chb': (
        ('1000 -> 1001', (175, 153, 219, 169),
         (((208.8, 154.8, 217.5, 167.5), (176.8, 154.8, 180.3, 167.5), (34.38, 0)),)),
        ('1000 -> 1010', (325, 153, 369, 169),
         (((347.6, 154.8, 356.3, 167.5), (327.0, 154.8, 330.6, 167.5), (22.86, 0)),)),
        ('1000 -> 1100', (475, 153, 519, 169),
         (((486.4, 154.8, 495.2, 167.5), (477.2, 154.8, 480.8, 167.5), (11.46, 0)),)),
        ('1000 -> 1001', (625, 153, 669, 169),
         (((659.6, 154.8, 668.3, 167.5), (627.5, 154.8, 631.1, 167.5), (34.38, 0)),)),
    ),
    'taoyuan': (
        ('110.04.29 -> 110.04.24', (1100, 637, 1169, 655),
         (((1160.1, 639.9, 1167, 653), (1138.2, 640.0, 1145.1, 651.8), (22.08, 0)),)),
        ('MB-02 -> MB-20', (1099, 798, 1139, 815),
         (((1122.5, 800.4, 1128.8, 813.3), (1129.7, 800.4, 1136.8, 812.3), (-7.32, 0)),
          ((1129.7, 800.4, 1136.8, 812.3), (1122.5, 800.4, 1128.8, 813.3), (7.32, 0)))),
        ('150A*2 -> 150A*1', (79, 586, 131, 604),
         (((121.4, 588.6, 129.0, 601.5), (81.9, 588.6, 87.1, 601.5), (40.2, 0)),)),
        ('CHR 100A -> CHS 100A', (432, 413, 456, 423),
         (((439.4, 415.1, 442.3, 421.1), (439.4, 432.5, 442.3, 438.5), (0, -17.4)),)),
    ),
}


def contains(outer, inner, epsilon=0.002):
    return all((outer[0] - epsilon <= inner[0], outer[1] - epsilon <= inner[1],
                outer[2] + epsilon >= inner[2], outer[3] + epsilon >= inner[3]))


def selected_drawings(page, rect):
    if not hasattr(page, '_cad_experiment_drawings'):
        page._cad_experiment_drawings = page.get_drawings()
    return [d for d in page._cad_experiment_drawings
            if contains(rect, d['rect'] * page.rotation_matrix)]


def drawing_signature(drawing, page, offset=(0, 0)):
    """Independent MuPDF interpretation of geometry, including Bezier controls."""
    result = []
    for item in drawing['items']:
        values = [item[0]]
        for value in item[1:]:
            if isinstance(value, fitz.Point):
                point = value * page.rotation_matrix
                values.append((point.x + offset[0], point.y + offset[1]))
            elif isinstance(value, fitz.Rect):
                rect = value * page.rotation_matrix
                values.append((rect.x0 + offset[0], rect.y0 + offset[1],
                               rect.x1 + offset[0], rect.y1 + offset[1]))
            else:
                values.append(value)
        result.append(values)
    style = (drawing['type'], drawing['color'], drawing['fill'],
                 drawing['width'], drawing['lineCap'], drawing['lineJoin'],
                 drawing['closePath'], drawing['even_odd'],
                 drawing['fill_opacity'], drawing['stroke_opacity'])
    return style, result


def geometry_equal(a, b):
    if isinstance(a, (tuple, list)):
        return isinstance(b, (tuple, list)) and len(a) == len(b) and all(
            geometry_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, float):
        # MuPDF float32 interpretation of translated coordinates, not a raster tolerance.
        return isinstance(b, (float, int)) and abs(a - b) < 0.002
    return a == b


def glyph_union(target, donor, delta):
    moved = fitz.Rect(donor) + (delta[0], delta[1], delta[0], delta[1])
    return fitz.Rect(target) | moved


def verify_vectors(source, candidate, cases):
    for label, _, edits in cases:
        for target, donor, delta in edits:
            expected = [drawing_signature(d, source, delta)
                        for d in selected_drawings(source, donor)]
            assert expected, ('empty donor', label, donor)
            actual = [drawing_signature(d, candidate)
                      for d in selected_drawings(candidate, glyph_union(target, donor, delta))]
            assert len(actual) == len(expected), ('glyph path count', label)
            assert all(a[0] == b[0] and geometry_equal(a[1], b[1])
                       for a, b in zip(actual, expected)), ('glyph geometry/style mismatch', label, target)


def verify_text(source, candidate):
    reg = DocumentFontRegistry(candidate.parent)
    for seq, original, replacement in TEXT_CASES:
        old_show = shows(source.parent, 0)[seq]
        new_show = shows(candidate.parent, 0)[seq]
        cap = reg.capability(candidate, new_show.font_resource)
        assert cap.cid is not None
        actual = cap.cid.decode_show_bytes(new_show.decoded_bytes)
        assert actual == replacement, (seq, actual, replacement)
        old = trace_for(source, old_show, original)
        new = trace_for(candidate, new_show, replacement)
        assert old['font'] == new['font'] == 'DFKaiShu-SB-Estd-BF'
        for key in ('dir', 'size', 'color', 'opacity', 'type'):
            assert old[key] == new[key], (seq, key)
        assert old['chars'][0][2] == new['chars'][0][2]
        for key in ('font_resource', 'font_size', 'tm', 'ctm', 'hscale',
                    'char_spacing', 'word_spacing', 'rise', 'render_mode'):
            assert getattr(old_show, key) == getattr(new_show, key), (seq, key)


def vector_paths(doc):
    """Narrow fixture parser: translation CTMs only, no clips/forms/text/images.

    Streams are concatenated for parsing because paths cross stream boundaries.
    Only a selected complete path inside one source stream can be patched.
    Decimal accumulation avoids drift through thousands of relative cm commands.
    """
    page = doc[0]
    assert not page.get_fonts() and not page.get_images() and not page.get_xobjects()
    chunks, spans, cursor = [], [], 0
    for xref in page.get_contents():
        chunk = doc.xref_stream(xref)
        spans.append((cursor, cursor + len(chunk), xref))
        chunks.append(chunk)
        cursor += len(chunk) + 1
    data = b'\n'.join(chunks)
    matrix = page.transformation_matrix * page.rotation_matrix
    ctm = (Decimal(0), Decimal(0))
    line_join = 0
    stack, operands, paths, points = [], [], [], []
    path_start = None
    path_ctm = None
    allowed = {b'G', b'g', b'J', b'j', b'w', b'M', b'd', b'gs', b'i',
               b'CS', b'cs', b'SCN', b'scn'}
    for token in lex_content_stream(data):
        raw = data[token.start:token.end]
        assert token.kind not in (TokenKind.MALFORMED, TokenKind.INLINE_IMAGE_DATA)
        if token.kind in (TokenKind.WHITESPACE, TokenKind.COMMENT):
            continue
        if token.kind != TokenKind.OPERATOR:
            operands.append((token, raw))
            continue
        if raw == b'q':
            assert path_start is None
            stack.append((ctm, line_join))
        elif raw == b'Q':
            assert path_start is None and stack
            ctm, line_join = stack.pop()
        elif raw == b'cm':
            assert path_start is None
            values = [Decimal(v.decode('ascii')) for _, v in operands]
            assert values[:4] == [1, 0, 0, 1], values
            ctm = (ctm[0] + values[4], ctm[1] + values[5])
        elif raw in (b'm', b'l', b'c', b're', b'h'):
            if path_start is None:
                assert raw in (b'm', b're')
                path_start = operands[0][0].start
                path_ctm = ctm
            assert path_ctm == ctm
            values = [float(v) for _, v in operands]
            if raw == b're':
                x, y, w, h = values
                values = [x, y, x + w, y + h]
            for x, y in zip(values[::2], values[1::2]):
                points.append(fitz.Point(x + float(ctm[0]), y + float(ctm[1])) * matrix)
        elif raw in (b'S', b's', b'f', b'f*'):
            assert path_start is not None and points
            rect = (min(p.x for p in points), min(p.y for p in points),
                    max(p.x for p in points), max(p.y for p in points))
            owner = next(((a, x) for a, b, x in spans
                          if a <= path_start and token.end <= b), None)
            paths.append({'start': path_start, 'end': token.end, 'rect': rect,
                          'ctm': ctm, 'line_join': line_join, 'owner': owner,
                          'bytes': data[path_start:token.end]})
            path_start, path_ctm, points = None, None, []
        else:
            assert raw in allowed and path_start is None, raw
            if raw == b'j':
                line_join = int(operands[0][1])
        operands = []
    assert not stack and path_start is None
    return paths


def replacement(doc, xref, start, end, payload):
    data = doc.xref_stream(xref)
    return StreamReplacement(xref, start, end, data[start:end], payload,
                             hashlib.sha256(data).hexdigest())


def vector_patches(doc, key):
    page = doc[0]
    paths = vector_paths(doc)
    patches, records, masks, crops = {}, [], [], []
    inverse = ~(page.transformation_matrix * page.rotation_matrix)
    for label, crop, edits in VECTOR_CASES[key]:
        record = {'label': label, 'method': 'source_vector_translation', 'glyphs': []}
        for target, donor, delta in edits:
            old = [p for p in paths if contains(target, p['rect'])]
            borrow = [p for p in paths if contains(donor, p['rect'])]
            assert old and borrow, (label, len(old), len(borrow))
            old_draws, donor_draws = selected_drawings(page, target), selected_drawings(page, donor)
            # Same native paint style; no font-name inference is involved.
            for attr in ('type', 'color', 'fill', 'width', 'lineCap', 'lineJoin',
                         'fill_opacity', 'stroke_opacity'):
                assert {repr(d[attr]) for d in old_draws} == {repr(d[attr]) for d in donor_draws}, attr
            shift = fitz.Point(delta) * inverse - fitz.Point(0, 0) * inverse
            last = old[-1]
            payload = b'n\n'
            for p in borrow:
                dx = float(p['ctm'][0] - last['ctm'][0]) + shift.x
                dy = float(p['ctm'][1] - last['ctm'][1]) + shift.y
                payload += f"q {p['line_join']} j 1 0 0 1 {dx:.8f} {dy:.8f} cm\n".encode('ascii') + p['bytes'] + b'\nQ\n'
            for p in old:
                assert p['owner'] is not None, 'Selected path crosses a stream; refuse, never split it.'
                base, xref = p['owner']
                patch = replacement(doc, xref, p['start'] - base, p['end'] - base,
                                    payload if p is last else b'n')
                patches.setdefault(xref, []).append(patch)
            masks.append(glyph_union(target, donor, delta) + (-0.8, -0.8, 0.8, 0.8))
            record['glyphs'].append({'target_visual': target, 'donor_visual': donor,
                                     'translation_visual': delta, 'removed_paths': len(old),
                                     'donor_paths': len(borrow),
                                     'donor_path_sha256': [hashlib.sha256(p['bytes']).hexdigest() for p in borrow]})
        records.append(record)
        crops.append((label, fitz.Rect(crop)))
    return patches, records, masks, crops


def resolve_text_cases(doc):
    reg = DocumentFontRegistry(doc)
    resolved = []
    for seq, old, new in TEXT_CASES:
        if old is None:
            show = shows(doc, 0)[seq]
            old = reg.capability(doc[0], show.font_resource).cid.decode_show_bytes(show.decoded_bytes)
            assert hashlib.sha256(old.encode('utf-8')).hexdigest() == TEXT_CASE_SHA256[seq], seq
        resolved.append((seq, old, new))
    return tuple(resolved)


def text_patches(doc):
    page = doc[0]
    reg = DocumentFontRegistry(doc)
    patches, records, masks, crops = {}, [], [], []
    for seq, old, new in TEXT_CASES:
        show = shows(doc, 0)[seq]
        cap = reg.capability(page, show.font_resource)
        assert cap.cid is not None and cap.cid.decode_show_bytes(show.decoded_bytes) == old
        cid = cap.cid
        codes = cid.encode_strict(new)
        assert not isinstance(codes, CidCapabilityFailure), codes
        assert cid.glyph_gate(codes, new) is None
        old_codes = tuple(int.from_bytes(show.decoded_bytes[i:i + 2], 'big')
                          for i in range(0, len(show.decoded_bytes), 2))
        delta = cid.advance_points(codes, show.font_size, show.char_spacing) - cid.advance_points(
            old_codes, show.font_size, show.char_spacing)
        kern = delta * 1000 / show.font_size
        encoded = encode_hex_string(cid.encode_cids(codes))
        assert show.operator == 'Tj' and show.string_kind == 'hex' and show.word_spacing == 0
        if abs(kern) < 1e-8:
            start, end, payload = show.string_start, show.string_end, encoded
        else:
            start, end = show.op_start, show.op_end
            payload = b'[' + encoded + f' {kern:.10f}'.encode('ascii') + b'] TJ'
        patches.setdefault(show.stream_xref, []).append(replacement(doc, show.stream_xref, start, end, payload))
        trace = trace_for(page, show, old)
        rect = fitz.Rect(trace['bbox']) * page.rotation_matrix
        # Actual before/after union is computed after reopening.
        crops.append((f'{old} -> {new}', rect))
        records.append({'method': 'original_type0_cid', 'seq': seq, 'before': old, 'after': new,
                        'font': trace['font'], 'font_xref': cap.font_xref,
                        'font_resource': show.font_resource, 'Tf': show.font_size,
                        'Tm': show.tm, 'CTM': show.ctm, 'Tz': show.hscale,
                        'Tc': show.char_spacing, 'Tw': show.word_spacing,
                        'TJ_compensation': kern, 'replacement_operator': payload.decode('ascii')})
    return patches, records, masks, crops


def verify_resources(source, candidate, patches):
    changed = []
    for xref in range(1, source.xref_length()):
        if xref in patches:
            expected = splice_stream(source.xref_stream(xref), patches[xref])
            assert candidate.xref_stream(xref) == expected, xref
            changed.append(xref)
        elif source.xref_is_stream(xref):
            assert source.xref_stream(xref) == candidate.xref_stream(xref), xref
        else:
            assert source.xref_object(xref) == candidate.xref_object(xref), xref
    for xref in range(source.xref_length(), candidate.xref_length()):
        assert candidate.xref_get_key(xref, 'Type') == ('name', '/XRef'), xref
    return {'changed_streams': changed, 'unchanged_existing_objects': source.xref_length() - 1 - len(changed)}


def save_comparison(source, candidate, key, crops, masks, out):
    pairs, stats = [], []
    if key == 'ecc':
        for i, (seq, _, new) in enumerate(TEXT_CASES):
            trace = trace_for(candidate, shows(candidate.parent, 0)[seq], new)
            rect = (crops[i][1] | fitz.Rect(trace['bbox']) * candidate.rotation_matrix) + (-2, -2, 2, 2)
            crops[i] = (crops[i][0], rect)
            masks.append(rect)
    for i, (label, rect) in enumerate(crops, 1):
        before, after = render(source, 8, rect), render(candidate, 8, rect)
        changed = int(np.any(np.array(before) != np.array(after), axis=2).sum())
        assert changed > 0, (key, label)
        before.save(out / f'{key}-{i:02}-before.png')
        after.save(out / f'{key}-{i:02}-after.png')
        pairs.append((before, after))
        stats.append({'label': label, 'crop_visual': list(rect), 'changed_pixels_8x': changed})
    a, b = np.array(render(source, 3)), np.array(render(candidate, 3))
    diff = np.any(a != b, axis=2)
    total = int(diff.sum())
    for rect in masks:
        r = (rect * fitz.Matrix(3, 3)).irect
        diff[max(0, r.y0):r.y1, max(0, r.x0):r.x1] = False
    outside = int(diff.sum())
    assert outside == 0, (key, 'pixels outside target', outside)
    width = max(a.width for a, _ in pairs) + 30
    heights = [max(a.height, b.height) + 45 for a, b in pairs]
    sheet = Image.new('RGB', (width * 2, sum(heights) + 35), '#e9edf2')
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), 'BEFORE - original PDF', fill='black')
    draw.text((width + 12, 10), 'AFTER - source glyphs retained', fill='black')
    y = 35
    for i, ((a, b), h) in enumerate(zip(pairs, heights), 1):
        draw.text((12, y), f'{key.upper()} case {i} / 8x PDF render', fill='black')
        sheet.paste(a, (12, y + 25))
        sheet.paste(b, (width + 12, y + 25))
        y += h
    sheet.save(out / f'{key}-comparison.png')
    return {'cases': stats, 'total_changed_pixels_3x': total,
            'outside_target_changed_pixels_3x': outside}


def verify_poppler(source, candidate, key, masks, crops, out):
    exe = shutil.which('pdftoppm')
    if exe is None:
        return {'status': 'not_run', 'reason': 'pdftoppm unavailable'}
    arrays = []
    for tag, path in [('before', source), ('after', candidate)]:
        prefix = out / f'{key}-poppler-{tag}'
        subprocess.run([exe, '-r', '216', '-f', '1', '-singlefile', '-png',
                        str(path), str(prefix)], check=True, capture_output=True)
        with Image.open(prefix.with_suffix('.png')) as img:
            arrays.append(np.array(img.convert('RGB')))
    diff = np.any(arrays[0] != arrays[1], axis=2)
    for _, crop in crops:
        r = (crop * fitz.Matrix(3, 3)).irect
        assert np.any(diff[r.y0:r.y1, r.x0:r.x1]), (key, 'Poppler unchanged target')
    total = int(diff.sum())
    for rect in masks:
        r = (rect * fitz.Matrix(3, 3)).irect
        diff[max(0, r.y0):r.y1, max(0, r.x0):r.x1] = False
    outside = int(diff.sum())
    assert outside == 0, (key, 'Poppler outside target', outside)
    return {'status': 'passed', 'dpi': 216, 'total_changed_pixels': total,
            'outside_target_changed_pixels': outside}


def run(args):
    global TEXT_CASES
    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    for key, name in FILES.items():
        path = args.fixtures / name
        original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        assert original_hash == SOURCE_HASHES[key], 'Fixture changed: manually reselect targets and donors.'
        output = args.output / f'{key}-edited.pdf'
        assert output.resolve() != path.resolve()
        with fitz.open(path) as source:
            if key == 'ecc':
                TEXT_CASES = resolve_text_cases(source)
            patches, records, masks, crops = text_patches(source) if key == 'ecc' else vector_patches(source, key)
            print(key, 'preflight ready', flush=True)
            if not args.verify_only:
                shutil.copyfile(path, output)
                with fitz.open(output) as candidate:
                    for xref, replacements in patches.items():
                        candidate.update_stream(xref, splice_stream(candidate.xref_stream(xref), replacements), compress=True)
                    candidate.saveIncr()
            with fitz.open(output) as candidate:
                src_page, dst_page = source[0], candidate[0]
                if key == 'ecc':
                    verify_text(src_page, dst_page)
                else:
                    verify_vectors(src_page, dst_page, VECTOR_CASES[key])
                    assert not dst_page.get_fonts() and not dst_page.get_text()
                resources = verify_resources(source, candidate, patches)
                visual = save_comparison(src_page, dst_page, key, crops, masks, args.output)
                poppler = verify_poppler(path, output, key, masks, crops, args.output)
                render(dst_page, 1.3).save(args.output / f'{key}-edited.png')
                reports.append({'file': name, 'output': output.name, 'source_sha256': original_hash,
                                'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                                'font_resources': src_page.get_fonts(full=True), 'edits': records,
                                'resources': resources, 'visual': visual, 'poppler': poppler})
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
        print(key, 'VERIFIED', resources, visual['outside_target_changed_pixels_3x'], flush=True)
    (args.output / 'results.json').write_text(json.dumps({'pymupdf_version': fitz.VersionBind,
        'typesafe_inference_used': False, 'reports': reports}, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, default=Path('test_files'))
    parser.add_argument('--output', type=Path, default=Path('output/pdf/cad-font-study'))
    parser.add_argument('--verify-originals', action='store_true')
    parser.add_argument('--verify-only', action='store_true', help='Verify saved candidates without rewriting PDFs.')
    parser.add_argument('--only', choices=tuple(FILES), help='Rerun one fixture after a scoped change.')
    args = parser.parse_args()
    if args.verify_originals:
        failures = []
        for key, name in FILES.items():
            with fitz.open(args.fixtures / name) as source:
                try:
                    if key == 'ecc':
                        verify_text(source[0], source[0])
                    else:
                        verify_vectors(source[0], source[0], VECTOR_CASES[key])
                except AssertionError as exc:
                    failures.append(key)
                    print(key, 'EXPECTED FAILURE:', exc, flush=True)
        assert len(failures) == 3, failures
        raise SystemExit(1)
    if args.only:
        name = FILES[args.only]
        FILES.clear()
        FILES[args.only] = name
    run(args)


if __name__ == '__main__':
    main()

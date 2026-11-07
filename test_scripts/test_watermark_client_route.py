from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from test_scripts.test_render_process_client import ready_client, source, job, finish_image
from test_scripts.test_watermark_worker_route import recipe


@pytest.mark.parametrize('ack', ['correct', 'missing', 'wrong'])
def test_client_freezes_and_checks_overlay_readiness(qapp, ack):
    client = ready_client(qapp)
    try:
        overlay = recipe().encode()
        document = replace(source(), watermarks_json=overlay)
        outcomes = []
        client.job_done.connect(lambda token, result: outcomes.append(result.status))
        client.submit(job(client, 'wm', document))
        header = client._process.commands[-1].header
        assert header['type'] == 'load_bytes'
        assert header['watermarks_json'].encode() == overlay
        assert header['overlay_schema'] == 1
        reply = dict(type='doc_ready', doc_key=document.doc_key, page_count=1)
        if ack != 'missing':
            reply['overlay_sha256'] = hashlib.sha256(overlay).hexdigest() if ack == 'correct' else '0' * 64
        client._process.reply(reply)
        if ack == 'correct':
            assert client._process.commands[-1].header['type'] == 'render'
            finish_image(client, 'wm')
            assert outcomes == ['image']
        else:
            assert outcomes == ['transport_lost']
            assert client.loaded_key is None
    finally:
        client.shutdown()


def test_same_key_changed_overlay_cannot_reuse_loaded_recipe(qapp):
    client = ready_client(qapp)
    try:
        owner = client.register_owner()
        overlay = recipe().encode()
        first = replace(source(), watermarks_json=overlay)
        client.submit(job(client, 'one', first, owner=owner))
        client._process.reply(dict(type='doc_ready', doc_key=first.doc_key, page_count=1,
                                  overlay_sha256=hashlib.sha256(overlay).hexdigest()))
        finish_image(client, 'one')
        changed = replace(first, watermarks_json=overlay.replace(b'Worker', b'Changed'))
        client.submit(job(client, 'two', changed, owner=owner))
        header = client._process.commands[-1].header
        assert header['type'] == 'load_bytes'
        assert header['watermarks_json'].encode() == changed.watermarks_json
    finally:
        client.shutdown()

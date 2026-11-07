from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from scripts.claude_api_tool import ApiError, call_api, read_key, reserve


def test_sonnet_selection_uses_its_own_budget_tariff(tmp_path, monkeypatch):
    from scripts.claude_api_tool import main

    key = tmp_path / 'key.txt'
    key.write_text('secret-value')
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('Return a bounded implementation patch.')
    calls = []

    def respond(key, endpoint, payload):
        calls.append((endpoint, dict(payload)))
        return {'input_tokens': 1000} if 'count' in endpoint else {
            'model': payload['model'], 'stop_reason': 'end_turn', 'usage': {}, 'content': []}

    monkeypatch.setattr('scripts.claude_api_tool.call_api', respond)
    output = tmp_path / 'result.json'
    monkeypatch.setattr('sys.argv', ['tool', '--key-file', str(key), '--prompt-file', str(prompt),
        '--output', str(output), '--ledger', str(tmp_path / 'budget.json'),
        '--model', 'claude-sonnet-5-5', '--max-tokens', '2000'])
    assert main() == 0
    assert all(payload['model'] == 'claude-sonnet-5-5' for _, payload in calls)
    assert json.loads(output.read_text())['reserved_usd'] == pytest.approx(.022)


def test_key_is_not_echoed(tmp_path):
    path = tmp_path / 'key.txt'
    path.write_text(' secret-value\n', encoding='utf-8')
    assert read_key(path) == 'secret-value'


def test_bad_key_is_rejected(tmp_path):
    path = tmp_path / 'key.txt'
    path.write_text('two words', encoding='utf-8')
    with pytest.raises(ApiError, match='single'):
        read_key(path)


def test_http_error_does_not_expose_response_or_key(monkeypatch):
    def fail(*args, **kwargs):
        raise HTTPError('https://api.anthropic.com/v1/messages', 401, 'secret-value', {}, None)
    monkeypatch.setattr('scripts.claude_api_tool.urlopen', fail)
    with pytest.raises(ApiError) as exc:
        call_api('secret-value', 'messages', {})
    assert str(exc.value) == 'Claude API HTTP 401'


def test_request_has_fixed_destination_and_auth(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, *args):
            return b'{"ok": true}'
    def respond(request, **kwargs):
        assert request.full_url == 'https://api.anthropic.com/v1/messages'
        assert request.get_header('X-api-key') == 'secret-value'
        return Response()
    monkeypatch.setattr('scripts.claude_api_tool.urlopen', respond)
    assert call_api('secret-value', 'messages', {}) == {'ok': True}


def test_reservations_survive_and_exhaust_budget(tmp_path):
    ledger = tmp_path / 'ledger.json'
    reserve(ledger, 0.6, 1.0)
    reserve(ledger, 0.3, 1.0)
    with pytest.raises(ApiError, match='budget'):
        reserve(ledger, 0.2, 1.0)
    assert len(json.loads(ledger.read_text())['reservations']) == 2


def test_ledger_lock_fails_closed(tmp_path):
    ledger = tmp_path / 'ledger.json'
    ledger.with_suffix('.lock').touch()
    with pytest.raises(ApiError, match='locked'):
        reserve(ledger, 0.1, 1.0)


def test_reserve_preserves_existing_temporary_neighbor(tmp_path):
    neighbor = tmp_path / 'budget.tmp'
    neighbor.write_text('credential', encoding='utf-8')
    reserve(tmp_path / 'budget.json', 0.1, 1.0)
    assert neighbor.read_text() == 'credential'


def test_main_redacts_console_metadata(tmp_path, monkeypatch, capsys):
    from scripts.claude_api_tool import main
    key = tmp_path / 'key.txt'
    key.write_text('secret-value')
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('Hello')
    monkeypatch.setattr('scripts.claude_api_tool.call_api',
                        lambda k, endpoint, payload: {'input_tokens': 1} if 'count' in endpoint
                        else {'model': 'secret-value', 'usage': {}, 'content': []})
    monkeypatch.setattr('sys.argv', ['tool', '--key-file', str(key), '--prompt-file', str(prompt),
                                   '--output', str(tmp_path / 'result.json'),
                                   '--ledger', str(tmp_path / 'budget.json')])
    assert main() == 0
    assert 'secret-value' not in capsys.readouterr().out


def _run_main(tmp_path, monkeypatch, *, model, max_tokens, extra=()):
    from scripts.claude_api_tool import main

    key = tmp_path / 'key.txt'
    key.write_text('secret-value')
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('Return a bounded implementation patch.')
    ledger = tmp_path / 'budget.json'
    monkeypatch.setattr('sys.argv', ['tool', '--key-file', str(key), '--prompt-file', str(prompt),
        '--output', str(tmp_path / 'result.json'), '--ledger', str(ledger),
        '--model', model, '--max-tokens', str(max_tokens), *extra])
    return main, ledger


def _fake_endpoints(monkeypatch):
    calls = []

    def respond(key, endpoint, payload):
        calls.append(('call_api', endpoint))
        return {'input_tokens': 1000} if 'count' in endpoint else {
            'model': payload['model'], 'stop_reason': 'end_turn', 'usage': {}, 'content': []}

    def stream(key, payload):
        calls.append(('stream_message', payload['max_tokens']))
        return {'model': payload['model'], 'stop_reason': 'end_turn', 'usage': {}, 'content': []}

    monkeypatch.setattr('scripts.claude_api_tool.call_api', respond)
    monkeypatch.setattr('scripts.claude_api_tool.stream_message', stream, raising=False)
    return calls


@pytest.mark.parametrize('limit', [32768, 65536, 131072])
def test_sonnet_accepts_policy_output_tiers_up_to_model_maximum(tmp_path, monkeypatch, limit):
    _fake_endpoints(monkeypatch)
    main, _ = _run_main(tmp_path, monkeypatch, model='claude-sonnet-5-5', max_tokens=limit)
    assert main() == 0
    reserved = json.loads((tmp_path / 'result.json').read_text())['reserved_usd']
    assert reserved == pytest.approx((1000 * 2 + limit * 10) / 1_000_000)


@pytest.mark.parametrize('limit', [0, 131073])
def test_output_limit_outside_model_maximum_is_rejected_before_any_call(tmp_path, monkeypatch, limit):
    calls = _fake_endpoints(monkeypatch)
    main, ledger = _run_main(tmp_path, monkeypatch, model='claude-sonnet-5-5', max_tokens=limit)
    with pytest.raises(ApiError, match='131072'):
        main()
    assert calls == [] and not ledger.exists()


def test_large_output_cannot_silently_reuse_the_default_call_approval(tmp_path, monkeypatch):
    calls = _fake_endpoints(monkeypatch)
    main, ledger = _run_main(tmp_path, monkeypatch, model='claude-opus-5-5', max_tokens=131072)
    with pytest.raises(ApiError, match='per-call budget'):
        main()
    assert not ledger.exists()
    assert all(endpoint == 'messages/count_tokens' for _, endpoint in calls)


@pytest.mark.parametrize('limit,streamed', [(16384, False), (16385, True), (32768, True)])
def test_long_outputs_stream_instead_of_waiting_on_one_90_second_read(
        tmp_path, monkeypatch, limit, streamed):
    calls = _fake_endpoints(monkeypatch)
    main, _ = _run_main(tmp_path, monkeypatch, model='claude-sonnet-5-5', max_tokens=limit)
    assert main() == 0
    sent = [c for c in calls if c != ('call_api', 'messages/count_tokens')]
    assert sent == ([('stream_message', limit)] if streamed else [('call_api', 'messages')])


def _sse(*events):
    lines = []
    for name, data in events:
        lines += [f'event: {name}\n'.encode(), f'data: {json.dumps(data)}\n'.encode(), b'\n']
    return lines


class _Stream:
    def __init__(self, lines):
        self.lines = list(lines)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def readline(self, limit=-1):
        return self.lines.pop(0) if self.lines else b''


_START = ('message_start', {'type': 'message_start', 'message': {
    'id': 'msg_1', 'model': 'claude-sonnet-5-5', 'role': 'assistant', 'content': [],
    'stop_reason': None, 'usage': {'input_tokens': 10, 'output_tokens': 1}}})


def test_stream_message_assembles_the_same_shape_as_a_plain_response(monkeypatch):
    from scripts.claude_api_tool import stream_message

    events = _sse(
        _START,
        ('ping', {'type': 'ping'}),
        ('content_block_start', {'type': 'content_block_start', 'index': 0,
                                 'content_block': {'type': 'thinking', 'thinking': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                 'delta': {'type': 'thinking_delta', 'thinking': 'think '}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                 'delta': {'type': 'signature_delta', 'signature': 'sig'}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
        ('content_block_start', {'type': 'content_block_start', 'index': 1,
                                 'content_block': {'type': 'text', 'text': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 1,
                                 'delta': {'type': 'text_delta', 'text': 'patch '}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 1,
                                 'delta': {'type': 'text_delta', 'text': 'body'}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 1}),
        ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'},
                           'usage': {'output_tokens': 42}}),
        ('message_stop', {'type': 'message_stop'}),
    )
    seen = {}

    def respond(request, **kwargs):
        seen['url'] = request.full_url
        seen['body'] = json.loads(request.data)
        seen['timeout'] = kwargs.get('timeout')
        return _Stream(events)

    monkeypatch.setattr('scripts.claude_api_tool.urlopen', respond)
    result = stream_message('secret-value', {'model': 'claude-sonnet-5-5', 'max_tokens': 32768,
                                             'messages': []})
    assert seen['url'] == 'https://api.anthropic.com/v1/messages'
    assert seen['body']['stream'] is True and seen['body']['max_tokens'] == 32768
    assert seen['timeout'] == 90
    assert result['stop_reason'] == 'end_turn'
    assert result['usage'] == {'input_tokens': 10, 'output_tokens': 42}
    assert result['content'] == [
        {'type': 'thinking', 'thinking': 'think ', 'signature': 'sig'},
        {'type': 'text', 'text': 'patch body'}]


def test_stream_that_ends_early_keeps_partial_text_and_is_marked_incomplete(monkeypatch):
    from scripts.claude_api_tool import stream_message

    events = _sse(
        _START,
        ('content_block_start', {'type': 'content_block_start', 'index': 0,
                                 'content_block': {'type': 'text', 'text': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                 'delta': {'type': 'text_delta', 'text': 'half a patch'}}),
    )
    monkeypatch.setattr('scripts.claude_api_tool.urlopen', lambda request, **kw: _Stream(events))
    result = stream_message('secret-value', {'max_tokens': 32768})
    assert result['stop_reason'] == 'stream_incomplete'
    assert result['content'][0]['text'] == 'half a patch'


def test_stream_error_event_does_not_expose_the_server_message(monkeypatch):
    from scripts.claude_api_tool import stream_message

    events = _sse(_START, ('error', {'type': 'error', 'error': {
        'type': 'overloaded_error', 'message': 'secret-value leaked'}}))
    monkeypatch.setattr('scripts.claude_api_tool.urlopen', lambda request, **kw: _Stream(events))
    with pytest.raises(ApiError) as exc:
        stream_message('secret-value', {'max_tokens': 32768})
    assert 'secret-value' not in str(exc.value)
    assert 'overloaded_error' in str(exc.value)


def test_stream_without_any_message_is_a_failure_not_an_empty_success(monkeypatch):
    from scripts.claude_api_tool import stream_message

    monkeypatch.setattr('scripts.claude_api_tool.urlopen', lambda request, **kw: _Stream([]))
    with pytest.raises(ApiError, match='stream'):
        stream_message('secret-value', {'max_tokens': 32768})


def test_stream_http_error_does_not_expose_response_or_key(monkeypatch):
    from scripts.claude_api_tool import stream_message

    def fail(*args, **kwargs):
        raise HTTPError('https://api.anthropic.com/v1/messages', 429, 'secret-value', {}, None)
    monkeypatch.setattr('scripts.claude_api_tool.urlopen', fail)
    with pytest.raises(ApiError) as exc:
        stream_message('secret-value', {'max_tokens': 32768})
    assert str(exc.value) == 'Claude API HTTP 429'


def _reserved(tmp_path, monkeypatch, *, model, input_tokens, max_tokens, extra=()):
    monkeypatch.setattr('scripts.claude_api_tool.call_api',
                        lambda key, endpoint, payload: {'input_tokens': input_tokens}
                        if 'count' in endpoint else
                        {'model': payload['model'], 'stop_reason': 'end_turn', 'usage': {}, 'content': []})
    monkeypatch.setattr('scripts.claude_api_tool.stream_message',
                        lambda key, payload: {'model': payload['model'], 'stop_reason': 'end_turn',
                                              'usage': {}, 'content': []})
    main, ledger = _run_main(tmp_path, monkeypatch, model=model, max_tokens=max_tokens, extra=extra)
    assert main() == 0
    return json.loads((tmp_path / 'result.json').read_text())['reserved_usd']


@pytest.mark.parametrize('model,input_tokens,per_mtok', [
    ('claude-fable-5-1', 1000, (10, 50)),
    ('claude-haiku-5-5', 1000, (0.10, 0.50)),
    ('claude-haiku-5-5', 100_000, (0.10, 0.50)),
    ('claude-haiku-5-5', 100_001, (0.50, 2.50)),
])
def test_fable_and_haiku_are_priced_with_their_own_tariff(
        tmp_path, monkeypatch, model, input_tokens, per_mtok):
    reserved = _reserved(tmp_path, monkeypatch, model=model, input_tokens=input_tokens,
                         max_tokens=2000)
    assert reserved == pytest.approx(
        (input_tokens * per_mtok[0] + 2000 * per_mtok[1]) / 1_000_000)


def test_fable_full_output_needs_an_explicit_call_limit(tmp_path, monkeypatch):
    calls = _fake_endpoints(monkeypatch)
    main, ledger = _run_main(tmp_path, monkeypatch, model='claude-fable-5-1', max_tokens=131072)
    with pytest.raises(ApiError, match='per-call budget'):
        main()
    assert not ledger.exists()
    assert all(endpoint == 'messages/count_tokens' for _, endpoint in calls)


def test_fable_full_output_runs_once_the_owner_raises_the_limit(tmp_path, monkeypatch):
    reserved = _reserved(tmp_path, monkeypatch, model='claude-fable-5-1', input_tokens=1000,
                         max_tokens=131072, extra=('--call-limit-usd', '8'))
    assert reserved == pytest.approx((1000 * 10 + 131072 * 50) / 1_000_000)

from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from scripts.claude_api_tool import ApiError, call_api, read_key, reserve


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

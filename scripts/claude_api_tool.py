from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


# Standard USD/MTok, checked against official model pages 2026-11-07.
# No caching, paid tools, geo premium or provider alternatives are enabled.
# Each model lists (largest prompt in tokens for the tier or None, input, output); Haiku 5.5
# bills prompts over 100,000 tokens at the higher tier.
MODEL_PRICES = {
    'claude-opus-5-5': ((None, 4, 20),),
    'claude-sonnet-5-5': ((None, 2, 10),),
    'claude-fable-5-1': ((None, 10, 50),),
    'claude-haiku-5-5': ((100_000, 0.10, 0.50), (None, 0.50, 2.50)),
}


def price_for(model: str, input_tokens: int) -> tuple[float, float]:
    for limit, input_price, output_price in MODEL_PRICES[model]:
        if limit is None or input_tokens <= limit:
            return input_price, output_price
    raise ApiError('No price tier for prompt size')


# Synchronous Messages API output maximum of both selectable models (official model pages, 2026-11-07).
MAX_OUTPUT_TOKENS = 131_072
# Above this, one non-streaming request can outlast the 90 s read timeout (billed, no result) and
# the API guidance is to stream long outputs; the final Message shape is rebuilt locally.
STREAM_ABOVE_TOKENS = 16_384
MAX_RESPONSE_BYTES = 8_000_000


class ApiError(Exception):
    """A diagnostic safe to print without credentials or remote response bodies."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


urlopen = build_opener(NoRedirect()).open


def read_key(path: Path) -> str:
    key = path.read_text(encoding='utf-8-sig').strip()
    if not key or any(char.isspace() for char in key):
        raise ApiError('Key file must contain a single nonempty token')
    return key


def call_api(key: str, endpoint: str, payload: dict) -> dict:
    if endpoint not in ('messages', 'messages/count_tokens'):
        raise ApiError('Unsupported endpoint')
    request = Request(
        'https://api.anthropic.com/v1/' + endpoint,
        data=json.dumps(payload).encode('utf-8'),
        headers={'x-api-key': key, 'anthropic-version': '2023-06-01',
                 'content-type': 'application/json'},
        method='POST',
    )
    try:
        with urlopen(request, timeout=90) as response:
            raw = response.read(8_000_001)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ApiError('Response too large; request may have been billed')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except HTTPError as exc:
        raise ApiError(f'Claude API HTTP {exc.code}') from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ApiError('Claude API transport/response failure; no automatic retry') from None


def _apply_delta(block: dict, delta: dict) -> None:
    kind = delta.get('type')
    if kind == 'text_delta':
        block['text'] = block.get('text', '') + delta.get('text', '')
    elif kind == 'thinking_delta':
        block['thinking'] = block.get('thinking', '') + delta.get('thinking', '')
    elif kind == 'signature_delta':
        block['signature'] = delta.get('signature', '')
    elif kind == 'input_json_delta':
        block['partial_json'] = block.get('partial_json', '') + delta.get('partial_json', '')


def stream_message(key: str, payload: dict) -> dict:
    """POST a streaming Messages request and rebuild the plain response object.

    Partial output is returned with stop_reason 'stream_incomplete' rather than discarded,
    because the request has already been billed.
    """
    request = Request(
        'https://api.anthropic.com/v1/messages',
        data=json.dumps({**payload, 'stream': True}).encode('utf-8'),
        headers={'x-api-key': key, 'anthropic-version': '2023-06-01',
                 'content-type': 'application/json'},
        method='POST',
    )
    message: dict | None = None
    blocks: dict[int, dict] = {}
    finished = False
    received = 0
    try:
        with urlopen(request, timeout=90) as response:
            while True:
                line = response.readline(1_000_001)
                if not line:
                    break
                received += len(line)
                if received > MAX_RESPONSE_BYTES or len(line) > 1_000_000:
                    raise ApiError('Response too large; request may have been billed')
                text = line.decode('utf-8').strip()
                if not text.startswith('data:'):
                    continue
                event = json.loads(text[5:])
                kind = event.get('type')
                if kind == 'message_start':
                    message = dict(event['message'])
                elif kind == 'content_block_start':
                    blocks[event['index']] = dict(event['content_block'])
                elif kind == 'content_block_delta':
                    _apply_delta(blocks[event['index']], event['delta'])
                elif kind == 'message_delta' and message is not None:
                    message.update({k: v for k, v in event.get('delta', {}).items()})
                    message['usage'] = {**message.get('usage', {}), **event.get('usage', {})}
                elif kind == 'message_stop':
                    finished = True
                    break
                elif kind == 'error':
                    raise ApiError('Claude API stream error: ' + str(
                        event.get('error', {}).get('type', 'unknown')))
    except ApiError:
        raise
    except HTTPError as exc:
        raise ApiError(f'Claude API HTTP {exc.code}') from None
    except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        if message is None:
            raise ApiError('Claude API transport/response failure; no automatic retry') from None
    if message is None:
        raise ApiError('Claude API stream returned no message; request may have been billed')
    message['content'] = [blocks[index] for index in sorted(blocks)]
    if not finished:
        message['stop_reason'] = 'stream_incomplete'
    return message


def reserve(ledger: Path, amount: float, total_limit: float) -> str:
    if not all(math.isfinite(v) and v > 0 for v in (amount, total_limit)):
        raise ApiError('Invalid budget')
    ledger.parent.mkdir(parents=True, exist_ok=True)
    lock = ledger.with_suffix('.lock')
    try:
        handle = lock.open('x')
    except FileExistsError:
        raise ApiError('Budget ledger locked; inspect previous run before continuing') from None
    try:
        with handle:
            data = json.loads(ledger.read_text()) if ledger.exists() else {'reservations': []}
            entries = data['reservations']
            spent = sum(float(entry['reserved_usd']) for entry in entries)
            if not math.isfinite(spent) or spent < 0 or spent + amount > total_limit:
                raise ApiError('Local budget exhausted')
            token = uuid.uuid4().hex
            entries.append({'id': token, 'reserved_usd': amount, 'time': time.time()})
            temporary = ledger.with_name(ledger.name + '.' + uuid.uuid4().hex + '.tmp')
            with temporary.open('x', encoding='utf-8') as output:
                output.write(json.dumps(data, indent=2))
            try:
                temporary.replace(ledger)
            finally:
                temporary.unlink(missing_ok=True)
            return token
    finally:
        lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description='Bounded development-only Claude review call')
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--prompt-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True,
                        help='Reuse ONE ledger across all calls; reservations are never refunded')
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--model', choices=tuple(MODEL_PRICES), default='claude-opus-5-5')
    parser.add_argument('--call-limit-usd', type=float, default=2.0)
    args = parser.parse_args()
    if not 1 <= args.max_tokens <= MAX_OUTPUT_TOKENS:
        raise ApiError(f'max-tokens must be 1..{MAX_OUTPUT_TOKENS}')
    if not math.isfinite(args.call_limit_usd) or not 0 < args.call_limit_usd <= 10:
        raise ApiError('call-limit-usd must be positive and at most 10')
    key = read_key(args.key_file)
    paths = [args.output.resolve(), args.ledger.resolve()]
    if len(set(paths + [args.key_file.resolve(), args.prompt_file.resolve()])) != 4:
        raise ApiError('Key, prompt, output and ledger paths must be distinct')
    if args.output.exists():
        raise ApiError('Output exists; choose a new output file')
    prompt = args.prompt_file.read_text(encoding='utf-8-sig')
    if not prompt.strip() or key in prompt or len(prompt.encode('utf-8')) > 500_000:
        raise ApiError('Prompt empty, oversized or contains credential')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {'model': args.model,
               'messages': [{'role': 'user', 'content': prompt}]}
    count = call_api(key, 'messages/count_tokens', payload)['input_tokens']
    if not isinstance(count, int) or count < 0:
        raise ApiError('Invalid input token count')
    input_price, output_price = price_for(args.model, count)
    upper_cost = (count * input_price + args.max_tokens * output_price) / 1_000_000
    if upper_cost > args.call_limit_usd:
        raise ApiError('Request exceeds per-call budget')
    reservation = reserve(args.ledger, upper_cost, 200.0)
    payload['max_tokens'] = args.max_tokens
    if args.max_tokens > STREAM_ABOVE_TOKENS:
        result = stream_message(key, payload)
    else:
        result = call_api(key, 'messages', payload)
    record = {'reservation': reservation, 'reserved_usd': upper_cost,
              'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'response': result}
    # Never persist or print a credential, even if unexpectedly echoed by the server.
    serialized = json.dumps(record, ensure_ascii=False, indent=2).replace(key, '[REDACTED]')
    with args.output.open('x', encoding='utf-8') as output:
        output.write(serialized)
    result = json.loads(serialized)['response']
    print(json.dumps({'ok': True, 'model': result.get('model'),
                      'stop_reason': result.get('stop_reason'), 'usage': result.get('usage'),
                      'reserved_usd': upper_cost}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, TypeError):
        # No traceback: local paths and transport diagnostics may contain secrets.
        print('Claude call failed; inspect configuration/status. No automatic retry.', file=sys.stderr)
        sys.exit(1)

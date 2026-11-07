from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> None:
    # One bounded history batch; no Qt, document loading, or user code execution.
    data = sys.stdin.buffer.readline(1024 * 1024)
    paths = json.loads(data)
    if not isinstance(paths, list) or len(paths) > 10:
        raise ValueError('invalid recent-file batch')
    for index, path in enumerate(paths):
        if not isinstance(path, str) or len(path) > 32768:
            raise ValueError('invalid recent-file path')
        try:
            available = Path(path).is_file()
        except OSError:
            available = False
        print(json.dumps([index, available]), flush=True)


if __name__ == '__main__':
    main()

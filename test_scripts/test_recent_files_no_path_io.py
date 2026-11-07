from __future__ import annotations

import os
from pathlib import Path

import pytest

from utils.preferences import UserPreferences


class Store:
    def __init__(self, paths):
        self.paths = paths

    def value(self, key, default=None, type=None):  # noqa: A002
        return self.paths if key == 'files/recent' else default

    def setValue(self, key, value):
        assert key == 'files/recent'
        self.paths = value


@pytest.mark.parametrize('operation', ['read', 'add', 'remove'])
def test_recent_path_bookkeeping_does_not_resolve_filesystem(monkeypatch, operation):
    """A stale mapped drive must not be contacted merely to sort the menu."""
    source = os.path.abspath(os.path.join('recent-fixture', 'subdir', '..', 'one.pdf'))
    prefs = UserPreferences(Store([source, source]))

    def forbidden(*args, **kwargs):
        raise AssertionError('recent menu contacted filesystem via Path.resolve')

    monkeypatch.setattr(Path, 'resolve', forbidden)
    if operation == 'read':
        assert prefs.get_recent_files() == [os.path.normpath(source)]
    elif operation == 'add':
        # Use a non-temp path, independent of the checkout/test Temp roots.
        path = os.path.join(os.path.abspath(os.sep), 'recent-fixture', 'two.pdf')
        assert prefs.add_recent_file(path)
        assert prefs.get_recent_files()[0] == path
    else:
        assert prefs.remove_recent_file(source)
        assert prefs.get_recent_files() == []

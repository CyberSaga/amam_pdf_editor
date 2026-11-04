"""Shared environment hygiene for pytest subprocesses.

Any variable in :data:`PYTEST_ENV_BLOCKLIST` can make a child pytest skip files,
filter tests or load foreign plugins silently, so a gate or the suite runner
could exit 0 without running the required set.  ``scripts/verify_no_jump.py``
and ``scripts/run_suite.py`` both build their child environment here.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping

logger = logging.getLogger(__name__)

PYTEST_ENV_BLOCKLIST: frozenset[str] = frozenset(
    {
        "PYTEST_ADDOPTS",  # can add -k/--ignore/--co and narrow collection silently
        "PYTEST_PLUGINS",  # can disable or inject plugins
        "PYTEST_CURRENT_TEST",  # leftover from a previous run, can confuse fixtures
    }
)


def clean_pytest_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a copy of *base* (default ``os.environ``) without the blocklisted vars.

    The input mapping is never mutated.
    """
    source = os.environ if base is None else base
    env = dict(source)
    for var in PYTEST_ENV_BLOCKLIST:
        if var in env:
            logger.warning("removing %s from the pytest subprocess env (value: %r)", var, env.pop(var))
    return env

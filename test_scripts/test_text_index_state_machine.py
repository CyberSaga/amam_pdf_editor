"""Card A6.4, class check for the text job state machine (controller + coordinator + stub runner).

Every text bug of the A6.4 reviews was an interleaving of the same state: a request (prewarm or
click), an edit, a delivery (ready / stale / failure), a cancel.  So the check is on outcomes, over
sequences of events, not on one hand-picked order:

* exhaustive: every sequence of up to ``EXHAUSTIVE_LENGTH`` events;
* seeded random: ``RANDOM_SEEDS`` sequences of 4..``RANDOM_MAX_LENGTH`` events, ``random.Random(seed)``
  for seed in ``range(RANDOM_SEEDS)`` (a failing seed names its sequence).

After each event and after draining the runner the invariants must hold:

I1 every queued job has exactly one terminal outcome (ready / dropped / failed);
I2 an open (pending) click always has a job of its page waiting, is closed by the terminal event of
   the job that owns it, and is never closed by an event of a job that does not;
I3 an armed inline route belongs to the current handle, is used by at most one inline build, and
   prewarm never builds a child-routed page inline;
I4 a bytes key is built inline at most once per invalidation of its index;
I5 the status text is shown iff a click is pending;
I6 a clean page's index equals ``extract_page_entry`` of the live page.
"""
from __future__ import annotations

import itertools
import random

import fitz
import pytest

from model import table_objects, text_index_jobs
from model.object_requests import TEXT_LOOKUP_PENDING
from model.pdf_model import PDFModel
from model.text_block import extract_page_entry
from test_scripts.qt_teardown import dispose_pdf_view
from test_scripts.test_object_probe import _controller
from test_scripts.test_text_index_gate import FrontStub, _answer_for
from utils import object_probe_platform

POINT = fitz.Point(80, 70)
EXHAUSTIVE_LENGTH = 3
RANDOM_SEEDS = 250
RANDOM_MAX_LENGTH = 7


class World:
    def __init__(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(object_probe_platform, "contained_probe_supported", lambda: True)
        monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)  # every page is child-routed
        self.path = str(tmp_path / "w.pdf")
        with fitz.open() as doc:
            doc.new_page(width=595, height=842).insert_text((72, 72), "hello world", fontsize=12)
            doc.save(self.path)
        self.model = PDFModel()
        self.model.open_pdf(self.path)
        self.view, self.controller, _stub, _log = _controller(qapp, self.model, monkeypatch)
        self.stub = FrontStub()
        self.coord = self.controller._object_probe
        self.coord._runner = self.stub
        self.terminal: list[tuple[str, int]] = []
        self.coord.text_index_ready.connect(lambda p: self.terminal.append(("ready", p)))
        self.coord.probe_dropped.connect(lambda k, p: k == "text" and self.terminal.append(("dropped", p)))
        self.coord.probe_failed.connect(lambda k, p, r: k == "text" and self.terminal.append(("failed", p)))
        self.view.drop_pending_text_click = lambda page=None: self._close("drop")
        self.view.resolve_pending_text_click = lambda page=None: self._close("resolve")
        self.stub_edits = 0
        self._wrap()

    def _wrap_blocks(self) -> None:
        """Count the inline builds; the manager may be a new object after a reopen."""
        w = self
        manager = self.model.block_manager
        if getattr(manager, "_counting", False):
            return
        real_rebuild = manager.rebuild_page

        def rebuild(page_idx, doc):
            key = table_objects.frame_key(w.model, page_idx + 1)
            w.builds[key] = w.builds.get(key, 0) + 1
            if w.in_prewarm:
                w.prewarm_builds.append(
                    (text_index_jobs.is_failed(w.model, key), text_index_jobs.is_slow(w.model, key))
                )
            return real_rebuild(page_idx, doc)

        manager.rebuild_page = rebuild
        manager._counting = True

    def _wrap(self) -> None:
        w = self
        real_add = self.controller._add_inline_route
        real_take = self.controller._take_inline_route

        def add(*a, **k):
            w.route_adds += 1
            return real_add(*a, **k)

        def take(*a, **k):
            used = real_take(*a, **k)
            w.route_takes += bool(used)
            return used

        self.controller._add_inline_route = add
        self.controller._take_inline_route = take

    # ------------------------------------------------------------------ state
    def reset(self) -> None:
        self.coord._jobs.clear()
        self.coord._early.clear()
        self.model.close()
        self.model.open_pdf(self.path)
        self.model.block_manager.clear()
        self._wrap_blocks()
        text_index_jobs._failed_keys(self.model).clear()
        text_index_jobs._slow_keys(self.model).clear()
        c = self.controller
        c._text_inline_routes = None
        c._text_status_message = None
        c._object_status_message = None
        if hasattr(c, "_text_clicks"):
            c._text_clicks.clear()
        s = self.stub
        s.jobs.clear()
        s.order.clear()
        s.front.clear()
        s.promoted.clear()
        s.running = None
        self.terminal.clear()
        self.open = False
        self.owner = None
        self.registered = 0
        self.closed = 0
        self.builds: dict[tuple, int] = {}
        self.invalidations: dict[tuple, int] = {}
        self.in_prewarm = False
        self.prewarm_builds: list[tuple[bool, bool]] = []
        self.route_adds = 0
        self.route_takes = 0
        self.violations: list[str] = []
        self.edit_counter = 0

    def _close(self, how: str) -> None:
        if self.open:
            self.open = False
            self.closed += 1

    def key(self) -> tuple:
        return table_objects.frame_key(self.model, 1)

    def owner_by_bytes(self):
        """The job a click waits on: the pending job of the page's CURRENT bytes if there is one
        (restored bytes match an older job, not the newest), else the newest job of the page."""
        jobs = sorted((jid, self.coord._jobs[jid].key) for jid in self.stub.jobs if jid in self.coord._jobs)
        keys = [key for _jid, key in jobs]
        current = self.key()
        if current in keys:
            return current
        return keys[-1] if keys else None

    # ------------------------------------------------------------------ events
    def prewarm(self):
        self.in_prewarm = True
        try:
            self.controller.request_page_index(1)
        finally:
            self.in_prewarm = False

    def click(self):
        result = self.controller.lookup_text_at_point(1, POINT, allow_fallback=False)
        if result is TEXT_LOOKUP_PENDING:
            if not self.open:
                self.open = True
                self.registered += 1
            self.owner = self.owner_by_bytes()

    def _edit(self, tick: bool):
        self.edit_counter += 1
        self.model.doc[0].insert_text((72, 100 + 20 * self.edit_counter), f"edit {self.edit_counter}", fontsize=12)
        self.model.block_manager.clear()  # an edit leaves the index not clean
        if tick:
            self.model.edit_count = self.model.edit_count

    def edit_tick(self):
        self._edit(True)

    def edit_notick(self):
        self._edit(False)

    def rotate_90(self):
        self.model.rotate_pages([1], 90)
        self.model.block_manager.clear()
        self.model.edit_count = self.model.edit_count
        self.invalidations[self.key()] = self.invalidations.get(self.key(), 0) + 1  # the rotation rebuilt it

    def rotate_back(self):
        self.model.rotate_pages([1], 270)  # rotate_90 then rotate_back restores the earlier bytes
        self.model.block_manager.clear()
        self.model.edit_count = self.model.edit_count
        self.invalidations[self.key()] = self.invalidations.get(self.key(), 0) + 1  # the rotation rebuilt it

    def invalidate(self):
        self.invalidations[self.key()] = self.invalidations.get(self.key(), 0) + 1
        self.model.block_manager.clear()

    def clean_gesture(self):
        self.model.ensure_page_index_built(1)
        self.click()

    def cancel(self):
        self.coord.cancel_all()
        self.stub.jobs.clear()
        self.stub.running = None

    def generation(self):
        original = self.key()
        self.invalidations[original] = self.invalidations.get(original, 0) + 1
        self.cancel()
        self.model.close()
        self.model.open_pdf(self.path)
        self.model.block_manager.clear()
        self._wrap_blocks()
        self.edit_counter = 0

    def _deliver(self, which: str, answer_kind: str):
        ids = sorted(self.stub.jobs)
        if not ids:
            return
        job_id = ids[0] if which == "oldest" else ids[-1]
        job = self.coord._jobs.get(job_id)
        if job is None:
            return
        payload = self.stub.jobs[job_id][2]
        if answer_kind == "ready":
            answer = _answer_for(payload)
        else:
            answer = {"v": 2, "status": answer_kind}
        was_open, owner, before = self.open, self.owner, len(self.terminal)
        self.stub.complete(job_id, answer)
        events = self.terminal[before:]
        self.check_delivery(job, events, was_open, owner)

    def check_delivery(self, job, events, was_open, owner):
        kinds = [e[0] for e in events]
        if len(events) != 1:
            self.violations.append(f"I1 {len(events)} terminal events for one delivery: {kinds}")
            return
        if kinds[0] != "ready" and was_open and self.owner is not None:
            owns = owner == job.key
            if owns and self.open:
                self.violations.append(f"I2 the owner's {kinds[0]} left its click open")
            if not owns and not self.open and self.coord.has_pending_text(job.page_num):
                self.violations.append(f"I2 an event of a non-owner ({kinds[0]}) closed the click")

    def deliver_oldest_ready(self):
        self._deliver("oldest", "ready")

    def deliver_newest_ready(self):
        self._deliver("newest", "ready")

    def deliver_oldest_no_headroom(self):
        self._deliver("oldest", "no_headroom")

    def deliver_newest_no_headroom(self):
        self._deliver("newest", "no_headroom")

    def deliver_newest_resource_limited(self):
        self._deliver("newest", "resource_limited")

    # ------------------------------------------------------------------ invariants
    def check_step(self, name: str) -> None:
        c = self.controller
        if self.open and not self.coord.has_pending_text(1):
            self.violations.append("I2 an open click has no job waiting")
        shown = c._text_status_message is not None
        if shown != self.open:
            self.violations.append(f"I5 status shown={shown}, click open={self.open}")
        gen = self.model.handle_generation
        for route in c._text_inline_routes or ():
            if route[0] != gen:
                self.violations.append("I3 a route of a retired handle is armed")
        if self.route_takes > self.route_adds:
            self.violations.append("I3 a route was used more often than it was armed")
        if any(not (failed or slow) for failed, slow in self.prewarm_builds):
            self.violations.append("I3 prewarm built a child-routed page inline")
        for key, count in self.builds.items():
            if count > 1 + self.invalidations.get(key, 0):
                self.violations.append("I4 a bytes key was built inline twice without an invalidation")
        if self.model.block_manager.page_state(0) == "clean":
            live = extract_page_entry(0, self.model.doc[0])
            bm = self.model.block_manager
            if not (
                tuple(bm.get_blocks(0)) == live.blocks
                and tuple(bm.get_spans(0)) == live.spans
                and tuple(bm.get_paragraphs(0)) == live.paragraphs
                and tuple(bm.get_fallback_rows(0)) == live.fallback_rows
            ):
                self.violations.append("I6 a clean index differs from the live page")

    def drain(self) -> None:
        while self.stub.jobs:
            before = len(self.terminal)
            self._deliver("oldest", "ready")
            if len(self.terminal) == before:  # nothing was delivered: avoid a loop
                break
        if self.open or self.registered != self.closed:
            self.violations.append(f"I2 {self.registered} clicks registered, {self.closed} closed, open={self.open}")
        if len(self.terminal) != len(self.stub.order):
            self.violations.append(f"I1 {len(self.stub.order)} jobs, {len(self.terminal)} terminal events")
        if self.controller._text_status_message is not None:
            self.violations.append("I5 a status text stays after the drain")
        self.check_step("drain")

    def run(self, names: tuple[str, ...]) -> list[str]:
        self.reset()
        for name in names:
            getattr(self, name)()
            self.check_step(name)
        self.drain()
        return self.violations


EVENTS = (
    "prewarm",
    "click",
    "edit_tick",
    "edit_notick",
    "rotate_90",
    "rotate_back",
    "invalidate",
    "deliver_oldest_ready",
    "deliver_newest_ready",
    "deliver_oldest_no_headroom",
    "deliver_newest_no_headroom",
    "deliver_newest_resource_limited",
    "cancel",
    "clean_gesture",
    "generation",
)


@pytest.fixture
def world(qapp, tmp_path, monkeypatch):
    w = World(qapp, monkeypatch, tmp_path)
    yield w
    dispose_pdf_view(w.view, w.controller, w.model)


def _sequences():
    for length in range(1, EXHAUSTIVE_LENGTH + 1):
        yield from itertools.product(EVENTS, repeat=length)
    for seed in range(RANDOM_SEEDS):
        rng = random.Random(seed)
        yield tuple(rng.choice(EVENTS) for _ in range(rng.randint(4, RANDOM_MAX_LENGTH)))


def test_no_sequence_of_events_breaks_an_invariant(world):
    failures: dict[str, tuple[tuple[str, ...], str]] = {}
    count = 0
    for names in _sequences():
        count += 1
        for violation in world.run(names):
            failures.setdefault(violation, (names, violation))
    shown = "\n".join(f"{code}: {' > '.join(names)}: {text}" for code, (names, text) in sorted(failures.items()))
    assert not failures, f"{count} sequences; first sequence per violation:\n{shown}"


def test_the_harness_reaches_its_states(world):
    """Guard against a vacuous check: a click gets pending, is resolved, and a failure closes it."""
    assert world.run(("click", "deliver_oldest_ready")) == []
    assert world.registered == 1 and world.closed == 1 and world.model.block_manager.page_state(0) == "clean"
    assert world.run(("click", "deliver_oldest_no_headroom", "click")) == []
    assert world.registered == 1 and world.route_adds == 1 and world.route_takes == 1
    assert world.run(("prewarm", "click", "edit_tick", "click", "deliver_newest_no_headroom", "deliver_oldest_ready")) == []


def test_a_click_waits_on_the_job_of_the_restored_bytes_not_the_newest_job(world):
    """Astra round 3: prewarm A (0 deg), rotate + prewarm B, rotate back, click: the click is
    A's.  B ends first (stale), A then installs and resolves the click once."""
    assert world.run(("prewarm", "rotate_90", "prewarm", "rotate_back", "click", "deliver_newest_ready")) == []
    assert world.registered == 1 and world.closed == 1
    # the same sequence, driven by hand: B's stale drop does not close the click, A's answer resolves it
    world.reset()
    resolved = []
    world.view.resolve_pending_text_click = lambda page=None: (resolved.append(page), world._close("resolve"))
    world.prewarm()
    world.rotate_90()
    world.prewarm()
    world.rotate_back()
    world.click()
    assert world.open and len(world.stub.order) == 2
    world._deliver("newest", "ready")  # B: stale
    assert world.open and resolved == []
    world._deliver("oldest", "ready")  # A: the page's bytes
    assert resolved == [1] and not world.open
    assert world.model.block_manager.page_state(0) == "clean"

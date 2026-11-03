"""Helper-process print pipeline tests."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import fitz
import pytest

from src.printing.base_driver import PrintJobOptions, PrintJobResult
from src.printing.errors import PrintJobSubmissionError
from src.printing.helper_main import run_print_helper
from src.printing.helper_protocol import PrintHelperJob
from src.printing.messages import (
    PRINT_HELPER_STARTED_MESSAGE,
    PRINT_PREPARING_MESSAGE,
    PRINT_SUBMITTING_MESSAGE,
)


def _make_single_page_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "print helper", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_run_print_helper_emits_success_events(tmp_path: Path) -> None:
    pdf_path = tmp_path / "input.pdf"
    job_path = tmp_path / "job.json"
    _make_single_page_pdf(pdf_path)

    job = PrintHelperJob(
        job_id="job-1",
        input_pdf_path=str(pdf_path),
        watermarks=[],
        options=PrintJobOptions(printer_name="Printer A", job_name="helper job"),
    )
    job_path.write_text(json.dumps(job.to_json_dict(), ensure_ascii=False), encoding="utf-8")

    events: list[dict] = []

    class _Dispatcher:
        def print_pdf_bytes(self, pdf_bytes: bytes, options: PrintJobOptions) -> PrintJobResult:
            assert isinstance(pdf_bytes, bytes)
            assert options.printer_name == "Printer A"
            return PrintJobResult(
                success=True,
                route="helper-test",
                message="Submitted 1 page(s) to printer.",
                job_id="spool-1",
            )

    exit_code = run_print_helper(str(job_path), dispatcher=_Dispatcher(), emit=events.append)

    assert exit_code == 0
    assert [event["event"] for event in events] == ["started", "progress", "progress", "succeeded"]
    assert events[0]["message"] == PRINT_HELPER_STARTED_MESSAGE
    assert events[1]["message"] == PRINT_PREPARING_MESSAGE
    assert events[2]["message"] == PRINT_SUBMITTING_MESSAGE
    assert events[-1]["route"] == "helper-test"
    assert events[-1]["result_job_id"] == "spool-1"


def test_run_print_helper_emits_failed_event_on_dispatch_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "input.pdf"
    job_path = tmp_path / "job.json"
    _make_single_page_pdf(pdf_path)

    job = PrintHelperJob(
        job_id="job-2",
        input_pdf_path=str(pdf_path),
        watermarks=[],
        options=PrintJobOptions(printer_name="Printer A", job_name="helper job"),
    )
    job_path.write_text(json.dumps(job.to_json_dict(), ensure_ascii=False), encoding="utf-8")

    events: list[dict] = []

    class _Dispatcher:
        def print_pdf_bytes(self, _pdf_bytes: bytes, _options: PrintJobOptions) -> PrintJobResult:
            raise PrintJobSubmissionError("driver exploded")

    exit_code = run_print_helper(str(job_path), dispatcher=_Dispatcher(), emit=events.append)

    assert exit_code == 1
    assert events[-1]["event"] == "failed"
    assert events[-1]["error_type"] == "PrintJobSubmissionError"
    assert "driver exploded" in events[-1]["message"]


def test_run_print_helper_emits_heartbeat_during_long_submission(tmp_path: Path) -> None:
    pdf_path = tmp_path / "input.pdf"
    job_path = tmp_path / "job.json"
    _make_single_page_pdf(pdf_path)

    job = PrintHelperJob(
        job_id="job-3",
        input_pdf_path=str(pdf_path),
        watermarks=[],
        options=PrintJobOptions(printer_name="Printer A", job_name="helper job"),
        heartbeat_interval_ms=20,
    )
    job_path.write_text(json.dumps(job.to_json_dict(), ensure_ascii=False), encoding="utf-8")

    events: list[dict] = []

    class _Dispatcher:
        def print_pdf_bytes(self, pdf_bytes: bytes, options: PrintJobOptions) -> PrintJobResult:
            assert isinstance(pdf_bytes, bytes)
            assert options.printer_name == "Printer A"
            time.sleep(0.22)
            return PrintJobResult(
                success=True,
                route="helper-test",
                message="Submitted 1 page(s) to printer.",
                job_id="spool-3",
            )

    exit_code = run_print_helper(str(job_path), dispatcher=_Dispatcher(), emit=events.append)

    assert exit_code == 0
    event_types = [event["event"] for event in events]
    assert "heartbeat" in event_types
    assert event_types[-1] == "succeeded"


@pytest.mark.parametrize("outcome", ("succeeded", "failed"))
def test_a_heartbeat_in_flight_never_lands_after_the_final_event(tmp_path: Path, outcome: str) -> None:
    """The final event is the last line the helper writes: a heartbeat already inside ``emit`` when the
    dispatcher returns must finish before ``succeeded``/``failed`` goes out (TODOS:118 flake, made
    deterministic: the dispatcher returns while the first heartbeat is mid-emit)."""
    pdf_path = tmp_path / "input.pdf"
    job_path = tmp_path / "job.json"
    _make_single_page_pdf(pdf_path)
    job = PrintHelperJob(
        job_id="job-4",
        input_pdf_path=str(pdf_path),
        watermarks=[],
        options=PrintJobOptions(printer_name="Printer A", job_name="helper job"),
        heartbeat_interval_ms=20,
    )
    job_path.write_text(json.dumps(job.to_json_dict(), ensure_ascii=False), encoding="utf-8")

    events: list[dict] = []
    heartbeat_entered = threading.Event()

    def _emit(event: dict) -> None:
        if event["event"] == "heartbeat" and not heartbeat_entered.is_set():
            heartbeat_entered.set()
            time.sleep(0.05)  # the main thread finishes the job meanwhile
        events.append(event)

    class _Dispatcher:
        def print_pdf_bytes(self, pdf_bytes: bytes, options: PrintJobOptions) -> PrintJobResult:
            assert heartbeat_entered.wait(2.0)
            if outcome == "failed":
                raise PrintJobSubmissionError("driver exploded")
            return PrintJobResult(success=True, route="helper-test", message="ok", job_id="spool-4")

    exit_code = run_print_helper(str(job_path), dispatcher=_Dispatcher(), emit=_emit)

    assert exit_code == (0 if outcome == "succeeded" else 1)
    event_types = [event["event"] for event in events]
    assert "heartbeat" in event_types
    assert event_types[-1] == outcome, event_types

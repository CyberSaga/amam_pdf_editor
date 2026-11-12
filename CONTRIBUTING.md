# Contributing to CyberSagaPDF

Thank you for considering a contribution. CyberSagaPDF is a Python desktop PDF
editor with a Qt UI, PyMuPDF-backed document operations, and Windows-first
printing workflows.

## Development Setup

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -r optional-requirements.txt
```

OCR is optional and intentionally separated because it has distinct dependency
and security tradeoffs:

```text
.venv\Scripts\python -m pip install -r ocr-requirements.txt
```

## Run Locally

```text
python main.py
```

## Test

Run one test file while you work:

```text
.venv\Scripts\python -m pytest test_scripts/<file>.py -q
```

Run the whole suite through the supervisor (the same script CI uses). Do not
run `pytest test_scripts/` in a single process: a hung Qt test cannot be ended
from inside it.

```text
.venv\Scripts\python scripts/run_suite.py
```

Check coverage of the files you changed when touching model, controller, or
view behavior:

```text
.venv\Scripts\python -m pytest test_scripts/<file>.py --cov --cov-report=term-missing
```

## Pull Request Expectations

- Keep changes focused and explain the user-visible behavior change.
- Add or update tests for bug fixes and behavior changes.
- Update documentation when changing workflows, dependencies, shortcuts, printing,
  OCR, optimization, or security-relevant behavior.
- Avoid committing private PDFs, local environment files, 
  generated build artifacts, or large test outputs.

## Security-Sensitive Changes

Please call out changes that affect:

- PDF parsing, saving, exporting, or optimization
- File paths, overwrite behavior, or temporary files
- OCR dependencies and model loading
- Image processing
- Printing helper subprocesses
- Dependency floors or security scan findings

For vulnerability reports, use `SECURITY.md`.


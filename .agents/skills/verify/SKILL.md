---
name: verify
description: Drive the real PySide6 app in-process via main.run() with QTest input and capture view.grab() screenshots. Use to confirm a UI or PDF-appearance change in the running app, not just in tests.
---

# Project runtime verification

Use the project venv and launch through the public app entry point:

```python
import main
startup = main.run(argv=[pdf_path], start_event_loop=False)
app, view, model, controller = (
    startup["app"], startup["view"], startup["model"], startup["controller"]
)
view.show()
```

Drive widgets with `PySide6.QtTest.QTest` and pump `app.processEvents()` with condition-based waits. Capture evidence with `view.grab().save(path)`.

## Modal dialogs

Before triggering the QAction/button, schedule a `QTimer.singleShot` callback that finds the visible `QDialog`, selects the intended values, and clicks its button with `QTest.mouseClick`. This works inside `dialog.exec()`'s nested event loop.

## Context menus

Native `QMenu.exec_()` is unreliable under automation. Prefer an equivalent toolbar/dialog user flow when one exists. Do not call View/Controller mutation methods directly for verification.

## Cleanup

Undo dirty mutations through the UI before closing when possible, then:

```python
view.close()
model.close()
app.quit()
```

Keep screenshots under `%TEMP%/pdf_editor_verify_*`; report observed widget state and screenshot paths.

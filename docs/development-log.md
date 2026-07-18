# Development Log (legacy, frozen)

This file is frozen. Do not append new development status here.
Use `docs/development-guide.md` for app development baseline and git history for past work.

---

# Development Log

## 2026-06-17: Phase 3 Dianping Application Consumer

### Completed

- Created `automation-app-dianping` as the second business application
  repository consuming `automation-kit`.
- Added package metadata, local verification configuration, and app-level
  workflow/config tests.
- Added `automation_app_dianping.workflow.create_workflow(...)` to prove the
  public `automation_runner.workflows` surface is not Damai-specific.
- Added `DianpingAppConfig` to keep Dianping domain fields out of the shared
  core.

### Decision Record

#### Decision: keep the second consumer narrower than the first migration

- Problem: this phase needs to prove that a second domain can reuse the same
  public runner contract without importing Damai-specific assumptions.
- Choice: implement a minimal Android-leaning workflow plus a small domain
  config object instead of copying the Damai repository layout wholesale.
- Reason: the acceptance signal for this phase is boundary proof, not feature
  completeness.
- Risk: more Dianping-specific layers will still be needed in later plans.

#### Decision: keep `poetry.lock` after verification

- Problem: the final audit must verify the repository the same way CI will run
  it, not just through manual venv commands.
- Choice: run `poetry install && poetry run pytest -q` and keep the generated
  lockfile.
- Reason: the repository now declares a Poetry-based CI path, so the lockfile
  is part of the reproducible baseline.
- Risk: dependency updates become explicit version-control events.

### Verification

```bash
/Users/mango/project/codex/automation-app-dianping/.venv/bin/python -m pytest -q
```

Result:

```text
3 passed
Total coverage: 100.00%
Required coverage: 80%
```

### Review

Production code quality review outcome:

- Severe issues: none
- Improvement suggestions:
  - add an app-side CLI helper only when the second consumer needs one
  - keep Dianping-specific publishing or scraping flows out of the shared core
- Quality score: 90
- Pass status: pass

### Final Audit Note

- Confirmed the documented Poetry path:
  `poetry install && poetry run pytest -q`.

## 2026-06-18: Slidex Visual Platform Alignment

### Completed

- Documented that future Dianping OCR, captcha, screenshot recognition, and
  manual visual fallback capabilities should be provided by `slidex`.
- Kept the current repository free of visual-platform dependencies because no
  Dianping workflow consumes them yet.

## 2026-06-18: Phase 4 Dianping Slidex Injection Baseline

### Completed

- Added lazy slidex integration helpers in `automation_app_dianping.workflow`:
  - `build_android_screenshot_visual_request(...)`
  - `visual_result_to_workflow_payload(...)`
- Added `describe_optional_capabilities(...)` so Dianping exposes the same
  optional visual capability signal as Damai.
- Extended `create_workflow(...)` with an optional `visual_solver` parameter
  while preserving the offline Android smoke workflow behavior.
- Added app-level compatibility tests for the latest slidex
  `ANDROID_SCREENSHOT_BYTES` request contract and JSON-safe adapter payloads.
- Kept default tests independent from slidex, browsers, devices, and network by
  skipping real slidex checks when slidex is not import-visible.

### Decision Record

#### Decision: model Dianping visual input as Android screenshot bytes

- Problem: Dianping is Android-oriented and does not naturally own a Playwright
  page, so the Damai `PLAYWRIGHT_PAGE` contract would be the wrong default.
- Choice: use `VisionContext.ANDROID_SCREENSHOT_BYTES` with
  `ChallengeType.IMAGE_TEXT` for the app-level helper.
- Reason: this matches the current automation-kit Android session boundary,
  where screenshots are captured as artifacts or bytes before visual
  interpretation.
- Risk: real Appium/ADB integration must later provide actual screenshot bytes
  and decide when OCR versus more specific visual providers are needed.

### Verification

Default offline suite:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
5 passed, 2 skipped
Total coverage: 80.00%
Required coverage: 80%
```

Slidex compatibility slice:

```bash
PYTHONPATH=/Users/mango/project/codex/automation-app-dianping:/Users/mango/project/codex/automation-kit:/Users/mango/project/codex/slidex /opt/homebrew/bin/pytest -q -o addopts='' tests/test_workflow.py -k 'visual_request or visual_result'
```

Result:

```text
2 passed, 3 deselected
```

### Production Code Quality Review

Mode: checkpoint.

Findings: no P0/P1/P2 correctness, boundary, safety, or irreversible operation
issues found in the current diff.

Improvement suggestions:

- Raise default-suite coverage above the 80% floor when the next Dianping
  workflow slice adds real Android behavior.

Quality score: 88/100.

Status: passed.

### Todo Status

- Dianping app-level slidex request helper: done.
- Dianping app-level slidex adapter payload helper: done.
- Default offline test independence: done.
- Real Android screenshot acquisition and visual workflow execution: pending
  future production workflow phase.

### Next Phase Risk

The current helper proves the contract but not a live Appium/ADB screenshot
path. The next Dianping production workflow phase must provide real screenshot
bytes and decide how visual results are reported.

### Follow-Up Hardening

- Added a default-suite fake-module test for the lazy slidex helper paths so
  coverage no longer sits exactly on the 80% threshold.
- Verification:
  - `.venv/bin/python -m pytest -q`: `6 passed, 2 skipped`, total coverage
    `100.00%`
  - slidex compatibility slice remains `2 passed, 4 deselected`

## 2026-06-18: Phase 5 Dianping Live Visual Helper

### Completed

- Added `solve_android_screenshot_visual_challenge(...)` to connect Android
  screenshot bytes, injected slidex visual solver, and workflow payload
  conversion in one production-callable async helper.
- Supported either direct `screenshot_bytes` or a `screenshot_provider` callback
  so future Appium/ADB workflow code owns screenshot acquisition explicitly.
- Added offline tests with fake slidex modules and fake visual solvers, proving
  the helper does not require real Appium, ADB, device, browser, network, or
  slidex installation in the default suite.
- Added a failure-path test so missing screenshot input raises before slidex is
  called.
- Updated README usage guidance for production workflows that already own
  Android screenshot bytes.

### Decision Record

#### Decision: accept screenshot bytes or a callback, not an Appium session

- Problem: the current Dianping app repository does not own a concrete Appium
  session API, but the next visual workflow phase must pass real screenshot
  bytes into slidex.
- Choice: make `solve_android_screenshot_visual_challenge(...)` accept direct
  bytes or a zero-argument provider callback.
- Reason: this completes the visual execution boundary while keeping Appium/ADB
  lifecycle ownership in the future production workflow layer.
- Risk: a later real-device E2E pass must still prove the callback captures the
  expected screen at the correct workflow moment.

### Verification

Focused live-helper slice:

```bash
PYTHONPATH=/Users/mango/project/codex/automation-app-dianping:/Users/mango/project/codex/automation-kit:/Users/mango/project/codex/slidex /opt/homebrew/bin/pytest -q -o addopts='' tests/test_workflow.py -k 'solve_android_screenshot_visual_challenge'
```

Result:

```text
3 passed, 6 deselected
```

Default offline suite:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
8 passed, 3 skipped
Total coverage: 94.59%
Required coverage: 80%
```

### Production Code Quality Review

Mode: checkpoint.

Findings: no P0/P1/P2 correctness, boundary, safety, or irreversible operation
issues found in the current diff.

Improvement suggestions:

- Keep the eventual real Appium/ADB screenshot E2E run opt-in because it
  depends on device state and target app availability.

Quality score: 91/100.

Status: passed.

### Todo Status

- Live Android screenshot visual helper: done.
- Real Appium/ADB screenshot E2E: pending opt-in production validation.

# automation-app-dianping

This repository proves that a second business domain can consume
`automation_runner.workflows` without adding Dianping logic to `automation-kit`.

If Dianping workflows need OCR, captcha solving, screenshot recognition, or
manual visual challenge fallback, those capabilities should come from `slidex`
as an optional application-layer dependency through the helper functions in
`automation_app_dianping.workflow`. Default offline tests do not require
`slidex`, browsers, devices, or network access.

When a production workflow owns Android screenshot bytes, call
`solve_android_screenshot_visual_challenge(...)` with an injected slidex
`VisualChallengeSolver` to build the `ANDROID_SCREENSHOT_BYTES` request, solve
it, and convert the result into workflow payload shapes.

GitHub repository: `https://github.com/dengyie/automation-app-dianping`

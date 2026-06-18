# automation-app-dianping

This repository proves that a second business domain can consume
`automation_runner.workflows` without adding Dianping logic to `automation-kit`.

If Dianping workflows need OCR, captcha solving, screenshot recognition, or
manual visual challenge fallback, those capabilities should come from `slidex`
as an optional application-layer dependency through the helper functions in
`automation_app_dianping.workflow`. Default offline tests do not require
`slidex`, browsers, devices, or network access.

GitHub repository: `https://github.com/dengyie/automation-app-dianping`

# NovelMaster Harness adaptation

Source: https://github.com/necolo007/NovelMaster (MIT)

Ported into VN Script Studio as `app/core/harness/`:

- Multi-role prompts: Architect / Writer / Editor → LN & visual-novel stagecraft
- AI-flavor detectors from `style_checker.py` / shared-standards
- Otaku literacy craft (types as play, not attribute labels)
- Wired into Agent writing skills + HTTP `/api/v1/.../harness/*`

Not ported wholesale: filesystem project_manager pipeline, web-novel platform export, ingredient EPUB crawler.

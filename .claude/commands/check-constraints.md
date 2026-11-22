---
description: Audit the codebase against the non-negotiable constraints before a deploy
---
Check each constraint in CLAUDE.md "Non-negotiable constraints" and report pass/fail with file:line evidence:
1. grep for any AI API hosts or keys (`api.openai.com`, `anthropic`, `generativelanguage`, `OPENAI_API_KEY` used without `base_url=MODEL_BASE_URL`).
2. Confirm the UI renders only `verdict == "supported"` claims in the answer body (trace answer_card → gate).
3. Confirm the quote text shown comes from `Span.text` (DB), never from LLM output.
4. Confirm no arithmetic on extracted values happens in prompts; calc results come from `core/answer/calc.py`.
5. Confirm conflicts and versions are read from the DB at query time (no corpus-wide scan in `core/answer`).
6. Confirm temperature 0 and prompt versions are logged.
7. Confirm nothing serves from Colab (no ngrok/cloudflared/pyngrok in code or notebooks).
8. Confirm the demo corpus uses only fictional names.
Fix any failure, or list it as a blocker.

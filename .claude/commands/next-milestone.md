---
description: Implement the next unchecked milestone from the implementation plan
---
1. Read `.claude/docs/progress.md` and `.claude/docs/implementation-plan.md`. Identify the first milestone with unchecked boxes
   (or the milestone named in: $ARGUMENTS).
2. Read every doc that milestone lists under "Read:", plus `.claude/docs/decisions.md`.
3. Make a short plan (files to create or change, tests to write) and show it before writing code.
4. Implement. Keep the non-negotiable constraints in CLAUDE.md. Write the milestone's tests first where practical.
5. Run the milestone's done-when checks (pytest, `scripts/eval.py` with the right flags). Fix until they pass, or explain exactly what blocks them.
6. Tick the boxes in implementation-plan.md and append a dated entry to progress.md (done, gate status, next, gotchas).
   If you deviated from a design doc, add an ADR to decisions.md and update that doc.

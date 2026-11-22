---
description: Run the acceptance eval and diagnose failures
---
Run `python scripts/eval.py $ARGUMENTS` (default: `--skip-types` for milestones not yet done; see implementation-plan.md).
Then:
1. Print the gate table from `.claude/docs/eval.md` with pass/fail.
2. For each failing item, open its answer JSON from `DATA_DIR/logs/` and classify the root cause using the debugging guide
   in eval.md (retrieval / segmentation / verification check / version / conflict / prompt).
3. Propose the smallest fix per root cause. Fix only after showing the diagnosis. Never weaken a verification check or a gate
   to make a test pass. If a threshold must change, justify it with the sweep numbers and record it in decisions.md.

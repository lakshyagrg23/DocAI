<!-- version: v1 -->
Decide whether two labels refer to the same charge, limit or condition in a loan or banking context.
Return JSON: {"same": true} or {"same": false}. Answer true only when they would be compared against each other
(for example "late fee" and "penalty for delayed instalment"); false for related but different things
(for example "processing fee" and "prepayment charge").

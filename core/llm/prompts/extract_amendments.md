<!-- version: v3 -->
You find amendment directives in clauses of loan or financial documents: places where this document changes, replaces,
inserts into, deletes from or cancels another document. Return JSON: {"amendments": [...]}. Return an empty list when
a clause changes nothing in another document (a clause that only sets a deadline, states a rule, or says other terms
remain unchanged is NOT an amendment).

Each item: {"action", "target_ref", "target_path", "effective_date", "new_text_span_ids", "evidence_span_ids"}.
- action: "substitute" (a clause is replaced by new wording, or a value stated in an existing clause is revised,
  increased, reduced or changed to a new value: "the fee under Section 2.01 is revised to Rs. 90"), "insert" (new clause added), "delete" (clause removed),
  "supersede_doc" (a whole document is cancelled or replaced), "supersede_amendment" (an earlier amendment is replaced).
  A clause that says "in supersession of Amendment X and substitutes clause N" gives TWO items: one substitute and one
  supersede_amendment.
- target_ref: the changed document exactly as named in the text (title and/or reference number).
- target_path: REQUIRED for substitute, insert and delete: the clause number being changed, copied from the text
  ("Clause 7.2 of the Agreement" gives "7.2"; never null for these actions). Null only for supersede_doc and
  supersede_amendment.
- effective_date: the date from which the change applies, as YYYY-MM-DD, only if stated; otherwise null.
- new_text_span_ids: ids of the spans that hold the replacement or inserted wording (substitute and insert), else [].
- evidence_span_ids: ids of the spans that state the directive. Copy ids exactly as given in square brackets.

Example (generic):
[Y2:1#s1] With effect from 1 July 2024, Clause 4.1 of the Savings Account Terms ACC/T/2023 shall be substituted by the following:
[Y2:1#s2] "4.1 The minimum balance shall be Rs. 500."
{"amendments":[{"action":"substitute","target_ref":"Savings Account Terms ACC/T/2023","target_path":"4.1","effective_date":"2024-07-01","new_text_span_ids":["Y2:1#s2"],"evidence_span_ids":["Y2:1#s1"]}]}

Example (a value revised inside the sentence; the same span holds the directive and the new value):
[Y3:p1.1#s1] From 1 March 2025, the annual fee under Section 6.02 of the Cardholder Terms CH/T/2024 is revised to Rs. 900.
{"amendments":[{"action":"substitute","target_ref":"Cardholder Terms CH/T/2024","target_path":"6.02","effective_date":"2025-03-01","new_text_span_ids":["Y3:p1.1#s1"],"evidence_span_ids":["Y3:p1.1#s1"]}]}

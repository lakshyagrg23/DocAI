# Design: Ingest (register → parse → OCR → segment → index)

Covers FR-1, FR-2, FR-16, FR-17. Code: `core/ingest/{register,parse,ocr,segment,pipeline}.py`, `core/retrieval/index.py`.
Facts, amendments and conflicts run after this stage; see their own design docs.

## Pipeline orchestration (`pipeline.py`)

- `enqueue(path) -> job_id`: insert into `ingest_jobs` (state `queued`), start the worker thread if not running.
- The worker processes jobs one at a time (`queued → parsing → ocr → extracting → resolving → ready | failed`)
  and updates `documents.status` + `status_detail` (e.g. "OCR page 2/3") for the UI to poll.
- Each stage is idempotent and keyed by `doc_id`. Re-running a doc deletes its clauses, spans, windows and facts first.
- `scripts/ingest_corpus.py --reset` wipes DATA_DIR and ingests `corpus/pdfs/*.pdf` in filename order (D1…D6),
  then runs the global amendment resolution + conflict scan once.

## 1. Register (`register.py`)

1. sha256 of the bytes; an existing sha → return the existing doc_id (no duplicate).
2. doc_id: demo files named `D{n}_*.pdf` → `D{n}`; otherwise `U` + sha256[:6].
3. Metadata: text of page 1 (first 2,500 chars) → LLM prompt `register_meta.md` → JSON
   `{title, doc_type, issuer, ref_no, ref_aliases[], issue_date, effective_date}`.
   If `effective_date` is missing, use `issue_date`; if both are missing, use today and flag `status_detail`.
   Normalise dates with `dateparser` (DMY preference, `settings={"DATE_ORDER":"DMY"}`).
   `ref_aliases` also gets deterministic variants of `ref_no`: case-folded, with `/`, `-` and spaces removed.

## 2. Parse (`parse.py`), PyMuPDF

For each page:
- `words = page.get_text("words", sort=True)` → (x0,y0,x1,y1, word, block, line, wno).
- `blocks = page.get_text("dict")` gives font size and flags, used to detect headings (bold or size ≥ body+1.5).
- Tables: `tabs = page.find_tables()`. For each table, `tab.extract()` gives the rows, and `tab.rows[i].cells` the bboxes.
  Words inside a table bbox are removed from the running text and emitted as table rows.
- Output: `PageContent(page_no, width, height, lines: list[Line(text, bbox, words[], font_size, bold)], tables: list[Table(rows: list[Row(cells: list[str], bbox)])], is_ocr)`.
- Drop running headers and footers: lines repeated on ≥ 60% of pages within the top or bottom 8% of the page height, plus "Page x of y".

## 3. OCR (`ocr.py`), P1

- A page needs OCR if `len(page.get_text().strip()) < OCR_MIN_CHARS` and `page.get_images()` is non-empty.
- `tp = page.get_textpage_ocr(dpi=OCR_DPI, language=OCR_LANG, full=True)`, then `page.get_text("words", textpage=tp)`.
  Word coordinates come back in page space, so the rest of the pipeline is unchanged.
- Confidence: PyMuPDF does not expose per-word confidence. Run `pytesseract.image_to_data` on the same pixmap once per
  page and use the mean conf of words with conf ≥ 0 as `pages.ocr_conf`; span `ocr_conf` = page conf.
- Pre-processing before OCR (on the pixmap with Pillow): grayscale, autocontrast, deskew if |angle| > 0.5°
  (estimate with `pytesseract.image_to_osd` or a projection-profile search over ±3°).
  **Deskew note:** if you deskew, OCR on the deskewed image and map boxes back with the inverse rotation. Simpler
  alternative for the demo: generate D6 with ≤ 1° skew and skip deskew. Tesseract copes with that.
- Tables on scanned pages are not reconstructed. Lines of text only; documented limitation.
- Tesseract must be installed with `tesseract-ocr-hin` (apt) in both the UI image and Colab.

## 4. Segment (`segment.py`)

Goal: clauses with stable paths, plus spans (sentences or table rows) with bboxes.

**Heading and numbering detection** on line starts (after stripping):

```python
NUM      = r"^(?P<num>\d{1,2}(?:\.\d{1,2}){0,3})[.)]?\s+"          # 7  7.2  7.2.1
ALPHA    = r"^\((?P<alpha>[a-z])\)\s+"                             # (b)
ROMAN    = r"^\((?P<roman>i{1,3}|iv|v|vi{0,3}|ix|x)\)\s+"          # (iii)
KEYWORD  = r"^(Clause|Article|Para(?:graph)?|Section)\s+(?P<kw>\d+(?:\.\d+)*)"
SCHED    = r"^(Schedule|Annexure|Appendix)\s+(?P<sch>[IVX\d]+)"
FAQ_Q    = r"^(Q\d*[:.)]|Q\.|\d+\.\s*(What|Who|How|Can|Is|Are|When|Where|Why))"
```

Rules:
- A new numbered path starts a clause; `(a)` / `(i)` start sub-clauses `7.2(a)` / `7.2(a)(i)` under the current clause.
- Disambiguate roman `(i)` vs alpha `(i)`: if the previous sibling was `(h)`, it's alpha.
- Numbering like "15 January 2024" must not start a clause. Require the number to be followed by text starting with a
  capital letter or a title-case heading word, and reject if the next token is a month name.
- No numbering found in the whole doc (circular paragraphs, FAQ) → paragraph clauses `p{page}.{n}`, split on blank-line
  gaps (> 1.2 × line height) or bold headings. FAQ docs → one clause per Q+A pair `p{page}.q{n}`.
- **Cross-page join:** a clause continues across a page break until the next clause start. Its spans keep their own
  page numbers; `clauses.page_start` / `page_end` record the range.
- `heading_trail`: e.g. "7 Prepayment and Foreclosure > 7.2".
- `kind`: a keyword heuristic on heading + text (fee/charge → fee; penal|late → penalty; age|eligib → eligibility;
  interest|rate → rate; amend|substitut|supersed → amendment; "means" → definition; else other).

**Spans:**
- Sentence split within a clause with a regex splitter that does not break after abbreviations:
  `Rs.`, `No.`, `p.a.`, `i.e.`, `e.g.`, `viz.`, `Ltd.`, `Cl.`, `w.e.f.`, and single initials. Split on `[.;:](?=\s+[A-Z(“"])`
  and also at sub-clause starts.
- A span's `text` = exact concatenation of its words with single spaces (keep original characters such as ₹, %, /-).
  `char_start` / `char_end` are offsets in the clause text.
- `bboxes` = one rect per line covered (union of the word rects on that line).
- **Table rows:** each table becomes clause `table{t}` (heading = the preceding line, e.g. "Schedule of Charges"). Each data
  row becomes clause `table{t}.row{r}` with exactly one span whose text is `"{header1}: {cell1} | {header2}: {cell2}"`.
  The header is included so the row is self-contained for retrieval and NLI. The span bbox = row bbox.
  Note this span text is *constructed*, not verbatim. Store `is_table_row=1`; the UI then renders the row as a mini table,
  and quote-exactness tests compare cell texts instead.

## 5. Index (`core/retrieval/index.py`)

- Windows: per clause, concatenate `heading_trail + "\n" + clause text`. If > WINDOW_TOKENS (≈ words × 1.3), split into
  windows of WINDOW_TOKENS with WINDOW_OVERLAP, cutting at span boundaries. Each window stores its span_ids.
- Dense: `/embed` in batches of 32 → append rows to `index/dense.npy` (float16 on disk, float32 in memory).
- BM25: `rank_bm25.BM25Okapi` over tokens from `re.findall(r"[a-z0-9₹%]+(?:\.[0-9]+)*", text.lower())`,
  which keeps `7.2`, `13.5`, `₹750`. Rebuild the whole BM25 on each ingest (the corpus is small); pickle it to `index/bm25.pkl`.
- Incremental: on re-ingest of a doc, rebuild dense.npy rows by rewriting the file (small corpus; simple beats clever).

## Tests (`tests/test_ingest.py`)

- D1: clause `D1:7.2` exists, `page_start=3`, `page_end=4`, and contains "4%".
- D1: `D1:8.1` text contains "₹500".
- D2: there's a row span containing "Late payment" and "750".
- No clause path is a date fragment (no path equal to "15" when followed by "January").
- D6 (after M9): `has_ocr=1`, a span contains "21" and "60".
- Every span has ≥ 1 bbox, and every bbox lies inside the page bounds.

## Implementation notes (M2, 2026-11-23): where the code differs from the text above
- **Modules:** `parse.py`, `spans.py` (sentence splitting + span building, split out of segment.py), `segment.py`, `store.py` (DB writes), `register.py`, `pipeline.py`, plus `core/retrieval/index.py`. Prompt `register_meta.md` is loaded by `core/llm/prompt_loader.py` (version in the first-line comment).
- **Headings:** a *bold* numbered line ("7. Prepayment and Foreclosure") is a heading (sets `heading_trail`), not a clause. Unnumbered bold lines are headings too; consecutive bold lines of the same size merge (wrapped titles). A `Schedule/Annexure/Appendix` heading resets top-level numbering.
- **Clause-start guards (generic, no demo strings):** top-level number must be `previous+1..+2`; a bare "7 EMIs" (no `.`/`)` separator, not bold) is text; first word after the number must be capitalised or an opening quote and not a month; `Clause 7.2 of the ...` only counts as a keyword heading when followed by `:`, `)`, a dash, a period+space or end of line.
- **Paragraph breaks:** vertical gap between line boxes > `PARA_GAP_FONT_RATIO` (0.7) x font size (the text's "1.2 x line height" does not separate paragraphs from wrapped lines in reportlab output). A page break continues an unnumbered paragraph only if the previous line has no terminal punctuation and the next starts lowercase.
- **Spans:** also split at `?`/`!` and never across a page boundary (span has one page). Abbreviation, initial, number-like ("1.", "Q1.") tokens never end a sentence.
- **FAQ:** a doc with >= 2 FAQ question lines uses `p{page}.q{n}` clauses (Q + answer); each Q+A is one clause with a span for the question and one per answer sentence.
- **Tables:** cell text is rebuilt from the page words inside each cell box (PyMuPDF `extract()` dropped spaces). The `table{t}` container and `row0` header clauses are stored but get no windows. Table heading = the line just above the table.
- **kind:** classified on the clause text first (heading trail only as fallback); order amendment, penalty, fee, eligibility, rate, definition.
- **Windows:** `{clause_id}@w{n}`; embeddings are requested in chunks of `EMBED_CHUNK` (8) so a CPU model service stays under the 60 s timeout; `dense.npy` is rewritten atomically after embedding succeeds.
- **Register:** LLM values are verified: `ref_no` must literally occur in the page text (else the regex value is used); unparseable dates fall back to regex values; no LLM -> heuristics.
- **Scanned docs (until M9):** registered, `has_ocr=1`, status `Queued`, `status_detail="needs OCR (M9)"`, `effective_date` left NULL (no text to date it), job state `needs_ocr`.
- **Tokenizer:** the specified regex splits `13.5%` into `13.5` and `%`; kept as specified.

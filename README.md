# ReviewAid v3.0.0 - Architecture Validation Study

Empirical validation of **ReviewAid v3.0.0** (Sahu & Balakrishnan 2026, *JORS* 14:21, doi:10.5334/jors.672) against published human gold standards.

The JORS paper described v2.1.0; v3.0.0's paradigm shift **from LLM self-assessment to deterministic source-grounded verification** (exact-string Check A, token-overlap Check B, negation detection Check E, override logic) - is the intervention this study measures.


**The validated artifact is the tool itself.** Every backend runs through ReviewAid v3.0.0's own `utils.py` / `parser.py` / `confidence.py` code paths - the exact screener and extractor prompts, the exact Tier-1 keyword rule, the exact confidence override - with the UI removed and version pinned (`CITATION.cff` must read `3.0.0`; the driver refuses to run otherwise). 

The three backends are a **stress test, not a contest** - "a better model gives better output" is trivial. They span ~10× capability: free cloud (GLM-4.7-Flash), cloud (Cohere `command-a-03-2025`), weak local (Ollama `llama3.2:3b`, 2 GB, M1-friendly).

---

## 2. Design: two arms, published human gold standards

| Arm | Corpus | N | Backends |
|---|---|---|---|
| Full-text screening | **CSMeD-FT** (Kusa et al., NeurIPS D&B 2023): real systematic-review papers with the human include/exclude decision at the *full-text* stage | ~2,000 papers, ≥300 included | all 3 |
| Data extraction | **EvidenceInference** (Lehman et al., NAACL 2019 + 2.0): full-text RCTs with human-annotated Population / Intervention / Comparator / Outcome + effect direction | ~2,184 articles | all 3 |

Each selected review's **published eligibility criteria go into ReviewAid verbatim** - same rules, same papers, different screener. Criteria are frozen after a pilot, together with every analysis setting in `config.ANALYSIS`.

All analyses come from ingredients **logged per paper** (raw self-assessed confidence, deterministic score, override event, per-field grounding verdicts, parse events) - **zero extra API calls**.


## 3. Layout

```
validation/
├── config.py             # models, paths, frozen analysis settings
├── keys.py               # Cohere rotation + budget check (python keys.py)
├── ra_driver.py          # headless v3.0.0 screener+extractor paths, full logging
├── viz.py                # publication figures: SVG + 600-dpi PNG, column sizing
├── 01_build_corpus.py    # EvidenceInference (auto) / CSMeD (bootstrap) / demo
├── 02_run_screening.py   # corpus x backends, resume-safe, determinism rerun
├── 03_run_extraction.py  # EvidenceInference x backends
├── 04_audit.py           # masked human-audit sheet (discordance + 10% sample)
├── 05_stats.py           # all analyses + figures
├── 06_auto_audit.py      # pre-fills the audit sheet (never touches filled rows)
├── run_all.py            # screening + extraction together, parallel + resume-safe
├── proclock.py           # process lockfiles, one instance of each task
├── .env_template         # template: fill in your details, then rename to .env
├── .env                  # API keys (never commit; rotate before publishing)
├── requirements.txt      # tool deps + analysis stack
├── corpus/               # built by 01: pdfs/, extraction_pdfs/, gold_labels.csv,
│                         # extraction_tasks.csv, reviews.json, attrition_report.md
├── results/<model>/      # screening_results.jsonl, extraction_results.jsonl,
│                         # rerun_results.jsonl
├── results/stats/        # CSVs + stats_report.md
├── results/figures/      # *.svg + *.png
├── results/audit/        # adjudication_sheet_union.xlsx (built by 04, filled
│                         # by 06 + manual adjudication)
└── state/                # Cohere usage counters
```

---

## 5. How it works (internals)

**Streamlit shim.** `ra_driver.install_streamlit_shim()` injects a minimal fake `streamlit` module *before* importing the tool, so `st.session_state` checks and UI logging become silent no-ops. Decision logic is byte-identical to the app.

**Screener path per paper** (mirrors `screener.py`):

1. PyMuPDF extraction (`utils.extract_pdf_content`) + preprocessing.
2. **Tier 1** keyword rule - if any exclusion criterion matches and no inclusion criterion does → *Exclude*, confidence 1.0, **zero API calls**.
3. Otherwise the tool's exact PICO prompt → backend via the tool's own provider classes → `parser.parse_result` (6-stage JSON recovery).
4. **Confidence + override** - `confidence.estimate_confidence` recomputes the deterministic score; if AI claims >0.5 while Tier-1 says <0.5, the score is overridden downward and flagged. Otherwise `min(AI confidence, 0.95)`.

**Extractor path per paper** (mirrors `extractor.py`): tool's exact prompt with `Paper Title` auto-prepended, `{"extracted": {...}, "confidence": ...}` JSON contract, "Not Found" convention, then `estimate_confidence(mode="extractor")` - per-field exact match → token overlap → negation windows and the same override logic.

**Logged analysis ingredients** (per record): `ai_confidence_raw` (pre-override), `deterministic_confidence`, `override_fired`, `tier`, `criteria_match` ratio, `grounding` per-field verdicts (screening records carry `tier1_keyword` too), `parse_ok`, `api_returned`, `latency_s`.

**Key rotation - Cohere AND GLM.** Both pools rotate. `keys.py` fingerprints keys, persists counts to `state/<provider>_usage.json` (re-read on every request, so the parallel screening + extraction processes never double-spend a key), and always issues the least-used key. Cohere trial keys ≈1,000 calls each - a key is retired on quota/auth errors (429s are transient → exponential backoff in `query_provider`). GLM keys rotate the same way on quota/server-busy errors, with **no fixed call cap**.

**GLM timed retries.** Free-tier GLM is flaky (timeouts, "server busy"). Every GLM call retries up to **4 attempts with 15/30/45 s timers**, rotating keys between attempts, before giving up (a giveaway to the tool's own regex fallback - never a crash). Cohere retries via backoff inside `keys.rotate`.

**Resume + error retry.** Every finished paper appends one JSON line; re-runs skip completed IDs. A paper that failed *completely* (API dead even after retries AND fallback parse failed) is recorded as `decision: "error"` and error rows are **retried automatically on the next run** instead of being skipped. Downstream scripts dedupe by paper_id (newest row wins), so a retried paper's old error row never contaminates the analysis. Interrupt anything, rerun the same command, and it carries on exactly where it stopped.

**No-skip / no-race guarantees.**
- *Worker containment:* each paper is wrapped in its own retry; a worker crash can never lose a paper - worst case it becomes an `error` row.
- *Reconciliation:* at the end of every run, the script compares the corpus against the results file and re-runs anything missing (up to 2 extra passes), then prints an `ACCOUNTING:` line (corpus / completed / error-rows). If anything is still unprocessed it says exactly which IDs and tells you to rerun.
- *Process lockfiles* (`proclock.py`): two instances of the same task cannot run concurrently (the second refuses while the first is alive; a stale lock from a crashed run is auto-removed). Key-usage state files are written with per-process temp names, so the parallel screening + extraction processes share key pools without racing.

---

## 6. Setup (once)

```bash
cd validation
```

```bash
# one virtualenv for everything (tool deps + analysis deps, single file)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` pulls in ReviewAid v3.0.0's own pinned dependencies (via `-r ../ReviewAid_v3.0.0/requirements.txt`) plus the analysis stack (numpy, scipy, matplotlib, openpyxl, requests).

- Fill `validation/.env_template` with your details (GLM keys, Cohere keys, real `ENTREZ_EMAIL`/`UNPAYWALL_EMAIL`), then rename it to `validation/.env`.
  
- **GLM key pool:** screening and extraction run *simultaneously* and share the GLM keys (least-used rotation, process-safe). Paste extra keys comma-separated into `ZAI_API_KEYS` - 2–3 keys are recommended so the two parallel jobs never starve.
  Check anytime: `python keys.py`.

> Ollama is (the local arm) in this study because the architecture claim is strongest if a deliberately *weak local* model (3B parameters) is still made safe by ReviewAid's confidence gating.
> Setup: install the app from <https://ollama.com>, then `ollama pull llama3.2:3b` (2 GB - chosen because it runs fast on an M1 Pro; llama3 8B choked this machine).
> Leave the app running during local runs. 


## 7. Quickstart - demo run (3 screening + 3 extraction, ~10 min, ~4 free API calls)

Copy-paste in order in the virtual environment during Setup:

```bash
# 1. build the demo corpus (3 screening papers + 3 extraction articles, gold answers included)
python 01_build_corpus.py --arm demo
```
Expect: `[demo] screening: 3 PDFs + labels + criteria` and `[demo] extraction: 3 article PDFs + gold fields`.

```bash
# 2. screening demo: 3 papers through ReviewAid's real screener (GLM backend)
python 02_run_screening.py --model glm --limit 3
```
Expect one line per paper, e.g.:
```
[glm] 1/3 demo_001: include conf=0.9 tier=tier2_llm_selfassess (15.2s)
[glm] 2/3 demo_002: exclude conf=1.0 tier=tier1_deterministic (0.0s)   <- zero API calls
[glm] 3/3 demo_003: exclude conf=... tier=... (...)
```
`demo_002` (a rat study) is auto-excluded by the Tier-1 keyword rule with confidence 1.0 and **no API call** - the deterministic layer working as designed.

```bash
# 3. extraction demo: 3 articles through ReviewAid's real extractor
python 03_run_extraction.py --model glm --limit 3
```
Expect per-article lines with `conf=`, `tier=`, and `ungrounded_fields=` counts (fields whose extracted text could not be grounded in the source - the hallucination instrument).

```bash
# 4. screening AND extraction simultaneously (what the real study does)
python run_all.py --model glm
```
Resume-safe: anything already completed in steps 2–3 is skipped.

```bash
# 5. statistics + figures from the demo run
python 05_stats.py --models glm
```
Expect the printed report plus `results/stats/stats_report.md` and figures in `results/figures/` - each as `.svg` (vector) and `.png` (600 dpi).

```bash
# 6. optional: same demo through the LOCAL model (no API, no internet)
ollama pull llama3.2:3b        # once, ~2 GB
python 02_run_screening.py --model ollama --limit 3
python 03_run_extraction.py --model ollama --limit 3
```

```bash
# 7. BEFORE building the real corpora, remove the demo data [Compulsory]
find corpus results -name 'demo_*' -delete
find results -name '*.jsonl' -delete
find results/stats results/figures -type f -delete
```

---

## 8. Running the real study - the commands, in order

Run these one at a time, top to bottom. Each step says what it does and what kind of step it is (`CORPUS`, `PILOT`, `MAIN RUN`, `DETERMINISM`, `AUDIT`, `ANALYSIS`,`MAINTENANCE`, `DIAGNOSTIC`).

1. **Environment** (`SETUP`, once per terminal):

```bash
   source .venv/bin/activate
```

2. **Extraction corpus** (`CORPUS`):

```bash
python 01_build_corpus.py --arm evidenceinference --limit 2184
```
   
   Downloads the EvidenceInference gold annotations + 4,470 full texts from GitHub (no keys), renders them to PDFs, writes `corpus/extraction_tasks.csv` with a deterministic seed-42 subsample of 2,184 articles (caps the Cohere budget). Re-run safe - PDFs are cached.

3. **Screening corpus** (`CORPUS`):

```bash
   git clone https://github.com/WojciechKusa/systematic-review-datasets
```

After cloning, run:
    
```bash
     python 01_build_corpus.py --arm csmed
```
   
 Uses the pre-built `CSMeD-FT.zip` inside the clone (auto-extracted). Selects reviews to hit ~2,000 papers / ≥300 includes, renders the PDFs, writes `corpus/gold_labels.csv`. Re-run safe - PDFs cached, filled criteria preserved.

4. **Criteria auto-fetch** (`CORPUS`):

```bash
   python 01_build_corpus.py --arm csmed --autofill-criteria
```
   
 Fetches each review's published eligibility criteria verbatim (Europe PMC open-access full text → structured abstract → PubMed, incl. 2025 format) with provenance per review.


5. **Curate the criteria** (`CORPUS - MANUAL`):
   Open `corpus/criteria_to_fill.json` and verify every review's auto-fetched criteria: check and complete the P/I/C/O include and exclude fields so they match what the review actually published. The fetcher is good but not perfect - this human pass is what makes the screening criteria trustworthy.

Once every review is checked, freeze them (step 6).

6. **FREEZE the criteria** (`CORPUS - FREEZE`):

```bash
python 01_build_corpus.py --arm csmed --finalize-criteria
```
   
Writes `corpus/reviews.json`. After this, criteria are frozen - any change is a documented deviation. Results processed with a different criteria version must be deleted before the main runs.

7. **Clear stale screening results** (`MAINTENANCE`):

```bash
   rm results/cohere/screening_results.jsonl results/glm/screening_results.jsonl results/ollama/screening_results.jsonl
```

Deletes screening rows processed under the old prose criteria. Do NOT delete `results/*/extraction_results.jsonl` - extraction never uses criteria.

8. **Budget check** (`DIAGNOSTIC`):

```bash
    python keys.py
```

9. **PILOT** (`PILOT`):

```bash
    python run_all.py --model glm --limit 5
    python run_all.py --model cohere --limit 5
    python run_all.py --model ollama --limit 5
```
Real PDFs + frozen criteria end-to-end before spending the big quota. Check: decisions include a mix of include/exclude, `parse_ok` ≈ 100%, confidence not a wall of 0.0 OVERRIDE.

 10. **PILOT CHECK** (`PILOT`): sanity-check one piloted backend end-to-end before spending the big quota:

```bash
     python 05_stats.py --models ollama    # or whichever model you piloted
     python 04_audit.py --model ollama     # pilot audit sheet (same workflow as 14–16)
```

 11. **Clean up pilot output** (`MAINTENANCE`) - required if you did step 10: 
 pilot rows are indistinguishable from main-run rows, so they must not be left in `results/`. Skip this step only if you skipped step 10 entirely.
 
```bash
     find corpus results -name 'demo_*' -delete
     find results -name '*.jsonl' -delete
     find results/stats results/figures results/audit -type f -delete
```

Then start the MAIN RUNS (step 12). Every run is resume-safe: an interrupted run picks up again at the first unprocessed article.

12. **MAIN RUNS** (`MAIN RUN`, screening 1,968 + extraction 2,184 per backend, simultaneously, checkpoint/resume, self-healing):

```bash
    python run_all.py --model cohere   #(~5 h)
    python run_all.py --model ollama   #(local, longest - around 20 h+)
    python run_all.py --model glm      #(overnight; free tier 429s are retried automatically)
```

```bash
# - if the storm is heavy for glm, run the two modules sequentially:
      `python 02_run_screening.py --model glm` #then
      `python 03_run_extraction.py --model glm`
```

13. **DETERMINISM check** (`DETERMINISM`):

```bash
    python 02_run_screening.py --model cohere --rerun-subset
```
Reruns 100 papers a second time (seed 42). Measures run-to-run stability - what % of decisions are identical when the stochastic LLM is queried twice - and flags any paper whose decision actually flips.

14. **AUDIT** (`AUDIT`):

```bash
    python 04_audit.py --models glm cohere ollama
```

Builds ONE union sheet: every paper where any backend disagreed with the published gold label (FNs, FPs, maybes) + a 10% sample of agreements per backend, each backend's decision side by side, masked.

15. Make sure the sheet exists (`results/audit/adjudication_sheet_union.xlsx`;
    step 14 creates it - re-run step 14 first if results changed since).
    
16. Pre-fill the comparison, then verify manually:

```bash
   python 06_auto_audit.py
```

It writes a *suggestion* into `human_agrees_with_gold` for every blank row (`yes` = some backend matched the gold label, `no` = a backend made a concrete decision against gold, `unsure` = only "maybe" referrals or no usable decisions) plus a factual counts line in `notes`. It never touches rows you already filled, so re-running is safe - but do your manual pass AFTER the last re-run, and verify every `no`/`unsure` row against the PDF.

Then manually check `human_agrees_with_gold` (yes/no/unsure). One adjudication covers all backends (the verdict is about the published gold label, not the tool).

17. **ANALYSIS** (`ANALYSIS`):

```bash
    python 05_stats.py
```

The full statistics suite (calibration raw-vs-final by tier, override-as-detector, ungrounded-field rates capability→workload with TOST, conformal risk control, cluster-bootstrap sens/spec/WSS, κ/F1) + every figure in SVG and 600-dpi PNG + `results/stats/stats_report.md`. When the adjudicated sheet has verdicts, section [H] joins it back by `paper_id` and reports raw vs adjudicated accuracy/sensitivity/specificity per backend (gold overturned = effective gold label flipped) see `results/stats/adjudicated_metrics.csv` and the raw-vs-adjudicated dumbbell `results/figures/fig9_adjudicated_impact` (SVG + PNG). Re-run 05 after you finish the manual adjudication so [H] reflects your final verdicts.

---

## 8a. Running the ollama arm on a second machine 

The union audit (step 14) and the final statistics (step 17) need **all three** backends' results, so you can spread the main runs across machines, but the audit and analysis happen in one place:

1. **Machine 2 - setup (once):** 
clone this repo → create the venv (`pip install -r requirements.txt`) → fill a minimal `.env` (the ollama arm needs only `OLLAMA_MODEL` - **no API keys**) → rebuild the corpus with steps 2–6. The selection is seed-42 deterministic, so you get the identical corpus; the frozen `corpus/reviews.json` is committed to git and must be identical on both machines.

   
2. **Machine 2 - run:** 
keep the Ollama app running, then `python run_all.py --model ollama`. Nothing else, no audit, no stats.
   
   
3. **Main machine - finish:** 
copy `results/ollama/` back (or `git pull` - `results/` is kept in git on purpose), then run steps 14–17 **once, after cohere + glm + ollama are all complete**.


---

## 9. Cohere key budget (strict 1,000 calls/key)

| Phase | Calls | With overhead | Keys |
|---|---|---|---|
| Screening (2,000 papers) | 2,000 | ~2,300 | 3 |
| Extraction E1 EvidenceInference (~2,184) | 2,184 | ~2,400 | 5 total |
| **Total** | **~4,200** | **~4,700** | **5 min / 6 recommended** |

You can append new keys to `COHERE_KEYS` in `.env`, then `python keys.py` to verify capacity. GLM and Ollama consume no Cohere quota; Tier-1 keyword exclusions consume none at all.


## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `ReviewAid folder is version X` | The study is strictly v3.0.0 - point `TOOL_DIR` at the v3.0.0 code |
| `All Cohere keys exhausted` | Add keys to `COHERE_KEYS` in `.env`; `python keys.py` |
| GLM jobs slow / "server busy" | Normal on the free tier: 4 timed retries (15/30/45 s) with key rotation happen automatically; add a 2nd/3rd key to `ZAI_API_KEYS` for more headroom |
| A paper shows `decision: "error"` | It failed even after retries - just rerun the same command; error rows are retried automatically |
| Frequent 429s (Cohere) | Normal on trial keys; rotation + backoff handles it; workers ≤3 |
| Ollama timeouts | If the app isn't running or the model is missing, start it (`ollama serve`, `ollama pull llama3.2:3b`). Transient busy/timeout errors retry automatically (10 attempts, backoff to 60 s) |
| `Corpus missing` | Run the relevant `01_build_corpus.py --arm ...` first |
| `CSMeD-FT folder not found` | Clone `WojciechKusa/systematic-review-datasets` inside `validation/`, or pass `--csmed-dir /path/to/CSMeD-FT` |
| Demo results mixed into real corpus | Run the §7 step-7 cleanup line before `--arm csmed` / `--arm evidenceinference` |
| Run interrupted | Rerun the same command; completed IDs are skipped |



---

## 11. Reproducing the results

Two routes, depending on what you want to establish:

### Route A - re-analysis of the deposited data (minutes, no API access)

Every number and figure in the paper regenerates from the deposited artifacts alone:

```bash
git clone <this repo> && cd validation
pip install -r requirements.txt
# results already exist in the repo: results/glm/*.jsonl  results/cohere/*.jsonl  results/ollama/*.jsonl  results/audit/adjudication_sheet_union.xlsx   (the adjudicated sheet)
python 05_stats.py --models glm cohere ollama
```

This re-runs the full analysis suite (report sections A–H) and rewrites `results/stats/stats_report.md` plus every figure. The analysis is deterministic (fixed seeds, thresholds frozen in `config.ANALYSIS`), so the outputs match the deposited report up to floating-point noise from library versions.


### Route B - full re-run of the study (days, API quota, statistically equivalent)

1. Make sure you erase all the results via:
```bash
find corpus results -name 'demo_*' -delete
find results -name '*.jsonl' -delete
find results/stats results/figures -type f -delete
```

2. Follow 6. (setup) and 8. (steps 1–17, the complete command walkthrough); The next section covers spreading backends across machines. In short: build the two corpora and freeze the criteria (8. steps 2–6), pilot (steps 9–11), run all three backends on the whole corpora (step 12), adjudicate the audit sheet (steps 14–16), analyse (step 17).

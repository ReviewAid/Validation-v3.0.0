"""Screening runs: corpus x backends, resumable, no paper left behind.

    python 02_run_screening.py --model cohere --limit 5   # smoke test
    python 02_run_screening.py --model all                # full runs
    python 02_run_screening.py --model ollamads --rerun-subset # determinism check

Guarantees:
- every corpus paper is attempted; a worker crash retries the paper, and if it
  still fails it is written as decision:"error" (accounted, retried next run);
- at the end, reconciliation compares corpus vs results and reruns anything
  missing (up to 2 extra passes);
- a process lockfile prevents two instances of the same task racing.

Reads  corpus/gold_labels.csv, corpus/reviews.json   (built by 01)
Writes results/<model>/screening_results.jsonl  (append; resume-safe)
       results/<model>/rerun_results.jsonl       (determinism subset)
"""
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

import config
import keys as keys_mod
import proclock
from ra_driver import screen_one_paper  # installs shim + asserts v3.0.0

_PRINT_LOCK, _APPEND_LOCK = threading.Lock(), threading.Lock()
PASSES = 3   # initial pass + 2 reconciliation passes


def load_corpus():
    labels, reviews = (config.CORPUS_DIR / "gold_labels.csv",
                       config.CORPUS_DIR / "reviews.json")
    if not labels.exists() or not reviews.exists():
        raise SystemExit("Corpus missing. Run 01_build_corpus.py first "
                         "(--arm csmed for the study, --arm demo for testing).")
    df = pd.read_csv(labels)
    criteria = json.loads(reviews.read_text())
    rows, no_pdf, no_criteria = [], [], []
    for _, r in df.iterrows():
        pdf = config.SCREEN_PDF_DIR / str(r["filename"])
        review_id = str(r["review_id"])
        if not pdf.exists():
            no_pdf.append(str(r["paper_id"]))
            continue
        if review_id not in criteria:
            no_criteria.append(str(r["paper_id"]))
            continue
        rows.append({"paper_id": str(r["paper_id"]), "review_id": review_id,
                     "gold_label": str(r["gold_label"]).strip().lower(),
                     "pdf_path": str(pdf), "criteria": criteria[review_id]})
    print(f"[corpus] {len(rows)} papers with PDF + criteria "
          f"({sum(1 for x in rows if x['gold_label'] == 'include')} included)")
    if no_pdf:
        print(f"[corpus] WARNING {len(no_pdf)} papers without a PDF (listed in "
              f"attrition): {no_pdf[:5]}{'...' if len(no_pdf) > 5 else ''}")
    if no_criteria:
        print(f"[corpus] WARNING {len(no_criteria)} papers without frozen "
              f"criteria: {no_criteria[:5]}")
    return rows


def completed_ids(results_file) -> set:
    """Papers with a COMPLETED result. 'error' rows are retried on rerun."""
    ids = set()
    if results_file.exists():
        for line in results_file.open():
            try:
                rec = json.loads(line)
                if rec.get("decision") != "error":
                    ids.add(rec["paper_id"])
            except Exception:
                continue
    return ids


def run_model(model_key: str, rows: list, workers: int):
    m = config.MODELS[model_key]
    out_dir = config.RESULTS_DIR / model_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "screening_results.jsonl"
    if model_key == "cohere":
        print(f"[cohere] keys:\n{keys_mod.get_manager('cohere').usage_report()}")

    by_id = {r["paper_id"]: r for r in rows}
    all_ids = set(by_id)
    t0 = time.time()

    def _append(rec):
        with _APPEND_LOCK, out_file.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _work(row):
        # contain worker failures: retry in-process, then write an error row so
        # the paper is accounted for and retried by reconciliation / next run
        last_exc = None
        for attempt in range(2):
            try:
                rec = screen_one_paper(row["pdf_path"], row["criteria"], model_key)
                rec["review_id"] = row["review_id"]
                rec["gold_label"] = row["gold_label"]
                _append(rec)
                return rec
            except Exception as e:
                last_exc = e
                time.sleep(3 * (attempt + 1))
        _append({"paper_id": row["paper_id"], "review_id": row["review_id"],
                 "gold_label": row["gold_label"], "model_key": model_key,
                 "decision": "error", "confidence": 0.0, "tier": "none",
                 "reason": f"worker failure: {type(last_exc).__name__}: "
                           f"{str(last_exc)[:200]}"})

    for pass_no in range(1, PASSES + 1):
        done = completed_ids(out_file)
        missing = [by_id[p] for p in sorted(all_ids - done)]
        if pass_no > 1:
            print(f"[{model_key}] reconciliation pass {pass_no}: "
                  f"{len(missing)} paper(s) to retry")
        if not missing:
            break
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_work, row): row for row in missing}
            for fut in as_completed(futures):
                row = futures[fut]
                try:
                    rec = fut.result()
                    if rec is None:
                        # retries exhausted; the error row is already written
                        with _PRINT_LOCK:
                            print(f"[{model_key}] {row['paper_id']}: ERROR row "
                                  "written (retried by reconciliation)", flush=True)
                        continue
                    with _PRINT_LOCK:
                        print(f"[{model_key}] {rec['paper_id']}: "
                              f"{rec['decision']} conf={rec['confidence']} "
                              f"tier={rec['tier']}"
                              + (" OVERRIDE" if rec.get("override_fired") else "")
                              + f" ({rec['latency_s']}s)", flush=True)
                except Exception as e:      # unreachable: _work contains errors
                    print(f"[{model_key}] UNEXPECTED failure on "
                          f"{row['paper_id']}: {e}", flush=True)

    # final accounting: nothing may be unaccounted for
    done = completed_ids(out_file)
    with out_file.open() as f:
        err_rows = [json.loads(l) for l in f if json.loads(l).get("decision") == "error"]
    print(f"[{model_key}] ACCOUNTING: corpus={len(all_ids)} completed="
          f"{len(done & all_ids)} error-rows={len(err_rows)} "
          f"(error rows are retried on the next run)")
    print(f"[{model_key}] finished in {(time.time()-t0)/60:.1f} min")
    not_done = sorted(all_ids - done)
    if not_done:
        print(f"[{model_key}] NOT completed yet: {not_done[:5]}"
              f"{'...' if len(not_done) > 5 else ''} — rerun this command")
    if model_key == "cohere":
        print(f"[cohere] keys:\n{keys_mod.get_manager('cohere').usage_report()}")


def rerun_subset(model_key: str, rows: list):
    import random
    random.seed(config.ANALYSIS["rerun_seed"])
    subset = random.sample(rows, min(config.ANALYSIS["rerun_subset_n"], len(rows)))
    out_dir = config.RESULTS_DIR / model_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "rerun_results.jsonl"
    for r in subset:
        rec = screen_one_paper(r["pdf_path"], r["criteria"], model_key)
        rec["review_id"], rec["gold_label"] = r["review_id"], r["gold_label"]
        with out_file.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[{model_key}] determinism subset -> {out_file}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="all", choices=["ollamads", "cohere", "ollama", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--rerun-subset", action="store_true")
    args = ap.parse_args()

    rows = load_corpus()
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        raise SystemExit("No papers selected.")
    models = list(config.MODELS) if args.model == "all" else [args.model]
    for mk in models:
        try:
            proclock.acquire(f"02_{mk}")
            if args.rerun_subset:
                rerun_subset(mk, rows)
            else:
                run_model(mk, rows, args.workers or config.MODELS[mk]["workers"])
        finally:
            proclock.release(f"02_{mk}")


if __name__ == "__main__":
    main()

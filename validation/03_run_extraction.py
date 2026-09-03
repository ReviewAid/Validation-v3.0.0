"""Extraction runs: EvidenceInference articles x backends, resumable.

    python 03_run_extraction.py --model cohere --limit 5   # smoke test
    python 03_run_extraction.py --model all                # full runs

Fields per article (config.EXTRACT_FIELDS): Population, Intervention,
Comparator, Outcome, Effect Direction — fed to ReviewAid's own extractor
prompt. Gold: prompts_merged.csv descriptions + majority effect-direction
label (built by 01 into corpus/extraction_tasks.csv).
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
from ra_driver import extract_one_paper  # installs shim + asserts v3.0.0

_PRINT_LOCK, _APPEND_LOCK = threading.Lock(), threading.Lock()


def load_tasks():
    tasks_path = config.CORPUS_DIR / "extraction_tasks.csv"
    if not tasks_path.exists():
        raise SystemExit("Extraction corpus missing. Run: "
                         "python 01_build_corpus.py --arm evidenceinference")
    df = pd.read_csv(tasks_path)
    tasks, no_pdf = [], []
    for _, r in df.iterrows():
        pdf = config.EXTRACT_PDF_DIR / str(r["filename"])
        if pdf.exists():
            tasks.append({"article_id": str(r["article_id"]),
                          "pdf_path": str(pdf),
                          "gold": {k: ("" if pd.isna(r[k]) else str(r[k]))
                                   for k in ("gold_intervention", "gold_comparator",
                                             "gold_outcome", "gold_effect_direction")}})
        else:
            no_pdf.append(str(r["article_id"]))
    print(f"[extraction] {len(tasks)} articles ready")
    if no_pdf:
        print(f"[extraction] WARNING {len(no_pdf)} articles without a PDF: "
              f"{no_pdf[:5]}{'...' if len(no_pdf) > 5 else ''}")
    return tasks


def run_model(model_key: str, tasks: list, workers: int, limit: int = 0):
    m = config.MODELS[model_key]
    out_dir = config.RESULTS_DIR / model_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "extraction_results.jsonl"
    def completed():
        done = set()
        if out_file.exists():
            for line in out_file.open():
                try:
                    rec = json.loads(line)
                    if rec.get("decision") != "error":  # errors retried on rerun
                        done.add(rec["article_id"])
                except Exception:
                    continue
        return done

    by_id = {t["article_id"]: t for t in tasks}
    all_ids = set(by_id)
    remaining = [by_id[a] for a in sorted(all_ids - completed())]
    todo = remaining[:limit] if limit else remaining   # limit=0 means NO limit
    print(f"[{model_key}] {len(todo)} to extract ({m['provider']} / {m['model']})")
    if not todo:
        return
    if model_key == "cohere":
        print(f"[cohere] keys:\n{keys_mod.get_manager("cohere").usage_report()}")

    t0, n = time.time(), 0

    def _append(rec):
        with _APPEND_LOCK, out_file.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _work(task):
        # contain worker failures: retry in-process, then write an error row so
        # the article is accounted for and retried by reconciliation / next run
        last_exc = None
        for attempt in range(2):
            try:
                rec = extract_one_paper(task["pdf_path"], config.EXTRACT_FIELDS,
                                        model_key)
                rec["article_id"] = rec.pop("paper_id")
                rec["gold"] = task["gold"]
                _append(rec)
                return rec
            except Exception as e:
                last_exc = e
                time.sleep(3 * (attempt + 1))
        _append({"article_id": task["article_id"], "model_key": model_key,
                 "decision": "error", "confidence": 0.0, "tier": "none",
                 "grounding": {}, "extracted": {},
                 "reason": f"worker failure: {type(last_exc).__name__}: "
                           f"{str(last_exc)[:200]}"})

    PASSES = 3  # initial pass + 2 reconciliation passes
    for pass_no in range(1, PASSES + 1):
        missing = [t for t in todo if t["article_id"] not in completed()]
        if pass_no > 1:
            print(f"[{model_key}] reconciliation pass {pass_no}: "
                  f"{len(missing)} article(s) to retry")
        if not missing:
            break
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_work, t): t for t in missing}
            for fut in as_completed(futures):
                task = futures[fut]
                try:
                    rec = fut.result()
                    if rec is None:
                        # retries exhausted; the error row is already written
                        with _PRINT_LOCK:
                            print(f"[{model_key}] {task['article_id']}: ERROR row "
                                  "written (retried by reconciliation)", flush=True)
                        continue
                    n += 1
                    with _PRINT_LOCK:
                        g = rec.get("grounding", {})
                        ungrounded = sum(1 for v in g.values()
                                         if v.get("verdict") == "ungrounded")
                        print(f"[{model_key}] {n}/{len(missing)} {rec['article_id']}: "
                              f"conf={rec['confidence']} tier={rec['tier']} "
                              f"ungrounded_fields={ungrounded} ({rec['latency_s']}s)",
                              flush=True)
                except Exception as e:
                    print(f"[{model_key}] UNEXPECTED failure on "
                          f"{task['article_id']}: {e}", flush=True)

    # final accounting
    done = completed()
    with out_file.open() as f:
        err_rows = [json.loads(l) for l in f if json.loads(l).get("decision") == "error"]
    print(f"[{model_key}] ACCOUNTING: corpus={len(all_ids)} completed="
          f"{len(done & all_ids)} error-rows={len(err_rows)} "
          f"(error rows are retried on the next run)")
    print(f"[{model_key}] done in {(time.time()-t0)/60:.1f} min "
          f"({(time.time()-t0)/max(len(todo),1):.1f}s/article)")
    not_done = sorted(all_ids - done)
    if not_done:
        print(f"[{model_key}] NOT completed yet: {not_done[:5]}"
              f"{'...' if len(not_done) > 5 else ''} — rerun this command")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="all", choices=["gemini", "cohere", "ollama", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()

    tasks = load_tasks()
    models = list(config.MODELS) if args.model == "all" else [args.model]
    for mk in models:
        try:
            proclock.acquire(f"03_{mk}")
            run_model(mk, tasks, args.workers or config.MODELS[mk]["workers"],
                      limit=args.limit)
        finally:
            proclock.release(f"03_{mk}")


if __name__ == "__main__":
    main()

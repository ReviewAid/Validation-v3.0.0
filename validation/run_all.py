"""Run the screener AND the extractor SIMULTANEOUSLY for each backend.

    python run_all.py --model ollamads              # 02 + 03 in parallel for Ollama 8B
    python run_all.py --model all              # ollamads -> cohere -> ollama
    python run_all.py --model cohere ollamads       # any order you like

Within a backend, screening (02_run_screening.py) and extraction
(03_run_extraction.py) run as two parallel processes that share the backend's
key pool (state/<provider>_usage.json is re-read on every key request, so the
two processes never double-spend a key). Backends run sequentially by default;
pass --fully-parallel to run every backend at once (only sensible for ollamads +
cohere — two local Ollama jobs would fight over the Mac).

Both processes are resume-safe: interrupt and rerun the same command.
"""
import argparse
import subprocess
import sys
import time

MODELS = ["ollamads", "cohere", "ollama"]


def spawn(model_key: str, script: str, extra: list[str]) -> subprocess.Popen:
    cmd = [sys.executable, script, "--model", model_key, *extra]
    print(f"[run_all] start: {' '.join(cmd)}")
    return subprocess.Popen(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", nargs="+", default=["all"],
                    choices=MODELS + ["all"])
    ap.add_argument("--fully-parallel", action="store_true",
                    help="run all requested backends at once")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    extra = ["--limit", str(args.limit)] if args.limit else []

    models = MODELS if "all" in args.model else args.model
    t0 = time.time()

    if args.fully_parallel:
        jobs = [(m, s) for m in models for s in
                ("02_run_screening.py", "03_run_extraction.py")]
        procs = {spawn(m, s, extra): (m, s) for m, s in jobs}
        fails = []
        for p, (m, s) in procs.items():
            if p.wait() != 0:
                fails.append((m, s))
        print(f"[run_all] finished in {(time.time()-t0)/60:.1f} min; "
              f"failures: {fails if fails else 'none'}")
        return

    for m in models:
        print(f"\n=== backend: {m} — screening + extraction in parallel ===")
        p_scr = spawn(m, "02_run_screening.py", extra)
        p_ext = spawn(m, "03_run_extraction.py", extra)
        rc_scr, rc_ext = p_scr.wait(), p_ext.wait()
        status = "OK" if (rc_scr == 0 and rc_ext == 0) else f"scr={rc_scr} ext={rc_ext}"
        print(f"=== backend {m} done ({status}) ===\n")

    print(f"[run_all] all done in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()

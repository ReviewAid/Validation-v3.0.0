"""Generate the masked human-audit sheet(s) for discordant decisions.

Single backend:
    python 04_audit.py --model glm

Union across backends (recommended — adjudicate each paper ONCE; the verdict
about the published gold label is backend-independent, and stats apply it to
every backend that flagged the paper):
    python 04_audit.py --models glm cohere ollama

Sheet contains: every FALSE NEGATIVE (gold include, tool exclude/maybe), every
FALSE POSITIVE (gold exclude, tool include), tool-maybe on gold-include
(referral audit), and a random 10% sample of concordant decisions (quality
control) per backend. Model identity and confidence are masked; the two
authors fill `human_agrees_with_gold` (yes/no/unsure) + notes independently.
"""
import argparse
import json
import random

import pandas as pd

import config

PICO_STRATA_PRIORITY = ("false_negative", "false_positive",
                        "maybe_on_include", "concordant_sample")


def load_results(model_key: str) -> pd.DataFrame:
    f = config.RESULTS_DIR / model_key / "screening_results.jsonl"
    if not f.exists():
        raise SystemExit(f"No screening results for {model_key}. Run 02 first.")
    rows = [json.loads(l) for l in f.open()]
    df = pd.DataFrame(rows)
    df = df.drop_duplicates("paper_id", keep="last")   # retried papers: newest wins
    if df.empty:
        raise SystemExit(f"Screening results for {model_key} are empty.")
    df = df[df["decision"] != "error"].copy()
    df["correct"] = (df["decision"] == df["gold_label"])
    return df


def strata_for(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    fn = df[(df["gold_label"] == "include") & (df["decision"] != "include")]
    fp = df[(df["gold_label"] == "exclude") & (df["decision"] == "include")]
    maybe = df[(df["gold_label"] == "include") & (df["decision"] == "maybe")]
    excluded = set(fn.index) | set(fp.index) | set(maybe.index)
    concordant = df[~df.index.isin(excluded)]
    sample = concordant.sample(
        frac=config.ANALYSIS["audit_concordant_sample"], random_state=seed)
    blocks = []
    for d, kind in ((fn, "false_negative"), (fp, "false_positive"),
                    (maybe, "maybe_on_include"), (sample, "concordant_sample")):
        d = d.copy()
        d["audit_stratum"] = kind
        blocks.append(d)
    return pd.concat(blocks)


def build_single(model_key: str) -> pd.DataFrame:
    df = load_results(model_key)
    out = strata_for(df, seed=42)
    out["model_key"] = model_key
    out["tool_decision"] = out["decision"]
    return out


def build_union(model_keys: list) -> pd.DataFrame:
    per_backend, parts = {}, []
    for mk in model_keys:
        df = load_results(mk)
        per_backend[mk] = df
        s = strata_for(df, seed=42)
        s["model_key"] = mk
        parts.append(s[["paper_id", "audit_stratum", "model_key", "decision"]])

    flags = pd.concat(parts)
    flagged = flags[flags["audit_stratum"] != "concordant_sample"]
    paper_flags = (flagged.groupby("paper_id")
                          .agg(audit_stratum=("audit_stratum",
                                              lambda s: sorted(set(s))[0]),
                               flagged_by=("model_key", lambda s: ", ".join(sorted(set(s))))))
    # also collect concordant-sample membership (papers that were fine but sampled)
    conc = (flags[flags["audit_stratum"] == "concordant_sample"]
            .groupby("paper_id")["model_key"]
            .apply(lambda s: ", ".join(sorted(set(s)))))
    for pid in conc.index:
        if pid not in paper_flags.index:
            paper_flags.loc[pid] = ("concordant_sample", conc[pid])
        else:
            paper_flags.loc[pid, "flagged_by"] += f" (+sample: {conc[pid]})"

    # decisions per backend, wide
    wide = {}
    for mk, df in per_backend.items():
        w = df.set_index("paper_id")[["decision", "reason"]].add_suffix(f"_{mk}")
        wide[mk] = w
    base = per_backend[model_keys[0]]
    base_cols = [c for c in ("review_id", "title", "gold_label") if c in base.columns]
    out = base.set_index("paper_id")[base_cols].join(
        list(wide.values()), how="outer")
    out = out.join(paper_flags, how="left")
    out = out[out["audit_stratum"].notna()].reset_index()
    out = out.sort_values(["audit_stratum", "paper_id"],
                          key=lambda col: col.map({k: i for i, k in
                                                   enumerate(PICO_STRATA_PRIORITY)})
                          if col.name == "audit_stratum" else col)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="single backend sheet")
    ap.add_argument("--models", nargs="+", default=None,
                    help="union sheet across backends (recommended)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.models:
        keys = [k for k in args.models if k in ("glm", "cohere", "ollama")]
        out = build_union(keys)
        name = "adjudication_sheet_union.xlsx"
        models_label = "+".join(keys)
    elif args.model:
        out = build_single(args.model)
        name = f"adjudication_sheet_{args.model}.xlsx"
        models_label = args.model
    else:
        raise SystemExit("pass --model glm  or  --models glm cohere ollama")

    keep_cols = [c for c in ("audit_stratum", "review_id", "paper_id", "title",
                             "gold_label", "flagged_by", "tool_decision",
                             "reason", "decision_glm", "decision_cohere",
                             "decision_ollama", "reason_glm", "reason_cohere",
                             "reason_ollama") if c in out.columns]
    sheet = out[keep_cols].copy()
    sheet["pdf_path"] = sheet["paper_id"].map(
        lambda p: str(config.SCREEN_PDF_DIR / f"{p}.pdf"))
    sheet["human_agrees_with_gold"] = ""   # yes / no / unsure
    sheet["notes"] = ""

    config.AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.AUDIT_DIR / name
    sheet.to_excel(path, index=False, sheet_name="audit")

    counts = sheet["audit_stratum"].value_counts().to_dict()
    print(f"[audit] {models_label}: {counts}")
    print(f"[audit] sheet -> {path}")
    print("[audit] Masked: model + confidence hidden. Fill the last two "
          "columns; 05_stats.py will join them back by paper_id. A 'yes' means "
          "the published gold label was correct; 'no' means the tool was right.")


if __name__ == "__main__":
    main()

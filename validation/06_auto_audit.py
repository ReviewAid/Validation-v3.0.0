"""Pre-fill the adjudication sheet: published gold labels vs AI decisions.

    python 06_auto_audit.py

Run after `04_audit.py --models gemini cohere ollama` has built
`results/audit/adjudication_sheet_union.xlsx`.

Per row, the pre-filled verdict (a suggestion to speed up adjudication —
verify `no`/`unsure` rows against the paper PDF):
  - "yes"    at least one backend's concrete decision matches the gold label
  - "no"     no backend matches and at least one made a concrete (include or
             exclude) decision against gold
  - "unsure" no concrete decisions ("maybe" is a referral, not a
             disagreement), or no usable decisions

Notes record factual counts only. Rows with an existing verdict in
`human_agrees_with_gold` are left untouched, so re-runs never overwrite
manual adjudication.
"""
import pandas as pd

import config


def check_agreement(row):
    gold = str(row.get("gold_label", "")).strip().lower()
    concrete, n_maybe = [], 0
    for model in ("gemini", "cohere", "ollama"):
        d = str(row.get(f"decision_{model}", "")).strip().lower()
        if not d or d in ("nan", "error"):
            continue
        if d == "maybe":
            n_maybe += 1
        else:
            concrete.append(d)

    n = len(concrete) + n_maybe
    note = (f"auto: {concrete.count(gold)}/{n} decisions match gold "
            f"({len(concrete)} concrete, {n_maybe} maybe)")
    if n == 0:
        return "unsure", "auto: no AI decisions recorded for this paper"
    if concrete.count(gold):
        return "yes", note
    if concrete:
        # at least one concrete decision against gold; maybes noted but they
        # alone would not justify a "no"
        return "no", note
    return "unsure", note + " — referral only, needs manual check"


def auto_audit():
    sheet_path = config.AUDIT_DIR / "adjudication_sheet_union.xlsx"
    if not sheet_path.exists():
        raise SystemExit("adjudication_sheet_union.xlsx not found. "
                         "Run 04_audit.py --models gemini cohere ollama first.")

    df = pd.read_excel(sheet_path)

    existing = (df["human_agrees_with_gold"].fillna("").astype(str)
                .str.strip().str.lower())
    manual = existing.isin(["yes", "no", "unsure"])
    todo = df.index[~manual]

    results = df.loc[todo].apply(check_agreement, axis=1, result_type="expand")
    if len(todo):
        df.loc[todo, "human_agrees_with_gold"] = results[0]
        df.loc[todo, "notes"] = results[1]

    df.to_excel(sheet_path, index=False, sheet_name="audit")

    counts = df.loc[todo, "human_agrees_with_gold"].value_counts().to_dict() \
        if len(todo) else {}
    print(f"[auto-audit] {sheet_path.name}: pre-filled {len(todo)} rows, "
          f"left {int(manual.sum())} manually adjudicated rows untouched")
    for k in ("yes", "no", "unsure"):
        print(f"[auto-audit]   {k}: {counts.get(k, 0)}")
    if counts.get("unsure", 0) + counts.get("no", 0):
        print("[auto-audit] 'no'/'unsure' rows are suggestions — verify them "
              "against the paper PDF before trusting the adjudication.")


if __name__ == "__main__":
    auto_audit()

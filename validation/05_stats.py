"""Full statistics suite + publication figures (SVG + 600-dpi PNG).

    python 05_stats.py            # analyses everything found in results/
    python 05_stats.py --models gemini cohere ollama

Architecture-first structure (see README section 3):
  A. Operational profile           (tier shares, parse recovery, latency)
  B. Calibration raw vs final      (headline: does deterministic verification
                                    re-calibrate LLM self-assessment?)
  C. Override-as-hallucination-detector  (screening + extraction)
  D. Extraction grounding & accuracy    (ungrounded rates, effect direction,
                                    kappa/PABAK, token-F1 vs gold)
  E. Capability -> workload        (referral rate vs auto-processed error; TOST)
  F. Conformal risk control        (tau picked on calibration reviews, bound
                                    validated on held-out reviews)
  G. Context metrics               (sens/spec/WSS with cluster bootstrap,
                                    per-topic forest, determinism rerun)
  H. Adjudicated audit             (raw vs adjudicated accuracy/sens/spec
                                    after human verdicts on the gold labels,
                                    fig9 dumbbell)

Outputs: results/stats/*.csv, results/stats/stats_report.md, results/figures/*
"""
import argparse
import json
import math
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from scipy import stats as st

import config
import viz

MODELS_DEFAULT = ["gemini", "cohere", "ollama"]
A = config.ANALYSIS
RNG = np.random.default_rng(A["bootstrap_seed"])


# ===========================================================================
# helpers
# ===========================================================================
def wilson(k: int, n: int, conf: float = 0.95):
    if n == 0:
        return (float("nan"),) * 3
    z = st.norm.ppf(1 - (1 - conf) / 2)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


def fmt_ci(k, n):
    p, lo, hi = wilson(k, n)
    return f"{100*p:.1f}% [{100*lo:.1f}, {100*hi:.1f}] (n={n})"


def fmt_w(w):
    """Format a (p, lo, hi) wilson tuple."""
    return f"{100*w[0]:.1f}% [{100*w[1]:.1f}, {100*w[2]:.1f}]"


def auc_score(scores, labels):
    """Rank-based AUC (Mann-Whitney). labels: 1 = positive class."""
    s = np.asarray(scores, float); y = np.asarray(labels)
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order)); ranks[order] = np.arange(1, len(order) + 1)
    r_pos = ranks[:len(pos)].sum()
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def brier_score(conf, correct):
    return float(np.mean((np.asarray(conf, float) - np.asarray(correct, float)) ** 2))


def ece(conf, correct, bins=10):
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    edges = np.linspace(0, 1, bins + 1)
    e, n = 0.0, len(conf)
    for i in range(bins):
        m = (conf > edges[i]) & (conf <= edges[i + 1]) if i else (conf <= edges[1])
        if m.sum() == 0:
            continue
        e += m.sum() / n * abs(correct[m].mean() - conf[m].mean())
    return float(e)


def cluster_bootstrap(df, stat_fn, n=A["bootstrap_n"], seed=A["bootstrap_seed"]):
    """Resample review_id clusters with replacement; returns (mean, lo, hi)."""
    rng = np.random.default_rng(seed)
    clusters = df["review_id"].unique()
    vals = []
    for _ in range(n):
        pick = rng.choice(clusters, size=len(clusters), replace=True)
        parts = [df[df["review_id"] == c] for c in pick]
        v = stat_fn(pd.concat(parts))
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            vals.append(v)
    if not vals:
        return float("nan"), float("nan"), float("nan")
    return float(np.mean(vals)), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def cohen_kappa(a, b):
    a, b = pd.Series(a), pd.Series(b)
    n, po = len(a), (a == b).mean()
    pe = sum((a == k).mean() * (b == k).mean() for k in set(a) | set(b))
    k = (po - pe) / (1 - pe) if pe < 1 else 1.0
    pabak = 2 * po - 1
    return po, k, pabak


def macro_f1(y_true, y_pred):
    f1s = []
    for c in set(y_true) | set(y_pred):
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        f1s.append(2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0)
    return float(np.mean(f1s))


def token_f1(a: str, b: str) -> float:
    ta = Counter(w for w in str(a).lower().split() if len(w) > 1)
    tb = Counter(w for w in str(b).lower().split() if len(w) > 1)
    if not ta or not tb:
        return float("nan")
    overlap = sum((ta & tb).values())
    if overlap == 0:
        return 0.0
    p, r = overlap / sum(ta.values()), overlap / sum(tb.values())
    return 2 * p * r / (p + r)


def load_jsonl(path):
    return [json.loads(l) for l in path.open()] if path.exists() else []


def load_screening(model_key: str) -> pd.DataFrame | None:
    f = config.RESULTS_DIR / model_key / "screening_results.jsonl"
    rows = load_jsonl(f)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df = df.drop_duplicates("paper_id", keep="last")   # retried papers: newest wins
    return df[df["decision"] != "error"].copy()


def load_extraction(model_key: str) -> pd.DataFrame | None:
    f = config.RESULTS_DIR / model_key / "extraction_results.jsonl"
    rows = load_jsonl(f)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df = df.drop_duplicates("article_id", keep="last")
    df = df[df["decision"] == "extracted"].copy()
    return df


REPORT = []


def say(line=""):
    print(line)
    REPORT.append(line)


# ===========================================================================
# G. context metrics (screening)
# ===========================================================================
def context_screening(df: pd.DataFrame, model_key: str) -> dict:
    out = {}
    for rule, treat_maybe in (("conservative", False), ("sensitivity_first", True)):
        pred = df["decision"].map(lambda d: ("include" if d == "include" or
                                             (treat_maybe and d == "maybe") else "exclude"))
        gold = df["gold_label"]
        tp = int(((pred == "include") & (gold == "include")).sum())
        fn = int(((pred != "include") & (gold == "include")).sum())
        tn = int(((pred != "include") & (gold == "exclude")).sum())
        fp = int(((pred == "include") & (gold == "exclude")).sum())
        out[rule] = {"tp": tp, "fn": fn, "tn": tn, "fp": fp,
                     "sens": wilson(tp, tp + fn), "spec": wilson(tn, tn + fp)}

    def sens_of(d):
        p = d["decision"].eq("include")
        g = d["gold_label"].eq("include")
        den = g.sum()
        return (p & g).sum() / den if den else None

    mean, lo, hi = cluster_bootstrap(df, sens_of)
    out["sens_cluster_boot"] = (mean, lo, hi)

    # policy metrics at frozen threshold
    tau = A["auto_threshold"]
    auto = (df["decision"] != "maybe") & (df["confidence"] >= tau)
    referred = ~auto
    fn_policy = int((auto & (df["decision"] == "exclude") & (df["gold_label"] == "include")).sum())
    n_auto = int(auto.sum())
    err_auto = int((auto & (df["decision"] != df["gold_label"])).sum())
    out["policy"] = {"tau": tau, "n_auto": n_auto, "n_referred": int(referred.sum()),
                     "wss": 1 - referred.mean() if len(df) else float("nan"),
                     "fn_policy": fn_policy, "err_auto": wilson(err_auto, n_auto)}
    return out


def per_topic_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for rid, g in df.groupby("review_id"):
        k = int(((g["decision"] == "include") & (g["gold_label"] == "include")).sum())
        n = int((g["gold_label"] == "include").sum())
        if n:
            rows.append({"review_id": rid, "n_included": n,
                         "sens": k / n, "lo": wilson(k, n)[1], "hi": wilson(k, n)[2]})
    return pd.DataFrame(rows)


# ===========================================================================
# B. calibration raw vs final
# ===========================================================================
def reliability_points(conf, correct, bins=10, min_count=3):
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    edges = np.linspace(0, 1, bins + 1)
    pts = []
    for i in range(bins):
        m = (conf > edges[i]) & (conf <= edges[i + 1]) if i else (conf <= edges[1])
        if m.sum() >= min_count:
            pts.append((float(conf[m].mean()), float(correct[m].mean()), int(m.sum())))
    return pts


def calibration(df: pd.DataFrame, model_key: str) -> dict:
    llm = df[(df["tier"] != "tier1_deterministic") & df["ai_confidence_raw"].notna()]
    correct = (llm["decision"] == llm["gold_label"]).astype(int)
    raw_conf = llm["ai_confidence_raw"].astype(float)
    # final confidence on the same subset
    final_conf = llm["confidence"].astype(float)

    # adaptive binning: frozen 10-bin scheme for the full study; small runs
    # (pilot/demo) still produce plottable points
    n = len(llm)
    if n >= 30:
        bins, min_count = A["calibration_bins"], 3
    else:
        bins, min_count = max(3, min(5, n)), 1

    res = {
        "n": len(llm),
        "raw": {"brier": brier_score(raw_conf, correct), "ece": ece(raw_conf, correct),
                "auc": auc_score(raw_conf, correct),
                "points": reliability_points(raw_conf, correct, bins, min_count)},
        "final": {"brier": brier_score(final_conf, correct), "ece": ece(final_conf, correct),
                  "auc": auc_score(final_conf, correct),
                  "points": reliability_points(final_conf, correct, bins, min_count)},
        "tier_counts": df["tier"].value_counts().to_dict(),
    }
    # per-tier accuracy (JORS medium-anomaly test)
    tiers = {}
    for tier, g in df.groupby("tier"):
        c = (g["decision"] == g["gold_label"])
        tiers[tier] = fmt_ci(int(c.sum()), len(g))
    res["tier_accuracy"] = tiers
    return res


def plot_calibration(all_cal: dict):
    n_panels = max(len(all_cal), 1)
    fig, axes = viz.new_fig(viz.DOUBLE_COL, 3.4, ncols=n_panels)
    axes = np.atleast_1d(axes)
    styles = (("raw", "--o", "Raw LLM self-assessment"),
              ("final", "-s", "Architecture-final (v3.0.0)"))
    for ax, (mk, c) in zip(axes, all_cal.items()):
        for key, style, label in styles:
            pts = c[key]["points"]
            if pts:
                x, y, s = zip(*pts)
                sizes = [max(14, min(30, 3 * s_i)) for s_i in s]
                ax.plot(x, y, style, color=viz.COLORS[mk], label=label,
                        ms=4.5, linewidth=1.0, markerfacecolor="white"
                        if key == "raw" else viz.COLORS[mk],
                        markeredgecolor=viz.COLORS[mk], zorder=3)
        ax.plot([-0.05, 1.05], [-0.05, 1.05], color=viz.COLORS["grey"], lw=0.6,
                ls=":", zorder=1)
        ax.set_title(viz.MODEL_LABELS.get(mk, mk), pad=4)
        ax.set_xlabel("Mean confidence")
        ax.set_xlim(-0.05, 1.05)
        ax.set_ylim(-0.05, 1.09)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    axes[0].set_ylabel("Observed accuracy")
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncols=len(labels),
                   frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.subplots_adjust(bottom=0.30, wspace=0.30)
    viz.save_fig(fig, "fig2_calibration_before_after")


def plot_ece_by_tier(all_cal: dict, out_rows: list):
    tiers = ["tier1_deterministic", "tier1_deterministic_score",
             "tier2_llm_selfassess", "tier1_override"]
    labels = ["T1 deterministic", "T1 det. score", "T2 self-assess", "T1 override"]
    fig, ax = viz.new_fig(viz.SINGLE_COL, 3.0)
    width = 0.27
    for i, mk in enumerate(all_cal):
        tc = all_cal[mk]["tier_counts"]
        vals = [tc.get(t, 0) / max(sum(tc.values()), 1) * 100 for t in tiers]
        ax.bar(np.arange(len(tiers)) + (i - 1) * width, vals, width,
               color=viz.COLORS[mk], label=viz.MODEL_LABELS[mk],
               edgecolor="white", linewidth=0.4)
        for t, v in zip(tiers, vals):
            out_rows.append({"model": mk, "tier": t, "share_pct": round(v, 2)})
    ax.set_xticks(range(len(tiers)))
    ax.set_xticklabels(labels, rotation=24, ha="right")
    ax.set_ylabel("Share of decisions (%)")
    ax.set_ylim(0, 132)
    ax.margins(x=0.06)
    ax.legend(frameon=False, ncols=3, loc="upper center",
              bbox_to_anchor=(0.5, 1.16), columnspacing=1.0)
    viz.save_fig(fig, "fig3_tier_shares")


# ===========================================================================
# C. override as hallucination detector (extraction arm mainly)
# ===========================================================================
def override_detector_screening(df: pd.DataFrame) -> dict | None:
    """Detector score = deterministic_confidence; event = decision incorrect."""
    llm = df[df["ai_confidence_raw"].notna()]
    if len(llm) < 10:
        return None
    incorrect = (llm["decision"] != llm["gold_label"]).astype(int)
    score = llm["deterministic_confidence"].astype(float)
    flagged = score < 0.5
    a = int((flagged & (incorrect == 1)).sum())
    b = int((flagged & (incorrect == 0)).sum())
    c = int((~flagged & (incorrect == 1)).sum())
    d = int((~flagged & (incorrect == 0)).sum())
    return {"sens": wilson(a, a + b), "spec": wilson(d, c + d),
            "auc_detector": auc_score(-score, incorrect),
            "p_err_flagged": wilson(a, a + b), "p_err_unflagged": wilson(c, c + d),
            "fisher_p": float(st.fisher_exact([[a, b], [c, d]])[1]),
            "n": len(llm), "n_flagged": int(flagged.sum())}


# ===========================================================================
# D. extraction grounding + accuracy
# ===========================================================================
def extraction_analysis(df: pd.DataFrame, model_key: str, out_rows: list) -> dict:
    verdicts = defaultdict(int)
    ungrounded = {"n_fields": 0, "n_ungrounded": 0, "n_negation": 0}
    f1_rows, dir_true, dir_pred = [], [], []
    GOLD_TO_FIELD = {"gold_intervention": "Intervention", "gold_comparator": "Comparator",
                     "gold_outcome": "Outcome"}

    def direction_match(gold: str, pred: str) -> bool:
        g = str(gold).lower().replace("significantly ", "").strip(" .")
        p = str(pred).lower().replace("significantly ", "").strip(" .")
        return bool(g) and (g in p or p in g)

    def norm_dir(s: str) -> str:
        return str(s).lower().replace("significantly ", "").replace("significant ", "").strip(" .-")

    for _, r in df.iterrows():
        g = r.get("grounding") or {}
        for f, v in g.items():
            if f in config.EXTRACT_FIELDS:      # score only the study fields
                verdicts[v.get("verdict", "?")] += 1
                ungrounded["n_fields"] += 1
                if v.get("verdict") == "ungrounded":
                    ungrounded["n_ungrounded"] += 1
                if v.get("verdict") == "negation_blocked":
                    ungrounded["n_negation"] += 1
        for gk, field in GOLD_TO_FIELD.items():
            gold_alts = [s for s in str(r["gold"].get(gk, "")).split("||") if s
                         and s.lower() != "nan"]
            extracted = r["extracted"].get(field)
            if gold_alts and extracted and str(extracted) != "Not Found":
                best = max(token_f1(extracted, alt) for alt in gold_alts)
                f1_rows.append({"field": field, "f1": best})
        gt, pt = r["gold"].get("gold_effect_direction"), r["extracted"].get("Effect Direction")
        if gt and pt and str(pt) != "Not Found":
            dir_true.append(norm_dir(gt))
            dir_pred.append(norm_dir(pt))

    for field in ("Intervention", "Comparator", "Outcome"):
        f1s = [x["f1"] for x in f1_rows if x["field"] == field and not math.isnan(x["f1"])]
        if f1s:
            out_rows.append({"model": model_key, "field": field,
                             "token_f1_mean": round(float(np.mean(f1s)), 3), "n": len(f1s)})

    res = {"verdict_shares": {k: v / max(ungrounded["n_fields"], 1)
                              for k, v in verdicts.items()},
           "ungrounded": ungrounded,
           "ungrounded_ci": wilson(ungrounded["n_ungrounded"], ungrounded["n_fields"])}
    if dir_true:
        matched = [g == p or direction_match(g, p) for g, p in zip(dir_true, dir_pred)]
        res["effect_direction"] = {
            "accuracy": fmt_ci(int(sum(matched)), len(matched)),
            "n": len(dir_true)}
    return res


def plot_grounding(all_ext: dict):
    verdicts = ["exact_match", "token_overlap", "negation_blocked", "ungrounded", "empty"]
    fig, ax = viz.new_fig(viz.SINGLE_COL, 3.2)
    bottom = np.zeros(len(verdicts))
    y = np.arange(len(verdicts))
    for mk in all_ext:
        shares = [100 * all_ext[mk]["verdict_shares"].get(v, 0) for v in verdicts]
        ax.barh(y, shares, left=bottom, color=viz.COLORS[mk],
                label=viz.MODEL_LABELS[mk], height=0.62,
                edgecolor="white", linewidth=0.4)
        bottom += np.array(shares)
    ax.set_yticks(y)
    ax.set_yticklabels(["Exact\nmatch", "Token\noverlap", "Negation\nblocked",
                        "Ungrounded", "Empty"])
    ax.set_xlim(0, 108)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.margins(y=0.12)
    ax.set_xlabel("Share of extracted fields (%)")
    ax.legend(frameon=False, ncols=1, loc="upper center", bbox_to_anchor=(0.5, -0.22),
              handlelength=1.2)
    viz.save_fig(fig, "fig8_extraction_grounding")


# ===========================================================================
# E. capability -> workload
# ===========================================================================
def workload_analysis(all_df: dict) -> dict:
    tau = A["auto_threshold"]
    stats = {}
    for mk, df in all_df.items():
        auto = (df["decision"] != "maybe") & (df["confidence"] >= tau)
        referred = ~auto
        err = int((auto & (df["decision"] != df["gold_label"])).sum())
        p, lo, hi = wilson(err, int(auto.sum()))
        stats[mk] = {"referral_rate": float(referred.mean()),
                     "auto_error": p, "auto_error_ci": (lo, hi),
                     "n_auto": int(auto.sum()), "n_referred": int(referred.sum()),
                     "wss": 1 - referred.mean()}
    boot = {}
    for mk, df in all_df.items():
        def err_of(d):
            a = (d["decision"] != "maybe") & (d["confidence"] >= tau)
            if a.sum() == 0:
                return None
            return float((a & (d["decision"] != d["gold_label"])).mean())
        boot[mk] = cluster_bootstrap(df, err_of)
    pairs = {}
    for a_m, b_m in (("gemini", "cohere"), ("ollama", "gemini"), ("ollama", "cohere")):
        if a_m in boot and b_m in boot:
            diff = boot[a_m][0] - boot[b_m][0]
            pairs[f"{a_m}_vs_{b_m}"] = {
                "diff": round(diff, 4),
                "tost_within_margin": bool(abs(diff) <= A["tost_margin"]),
                "margin": A["tost_margin"]}
    return {"per_backend": stats, "cluster_boot_err": boot, "pairs": pairs}


def plot_workload(w: dict):
    fig, ax = viz.new_fig(viz.SINGLE_COL, 3.2)
    markers = {"gemini": "o", "cohere": "s", "ollama": "^"}
    for mk, s in w["per_backend"].items():
        p = s["auto_error"] * 100
        lo, hi = s["auto_error_ci"][0] * 100, s["auto_error_ci"][1] * 100
        ax.errorbar(s["referral_rate"] * 100, p,
                    yerr=[[max(p - lo, 0)], [max(hi - p, 0)]],
                    fmt=markers.get(mk, "o"), color=viz.COLORS[mk], capsize=2.5,
                    markersize=5.5, markeredgecolor="white", markeredgewidth=0.6,
                    label=viz.MODEL_LABELS[mk])
    ax.margins(x=0.22, y=0.25)
    ax.set_xlabel("Referral rate (% of papers sent to human)")
    ax.set_ylabel("Error rate within auto-processed (%)")
    ax.axhline(A["risk_target_eps"] * 100, color=viz.COLORS["grey"], lw=0.6, ls=":")
    ax.legend(frameon=False, ncols=1, loc="upper center", bbox_to_anchor=(0.5, -0.18),
              handlelength=1.2, columnspacing=1.0)
    viz.save_fig(fig, "fig5_workload_vs_error")


# ===========================================================================
# F. conformal risk control
# ===========================================================================
def conformal_tau(df: pd.DataFrame) -> dict | None:
    """Pick tau on calibration reviews; validate the bound on held-out reviews."""
    rng = np.random.default_rng(A["bootstrap_seed"])
    reviews = df["review_id"].unique()
    rng.shuffle(reviews)
    n_cal = max(1, int(len(reviews) * A["calibration_fraction"]))
    cal_ids, val_ids = set(reviews[:n_cal]), set(reviews[n_cal:])
    cal, val = df[df["review_id"].isin(cal_ids)], df[df["review_id"].isin(val_ids)]
    if len(cal) < 30 or len(val) < 30:
        return None
    alpha = A["conformal_confidence"]
    z = st.norm.ppf(alpha)
    best_tau = None
    for tau in np.arange(0.50, 0.99, 0.01):
        auto = (cal["decision"] != "maybe") & (cal["confidence"] >= tau)
        n = int(auto.sum())
        if n < 20:
            continue
        err = float((auto & (cal["decision"] != cal["gold_label"])).mean())
        bound = err + z * math.sqrt(err * (1 - err) / n) + 1 / n
        if bound <= A["risk_target_eps"]:
            best_tau = round(float(tau), 2)
            break
    if best_tau is None:
        return {"tau": None, "note": "no threshold reached the target bound on calibration reviews"}
    auto = (val["decision"] != "maybe") & (val["confidence"] >= best_tau)
    err_v, n_v = int((auto & (val["decision"] != val["gold_label"])).sum()), int(auto.sum())
    p, lo, hi = wilson(err_v, n_v)
    return {"tau": best_tau, "eps": A["risk_target_eps"], "cal_n": len(cal), "val_n": len(val),
            "val_auto_n": n_v, "val_error": p, "val_error_ci": (lo, hi),
            "holds": bool(hi <= A["risk_target_eps"])}


# ===========================================================================
# WSS@95 sweep
# ===========================================================================
def wss_sweep(df: pd.DataFrame):
    taus = np.arange(0.5, 0.99, 0.02)
    best95 = best100 = (None, float("nan"))
    for tau in taus:
        auto = (df["decision"] != "maybe") & (df["confidence"] >= tau)
        if auto.sum() == 0:
            continue
        fn = int((auto & (df["decision"] == "exclude") & (df["gold_label"] == "include")).sum())
        sens = 1 - fn / max(int((df["gold_label"] == "include").sum()), 1)
        wss = 1 - auto.mean()
        if sens >= 0.95 and (best95[1] is None or math.isnan(best95[1]) or wss > best95[1]):
            best95 = (round(float(tau), 2), float(wss))
        if sens == 1.0 and (math.isnan(best100[1]) or wss > best100[1]):
            best100 = (round(float(tau), 2), float(wss))
    return {"wss95": best95, "wss100": best100}


# ===========================================================================
# H. adjudicated audit (human verdicts on the published gold labels)
# ===========================================================================
def load_adjudication() -> pd.DataFrame | None:
    f = config.AUDIT_DIR / "adjudication_sheet_union.xlsx"
    if not f.exists():
        return None
    df = pd.read_excel(f)
    if not {"paper_id", "human_agrees_with_gold"}.issubset(df.columns):
        return None
    df["human_agrees_with_gold"] = (df["human_agrees_with_gold"].fillna("")
                                    .astype(str).str.strip().str.lower())
    return df


def adjudicated_analysis(all_screen: dict, adj: pd.DataFrame) -> list:
    """Raw vs adjudicated screening metrics. Returns per-backend rows (also
    used by plot_adjudicated).

    The adjudication verdict is about the published gold label, so it applies
    to every backend: "no" (gold wrong) flips the effective gold label
    include<->exclude for that paper; "yes"/blank keep it; "unsure" keeps the
    published gold (conservative) and is reported separately. Papers not in
    the sheet were never flagged, so their gold stands.
    """
    rows = []
    verdict = adj.set_index("paper_id")["human_agrees_with_gold"]
    stratum = (adj.set_index("paper_id")["audit_stratum"]
               if "audit_stratum" in adj.columns else None)

    say("\n[H] adjudicated audit (human verdicts on the published gold labels):")
    filled = adj[adj["human_agrees_with_gold"].isin(["yes", "no", "unsure"])]
    if not len(filled):
        say("    sheet found but no verdicts filled yet — run 06_auto_audit.py, "
            "adjudicate, then re-run 05_stats.py (metrics unchanged meanwhile)")
        return []
    n_blank = len(adj) - len(filled)
    if n_blank:
        say(f"    {n_blank}/{len(adj)} sheet rows still blank — they keep the "
            "published gold label")
    if stratum is not None:
        tab = (filled.assign(audit_stratum=filled["paper_id"].map(stratum))
               .groupby(["audit_stratum", "human_agrees_with_gold"])
               .size().unstack(fill_value=0))
        say("    verdicts by stratum (yes = gold correct, no = gold wrong):")
        for s, r in tab.iterrows():
            cells = ", ".join(f"{k}={int(v)}" for k, v in r.items() if v)
            say(f"      {s}: {cells}")
    else:
        vc = filled["human_agrees_with_gold"].value_counts().to_dict()
        say("    verdicts: " + ", ".join(f"{k}={v}" for k, v in sorted(vc.items())))

    for mk, df in all_screen.items():
        v = df["paper_id"].map(verdict).fillna("")
        eff = df["gold_label"].astype(str).str.strip().str.lower()
        overturned = v == "no"
        # a "no" verdict overturns the published label: flip the binary gold
        flip = {"include": "exclude", "exclude": "include"}
        eff = eff.where(~overturned, other=eff.map(flip).combine_first(eff))
        n_unsure = int((v == "unsure").sum())
        oved = df.loc[overturned]
        n_oved = int(overturned.sum())

        raw_ok = df["decision"] == df["gold_label"]
        adj_ok = df["decision"] == eff
        n = len(df)

        def sens_spec(gold: pd.Series):
            pred_inc = df["decision"] == "include"
            gold_inc = gold == "include"
            tp = int((pred_inc & gold_inc).sum())
            fn = int((~pred_inc & gold_inc).sum())
            tn = int((~pred_inc & ~gold_inc).sum())
            fp = int((pred_inc & ~gold_inc).sum())
            return wilson(tp, tp + fn), wilson(tn, tn + fp)

        raw_sens, raw_spec = sens_spec(df["gold_label"])
        adj_sens, adj_spec = sens_spec(eff)

        say(f"    {viz.MODEL_LABELS.get(mk, mk)}: gold overturned for "
            f"{fmt_ci(n_oved, len(filled))} of adjudicated papers"
            + (f" (unsure kept as gold: {n_unsure})" if n_unsure else ""))
        say(f"    {mk}: accuracy raw {fmt_w(wilson(int(raw_ok.sum()), n))} -> "
            f"adjudicated {fmt_w(wilson(int(adj_ok.sum()), n))}; "
            f"{int((raw_ok != adj_ok).sum())} decisions reclassified")
        say(f"    {mk}: sensitivity raw {fmt_w(raw_sens)} -> adjudicated "
            f"{fmt_w(adj_sens)}; specificity raw {fmt_w(raw_spec)} -> "
            f"adjudicated {fmt_w(adj_spec)}")

        rows.append({
            "model": mk, "n": n,
            "n_overturned": n_oved,
            "overturn_rate": round(n_oved / len(filled), 4) if len(filled) else None,
            "n_unsure_kept_gold": n_unsure,
            "n_reclassified": int((raw_ok != adj_ok).sum()),
            "raw_accuracy": round(raw_ok.mean(), 4),
            "adj_accuracy": round(adj_ok.mean(), 4),
            "raw_sensitivity": round(raw_sens[0], 4),
            "adj_sensitivity": round(adj_sens[0], 4),
            "raw_specificity": round(raw_spec[0], 4),
            "adj_specificity": round(adj_spec[0], 4),
        })

    pd.DataFrame(rows).to_csv(config.STATS_DIR / "adjudicated_metrics.csv",
                              index=False)
    return rows


def plot_adjudicated(rows: list):
    """Dumbbell chart: raw -> adjudicated sensitivity/specificity per backend."""
    fig, axes = viz.new_fig(viz.DOUBLE_COL, 2.7, ncols=2)
    for ax, rk, ak, title in (
            (axes[0], "raw_sensitivity", "adj_sensitivity", "Sensitivity"),
            (axes[1], "raw_specificity", "adj_specificity", "Specificity")):
        for r in rows:
            mk = r["model"]
            ax.plot([0, 1], (r[rk] * 100, r[ak] * 100), "-o",
                    color=viz.COLORS[mk], label=viz.MODEL_LABELS.get(mk, mk),
                    ms=4.5, linewidth=1.1, markeredgecolor="white",
                    markeredgewidth=0.5, zorder=3)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Raw\n(published gold)", "Adjudicated"])
        ax.set_xlim(-0.3, 1.3)
        ax.set_ylim(0, 104)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_ylabel(f"{title} (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncols=len(labels),
                   frameon=False, bbox_to_anchor=(0.5, -0.04))
    fig.subplots_adjust(bottom=0.30, wspace=0.32)
    viz.save_fig(fig, "fig9_adjudicated_impact")


# ===========================================================================
# main
# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=MODELS_DEFAULT)
    args = ap.parse_args()

    all_screen, all_cal, all_ext = {}, {}, {}
    out_rows = []

    for mk in args.models:
        df = load_screening(mk)
        if df is None:
            say(f"[skip] {mk}: no screening results")
            continue
        all_screen[mk] = df
        say(f"\n================ {viz.MODEL_LABELS[mk]} (screening, N={len(df)}) ================")

        ctx = context_screening(df, mk)
        for rule in ("conservative", "sensitivity_first"):
            c = ctx[rule]
            say(f"[G] {rule}: sensitivity {fmt_ci(c['tp'], c['tp']+c['fn'])} | "
                f"specificity {fmt_ci(c['tn'], c['tn']+c['fp'])}")
        m, lo, hi = ctx["sens_cluster_boot"]
        say(f"[G] sensitivity, cluster bootstrap by review: {100*m:.1f}% [{100*lo:.1f}, {100*hi:.1f}]")
        p = ctx["policy"]
        if p["n_auto"]:
            say(f"[G] policy tau={p['tau']}: auto {p['n_auto']}, referred {p['n_referred']} "
                f"(WSS {100*p['wss']:.1f}%), errors in auto: "
                f"{fmt_ci(round(p['err_auto'][0]*p['n_auto']), p['n_auto'])}")
        else:
            say("[G] policy: no auto-processed papers at frozen tau")
        say(f"[G] policy missed includes at tau: {p['fn_policy']}")
        wss = wss_sweep(df)
        say(f"[G] WSS@95 (tau, value): {wss['wss95']} | WSS@100: {wss['wss100']}")

        cal = calibration(df, mk)
        all_cal[mk] = cal
        say(f"[B] calibration N={cal['n']}: RAW Brier {cal['raw']['brier']:.3f}, "
            f"ECE {cal['raw']['ece']:.3f}, AUC {cal['raw']['auc']:.3f} -> FINAL Brier "
            f"{cal['final']['brier']:.3f}, ECE {cal['final']['ece']:.3f}, AUC {cal['final']['auc']:.3f}")
        say(f"[B] tier accuracy: " + "; ".join(f"{k}: {v}" for k, v in cal["tier_accuracy"].items()))

        det = override_detector_screening(df)
        if det:
            say(f"[C] override-as-detector: P(err|flag)={fmt_w(det['p_err_flagged'])}, "
                f"P(err|no-flag)={fmt_w(det['p_err_unflagged'])}, "
                f"detector AUC={det['auc_detector']:.3f}, fisher p={det['fisher_p']:.2g} "
                f"(n_flagged={det['n_flagged']}/{det['n']})")

        par = conformal_tau(df)
        if par:
            if par["tau"] is None:
                say(f"[F] conformal: no threshold reached the target bound ({par['note']})")
            else:
                say(f"[F] conformal: tau={par['tau']}, held-out auto-processed error "
                    f"{fmt_ci(round(par['val_error']*par['val_auto_n']), par['val_auto_n'])}, "
                    f"bound (<= {100*par['eps']:.0f}%) holds: {par['holds']}")

        op = df.groupby("tier").size()
        lat = df["latency_s"].astype(float)
        say(f"[A] latency s/paper: median {lat.median():.1f}, mean {lat.mean():.1f}; "
            f"parse_ok {100*df['parse_ok'].mean():.1f}%")
        out_rows.append({"model": mk, "median_latency_s": round(float(lat.median()), 2),
                         "parse_ok_rate": round(float(df['parse_ok'].mean()), 4),
                         **{f"n_{k}": int(v) for k, v in op.items()}})

        ext = load_extraction(mk)
        if ext is not None:
            ea = extraction_analysis(ext, mk, out_rows)
            all_ext[mk] = ea
            u = ea["ungrounded"]
            say(f"[D] extraction N={len(ext)}: ungrounded fields {fmt_ci(u['n_ungrounded'], u['n_fields'])}"
                f", negation-blocked {u['n_negation']}")
            if "effect_direction" in ea:
                ed = ea["effect_direction"]
                say(f"[D] effect direction: acc {ed['accuracy']} (n={ed['n']})")

    if all_screen:
        w = workload_analysis(all_screen)
        say("\n[E] capability -> workload:")
        for mk, s in w["per_backend"].items():
            say(f"    {viz.MODEL_LABELS[mk]}: referral {100*s['referral_rate']:.1f}%, "
                f"auto-processed error {100*s['auto_error']:.2f}% "
                f"[{100*s['auto_error_ci'][0]:.2f}, {100*s['auto_error_ci'][1]:.2f}], WSS {100*s['wss']:.1f}%")
        for pair, v in w["pairs"].items():
            say(f"    {pair}: diff {100*v['diff']:.2f} pp, within +-{100*v['margin']:.0f} pp margin: {v['tost_within_margin']}")
        plot_workload(w)
        plot_calibration(all_cal)
        plot_ece_by_tier(all_cal, out_rows)
    if all_ext:
        plot_grounding(all_ext)

    if all_screen:
        adj = load_adjudication()
        if adj is not None:
            adj_rows = adjudicated_analysis(all_screen, adj)
            if adj_rows:
                plot_adjudicated(adj_rows)
        else:
            say("\n[H] adjudicated audit skipped: "
                "results/audit/adjudication_sheet_union.xlsx not found "
                "(run 04_audit.py --models ... then 06_auto_audit.py, "
                "adjudicate, and re-run 05_stats.py)")

    pd.DataFrame(out_rows).to_csv(config.STATS_DIR / "operational_profile.csv", index=False)
    pd.DataFrame(out_rows).to_csv(config.STATS_DIR / "summary_tables.csv", index=False)
    (config.STATS_DIR / "stats_report.md").write_text(
        "# ReviewAid v3.0.0 validation — auto-generated statistics report\n\n"
        + "\n".join(REPORT) + "\n")
    print(f"\n[done] report -> {config.STATS_DIR/'stats_report.md'}; "
          f"figures -> {config.FIG_DIR}")


if __name__ == "__main__":
    main()

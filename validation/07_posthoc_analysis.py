#!/usr/bin/env python3
"""Post-hoc analyses for the ReviewAid v3.0.0 validation study.

Purely offline: reads the already-collected screening/extraction JSONLs and the
frozen corpus, and adds the analyses that contextualise 05_stats.py for
publication. It NEVER calls any backend/API and NEVER writes to the 05_stats
outputs (results/stats/stats_report.md, *_tables.csv, adjudicated_metrics.csv,
operational_profile.csv) or to results/{ollama,ollamads,cohere}/.

Sections
  [P1] Decision-layer decomposition - accuracy per decision layer (keyword
       tier, deterministic-score/fallback tier, LLM override, LLM self-assess),
       per backend. Separates "what the model said" from "what the machinery
       decided".
  [P2] Counterfactuals - as-run vs keyword-tier-off vs LLM-decided-only
       sensitivity/specificity/accuracy with Wilson 95% CIs.
  [P3] Recall-vs-workload operating curves + WSS@95/WSS@90 on the LLM-decided
       subset, ranked by the AI's own confidence; review-cluster bootstrap CIs.
       Also recall@k prioritization (top 10/20/30/50% of the ranked queue).
  [P4] Effect-direction accuracy, strict (05_stats substring rule) vs fuzzy
       (3-class root matching), with Wilson CIs.
  [P5] Tier-1 keyword audit - which exclusion keywords fired, how often, and
       how often they killed a gold-include.

Usage:  python 07_posthoc_analysis.py
Outputs: results/stats/posthoc_*.csv, results/stats/posthoc_report.md,
         results/figures/fig10_recall_vs_workload.{svg,png}
"""
import csv
import json
import math
import re
import collections
import numpy as np

BASE = "results"
CORPUS = "corpus"
MODELS = [("ollamads", "DeepSeek-V2-Lite 16B"),
          ("cohere", "Command-A"),
          ("ollama", "Llama3.2-3B")]
BOOT_N = 2000
RNG_SEED = 42
FIG_LABEL = {"ollamads": "DeepSeek-V2-Lite 16B", "cohere": "Command-A",
             "ollama": "Llama3.2-3B (local)"}


# ---------- helpers ----------
def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 3
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def fmt_ci(k, n):
    p, lo, hi = wilson(k, n)
    return f"{p * 100:.1f}% [{lo * 100:.1f}, {hi * 100:.1f}] (n={n})"


def load_gold():
    gold = {}
    with open(f"{CORPUS}/gold_labels.csv") as f:
        for r in csv.DictReader(f):
            gold[r["paper_id"]] = r["gold_label"]
    return gold


def load_extraction(model):
    """Newest extraction row per article_id."""
    best = {}
    with open(f"{BASE}/{model}/extraction_results.jsonl") as f:
        for line in f:
            r = json.loads(line)
            best[r["article_id"]] = r
    return list(best.values())


def load_screening(model, gold):
    """Newest row wins per paper_id, restricted to the gold corpus."""
    best = {}
    with open(f"{BASE}/{model}/screening_results.jsonl") as f:
        for line in f:
            r = json.loads(line)
            if r["paper_id"] in gold:
                best[r["paper_id"]] = r
    return list(best.values())


def sens_spec(rows, gold):
    inc = [r for r in rows if gold[r["paper_id"]] == "include"]
    exc = [r for r in rows if gold[r["paper_id"]] == "exclude"]
    tp = sum(1 for r in inc if r["decision"] == "include")
    fn = len(inc) - tp
    tn = sum(1 for r in exc if r["decision"] == "exclude")
    fp = len(exc) - tn
    return tp, fn, tn, fp


def llama_conf(raw):
    """Inclusion score from the AI's own confidence (pre-override)."""
    if raw is None:
        return None
    raw = float(raw)
    return raw


# ---------- [P1] layer decomposition + [P2] counterfactuals ----------
def layers_and_counterfactuals(rows, gold):
    groups = {
        "keyword_tier": lambda r: r["tier"] == "tier1_deterministic",
        "deterministic_score/fallback": lambda r: r["tier"] == "tier1_deterministic_score",
        "llm_override": lambda r: r["tier"] == "tier1_override",
        "llm_selfassess": lambda r: r["tier"] == "tier2_llm_selfassess",
    }
    out = []
    for name, pred in groups.items():
        sub = [r for r in rows if pred(r)]
        if not sub:
            continue
        tp, fn, tn, fp = sens_spec(sub, gold)
        n_inc, n_exc = tp + fn, tn + fp
        out.append({"layer": name, "n": len(sub), "sens": fmt_ci(tp, n_inc),
                    "spec": fmt_ci(tn, n_exc), "acc": fmt_ci(tp + tn, len(sub)),
                    "wrong_excludes": fn, "wrong_includes": fp})
    return out


def counterfactuals(rows, gold):
    res = {}
    tp, fn, tn, fp = sens_spec(rows, gold)
    res["as_run"] = {"n": len(rows), "sens": fmt_ci(tp, tp + fn),
                     "spec": fmt_ci(tn, tn + fp), "acc": fmt_ci(tp + tn, len(rows))}
    kw_off = [r for r in rows if r["tier"] != "tier1_deterministic"]
    tp, fn, tn, fp = sens_spec(kw_off, gold)
    res["keyword_tier_off"] = {"n": len(kw_off), "sens": fmt_ci(tp, tp + fn),
                               "spec": fmt_ci(tn, tn + fp), "acc": fmt_ci(tp + tn, len(kw_off))}
    llm = [r for r in rows if r.get("ai_confidence_raw") is not None]
    tp, fn, tn, fp = sens_spec(llm, gold)
    res["llm_decided_only"] = {"n": len(llm), "sens": fmt_ci(tp, tp + fn),
                               "spec": fmt_ci(tn, tn + fp), "acc": fmt_ci(tp + tn, len(llm))}
    return res


# ---------- [P3] recall-vs-workload ----------
def operating_curve(rows, score_fn):
    """rows: LLM-decided rows. score in [0,1] = P(include)-ish. Sweep cut:
    score >= t -> 'include' (human reads), else auto-excluded."""
    scored = [(score_fn(r), r) for r in rows]
    scored = [(s, r) for s, r in scored if s is not None]
    scored.sort(key=lambda x: -x[0])
    n_inc = sum(1 for _, r in scored if r["gold_label"] == "include")
    n = len(scored)
    tp = 0
    pts = []
    for i, (s, r) in enumerate(scored):
        if r["gold_label"] == "include" and r["decision"] == "include":
            tp += 1
        elif r["gold_label"] == "include" and r["decision"] != "include":
            tp += 0
        # recall proxy: gold includes found in the referred queue regardless of decision
        pts.append((i + 1, s))
    # recompute properly: referred = first i rows
    inc_rank = [1 if r["gold_label"] == "include" else 0 for _, r in scored]
    csum = np.cumsum(inc_rank)
    recall = csum / max(n_inc, 1)
    workload = [1 - (i + 1) / n for i in range(n)]  # WSS if queue were the auto-include set
    return scored, recall, workload, n_inc, n


def wss_at_recall(scored, recall, workload, target):
    """Max fraction auto-excluded while gold-include recall >= target, by
    referring the top of the ranked queue."""
    best = float("nan")
    for i, rc in enumerate(recall):
        if rc >= target:
            best = workload[i]
            break
    return best


def recall_at_k(scored, recall, n):
    out = {}
    for k in (0.10, 0.20, 0.30, 0.50):
        i = min(int(k * n) - 1, n - 1)
        out[f"recall@top{int(k * 100)}%"] = recall[i]
    return out


def boot_wss95(scored, target=0.95):
    """Review-cluster bootstrap for max WSS at recall>=target."""
    by_rev = collections.defaultdict(list)
    for rank, (s, r) in enumerate(scored):
        by_rev[r["review_id"]].append((s, r))
    revs = list(by_rev.values())
    rng = np.random.default_rng(RNG_SEED)
    vals = []
    for _ in range(BOOT_N):
        sample = [r for grp in (revs[i] for i in rng.integers(0, len(revs), len(revs)))
                  for r in grp]
        sample.sort(key=lambda x: -x[0])
        n_inc = sum(1 for _, r in sample if r["gold_label"] == "include")
        if n_inc == 0:
            continue
        csum = np.cumsum([1 if r["gold_label"] == "include" else 0 for _, r in sample])
        rc = csum / n_inc
        wl = [1 - (i + 1) / len(sample) for i in range(len(sample))]
        v = wss_at_recall(sample, rc, wl, target)
        if not math.isnan(v):
            vals.append(v)
    if not vals:
        return (float("nan"),) * 2
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


# ---------- [P4] effect direction ----------
DIR_ROOTS = (
    (re.compile(r"no (?:significant |statistically significant )?(?:difference|effect|change)|"
                r"comparable|similar (?:efficacy|effect|outcome)|did not (?:differ|change)", re.I), "no difference"),
    (re.compile(r"decreas|reduc|lower|declin|deteriorat|worsen", re.I), "decreased"),
    (re.compile(r"increas|improv|higher|elevat|superior", re.I), "increased"),
)


def fuzzy_dir(s):
    s = str(s).lower()
    for rx, cls in DIR_ROOTS:
        if rx.search(s):
            return cls
    return None


def strict_dir_match(g, p):
    g = str(g).lower().replace("significantly ", "").strip(" .")
    p = str(p).lower().replace("significantly ", "").strip(" .")
    return bool(g) and (g in p or p in g)


def direction(rows):
    strict = fuzz = n = 0
    for r in rows:
        ex = r.get("extracted") or {}
        gt = (r.get("gold") or {}).get("gold_effect_direction")
        pt = ex.get("Effect Direction")
        if not gt or not pt or str(pt) == "Not Found":
            continue
        n += 1
        if strict_dir_match(gt, pt):
            strict += 1
        if fuzzy_dir(gt) is not None and fuzzy_dir(gt) == fuzzy_dir(pt):
            fuzz += 1
    return strict, fuzz, n


# ---------- [P5] keyword audit ----------
def keyword_audit(rows, gold):
    wrong_kw = collections.Counter()
    all_kw = collections.Counter()
    n_kw_exc = n_kw_exc_wrong = 0
    for r in rows:
        if r["tier"] == "tier1_deterministic" and r["decision"] == "exclude":
            n_kw_exc += 1
            wrong = gold[r["paper_id"]] == "include"
            if wrong:
                n_kw_exc_wrong += 1
            t1 = (r.get("tier1_keyword") or {}).get("exclusion_matches") or []
            for kw in t1:
                all_kw[kw] += 1
                if wrong:
                    wrong_kw[kw] += 1
    top = all_kw.most_common(12)
    return n_kw_exc, n_kw_exc_wrong, [(kw, c, wrong_kw.get(kw, 0)) for kw, c in top]


# ---------- main ----------
def main():
    gold = load_gold()
    rng = np.random.default_rng(RNG_SEED)
    lines = ["# ReviewAid v3.0.0 validation — post-hoc analyses (offline)",
             "",
             "Generated by `07_posthoc_analysis.py` from the deposited run data; no API calls. "
             "Complements `stats_report.md` (which is unchanged). Wilson 95% CIs unless noted; "
             "WSS@95 bootstrap is review-cluster (2,000 resamples, seed 42).", ""]
    csv_layers, csv_cf, csv_ops, csv_dir, csv_kw = [], [], [], [], []
    curves = {}
    for key, label in MODELS:
        rows = load_screening(key, gold)
        for r in rows:
            r["gold_label"] = gold[r["paper_id"]]
        lines.append(f"================ {label} ================")

        # [P1]
        lines.append("[P1] accuracy by decision layer:")
        lay = layers_and_counterfactuals(rows, gold)
        for d in lay:
            lines.append(f"    {d['layer']:<28} n={d['n']:<5} sens {d['sens']}  spec {d['spec']}  acc {d['acc']}")
            csv_layers.append({"model": key, **d})

        # [P2]
        lines.append("[P2] counterfactuals:")
        cf = counterfactuals(rows, gold)
        for name, d in cf.items():
            lines.append(f"    {name:<18} n={d['n']:<5} sens {d['sens']}  spec {d['spec']}  acc {d['acc']}")
            csv_cf.append({"model": key, "scenario": name, **d})

        # [P3] operating curve on the LLM-decided subset
        llm = [r for r in rows if r.get("ai_confidence_raw") is not None]
        def score_fn(r):
            raw = float(r["ai_confidence_raw"])
            return raw if r["decision"] == "include" else 1.0 - raw
        scored, recall, workload, n_inc, n = operating_curve(llm, score_fn)
        curves[key] = (recall, workload)
        w95 = wss_at_recall(scored, recall, workload, 0.95)
        w90 = wss_at_recall(scored, recall, workload, 0.90)
        lo, hi = boot_wss95(scored)
        lines.append(f"[P3] ranked queue (LLM-decided subset, n={n}, gold-includes={n_inc}); "
                     f"score = AI confidence (pre-override), include-side inverted")
        lines.append(f"    max workload saved at recall>=95%: "
                     + (f"{w95 * 100:.1f}% [{lo * 100:.1f}, {hi * 100:.1f}]" if not math.isnan(w95)
                        else f"not reachable (best recall {recall[-1] * 100:.1f}%)"))
        lines.append(f"    max workload saved at recall>=90%: "
                     + (f"{w90 * 100:.1f}%" if not math.isnan(w90) else "not reachable"))
        for k, v in recall_at_k(scored, recall, n).items():
            lines.append(f"    {k}: {v * 100:.1f}% of gold-includes")
        csv_ops.append({"model": key, "n_llm_decided": n, "n_gold_includes": n_inc,
                        "wss_at_recall95": w95, "wss95_boot_lo": lo, "wss95_boot_hi": hi,
                        "wss_at_recall90": w90,
                        **recall_at_k(scored, recall, n)})

        # [P4]
        ext = load_extraction(key)
        s, fz, nd = direction(ext)
        lines.append(f"[P4] effect direction (all extraction rows): strict {fmt_ci(s, nd)} | fuzzy-3class {fmt_ci(fz, nd)}")
        csv_dir.append({"model": key, "source": "all extraction rows", "n": nd,
                        "strict_acc": fmt_ci(s, nd), "fuzzy_acc": fmt_ci(fz, nd)})

        # [P5]
        n_kw, n_wrong, topkws = keyword_audit(rows, gold)
        lines.append(f"[P5] Tier-1 keyword auto-exclusions: {n_kw} papers, {n_wrong} killed a gold-include")
        for kw, c, w in topkws:
            lines.append(f"      '{kw}': fired {c}x, wrong {w}x")
            csv_kw.append({"model": key, "keyword": kw, "fires": c, "wrong_kills_include": w})
        lines.append("")

    # figure
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6.2, 4.6))
        for key, label in MODELS:
            rc, wl = curves[key]
            ax.plot(np.asarray(wl) * 100, np.asarray(rc) * 100, label=FIG_LABEL[key])
        ax.set_xlabel("Workload saved (% of papers auto-excluded)")
        ax.set_ylabel("Recall of gold-includes")
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.axvline(0, color="grey", lw=0.5)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        ax.set_title("Screening operating curves (LLM-decided subset, ranked by AI confidence)")
        fig.tight_layout()
        for ext in ("svg", "png"):
            fig.savefig(f"{BASE}/figures/fig10_recall_vs_workload.{ext}", dpi=600)
        lines.append("Figure: `results/figures/fig10_recall_vs_workload.svg` / `.png`")
    except Exception as e:  # pragma: no cover
        lines.append(f"(figure skipped: {e})")

    with open(f"{BASE}/stats/posthoc_report.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    for name, rws in [("posthoc_layers.csv", csv_layers), ("posthoc_counterfactuals.csv", csv_cf),
                      ("posthoc_operating_points.csv", csv_ops), ("posthoc_direction.csv", csv_dir),
                      ("posthoc_keywords.csv", csv_kw)]:
        if rws:
            with open(f"{BASE}/stats/{name}", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rws[0].keys()))
                w.writeheader()
                w.writerows(rws)
    print("\n".join(lines))


if __name__ == "__main__":
    main()

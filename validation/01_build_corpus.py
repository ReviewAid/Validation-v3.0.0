"""Build the two gold-standard corpora.

Arms
----
--arm evidenceinference   Extraction corpus (default-ready, zero API keys):
                          downloads annotations + prompts + full texts from the
                          official jayded/evidence-inference GitHub repo, renders
                          each article's text into a PDF ReviewAid can ingest,
                          writes corpus/extraction_tasks.csv with gold fields.

--arm csmed               Screening corpus: needs CSMeD-FT metadata (one-time
                          bootstrap, see instructions the script prints), then
                          fetches OA PDFs (Semantic Scholar -> Unpaywall -> CORE
                          -> Europe PMC), writes corpus/gold_labels.csv and a
                          criteria template (corpus/criteria_to_fill.json) the
                          user fills VERBATIM from each review's published
                          eligibility criteria -> --finalize-criteria builds
                          corpus/reviews.json.

--arm demo                3 synthetic PDFs + labels + criteria for offline
                          end-to-end testing of 02->05 without spending quota.

All steps are resumable; every downloaded PDF is content-verified.
"""
import argparse
import json
import os
import re
import sys
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import config

GH_RAW = "https://raw.githubusercontent.com/jayded/evidence-inference/master"
GH_API = "https://api.github.com/repos/jayded/evidence-inference"
UA = {"User-Agent": "ReviewAid-validation/1.0 (academic use)"}


def _get(url, **kw):
    r = requests.get(url, headers=UA, timeout=60, **kw)
    r.raise_for_status()
    return r


# ===========================================================================
# EvidenceInference (extraction arm)
# ===========================================================================
def _list_txt_files() -> list[str]:
    r = _get(f"{GH_API}/git/trees/master?recursive=1")
    paths = [t["path"] for t in r.json()["tree"]
             if t["path"].startswith("annotations/txt_files/") and t["type"] == "blob"]
    return paths


def _download_txts(paths: list[str]) -> dict:
    done = {}
    todo = [p for p in paths if not (config.RAW_DIR / "ei_txt" / Path(p).name).exists()
            or (config.RAW_DIR / "ei_txt" / Path(p).name).stat().st_size == 0]
    print(f"[ei] full texts: {len(paths) - len(todo)} cached, {len(todo)} to download")
    tdir = config.RAW_DIR / "ei_txt"
    tdir.mkdir(parents=True, exist_ok=True)

    def _one(p):
        for attempt in range(4):
            try:
                r = _get(f"{GH_RAW}/{p}")
                out = tdir / Path(p).name
                out.write_bytes(r.content)
                return p, out
            except Exception:
                if attempt == 3:
                    return p, None
                time.sleep(2 * (attempt + 1))

    with ThreadPoolExecutor(max_workers=8) as pool:
        for fut in as_completed({pool.submit(_one, p) for p in todo}):
            p, out = fut.result()
            if out:
                done[p] = out
            if len(done) % 200 == 0 and done:
                print(f"[ei] downloaded {len(done)}/{len(todo)}")
    print(f"[ei] downloaded {len(done)}/{len(todo)} this run")
    return done


def _render_pdf(text: str, out_pdf: Path) -> None:
    import fitz
    doc = fitz.open()
    CHARS_PER_PAGE = 4500
    for i in range(0, max(len(text), 1), CHARS_PER_PAGE):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(36, 36, 576, 806), text[i:i + CHARS_PER_PAGE],
                            fontname="helv", fontsize=8)
    doc.save(str(out_pdf))
    doc.close()


def build_evidenceinference(limit: int = 0) -> None:
    import pandas as pd

    ann_p = config.RAW_DIR / "annotations_merged.csv"
    prm_p = config.RAW_DIR / "prompts_merged.csv"
    if not ann_p.exists():
        ann_p.write_bytes(_get(f"{GH_RAW}/annotations/annotations_merged.csv").content)
    if not prm_p.exists():
        prm_p.write_bytes(_get(f"{GH_RAW}/annotations/prompts_merged.csv").content)

    ann = pd.read_csv(ann_p)
    prm = pd.read_csv(prm_p)
    print(f"[ei] annotations: {len(ann)} rows, columns: {list(ann.columns)}")
    print(f"[ei] prompts:     {len(prm)} rows, columns: {list(prm.columns)}")

    # Resolve columns defensively (schema per Lehman et al. 2019)
    def col(df, *cands):
        for c in df.columns:
            if c.lower() in {x.lower() for x in cands}:
                return c
        raise KeyError(f"none of {cands} in {list(df.columns)}")

    prm_pid = col(prm, "PromptID")
    prm_pmc = col(prm, "PMCID")
    prm_i, prm_c, prm_o = col(prm, "Intervention", "I"), col(prm, "Comparator", "C"), col(prm, "Outcome", "O")
    ann_pid = col(ann, "PromptID")
    ann_label = col(ann, "Label")

    # Gold effect direction per prompt = majority label across annotators
    # (prefer rows where the label was validated).
    if "Valid Label" in ann.columns:
        ann_ok = ann[ann["Valid Label"].astype(str).str.lower() == "true"]
        ann_gold = ann_ok if len(ann_ok) else ann
    else:
        ann_gold = ann
    gold_prompt = ann_gold.groupby(ann_pid)[ann_label].agg(
        lambda s: s.mode().iat[0])

    paths = _list_txt_files()
    _download_txts(paths)
    tdir = config.RAW_DIR / "ei_txt"

    def _txt_name(pmcid: str) -> Path:
        # prompts store bare numeric IDs ("2206488"); repo files are "PMC2206488.txt"
        return tdir / (f"{pmcid}.txt" if pmcid.lower().startswith("pmc")
                       else f"PMC{pmcid}.txt")

    # Aggregate per ARTICLE (a PMCID has several prompts with different I/C/O;
    # gold strings are pipe-joined and 05_scores takes the best token-F1 match).
    from collections import defaultdict
    art = defaultdict(lambda: {"labels": [], "interv": set(), "comp": set(),
                               "out": set(), "n_prompts": 0})
    skipped_label = 0
    for _, row in prm.iterrows():
        pid = row[prm_pid]
        if pid not in gold_prompt.index:
            skipped_label += 1
            continue
        pmcid = str(row[prm_pmc]).strip()
        a = art[pmcid]
        a["n_prompts"] += 1
        a["labels"].append(str(gold_prompt[pid]))
        for key, colname in (("interv", prm_i), ("comp", prm_c), ("out", prm_o)):
            v = str(row[colname]).strip()
            if v and v.lower() != "nan":
                a[key].add(v)

    tasks, missing_txt = [], 0
    for pmcid, a in art.items():
        txt = _txt_name(pmcid)
        if not txt.exists() or txt.stat().st_size == 0:
            missing_txt += 1
            continue
        from collections import Counter
        labels = Counter(a["labels"])
        mode_label, mode_n = labels.most_common(1)[0]
        pdf = config.EXTRACT_PDF_DIR / f"PMC{pmcid.replace('PMC', '')}.pdf"
        if not pdf.exists():
            _render_pdf(txt.read_text(errors="ignore"), pdf)
        tasks.append({
            "article_id": f"PMC{pmcid.replace('PMC', '')}",
            "filename": pdf.name,
            "gold_intervention": "||".join(sorted(a["interv"])),
            "gold_comparator": "||".join(sorted(a["comp"])),
            "gold_outcome": "||".join(sorted(a["out"])),
            "gold_effect_direction": mode_label,
            "label_variety": len(labels),
            "n_prompts": a["n_prompts"],
            "txt_source": f"{GH_RAW}/annotations/txt_files/{txt.name}",
        })
        if limit and len(tasks) >= limit:
            break

    out = config.CORPUS_DIR / "extraction_tasks.csv"
    if limit and len(tasks) > limit:
        import random
        random.seed(42)  # pre-specified subsample, deterministic
        tasks = random.sample(tasks, limit)
        print(f"[ei] subsampled to {limit} articles (seed 42) to cap API budget")
    pd.DataFrame(tasks).to_csv(out, index=False)
    variety = sum(1 for t in tasks if t["label_variety"] > 1)
    print(f"[ei] extraction corpus: {len(tasks)} articles -> {out}")
    print(f"[ei] {sum(t['n_prompts'] for t in tasks)} prompts collapsed into "
          f"{len(tasks)} articles; {variety} articles have mixed direction labels")
    print(f"[ei] skipped: {missing_txt} without full text, {skipped_label} prompts without label")
    (config.CORPUS_DIR / "extraction_readme.txt").write_text(
        "Extraction corpus: EvidenceInference (Lehman et al., NAACL 2019; 2.0).\n"
        "Full texts are repo-provided .txt files rendered to PDF for ReviewAid's\n"
        "PDF ingest (PyMuPDF); provenance in extraction_tasks.csv txt_source.\n"
        "Gold: prompts_merged.csv I/C/O descriptions (pipe-joined alternatives\n"
        "per article) + annotations_merged.csv majority effect-direction label.\n"
        "Scoring takes the best token-F1 across the gold alternatives.\n")


# ===========================================================================
# CSMeD screening arm
# ===========================================================================
CSMED_LOCAL_NOTE = """CSMeD-FT screening corpus (local, zero setup)
=============================================
The pre-built CSMeD-FT.zip ships inside the cloned dataset repo:
  systematic-review-datasets/data/CSMeD/CSMeD-FT/  (train/dev/test CSVs)
Each row has the human full-text decision (included/excluded), exclusion
reason, DOI/PMID, and the GROBID-parsed main text. This script renders the
main text into PDFs for ReviewAid, selects reviews to reach the study
targets, and writes corpus/gold_labels.csv + a criteria template.
"""


def find_csmed_dir(cli_path: str) -> Path:
    candidates = []
    if cli_path:
        candidates.append(Path(cli_path))
    candidates += [
        config.BASE / "systematic-review-datasets" / "data" / "CSMeD",
        config.RAW_CACHE,
    ]
    import zipfile
    for c in candidates:
        if not c.exists():
            continue
        ft = c / "CSMeD-FT" if (c / "CSMeD-FT").is_dir() else c
        if (ft / "CSMeD-FT-train.csv").exists():
            return ft
        # fresh clone ships the CSVs zipped — extract automatically
        zips = list(c.glob("CSMeD-FT*.zip"))
        if zips:
            target = config.RAW_CACHE / "CSMeD-FT"
            if not (target / "CSMeD-FT-train.csv").exists():
                print(f"[csmed] extracting {zips[0].name} (one-time)...")
                target.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zips[0]) as zf:
                    for member in zf.namelist():
                        if "__MACOSX" in member or member.endswith("/"):
                            continue
                        zf.extract(member, config.RAW_CACHE)
            if (target / "CSMeD-FT-train.csv").exists():
                return target
    raise SystemExit(
        "CSMeD-FT not found. Clone the dataset repo inside validation/ "
        "(git clone https://github.com/WojciechKusa/systematic-review-datasets) "
        "or pass --csmed-dir /path/to/CSMeD-FT")


def select_reviews(df, target_n: int, min_included: int):
    """Deterministic greedy selection of whole reviews to hit corpus targets."""
    g = df.groupby("review_id").agg(
        n=("document_id", "size"),
        inc=("decision", lambda s: int((s == "included").sum())))
    g = g.sort_values(["n", "inc"], ascending=False)
    chosen, tot, inc_tot = [], 0, 0
    for rid, row in g.iterrows():
        if tot >= target_n and inc_tot >= min_included:
            break
        if row["n"] > 2500 and chosen:
            continue
        chosen.append(rid)
        tot += int(row["n"])
        inc_tot += int(row["inc"])
    if inc_tot < min_included:
        for rid, row in g.sort_values("inc", ascending=False).iterrows():
            if inc_tot >= min_included:
                break
            if rid not in chosen:
                chosen.append(rid)
                tot += int(row["n"])
                inc_tot += int(row["inc"])
    return chosen, tot, inc_tot


def build_csmed(csmed_dir: str = "", limit: int = 0) -> None:
    import pandas as pd

    d = find_csmed_dir(csmed_dir)
    print(f"[csmed] reading CSMeD-FT from {d}")
    frames = [pd.read_csv(d / f"CSMeD-FT-{s}.csv") for s in ("train", "dev", "test")]
    df = pd.concat(frames, ignore_index=True).drop_duplicates("document_id")
    df["gold_label"] = df["decision"].map({"included": "include", "excluded": "exclude"})
    df = df[df["gold_label"].notna()]

    reviews_meta = {}
    for s in ("train", "dev", "test"):
        f = d / f"CSMeD-FT-{s}_reviews_metadata.json"
        if f.exists():
            reviews_meta.update(json.loads(f.read_text()))

    chosen, tot, inc_tot = select_reviews(df, config.TARGET_SCREENING_N,
                                          config.MIN_INCLUDED)
    sel = df[df["review_id"].isin(chosen)]
    print(f"[csmed] selected {len(chosen)} reviews, {len(sel)} records, "
          f"{inc_tot} included")

    rows, no_text = [], 0
    for i, (_, r) in enumerate(sel.iterrows(), 1):
        paper_id = str(r["document_id"]).replace("/", "-")
        pdf = config.SCREEN_PDF_DIR / f"{paper_id}.pdf"
        source = "cached"
        main_text = str(r.get("main_text") or "")
        if not pdf.exists():
            if len(main_text) >= 1000:
                _render_pdf(main_text, pdf)
                source = "csmed_text_render"
            else:
                links = str(r.get("PDF links") or "")
                url = links.split(";")[0].strip() if links else ""
                ok = False
                if url.startswith("http"):
                    try:
                        pr = requests.get(url, headers=UA, timeout=60)
                        if pr.ok and pr.content[:4] == b"%PDF":
                            pdf.write_bytes(pr.content)
                            source, ok = "pdf_link", True
                    except Exception:
                        pass
                if not ok:
                    no_text += 1
                    continue
        rows.append({"paper_id": paper_id, "review_id": r["review_id"],
                     "filename": pdf.name, "gold_label": r["gold_label"],
                     "doi": "" if pd.isna(r.get("doi")) else r.get("doi"),
                     "pmid": "" if pd.isna(r.get("PubMed ID")) else r.get("PubMed ID"),
                     "title": r.get("title", ""), "pdf_source": source,
                     "reason_for_exclusion": r.get("reason_for_exclusion", "")})
        if i % 200 == 0:
            print(f"[csmed] {i}/{len(sel)} processed, {len(rows)} PDFs so far")

    out = config.CORPUS_DIR / "gold_labels.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    n_inc = sum(1 for x in rows if x["gold_label"] == "include")
    (config.CORPUS_DIR / "attrition_report.md").write_text(
        f"# Screening corpus (CSMeD-FT)\n\n"
        f"- selected reviews: {len(chosen)}\n"
        f"- records in selection: {len(sel)}\n"
        f"- PDFs built: {len(rows)} ({n_inc} included)\n"
        f"- dropped (no usable full text): {no_text}\n\n"
        f"Provenance: CSMeD-FT (Kusa et al., NeurIPS D&B 2023), GROBID-parsed\n"
        f"main texts rendered to PDF by 01_build_corpus.py.\n\n"
        f"Reviews: {sorted(chosen)}\n")
    print(f"[csmed] corpus: {len(rows)} PDFs ({n_inc} included) -> {out}")

    template = {}
    prev_path = config.CORPUS_DIR / "criteria_to_fill.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {}
    pico = ("pop_inc", "pop_exc", "int_inc", "int_exc",
            "comp_inc", "comp_exc", "outcome")
    for rid in chosen:
        meta = reviews_meta.get(rid, {})
        entry = {"title": meta.get("title", ""),
                 "pop_inc": "", "pop_exc": "", "int_inc": "",
                 "int_exc": "", "comp_inc": "", "comp_exc": "",
                 "outcome": ""}
        old = prev.get(rid, {})
        # preserve any previously filled/auto-fetched criteria and provenance
        for k in pico:
            if str(old.get(k, "")).strip():
                entry[k] = old[k]
        for k in ("autofill_source", "provenance"):
            if k in old:
                entry[k] = old[k]
        template[rid] = entry
    kept = sum(1 for e in template.values()
               if any(str(e.get(k, "")).strip() for k in pico))
    (config.CORPUS_DIR / "criteria_to_fill.json").write_text(
        json.dumps(template, indent=2))
    print(f"[csmed] criteria template: {kept}/{len(template)} entries already "
          "filled (preserved). Run --autofill-criteria for the empty ones, "
          "spot-check, then run --finalize-criteria")


def finalize_criteria() -> None:
    """Freeze the criteria: corpus/criteria_to_fill.json -> corpus/reviews.json."""
    src = config.CORPUS_DIR / "criteria_to_fill.json"
    dst = config.CORPUS_DIR / "reviews.json"
    if not src.exists():
        raise SystemExit("criteria_to_fill.json missing — run --arm csmed first.")
    data = json.loads(src.read_text())
    pico = ("pop_inc", "pop_exc", "int_inc", "int_exc",
            "comp_inc", "comp_exc", "outcome")
    empty = [rid for rid, c in data.items()
             if not any(str(c.get(k, "")).strip() for k in pico)]
    if empty:
        raise SystemExit(
            f"PICO fields still empty for {len(empty)} review(s): {empty[:5]}. "
            "Fill them (or run --arm csmed --autofill-criteria), then retry.")
    dst.write_text(json.dumps(data, indent=2))
    print(f"[csmed] criteria frozen -> {dst} ({len(data)} reviews)")


# ===========================================================================
# Demo arm (offline end-to-end testing, zero quota)
# ===========================================================================
def build_demo() -> None:
    import pandas as pd

    # ---- screening: 3 papers (1 include, 2 exclude) ------------------------
    docs = {
        "demo_001": ("demo_review_a", "include", """Randomized controlled trial: Effects of lisinopril
on blood pressure in hypertensive adults. 240 adults aged 40-65 with diagnosed hypertension were
randomized to lisinopril 20mg daily or placebo for 12 weeks. Systolic blood pressure fell 14.2 mmHg
with lisinopril vs 3.1 mmHg with placebo (p<0.001). Lisinopril significantly reduces blood
pressure in hypertensive adults."""),
        "demo_002": ("demo_review_a", "exclude", """Preclinical study: antihypertensive effects of
compound X in spontaneously hypertensive rats. Twelve rats were treated for 4 weeks; blood
pressure measured by tail cuff. Rats showed reduced blood pressure."""),
        "demo_003": ("demo_review_a", "exclude", """Editorial: The role of diet in managing
hypertension. This commentary discusses nutrition policy and does not report a randomized
trial of any antihypertensive drug in adults."""),
    }
    criteria = {"demo_review_a": {
        "pop_inc": "adults aged 18-65 with hypertension",
        "pop_exc": "rats, animals, preclinical studies",
        "int_inc": "antihypertensive drug treatment",
        "int_exc": "", "comp_inc": "placebo or active comparator",
        "comp_exc": "", "outcome": "blood pressure reduction"}}
    rows = []
    for pid, (rev, label, text) in docs.items():
        pdf = config.SCREEN_PDF_DIR / f"{pid}.pdf"
        _render_pdf(text, pdf)
        rows.append({"paper_id": pid, "review_id": rev, "filename": pdf.name,
                     "gold_label": label, "doi": "", "pmid": "", "title": pid,
                     "pdf_source": "synthetic", "source": "demo"})
    pd.DataFrame(rows).to_csv(config.CORPUS_DIR / "gold_labels.csv", index=False)
    (config.CORPUS_DIR / "reviews.json").write_text(json.dumps(criteria, indent=2))

    # ---- extraction: 3 articles with gold PICO + effect direction ----------
    articles = {
        "demo_e001": {
            "text": """Randomized trial of lisinopril in hypertension. 240 adults aged 40-65 with
hypertension received lisinopril 20mg daily or placebo for 12 weeks. Systolic blood pressure
decreased by 14.2 mmHg in the lisinopril group versus 3.1 mmHg with placebo (p<0.001). No serious
adverse events were attributed to lisinopril.""",
            "gold": {"gold_population": "adults aged 40-65 with hypertension",
                     "gold_intervention": "lisinopril 20mg daily",
                     "gold_comparator": "placebo",
                     "gold_outcome": "systolic blood pressure change",
                     "gold_effect_direction": "significantly decreased"}},
        "demo_e002": {
            "text": """Double-blind RCT of atorvastatin 40mg versus placebo in 180 adults with
hypercholesterolemia. LDL cholesterol increased by 2 mg/dL in the atorvastatin arm and by
28 mg/dL in the placebo arm over 24 weeks; the between-group difference was not statistically
significant.""",
            "gold": {"gold_population": "adults with hypercholesterolemia",
                     "gold_intervention": "atorvastatin 40mg",
                     "gold_comparator": "placebo",
                     "gold_outcome": "LDL cholesterol change",
                     "gold_effect_direction": "no significant difference"}},
        "demo_e003": {
            "text": """Placebo-controlled trial of metformin 1500mg daily in 95 adults with
prediabetes. Fasting glucose significantly decreased by 12 mg/dL compared with placebo over
one year. Gastrointestinal upset was the most common adverse effect.""",
            "gold": {"gold_population": "adults with prediabetes",
                     "gold_intervention": "metformin 1500mg daily",
                     "gold_comparator": "placebo",
                     "gold_outcome": "fasting glucose change",
                     "gold_effect_direction": "significantly decreased"}},
    }
    tasks = []
    for aid, spec in articles.items():
        pdf = config.EXTRACT_PDF_DIR / f"{aid}.pdf"
        _render_pdf(spec["text"], pdf)
        tasks.append({"article_id": aid, "prompt_id": aid, "filename": pdf.name,
                      **spec["gold"], "txt_source": "synthetic", "source": "demo"})
    pd.DataFrame(tasks).to_csv(config.CORPUS_DIR / "extraction_tasks.csv", index=False)

    print(f"[demo] screening: {len(rows)} PDFs + labels + criteria")
    print(f"[demo] extraction: {len(tasks)} article PDFs + gold fields")
    print("[demo] test with:")
    print("         python 02_run_screening.py --model glm --limit 3")
    print("         python 03_run_extraction.py --model glm --limit 3")
    print("         python 05_stats.py --models glm")
    print("[demo] BEFORE building the real corpora, remove demo data:")
    print("         rm corpus/gold_labels.csv corpus/reviews.json "
          "corpus/extraction_tasks.csv corpus/pdfs/demo_*.pdf corpus/extraction_pdfs/demo_*.pdf")


# ===========================================================================
# Auto-fill eligibility criteria from the reviews' own publications
# (Europe PMC: open-access full text first, structured abstract as fallback)
# ===========================================================================
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_PICO_LABELS = ("types of studies", "types of participants", "types of interventions",
                "types of comparisons", "types of outcomes")
_NEXT_SECTIONS = ("criteria for considering studies", "search methods for identification",
                  "selection of studies", "data collection and analysis",
                  "methods of the review", "quality assessment")


def _epmc_search(query: str) -> dict | None:
    try:
        r = requests.get(f"{EPMC}/search",
                         params={"query": query, "format": "json",
                                 "resultType": "core", "pageSize": 5},
                         timeout=30)
        hits = r.json().get("resultList", {}).get("result", [])
        return hits[0] if hits else None
    except Exception:
        return None


def _epmc_fulltext(pmcid: str) -> str:
    try:
        r = requests.get(f"{EPMC}/{pmcid}/fullTextXML", timeout=60)
        return r.text if r.ok else ""
    except Exception:
        return ""


def _clean_xml(xml: str) -> str:
    import re as _re
    return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", xml)).strip()


def _parse_criteria_chunk(chunk: str) -> dict:
    """Map 'Types of X' subsections to the tool's PICO fields."""
    import re as _re
    out = {}
    pattern = _re.compile(
        r"types of (studies|participants|interventions|comparisons|outcomes)\s*[:\-]?\s*"
        r"(.*?)(?=types of (?:studies|participants|interventions|comparisons|outcomes)|$)",
        _re.IGNORECASE | _re.DOTALL)
    mapping = {"studies": "pop_inc", "participants": "pop_inc",
               "interventions": "int_inc", "comparisons": "comp_inc",
               "outcomes": "outcome"}
    for m in pattern.finditer(chunk):
        field = mapping[m.group(1).lower()]
        text = m.group(2).strip(" .;")
        if text:
            out[field] = (out.get(field, "") + " " + text).strip()
    return {k: v for k, v in out.items() if v}


def _criteria_from_fulltext(pmcid: str) -> tuple[dict | None, str]:
    xml = _epmc_fulltext(pmcid)
    if not xml:
        return None, ""
    text = _clean_xml(xml)
    text_lower = text.lower()
    start = text_lower.find("criteria for considering studies")
    if start == -1:
        return None, ""
    end = len(text)
    for marker in _NEXT_SECTIONS:
        pos = text_lower.find(marker, start + 40)
        if pos != -1:
            end = min(end, pos)
    chunk = text_lower[start:end]
    parsed = _parse_criteria_chunk(chunk)
    if parsed:
        # recover original casing by mapping the matched spans onto `text`
        import re as _re
        out = {}
        for field, val in parsed.items():
            m = _re.search(_re.escape(val[:60]), text_lower[start:end])
            out[field] = text[start + m.start():start + m.start() + len(val)].strip() \
                if m else val
        parsed = out
    return (parsed or None), ("europepmc_fulltext", chunk[:400])


def _criteria_from_abstract(hit: dict) -> tuple[dict | None, str]:
    """Cochrane structured abstracts carry a verbatim 'Selection criteria' block.
    The label must sit at a section boundary (start of text or after a period)
    so we never capture mid-sentence occurrences."""
    import re as _re
    abstract = _re.sub(r"<[^>]+>", " ", str(hit.get("abstractText") or ""))
    m = _re.search(r"(?:^|[.!?]\s)Selection criteria[:\s]*(.*?)(?=Data collection|"
                   r"Main results|Authors' conclusions|Ways to use this review|\Z)",
                   abstract, _re.IGNORECASE | _re.DOTALL)
    if not m:
        return None, ""
    blob = _re.sub(r"\s+", " ", m.group(1)).strip()
    if len(blob) < 20:
        return None, ""
    parsed = _parse_criteria_chunk(blob)
    if parsed:
        return parsed, ("abstract_types_of", blob[:400])
    # prose fallback: the whole verbatim block goes to Population-Inclusion
    return ({"pop_inc": blob}, ("abstract_blob", blob[:400]))


def _criteria_from_pubmed(rid: str) -> tuple[dict | None, str]:
    """PubMed fallback: handles old-format ('Selection criteria') and
    new-2025-format ('ELIGIBILITY CRITERIA:') Cochrane abstracts."""
    import re as _re
    import os as _os
    E = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    email = _os.getenv("ENTREZ_EMAIL", "")
    try:
        r = requests.get(f"{E}/esearch.fcgi",
                         params={"db": "pubmed", "term": rid, "retmode": "json",
                                 "email": email}, timeout=30)
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return None, ""
        time.sleep(0.4)
        txt = requests.get(f"{E}/efetch.fcgi",
                           params={"db": "pubmed", "id": ids[0],
                                   "rettype": "abstract", "retmode": "text",
                                   "email": email}, timeout=30).text
        time.sleep(0.4)
    except Exception:
        return None, ""
    for pattern, stop in (
            (r"(?:^|[.!?]\s)Selection criteria[:\s]*(.*?)(?=Data collection|Main results|Authors)", "old"),
            (r"(?:^|[.!?]\s)Eligibility criteria[:\s]*(.*?)(?=\bOUTCOMES\b|\bSAMPLE SIZE\b|\bINTERVENTIONS\b|\bDATA\b|\bSTUDY CHARACTERISTICS\b|\Z)", "new"),
    ):
        m = _re.search(pattern, txt, _re.IGNORECASE | _re.DOTALL)
        if m and len(m.group(1).strip()) > 20:
            blob = _re.sub(r"\s+", " ", m.group(1)).strip()
            parsed = _parse_criteria_chunk(blob)
            if parsed:
                return parsed, (f"pubmed_{stop}", blob[:400])
            return ({"pop_inc": blob}, (f"pubmed_{stop}_blob", blob[:400]))
    return None, ""


def _clean_criteria_text(s: str) -> str:
    import re as _re
    s = _re.sub(r"<[^>]+>", " ", str(s))            # residual XML tags
    s = s.replace("’", "'").replace("‘", "'")
    s = _re.sub(r"\s+", " ", s).strip()
    return _re.sub(r"^[\s:;,\-–—>]+", "", s)         # leading markup punctuation



def _decompose(text: str) -> str:
    """Reformat a verbatim criteria blob into the tool's expected input format:
    comma-separated short phrases (ReviewAid's Tier-1 matcher splits criteria on
    commas and checks literal phrase matches). Wording is preserved; structural
    decomposition happens — sentence/semicolon/numbered boundaries, commas,
    'and'/'or'/'with' joins inside long phrases — plus two cleanups:
    procedural sentences (screening/analysis bookkeeping) are dropped, and
    phrases stating exclusions are routed to the exclusion field by the caller."""
    import re as _re
    t = _re.sub(r"\s+", " ", str(text)).strip()
    for _ in range(2):
        t = _re.sub(
            r"^(we\s+(only\s+)?(considered|included|sought|selected)|"
            r"trials?\s+fulfilled the following criteria:?|"
            r"studies\s+(were\s+)?included\s+(if|that|were)|"
            r"included studies (were|must)|eligible studies were)\s*", "", t,
            flags=_re.IGNORECASE)
    chunks = _re.split(r"(?<=[.;])\s+|;\s*|\b\d\)\s*", t)
    procedural = _re.compile(
        r"independent reviewers|screened (abstracts|titles|full[- ]text)|"
        r"extracted data|meta-analys|data collection|risk of bias tool|"
        r"in duplicate|disagreements were resolved", _re.IGNORECASE)
    frags, seen = [], set()

    def add(piece):
        piece = piece.strip(" .;:\u2013\u2014-")
        if 3 <= len(piece) <= 140 and piece.lower() not in seen:
            seen.add(piece.lower())
            frags.append(piece)

    for chunk in chunks:
        if procedural.search(chunk):
            continue
        pieces = [chunk]
        # further split long phrases on common joins
        while any(len(x.split()) > 12 for x in pieces):
            out = []
            for x in pieces:
                if len(x.split()) > 12:
                    out.extend(_re.split(r"\s+(?:and|or|with)\s+", x, maxsplit=0)
                               if False else _re.split(r",\s*|\s+and\s+|\s+or\s+|:\s+", x))
                else:
                    out.append(x)
            pieces = out
            if len(pieces) > 24:   # safety valve
                break
        for piece in pieces:
            add(piece)
    return ", ".join(frags)


def decompose_criteria() -> None:
    """criteria v2: decompose prose criteria blobs into the tool's documented
    comma-separated phrase format (format change documented; wording verbatim;
    original blob kept per field as provenance). Idempotent: re-decomposes from
    the stored verbatim originals."""
    tf_path = config.CORPUS_DIR / "criteria_to_fill.json"
    data = json.loads(tf_path.read_text())
    pico = ("pop_inc", "pop_exc", "int_inc", "int_exc",
            "comp_inc", "comp_exc", "outcome")
    changed = 0
    for rid, crit in data.items():
        touched = False
        for field in pico:
            source = str(crit.get("original_verbatim", {}).get(field) or
                         crit.get(field, "")).strip()
            if len(source) < 120:
                continue
            shorter = _decompose(source)
            if not shorter:
                continue
            # phrases that state exclusions belong in the exclusion field
            keep, excl = [], []
            for phrase in shorter.split(", "):
                (excl if re.search(r"exclud|not include", phrase, re.IGNORECASE)
                 else keep).append(phrase)
            if keep:
                crit[field] = ", ".join(keep)
            if excl and field == "pop_inc":
                crit["pop_exc"] = (crit.get("pop_exc", "") + ", " if crit.get("pop_exc")
                                   else "") + ", ".join(excl)
            if keep or excl:
                crit.setdefault("original_verbatim", {})[field] = source
                touched = True
        if touched:
            crit["criteria_format"] = "decomposed_v2"
            changed += 1
    baseline = config.CORPUS_DIR / "criteria_old_v1.json"
    if not baseline.exists():
        baseline.write_text(json.dumps(data, indent=2))
    tf_path.write_text(json.dumps(data, indent=2))
    print(f"[criteria] decomposed {changed}/{len(data)} reviews to the tool's "
          "comma-separated phrase format (originals kept in "
          "original_verbatim). Now re-run --finalize-criteria.")



_CURATION_PROMPT = """You are preparing input for a systematic-review screening tool.
The tool expects eligibility criteria as SHORT comma-separated phrases per category
(2-8 words each, noun-phrase style, e.g. "randomized controlled trials", "adults 18-65",
"antidepressant drugs", "placebo comparator", "smoking cessation").

Convert the published criteria below into that format. Use the review's own terms.
Output ONLY a single JSON object, no markdown, no commentary:
{{"extracted": {{"pop_inc": "phrase, phrase", "pop_exc": "...", "int_inc": "...", "int_exc": "...",
  "comp_inc": "...", "comp_exc": "...", "outcome": "..."}}, "confidence": 0.9}}

Published criteria (verbatim):
{blob}"""


def curate_criteria() -> None:
    """criteria v3: LLM-assisted curation of the verbatim criteria into SHORT
    PICO phrases (the tool's documented input format). GLM free backend; every
    original retained for provenance; author spot-check still required before
    --finalize-criteria."""
    sys.path.insert(0, str(config.BASE))
    from ra_driver import query_provider, ra_parser   # noqa: E402 (shim + v3.0.0 assert)

    tf_path = config.CORPUS_DIR / "criteria_to_fill.json"
    data = json.loads(tf_path.read_text())
    pico = ("pop_inc", "pop_exc", "int_inc", "int_exc",
            "comp_inc", "comp_exc", "outcome")
    done = 0
    for rid, crit in data.items():
        if crit.get("criteria_format") == "curated_v3":
            done += 1
            continue
        blob = "\n".join(f"{k}: {crit[k]}" for k in pico if str(crit.get(k, "")).strip())
        if not blob.strip():
            continue
        raw, key = query_provider("ollama", _CURATION_PROMPT.format(blob=blob[:4000]),
                                  temperature=0.1, max_tokens=1500)
        if not raw:
            print(f"[curate] {rid}: GLM call failed (rate limit?) — rerun later")
            continue
        # route through the tool's own bulletproof parser (6-stage JSON recovery)
        result = ra_parser.parse_result(raw, "Ollama (Local)", key, "llama3.2:3b",
                                        mode="extractor", fields_list=list(pico),
                                        original_text="")
        parsed = (result or {}).get("extracted") or None
        if not parsed:
            print(f"[curate] {rid}: GLM output unparseable — keeping v2, rerun later")
            continue
        for k in pico:
            v = str((parsed or {}).get(k, "")).strip()
            if v and v.lower() not in ("not found", "n/a", "none"):
                crit[k] = re.sub(r"\s+", " ", v)[:1500]
        crit["criteria_format"] = "curated_v3"
        done += 1
        print(f"[curate] {rid}: curated phrases written "
              f"({sum(1 for k in pico if str(crit.get(k,'')).strip())}/7 fields)")
    tf_path.write_text(json.dumps(data, indent=2))
    print(f"[curate] {done}/{len(data)} reviews curated (v3). Spot-check, "
          "then --finalize-criteria.")


def det_score_check(sample_per_review: int = 2) -> None:
    """OFFLINE (no API): measure the Tier-1 deterministic score on real papers
    under the OLD (verbatim prose) vs CURRENT criteria, to verify the override
    storm is fixed before spending API calls."""
    sys.path.insert(0, str(config.BASE))
    from ra_driver import utils, ra_confidence  # noqa: E402

    gold = pd.read_csv(config.CORPUS_DIR / "gold_labels.csv")
    old = json.loads((config.CORPUS_DIR / "criteria_old_v1.json").read_text()) \
        if (config.CORPUS_DIR / "criteria_old_v1.json").exists() else {}
    cur = json.loads((config.CORPUS_DIR / "reviews.json").read_text())
    fields = ("pop_inc", "pop_exc", "int_inc", "int_exc",
              "comp_inc", "comp_exc", "outcome")
    per_review = gold.groupby("review_id")
    results = []
    for rid, grp in per_review:
        if rid not in cur:
            continue
        sample = grp.head(sample_per_review)
        for _, r in sample.iterrows():
            pdf = config.SCREEN_PDF_DIR / str(r["filename"])
            if not pdf.exists():
                continue
            text, _, _, _ = utils.extract_pdf_content(pdf.read_bytes())
            if len(text) < 500:
                continue
            row = {"review_id": rid, "paper_id": r["paper_id"]}
            for label, crit_src in (("old", old.get(rid, cur.get(rid, {}))),
                                    ("cur", cur.get(rid, {}))):
                cd = {k: str(crit_src.get(k, "")) for k in fields}
                row[label] = ra_confidence.estimate_confidence(
                    text, mode="screener", criteria_dict=cd,
                    extracted_data=None, fields_list=[])
            results.append(row)
    df = pd.DataFrame(results)
    if df.empty:
        print("[det-check] no sample papers found")
        return
    print(df.groupby("review_id")[["old", "cur"]].mean().round(2)
          .to_string())
    print(f"\n[det-check] mean Tier-1 score: old={df['old'].mean():.2f} -> "
          f"cur={df['cur'].mean():.2f}  (override fires when < 0.5; automation "
          f"policy needs >= 0.8)")
    df.to_csv(config.STATS_DIR / "criteria_det_score_check.csv", index=False)


def autofill_criteria() -> None:
    """Fetch each selected review's published eligibility criteria automatically.

    Source order: (1) open-access Cochrane full text on Europe PMC ('Criteria
    for considering studies' -> Types of ... subsections), (2) the review's
    structured abstract 'Selection criteria' block. Everything stays verbatim;
    provenance is recorded per review. Only fields that remain empty after this
    need manual attention.
    """
    tf_path = config.CORPUS_DIR / "criteria_to_fill.json"
    if not tf_path.exists():
        raise SystemExit("criteria_to_fill.json missing — run --arm csmed first.")
    template = json.loads(tf_path.read_text())

    filled = patched = 0
    pico = ("pop_inc", "pop_exc", "int_inc", "int_exc",
            "comp_inc", "comp_exc", "outcome")
    for rid, crit in template.items():
        already = any(str(crit.get(k, "")).strip() for k in pico)
        if already:
            patched += 1
            continue
        title = crit.get("title", "")
        short = " ".join(title.split()[:14])
        # Cochrane review IDs map deterministically to their DOI
        hit = _epmc_search(f'DOI:"10.1002/14651858.{rid}"')
        if not hit:
            hit = _epmc_search(f'TITLE:"{short}" AND SRC:CDR')
        if not hit:
            hit = _epmc_search(f'TITLE:"{short}"')
        if not hit:
            crit["autofill_source"] = "NOT FOUND - fill manually"
            print(f"[criteria] {rid}: not found on Europe PMC — fill manually")
            continue
        crit["provenance"] = {"pmid": hit.get("pmid", ""), "pmcid": hit.get("pmcid", ""),
                              "doi": hit.get("doi", ""), "title": hit.get("title", "")}
        parsed, src = (None, "")
        if hit.get("pmcid"):
            parsed, src = _criteria_from_fulltext(hit["pmcid"])
        if not parsed:
            parsed, src = _criteria_from_abstract(hit)
        if not parsed:
            parsed, src = _criteria_from_pubmed(rid)
        if not parsed:
            crit["autofill_source"] = "FOUND but criteria not extractable - fill manually"
            print(f"[criteria] {rid}: found ({hit.get('pmid')}) but no criteria extracted")
            continue
        for k, v in parsed.items():
            crit[k] = _clean_criteria_text(v)[:2000]
        crit["autofill_source"] = src[0] if isinstance(src, tuple) else src
        filled += 1
        print(f"[criteria] {rid}: {crit['autofill_source']} "
              f"({', '.join(parsed.keys())})")

    tf_path.write_text(json.dumps(template, indent=2))
    print(f"\n[criteria] auto-filled {filled} reviews ({patched} were already "
          "filled/checked). Review corpus/criteria_to_fill.json, correct anything "
          "that looks off, then run --finalize-criteria.")


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True,
                    choices=["evidenceinference", "csmed", "demo"])
    ap.add_argument("--csmed-dir", default="", help="path to CSMeD-FT folder")
    ap.add_argument("--autofill-criteria", action="store_true",
                    help="fetch published eligibility criteria from Europe PMC")
    ap.add_argument("--finalize-criteria", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap articles/records (smoke test)")
    args = ap.parse_args()

    if args.arm == "evidenceinference":
        build_evidenceinference(limit=args.limit)
    elif args.arm == "csmed":
        if args.autofill_criteria:
            autofill_criteria()
        elif args.finalize_criteria:
            finalize_criteria()
        else:
            build_csmed(args.csmed_dir, limit=args.limit)
    elif args.arm == "demo":
        build_demo()


if __name__ == "__main__":
    main()

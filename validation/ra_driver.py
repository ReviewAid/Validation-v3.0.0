"""Headless driver for ReviewAid v3.0.0 — the validated artifact is the tool.

This module runs ReviewAid_v3.0.0's OWN code paths without the Streamlit UI:
- screener: Tier-1 keyword rule -> LLM classification (tool's exact prompt) ->
  parse_result -> Tier-1 deterministic confidence + override logic
- extractor: tool's exact extraction prompt -> parse_result ->
  estimate_confidence(mode="extractor") + override logic

Faithfulness contract:
- All decision logic is the tool's (utils.py, parser.py, confidence.py of the
  local ReviewAid_v3.0.0 folder; version asserted against CITATION.cff).
- This driver adds NOTHING to decisions. It only (a) removes the UI, (b) adds
  Cohere key rotation, (c) LOGS extra analysis ingredients: the AI's raw
  self-assessed confidence before the override, the deterministic score,
  per-field grounding verdicts, criteria-match ratios, parse events, latency.
"""
import importlib
import json
import re
import sys
import time
import types
from pathlib import Path

import config
import keys as keys_mod

sys.path.insert(0, str(config.TOOL_DIR))

_RATE_KEYWORDS = ("429", "rate limit", "too many requests", "quota",
                  "overload", "rate_limit_exceeded")


def _is_rate_limit(err: Exception) -> bool:
    s = str(err).lower()
    return any(k in s for k in _RATE_KEYWORDS)


# ---------------------------------------------------------------------------
# Streamlit shim: the tool's modules touch st.session_state / UI calls even in
# pure-logic paths. A dict-backed session state makes update_terminal_log a
# silent no-op; all decision logic is untouched.
# ---------------------------------------------------------------------------
def install_streamlit_shim() -> None:
    if "streamlit" in sys.modules:
        return

    class _SessionState(dict):
        def get(self, k, default=None):
            return dict.get(self, k, default)

    mod = types.ModuleType("streamlit")
    mod.session_state = _SessionState()
    errors = types.ModuleType("streamlit.errors")
    errors.StreamlitDuplicateElementId = type(
        "StreamlitDuplicateElementId", (Exception,), {})
    mod.errors = errors
    v1 = types.ModuleType("streamlit.components.v1")
    v1.html = lambda *a, **k: None
    comps = types.ModuleType("streamlit.components")
    comps.v1 = v1
    mod.components = comps

    def _noop(name):
        def f(*a, **k):
            return None
        f.__name__ = name
        return f

    for name in ("markdown", "write", "text", "title", "header", "subheader",
                 "caption", "code", "metric", "json", "dataframe", "table",
                 "plotly_chart", "image", "warning", "error", "info",
                 "success", "progress", "empty", "button", "selectbox",
                 "text_area", "text_input", "file_uploader", "radio",
                 "checkbox", "tabs", "pyplot", "toast", "balloons"):
        setattr(mod, name, _noop(name))

    def _stop(*a, **k):
        raise SystemExit("st.stop() called in headless mode")
    mod.stop = _stop

    import contextlib

    @contextlib.contextmanager
    def _ctx(*a, **k):
        yield None
    mod.expander = _ctx
    mod.spinner = _ctx
    mod.sidebar = types.SimpleNamespace(**{n: _noop(n) for n in
                                           ("markdown", "write", "selectbox",
                                            "checkbox", "header", "radio")})
    sys.modules["streamlit"] = mod
    sys.modules["streamlit.components"] = comps
    sys.modules["streamlit.components.v1"] = v1

    try:
        importlib.import_module("streamlit_lottie")
    except ImportError:
        lottie = types.ModuleType("streamlit_lottie")
        lottie.st_lottie = lambda *a, **k: None
        sys.modules["streamlit_lottie"] = lottie


install_streamlit_shim()

import utils            # noqa: E402  (ReviewAid v3.0.0)
import parser as ra_parser  # noqa: E402
import confidence as ra_confidence  # noqa: E402


def assert_tool_version() -> str:
    """Fail fast unless the local tool folder is exactly v3.0.0."""
    cff = config.TOOL_DIR / "CITATION.cff"
    version = None
    for line in cff.read_text().splitlines():
        m = re.match(r'^version:\s*"([^"]+)"', line.strip())
        if m:
            version = m.group(1)
            break
    if version != config.REQUIRED_TOOL_VERSION:
        raise RuntimeError(
            f"ReviewAid folder is version {version!r}; this validation is "
            f"strictly for v{config.REQUIRED_TOOL_VERSION}. Point TOOL_DIR at "
            f"the v{config.REQUIRED_TOOL_VERSION} code.")
    return version


TOOL_VERSION = assert_tool_version()

# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
def query_provider(model_key: str, prompt: str, temperature: float = 0.1,
                   max_tokens: int = 8192):
    """Call a backend with ReviewAid's own provider classes.

    Retry semantics mirror utils.query_llm (exponential backoff on rate
    limits, short retries otherwise, None on exhaustion). Cloud providers
    rotate keys via keys.rotate (process-safe, shared across the parallel
    screening/extraction jobs). Returns (raw_text|None, active_key).
    """
    m = config.MODELS[model_key]
    messages = [{"role": "user", "content": prompt}]

    if m["provider"] == "Cohere":
        def _call(key):
            prov = utils.get_provider_instance("Cohere", key, m["model"])
            return prov.generate(messages, temperature, max_tokens)
        return keys_mod.rotate("cohere", _call)

    if m.get("base_url"):
        # OpenAI-compatible endpoint on a custom host (Gemini free tier):
        # the tool's own OpenAIProvider + cohere-style rotation/backoff
        def _call(k):
            prov = utils.get_provider_instance(m["provider"], k, m["model"],
                                               base_url=m["base_url"])
            return prov.generate(messages, temperature, max_tokens)
        return keys_mod.rotate(model_key, _call)

    key = m["keys"]()[0]  # Ollama: local, no keys
    base_url = config.OLLAMA_BASE_URL if m["provider"] == "Ollama (Local)" else None
    # Ollama-specific: screening + extraction run in parallel on one Mac, so the
    # local server queues requests and can time out or refuse connections while
    # busy. Treat local-capacity errors as retryable with patient backoff.
    ollama_busy = ("timeout", "timed out", "connection", "refused", "busy",
                   "overloaded", "unreachable", "failed to establish",
                   "server error", "500")
    for attempt in range(10):
        try:
            kwargs = {"base_url": base_url} if base_url else {}
            prov = utils.get_provider_instance(m["provider"], key, m["model"], **kwargs)
            return prov.generate(messages, temperature, max_tokens), key
        except Exception as e:
            retryable = _is_rate_limit(e) or (
                base_url is not None and any(k in str(e).lower() for k in ollama_busy))
            if retryable:
                if attempt < 9:
                    wait = min(10 * (2 ** attempt), 60) if base_url else \
                        min(15 * (2 ** attempt), 120)
                    print(f"[ollama] local server busy — retry {attempt + 1}/10 "
                          f"after {wait}s ({str(e)[:70]})", flush=True)
                    time.sleep(wait)
                    continue
                return None, key
            if attempt < 3:
                time.sleep(2)
                continue
            return None, key
    return None, key


def _normalize_status(status: str) -> str:
    s = (status or "").strip().lower()
    if "include" in s and "exclude" not in s:
        return "include"
    if "exclude" in s:
        return "exclude"
    if "maybe" in s:
        return "maybe"
    return "exclude"


def _base_record(pdf_path, model_key, t0):
    m = config.MODELS[model_key]
    return {
        "paper_id": Path(pdf_path).stem,
        "model_key": model_key,
        "provider": m["provider"],
        "model": m["model"],
        "tool_version": TOOL_VERSION,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "latency_s": None,
        "_t0": t0,
    }


def _finalize(rec):
    rec["latency_s"] = round(time.time() - rec.pop("_t0"), 2)
    return rec


# ---------------------------------------------------------------------------
# Screener path
# ---------------------------------------------------------------------------
SCREENER_PROMPT = """You are an expert systematic reviewer. Your task is to screen a research paper based on specific PICO criteria.

**CRITICAL INSTRUCTION:**
Return your response as a SINGLE valid JSON object. Do not include markdown formatting (like ```json), do not add comments, and do not include conversational filler text.

**Population**
Inclusion: {population_inclusion}
Exclusion: {population_exclusion}

**Intervention**
Inclusion: {intervention_inclusion}
Exclusion: {intervention_exclusion}

**Comparison**
Inclusion: {comparison_inclusion}
Exclusion: {comparison_exclusion}

**Outcomes**: {outcome_criteria}

**Paper Text:**
\"\"\"
{text}
\"\"\"

**Task:**
1. Classify paper as "Include", "Exclude", or "Maybe" based strictly on the criteria.
2. Provide a detailed reason for the classification.
3. Extract the Paper Title, Main Author, and Publication Year.
4. If a value is not found, use "Not Found".
5. **CONFIDENCE SCORE**: Rate your confidence (0.0 to 1.0).
   - 1.0 = The paper perfectly matches or perfectly violates the criteria with explicit evidence.
   - 0.8 - 0.9 = High confidence based on strong evidence.
   - 0.5 - 0.7 = Moderate confidence (Some ambiguity in criteria or text).
   - < 0.5 = Low confidence (Guessing, criteria vague, or text unclear).

**JSON Format Required:**
{{
  "status": "Include",
  "reason": "Detailed classification reason explaining why it fits or fails the criteria.",
  "title": "Full paper title extracted from text",
  "author": "Main author name",
  "year": "2023",
  "confidence": 0.95
}}
"""


def _find_exclusion_matches(text, exclusion_lists):
    """Verbatim copy of screener.find_exclusion_matches (UI logging removed)."""
    return [c for c in (x.strip() for x in exclusion_lists)
            if c and c.lower() in text.lower()]


def _criteria_match_stats(text: str, criteria_dict: dict) -> dict:
    """Raw criteria-match ratio behind the screener's Tier-1 score (confidence.py
    screener branch) without the +0.1 bonus/caps — the unmodified ingredient."""
    t = text.lower()
    matches = total = 0
    per_block = {}
    for block in ("pop_inc", "pop_exc", "int_inc", "int_exc",
                  "comp_inc", "comp_exc", "outcome"):
        s = (criteria_dict.get(block) or "").strip()
        if not s:
            continue
        items = [c.strip() for c in s.split(",") if c.strip()]
        m = sum(1 for c in items if c.lower() in t)
        per_block[block] = f"{m}/{len(items)}"
        matches += m
        total += len(items)
    return {"matched": matches, "total": total,
            "ratio": (matches / total) if total else None}


def screen_one_paper(pdf_path: str, criteria: dict, model_key: str) -> dict:
    """One PDF through ReviewAid v3.0.0's screener logic."""
    t0 = time.time()
    rec = _base_record(pdf_path, model_key, t0)

    pdf_bytes = Path(pdf_path).read_bytes()
    text, title, author, year = utils.extract_pdf_content(pdf_bytes)
    del pdf_bytes
    if not text.strip():
        rec.update({"decision": "error", "confidence": 0.0, "tier": "none",
                    "reason": "PDF empty/unreadable"})
        return _finalize(rec)

    processed = utils.preprocess_text_for_ai(text, max_tokens=utils.MAX_INPUT_TOKENS_SCREENER)
    backup = text

    criteria_dict = {k: (criteria.get(k) or "") for k in
                     ("pop_inc", "pop_exc", "int_inc", "int_exc",
                      "comp_inc", "comp_exc", "outcome")}

    # ---- Tier 1: deterministic keyword exclusion (screener.py, verbatim logic)
    all_exclusions = [c.strip()
                      for block in (criteria_dict["pop_exc"], criteria_dict["int_exc"],
                                    criteria_dict["comp_exc"])
                      for c in block.split(",") if c.strip()]
    matches_exc = _find_exclusion_matches(backup, all_exclusions)
    all_inclusions = [c.strip()
                      for block in (criteria_dict["pop_inc"], criteria_dict["int_inc"],
                                    criteria_dict["comp_inc"])
                      for c in block.split(",") if c.strip()]
    matches_inc = [c for c in all_inclusions if c.lower() in backup.lower()]
    rec["tier1_keyword"] = {"exclusion_matches": matches_exc,
                            "inclusion_matches": matches_inc}

    if len(matches_exc) >= 1 and len(matches_inc) == 0:
        rec.update({
            "decision": "exclude", "confidence": 1.0,
            "tier": "tier1_deterministic", "override_fired": False,
            "ai_confidence_raw": None, "deterministic_confidence": 1.0,
            "parse_ok": True, "api_returned": False, "api_calls": 0,
            "reason": (f"Auto-excluded because {len(matches_exc)} exclusion "
                       f"criteria matched: {', '.join(matches_exc)}")[:500],
            "title": title, "author": author, "year": year,
            "criteria_match": _criteria_match_stats(backup, criteria_dict),
        })
        return _finalize(rec)

    time.sleep(1)  # the tool's pacing between PDFs

    prompt = SCREENER_PROMPT.format(
        text=processed,
        population_inclusion=criteria_dict["pop_inc"],
        population_exclusion=criteria_dict["pop_exc"],
        intervention_inclusion=criteria_dict["int_inc"],
        intervention_exclusion=criteria_dict["int_exc"],
        comparison_inclusion=criteria_dict["comp_inc"],
        comparison_exclusion=criteria_dict["comp_exc"],
        outcome_criteria=criteria_dict["outcome"],
    )
    del processed

    raw, active_key = query_provider(model_key, prompt, temperature=0.1, max_tokens=8192)
    del prompt

    result = ra_parser.parse_result(raw, config.MODELS[model_key]["provider"],
                                    active_key, config.MODELS[model_key]["model"],
                                    mode="screener", original_text=backup,
                                    fields_list=[])

    # ---- Confidence assignment with Tier-1 override (screener.py 478-521)
    deterministic_confidence = ra_confidence.estimate_confidence(
        backup, mode="screener", criteria_dict=criteria_dict,
        extracted_data=None, fields_list=[])

    ai_confidence = result.get("confidence", None) if result else None
    tier, override_fired = "tier2_llm_selfassess", False
    if ai_confidence is not None:
        try:
            ai_confidence = max(0.0, min(1.0, float(ai_confidence)))
        except (TypeError, ValueError):
            ai_confidence = 0.0
        if deterministic_confidence < 0.5 and ai_confidence > 0.5:
            confidence, tier, override_fired = deterministic_confidence, "tier1_override", True
        else:
            confidence = min(ai_confidence, 0.95)
    else:
        confidence = deterministic_confidence
        tier = "tier1_deterministic_score"

    status = _normalize_status(result.get("status", "") if result else "")
    if not result:
        # Total failure (API dead + fallback failed): mark as error so the
        # resume logic retries this paper on the next run, instead of
        # silently counting it as an exclusion.
        status = "error"
    rec.update({
        "decision": status,
        "confidence": round(float(confidence), 4),
        "tier": tier,
        "override_fired": override_fired,
        "ai_confidence_raw": ai_confidence,
        "deterministic_confidence": deterministic_confidence,
        "criteria_match": _criteria_match_stats(backup, criteria_dict),
        "reason": str(result.get("reason", ""))[:500] if result else "parse failed",
        "title": (result.get("title") or title) if result else title,
        "author": (result.get("author") or author) if result else author,
        "year": (result.get("year") or year) if result else year,
        "parse_ok": bool(result),
        "api_returned": raw is not None,
        "api_calls": 1,
    })
    if confidence < 0.5:
        rec["flags"] = ["low_confidence"]
    return _finalize(rec)


# ---------------------------------------------------------------------------
# Extractor path
# ---------------------------------------------------------------------------
FIELD_DESCRIPTIONS = {
    "Paper Title": "The full title of the research paper",
    "Author": "The main author(s) of the paper",
    "Year": "The publication year of the paper",
    "Journal": "The journal where the paper was published",
    "DOI": "The Digital Object Identifier of the paper",
    "Abstract": "A brief summary of the paper's content",
    "Keywords": "Key terms associated with the paper",
    "Study Design": "The methodology used in the study (e.g. randomized controlled trial, cohort study)",
    "Sample Size": "The number of participants in the study",
    "Intervention": "The treatment or intervention being studied",
    "Comparison": "The control or comparison group",
    "Outcome": "The main results or findings of the study",
    "Conclusion": "The authors' conclusion based on the findings",
    "Funding": "Information about who funded the research",
    "Conflicts of Interest": "Any declared conflicts of interest by the authors",
}


def extract_one_paper(pdf_path: str, fields_list: list, model_key: str) -> dict:
    """One PDF through ReviewAid v3.0.0's extractor logic (extractor.py flow)."""
    t0 = time.time()
    rec = _base_record(pdf_path, model_key, t0)
    m = config.MODELS[model_key]

    fields_list = [f.strip() for f in fields_list if f.strip()]
    if "Paper Title" not in fields_list:
        fields_list.insert(0, "Paper Title")  # extractor.py lines 91-92

    pdf_bytes = Path(pdf_path).read_bytes()
    text, title, author, year = utils.extract_pdf_content(pdf_bytes)
    del pdf_bytes
    if not text.strip():
        rec.update({"decision": "error", "confidence": 0.0, "tier": "none",
                    "extracted": {}, "reason": "PDF empty/unreadable"})
        return _finalize(rec)

    processed = utils.preprocess_text_for_ai(text, max_tokens=utils.MAX_INPUT_TOKENS_EXTRACTOR)
    backup = text

    # ---- Tool's exact extraction prompt (extractor.py lines 279-310)
    prompt = "Extract the following information from the research paper:\n\n"
    for field in fields_list:
        description = FIELD_DESCRIPTIONS.get(field, f"Information about {field}")
        prompt += f"- {field}: {description}\n"
    time.sleep(1)
    prompt += f"""
**Paper Text:**
\"\"\"
{processed}
\"\"\"

**CRITICAL INSTRUCTION:**
Return your response as a SINGLE valid JSON object. Do not include markdown formatting. Ensure all keys are present.
If a field is not found in the text, use the value "Not Found".
**CONFIDENCE SCORE**: Rate your confidence (0.0 to 1.0).
- 1.0 = All extracted fields are explicitly stated in the text.
- 0.8 - 0.9 = Most fields are explicit, some inferred.
- 0.5 - 0.7 = Some fields missing or ambiguous.
- < 0.5 = Data largely missing or garbled.

**JSON Format Required:**
{{
  "extracted": {{
"""
    for field in fields_list:
        prompt += f'    "{field}": "",\n'
    prompt = prompt.rstrip(",\n") + "\n  },\n"
    prompt += '  "confidence": 0.0\n}'
    prompt += "\nEnsure that JSON is valid. Use 'Not Found' for missing data.\n"
    del processed

    raw, active_key = query_provider(model_key, prompt, temperature=0.1,
                                     max_tokens=utils.MAX_OUTPUT_TOKENS)
    del prompt

    result = ra_parser.parse_result(raw, m["provider"], active_key, m["model"],
                                    mode="extractor", fields_list=fields_list,
                                    original_text=backup)
    if not result:
        # Total failure (API dead + fallback failed): mark as error so the
        # resume logic retries this article on the next run.
        rec.update({"decision": "error", "confidence": 0.0, "tier": "none",
                    "extracted": {}, "reason": "parse failed after API failure",
                    "parse_ok": False, "api_returned": raw is not None,
                    "api_calls": 1})
        return _finalize(rec)
    if "extracted" not in result:
        result["extracted"] = {}
    for field in fields_list:
        result["extracted"].setdefault(field, "Not Found")

    # ---- Tier-1 deterministic verification + override (extractor.py 402-446)
    deterministic_confidence = ra_confidence.estimate_confidence(
        backup, mode="extractor", criteria_dict={},
        extracted_data=result["extracted"], fields_list=fields_list)

    ai_confidence = result.get("confidence", None)
    tier, override_fired = "tier2_llm_selfassess", False
    if ai_confidence is not None:
        try:
            ai_confidence = max(0.0, min(1.0, float(ai_confidence)))
        except (TypeError, ValueError):
            ai_confidence = 0.0
        if deterministic_confidence < 0.5 and ai_confidence > 0.5:
            confidence, tier, override_fired = deterministic_confidence, "tier1_override", True
        else:
            confidence = min(ai_confidence, 0.95)
    else:
        confidence = deterministic_confidence
        tier = "tier1_deterministic_score"

    result["confidence"] = confidence
    if confidence < 0.5:
        result["flags"] = ["low_confidence"]
    if result["extracted"].get("Paper Title") in (None, "", "Not Found"):
        result["extracted"]["Paper Title"] = title

    rec.update({
        "decision": "extracted",
        "confidence": round(float(confidence), 4),
        "tier": tier,
        "override_fired": override_fired,
        "ai_confidence_raw": ai_confidence,
        "deterministic_confidence": deterministic_confidence,
        "grounding": analyze_field_grounding(backup, result["extracted"]),
        "extracted": {k: (str(v)[:10000] if isinstance(v, str) else v)
                      for k, v in result["extracted"].items()},
        "parse_ok": bool(result),
        "api_returned": raw is not None,
        "api_calls": 1,
    })
    if confidence < 0.5:
        rec["flags"] = ["low_confidence"]
    return _finalize(rec)


# ---------------------------------------------------------------------------
# Analysis-only instrumentation (never feeds decisions)
# ---------------------------------------------------------------------------
_NEGATIONS = ["not ", "no ", "failed", "unable", "cannot", "without"]


def analyze_field_grounding(text: str, extracted_data: dict) -> dict:
    """Per-field Tier-1 grounding verdicts mirroring confidence.py's extractor
    branch (exact match -> token overlap >0.6, 20-char negation windows). Used
    for the hallucination quantification; the decision path always uses the
    tool's own estimate_confidence."""
    t = text.lower()
    out = {}
    for key, value in (extracted_data or {}).items():
        if not value or str(value).strip() == "Not Found":
            out[key] = {"verdict": "empty", "overlap": 0.0}
            continue
        val_str = str(value).strip()
        val_lower = val_str.lower()
        idx = t.find(val_lower)
        if idx != -1:
            window = t[max(0, idx - 20): idx + len(val_lower) + 20]
            verdict = "negation_blocked" if any(n in window for n in _NEGATIONS) else "exact_match"
            out[key] = {"verdict": verdict, "check": "exact_match", "overlap": 1.0}
            continue
        words = set(re.findall(r"\b\w{4,}\b", val_lower))
        if not words:
            out[key] = {"verdict": "exact_match", "check": "trivial", "overlap": 1.0}
            continue
        overlap = sum(1 for w in words if w in t) / len(words)
        if overlap > 0.6:
            first_word = next(iter(words))
            widx = t.find(first_word)
            window = t[max(0, widx - 20): widx + len(val_str) + 20] if widx != -1 else ""
            neg = widx != -1 and any(n in window for n in _NEGATIONS)
            out[key] = {"verdict": "negation_blocked" if neg else "token_overlap",
                        "check": "token_overlap", "overlap": round(overlap, 3)}
        else:
            out[key] = {"verdict": "ungrounded", "check": "token_overlap",
                        "overlap": round(overlap, 3)}
    return out

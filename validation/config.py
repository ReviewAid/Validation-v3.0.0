"""Central configuration for the ReviewAid v3.0.0 validation study.

The validated artifact is the tool itself: every backend below runs through
ReviewAid_v3.0.0's own utils/parser/confidence code path (see ra_driver.py).
Nothing in this study reimplements the tool's logic.

Analysis settings in ANALYSIS are frozen before the main runs.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
WORKSPACE = BASE.parent
TOOL_DIR = WORKSPACE / "ReviewAid_v3.0.0"
REQUIRED_TOOL_VERSION = "3.0.0"   

CORPUS_DIR = BASE / "corpus"
SCREEN_PDF_DIR = CORPUS_DIR / "pdfs"
EXTRACT_PDF_DIR = CORPUS_DIR / "extraction_pdfs"
RAW_DIR = CORPUS_DIR / "raw"
RESULTS_DIR = BASE / "results"
FIG_DIR = RESULTS_DIR / "figures"
STATS_DIR = RESULTS_DIR / "stats"
AUDIT_DIR = RESULTS_DIR / "audit"
STATE_DIR = BASE / "state"
RAW_CACHE = BASE / "raw_cache"

for _d in (CORPUS_DIR, SCREEN_PDF_DIR, EXTRACT_PDF_DIR, RAW_DIR, RESULTS_DIR,
           FIG_DIR, STATS_DIR, AUDIT_DIR, STATE_DIR, RAW_CACHE):
    _d.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE / ".env")

# ---------------------------------------------------------------------------
# Backends under test: free cloud / free cloud / weak local (~10x capability
# spread). Not a contest - a stress test of the architecture.
# ---------------------------------------------------------------------------
MODELS = {
    "glm": {
        "provider": "GLM (Z.ai)", "model": "GLM-4.7-Flash",
        # ZAI_API_KEYS supports a comma-separated pool (recommended: 3 keys so
        # parallel screening+extraction runs never starve). Falls back to ZAI_API_KEY.
        "keys": lambda: [k.strip() for k in
                         (os.getenv("ZAI_API_KEYS") or os.getenv("ZAI_API_KEY") or "").split(",")
                         if k.strip()],
        "workers": 2,  # free tier is rate-limited (429s at higher concurrency)
    },
    "cohere": {
        "provider": "Cohere", "model": "command-a-03-2025",
        "keys": lambda: [k.strip() for k in os.getenv("COHERE_KEYS", "").split(",") if k.strip()],
        "workers": 3,
    },
    "ollama": {
        "provider": "Ollama (Local)", "model": os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
        "keys": lambda: [""], "workers": 1,
    },
}
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# ---------------------------------------------------------------------------
# Corpus targets
# ---------------------------------------------------------------------------
TARGET_SCREENING_N = 2000
MIN_INCLUDED = 300          # so "0 missed studies" => FNR upper 95% bound < 1%

# EvidenceInference extraction fields (fed to ReviewAid's Extractor).
# Population is not annotated in the public prompts file, so it is not scored.
EXTRACT_FIELDS = ["Intervention", "Comparator", "Outcome", "Effect Direction"]

# ---------------------------------------------------------------------------
# Frozen analysis settings
# ---------------------------------------------------------------------------
ANALYSIS = {
    "auto_threshold": 0.8,        # policy: conf >= tau auto-processed
    "tost_margin": 0.03,          # equivalence margin, +-3 pp
    "bootstrap_n": 2000,
    "bootstrap_seed": 42,
    "calibration_bins": 10,
    "risk_target_eps": 0.05,      # conformal target: auto-accept error <= 5%
    "conformal_confidence": 0.95,
    "calibration_fraction": 0.4,  # share of reviews used to pick tau
    "rerun_subset_n": 100,
    "rerun_seed": 42,
    "audit_concordant_sample": 0.10,
}

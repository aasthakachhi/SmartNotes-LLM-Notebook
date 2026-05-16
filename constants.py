"""
constants.py
============
All static data for SmartNotes v5:
  - Config loader (reads config.yaml once at import)
  - DOMAINS dictionary
  - Language name → BCP-47 code map
  - Noto font registry map
  - Ad / overlay keyword list
  - YouTube URL regex
  - Visual artifact type enum + dataclasses
  - Agent status enum + result / pipeline dataclasses
"""

import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

import yaml

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG LOADER
# ─────────────────────────────────────────────────────────────────────────────

def _load_config(path: str = None) -> dict:
    """Load config.yaml from the given path, or search common locations."""
    candidates = [
        path,
        os.path.join(os.path.dirname(__file__), "config.yaml"),
        "config.yaml",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    raise FileNotFoundError(
        "config.yaml not found. Place it next to constants.py or pass a path.")


CFG: dict = _load_config()

# ── Convenience accessors ─────────────────────────────────────────────────────
MODEL_ID          = CFG["model"]["id"]
FRAME_EVERY_N_SEC = CFG["video"]["frame_every_n_sec"]   # mutable via CLI
DIAGRAM_DPI       = CFG["video"]["diagram_dpi"]
DIAGRAM_MAX_W_CM  = CFG["video"]["diagram_max_width_cm"]
AUDIO_SR          = CFG["audio"]["sample_rate"]
MAX_AUDIO_SEC     = CFG["audio"]["max_duration_sec"]
DUP_THRESHOLD     = CFG["quality"]["dup_threshold"]
MAX_RETRIES       = CFG["quality"]["max_retries"]
QA_MIN_WORDS      = CFG["quality"]["qa_min_words"]
FONT_CACHE        = os.path.expanduser(CFG["fonts"]["cache_dir"])

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING (configured once here; modules just call logging.getLogger)
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, CFG["logging"]["level"], logging.INFO),
    format=CFG["logging"]["format"],
    datefmt=CFG["logging"]["datefmt"],
)

# ─────────────────────────────────────────────────────────────────────────────
# REGEXES
# ─────────────────────────────────────────────────────────────────────────────

YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|"
    r"youtube\.com/shorts/|youtube\.com/embed/)[\w\-]+"
)

# ─────────────────────────────────────────────────────────────────────────────
# AD / PROMOTIONAL OVERLAY KEYWORDS
# ─────────────────────────────────────────────────────────────────────────────

AD_KEYWORDS: List[str] = [
    "live classes", "pyqs", "previous year questions", "csat",
    "test series", "1:1 mentorship", "revision booklets",
    "ncert coverage", "enroll now", "subscribe", "discount",
    "offer valid", "buy now", "join now", "limited seats",
    "gold plan", "platinum plan", "sip package",
    "validity: ", "8 months", "12 months validity",
    "current affairs package", "special prelims",
]

# ─────────────────────────────────────────────────────────────────────────────
# LANGUAGE MAP
# ─────────────────────────────────────────────────────────────────────────────

LANG_NAME_TO_CODE: Dict[str, str] = {
    "hindi": "hi", "bengali": "bn", "tamil": "ta", "telugu": "te",
    "marathi": "mr", "gujarati": "gu", "kannada": "kn", "malayalam": "ml",
    "punjabi": "pa", "urdu": "ur", "odia": "or", "sanskrit": "sa",
    "english": "en", "french": "fr", "spanish": "es", "german": "de",
    "italian": "it", "portuguese": "pt", "russian": "ru", "japanese": "ja",
    "chinese": "zh-CN", "korean": "ko", "arabic": "ar", "turkish": "tr",
    "dutch": "nl", "polish": "pl", "swedish": "sv", "norwegian": "no",
    "danish": "da", "finnish": "fi", "greek": "el", "hebrew": "iw",
    "thai": "th", "vietnamese": "vi", "indonesian": "id", "malay": "ms",
    "swahili": "sw", "yoruba": "yo", "zulu": "zu", "amharic": "am",
    "nepali": "ne", "sinhala": "si", "myanmar": "my", "khmer": "km",
}

# ─────────────────────────────────────────────────────────────────────────────
# NOTO FONT REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

# Maps BCP-47 code → (ReportLab font name, TTF filename)
NOTO_FONT_MAP: Dict[str, Tuple[str, str]] = {
    "hi": ("NotoSansDevanagari", "NotoSansDevanagari-Regular.ttf"),
    "mr": ("NotoSansDevanagari", "NotoSansDevanagari-Regular.ttf"),
    "ne": ("NotoSansDevanagari", "NotoSansDevanagari-Regular.ttf"),
    "sa": ("NotoSansDevanagari", "NotoSansDevanagari-Regular.ttf"),
    "bn": ("NotoSansBengali",    "NotoSansBengali-Regular.ttf"),
    "ta": ("NotoSansTamil",      "NotoSansTamil-Regular.ttf"),
    "te": ("NotoSansTelugu",     "NotoSansTelugu-Regular.ttf"),
    "gu": ("NotoSansGujarati",   "NotoSansGujarati-Regular.ttf"),
    "kn": ("NotoSansKannada",    "NotoSansKannada-Regular.ttf"),
    "ml": ("NotoSansMalayalam",  "NotoSansMalayalam-Regular.ttf"),
    "pa": ("NotoSansGurmukhi",   "NotoSansGurmukhi-Regular.ttf"),
    "ur": ("NotoNastaliqUrdu",   "NotoNastaliqUrdu-Regular.ttf"),
    "or": ("NotoSansOriya",      "NotoSansOriya-Regular.ttf"),
    "si": ("NotoSansSinhala",    "NotoSansSinhala-Regular.ttf"),
    "ar": ("NotoSansArabic",     "NotoSansArabic-Regular.ttf"),
    "iw": ("NotoSansHebrew",     "NotoSansHebrew-Regular.ttf"),
    "th": ("NotoSansThai",       "NotoSansThai-Regular.ttf"),
    "my": ("NotoSansMyanmar",    "NotoSansMyanmar-Regular.ttf"),
    "km": ("NotoSansKhmer",      "NotoSansKhmer-Regular.ttf"),
    "ja": ("NotoSansCJKjp",      "NotoSansJP-Regular.ttf"),
    "zh-CN": ("NotoSansCJKsc",   "NotoSansSC-Regular.ttf"),
    "ko": ("NotoSansCJKkr",      "NotoSansKR-Regular.ttf"),
    "el": ("NotoSans",           "NotoSans-Regular.ttf"),
    "ru": ("NotoSans",           "NotoSans-Regular.ttf"),
    "vi": ("NotoSans",           "NotoSans-Regular.ttf"),
    "am": ("NotoSansEthiopic",   "NotoSansEthiopic-Regular.ttf"),
}

# ─────────────────────────────────────────────────────────────────────────────
# DOMAINS
# ─────────────────────────────────────────────────────────────────────────────

DOMAINS: Dict[str, Dict] = {
    "mathematics": {
        "label": "Mathematics",
        "theme": {"primary": "#1a237e", "secondary": "#3949ab",
                  "accent_bg": "#e8eaf6", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS", "THEOREMS & PROOFS",
                     "WORKED EXAMPLES", "IMPORTANT FORMULAS",
                     "COMMON MISTAKES", "SUMMARY"],
        "prompt_hint": (
            "Mathematics lecture. Write all theorems and proofs formally. "
            "Every equation MUST be in LaTeX ($...$ or $$...$$). "
            "Include step-by-step worked examples."
        ),
        "qa_checks": ["THEOREMS & PROOFS", "IMPORTANT FORMULAS", "WORKED EXAMPLES"],
        "expects_latex": True,
    },
    "physics": {
        "label": "Physics",
        "theme": {"primary": "#0d47a1", "secondary": "#1565c0",
                  "accent_bg": "#e3f2fd", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS", "LAWS & PRINCIPLES",
                     "DERIVATIONS", "IMPORTANT FORMULAS",
                     "EXPERIMENTAL OBSERVATIONS", "APPLICATIONS", "SUMMARY"],
        "prompt_hint": (
            "Physics lecture. State all laws clearly. Show derivations step by "
            "step. All equations in LaTeX. Mention units and real-world applications."
        ),
        "qa_checks": ["LAWS & PRINCIPLES", "IMPORTANT FORMULAS", "DERIVATIONS"],
        "expects_latex": True,
    },
    "chemistry": {
        "label": "Chemistry",
        "theme": {"primary": "#b71c1c", "secondary": "#c62828",
                  "accent_bg": "#fce4ec", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS", "REACTIONS & EQUATIONS",
                     "MECHANISMS", "IMPORTANT FORMULAS",
                     "LAB OBSERVATIONS", "APPLICATIONS", "SUMMARY"],
        "prompt_hint": (
            "Chemistry lecture. Write all equations correctly balanced. "
            "Describe reaction mechanisms. Include states of matter."
        ),
        "qa_checks": ["REACTIONS & EQUATIONS", "MECHANISMS"],
        "expects_latex": True,
    },
    "biology": {
        "label": "Biology",
        "theme": {"primary": "#1b5e20", "secondary": "#2e7d32",
                  "accent_bg": "#e8f5e9", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS",
                     "PROCESSES & MECHANISMS", "CLASSIFICATION & TAXONOMY",
                     "FUNCTIONS & ROLES", "APPLICATIONS", "SUMMARY"],
        "prompt_hint": (
            "Biology lecture. Describe processes step by step. "
            "Use correct scientific nomenclature."
        ),
        "qa_checks": ["PROCESSES & MECHANISMS", "FUNCTIONS & ROLES"],
        "expects_latex": False,
    },
    "computer_science": {
        "label": "Computer Science",
        "theme": {"primary": "#311b92", "secondary": "#4527a0",
                  "accent_bg": "#ede7f6", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS", "ALGORITHMS & LOGIC",
                     "CODE EXAMPLES", "TIME & SPACE COMPLEXITY",
                     "DATA STRUCTURES USED", "USE CASES", "SUMMARY"],
        "prompt_hint": (
            "CS/programming lecture. All code in ```lang...``` fences. "
            "Explain algorithms in plain language then pseudocode. "
            "Always state Big-O complexity."
        ),
        "qa_checks": ["CODE EXAMPLES", "TIME & SPACE COMPLEXITY", "ALGORITHMS & LOGIC"],
        "expects_latex": False,
    },
    "history": {
        "label": "History",
        "theme": {"primary": "#bf360c", "secondary": "#d84315",
                  "accent_bg": "#fbe9e7", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "TIME PERIOD & CONTEXT",
                     "KEY EVENTS (TIMELINE)", "KEY FIGURES",
                     "CAUSES & EFFECTS", "SIGNIFICANCE", "SUMMARY"],
        "prompt_hint": (
            "History lecture. Create a chronological timeline with dates. "
            "Profile key figures. Analyze causes and effects."
        ),
        "qa_checks": ["KEY EVENTS (TIMELINE)", "KEY FIGURES", "CAUSES & EFFECTS"],
        "expects_latex": False,
    },
    "economics": {
        "label": "Economics",
        "theme": {"primary": "#004d40", "secondary": "#00695c",
                  "accent_bg": "#e0f2f1", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS", "MODELS & THEORIES",
                     "DATA & STATISTICS", "POLICY IMPLICATIONS",
                     "REAL-WORLD EXAMPLES", "SUMMARY"],
        "prompt_hint": (
            "Economics lecture. Explain all models and assumptions. "
            "Describe graphs in detail. Include numerical data."
        ),
        "qa_checks": ["MODELS & THEORIES", "DATA & STATISTICS"],
        "expects_latex": False,
    },
    "medicine": {
        "label": "Medicine / Health",
        "theme": {"primary": "#01579b", "secondary": "#0277bd",
                  "accent_bg": "#e1f5fe", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS",
                     "ANATOMY & PHYSIOLOGY", "PATHOPHYSIOLOGY",
                     "DIAGNOSIS & SYMPTOMS", "TREATMENT & MANAGEMENT",
                     "CLINICAL PEARLS", "SUMMARY"],
        "prompt_hint": (
            "Medical lecture. Use correct anatomical terminology. "
            "Describe pathophysiology clearly. List diagnostic criteria."
        ),
        "qa_checks": [
            "PATHOPHYSIOLOGY", "DIAGNOSIS & SYMPTOMS", "TREATMENT & MANAGEMENT"
        ],
        "expects_latex": False,
    },
    "engineering": {
        "label": "Engineering",
        "theme": {"primary": "#e65100", "secondary": "#f57f17",
                  "accent_bg": "#fffde7", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS", "DESIGN PRINCIPLES",
                     "CALCULATIONS & FORMULAS", "WORKED PROBLEMS",
                     "FAILURE MODES & SAFETY", "SUMMARY"],
        "prompt_hint": (
            "Engineering lecture. All formulas in LaTeX with units. "
            "Worked problems step by step. Note safety considerations."
        ),
        "qa_checks": ["CALCULATIONS & FORMULAS", "DESIGN PRINCIPLES"],
        "expects_latex": True,
    },
    "polity": {
        "label": "Polity / Civics",
        "theme": {"primary": "#283593", "secondary": "#3949ab",
                  "accent_bg": "#e8eaf6", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS & DEFINITIONS",
                     "CONSTITUTIONAL PROVISIONS", "GOVERNMENT STRUCTURE",
                     "KEY ARTICLES & SCHEDULES", "LANDMARK CASES",
                     "CURRENT RELEVANCE", "SUMMARY"],
        "prompt_hint": (
            "Polity/civics/governance lecture. Define all constitutional terms. "
            "Cite articles, schedules, and landmark judgments accurately."
        ),
        "qa_checks": ["CONSTITUTIONAL PROVISIONS", "KEY ARTICLES & SCHEDULES"],
        "expects_latex": False,
    },
    "law": {
        "label": "Law",
        "theme": {"primary": "#212121", "secondary": "#37474f",
                  "accent_bg": "#eceff1", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS & DEFINITIONS",
                     "RELEVANT STATUTES & PROVISIONS", "CASE LAW MENTIONED",
                     "LEGAL PRINCIPLES", "PROCEDURE",
                     "PRACTICAL IMPLICATIONS", "SUMMARY"],
        "prompt_hint": (
            "Law lecture. Define all legal terms precisely. "
            "Cite statutes, sections, and case names accurately."
        ),
        "qa_checks": ["LEGAL PRINCIPLES", "RELEVANT STATUTES & PROVISIONS"],
        "expects_latex": False,
    },
    "general": {
        "label": "General",
        "theme": {"primary": "#1a237e", "secondary": "#283593",
                  "accent_bg": "#e8eaf6", "header_text": "#ffffff"},
        "sections": ["TITLE", "OVERVIEW", "KEY CONCEPTS", "DETAILED NOTES",
                     "KEY TAKEAWAYS", "IMPORTANT POINTS", "SUMMARY"],
        "prompt_hint": (
            "Capture all important information comprehensively. "
            "Organize logically. Use LaTeX for any equations."
        ),
        "qa_checks": ["KEY CONCEPTS", "DETAILED NOTES"],
        "expects_latex": False,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# VISUAL ARTIFACT TYPES
# ─────────────────────────────────────────────────────────────────────────────

class ArtifactType(str, Enum):
    EQUATION     = "equation"
    GEOMETRY     = "geometry"
    CHART        = "chart"
    FLOWCHART    = "flowchart"
    TIMELINE     = "timeline"
    TABLE        = "table"
    SCIENCE_DIAG = "science_diag"
    MAP_DESC     = "map_desc"
    TEXT_SLIDE   = "text_slide"
    UNKNOWN      = "unknown"


@dataclass
class VisualArtifact:
    timestamp:    str
    atype:        ArtifactType
    raw_desc:     str
    structured:   Dict
    confidence:   float           = 1.0
    rendered_img: Optional[bytes] = None


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE STATE ENUMS + DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

class AgentStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED  = auto()
    SKIPPED = auto()


@dataclass
class AgentResult:
    agent_name: str
    status:     AgentStatus
    output:     Any   = None
    error:      str   = ""
    duration_s: float = 0.0


@dataclass
class FusedSegment:
    timestamp:  str
    transcript: str
    visuals:    List[VisualArtifact] = field(default_factory=list)


@dataclass
class PipelineState:
    video_path:         str  = ""
    original_source:    str  = ""
    output_path:        str  = CFG["defaults"]["output_path"]
    target_lang_code:   str  = "en"
    target_lang_name:   str  = "English"
    skip_audio:         bool = False
    skip_video:         bool = False
    forced_domain:      Optional[str] = None

    audio_path:         str  = ""
    transcription:      str  = ""
    detected_lang:      str  = "Unknown"
    detected_lang_code: str  = "en"
    artifacts:          List[VisualArtifact] = field(default_factory=list)
    fused_segments:     List[FusedSegment]   = field(default_factory=list)
    domain:             str  = "general"
    domain_scores:      Dict[str, float]     = field(default_factory=dict)
    target_notes:       str  = ""
    source_notes:       str  = ""
    title:              str  = "Lecture Notes"
    qa_repair_hint:     str  = ""
    qa_issues:          List[str]            = field(default_factory=list)

    model:     Any = None
    processor: Any = None

    # ── New fields ────────────────────────────────────────────────────────────
    input_type:        str  = "video"          # "video" | "pdf"
    practice_pdf_path: str  = ""               # path for practice questions PDF
    chat_history:      List[Dict] = field(default_factory=list)  # interactive bot history

    agent_results: Dict[str, AgentResult] = field(default_factory=dict)
    retry_count:   int = 0

    def record(self, result: AgentResult):
        log = logging.getLogger("SmartNotes")
        self.agent_results[result.agent_name] = result
        icon = {"SUCCESS": "✓", "FAILED": "✗",
                "SKIPPED": "⊘", "RUNNING": "⋯"}.get(result.status.name, "?")
        msg = f"{icon} {result.agent_name} [{result.status.name}]"
        if result.duration_s:
            msg += f"  {result.duration_s:.1f}s"
        if result.error:
            msg += f"  — {result.error}"
        log.info(msg)

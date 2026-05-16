"""
app.py  —  SmartNotes v5
Run with:  streamlit run app.py
"""
import os, logging, warnings, re, asyncio, threading, time
from pathlib import Path

os.environ["TRANSFORMERS_VERBOSITY"] = "error"
warnings.filterwarnings("ignore")
for _n in ["transformers","transformers.modeling_utils","transformers.configuration_utils",
           "streamlit.runtime.scriptrunner_utils.script_run_context","streamlit"]:
    logging.getLogger(_n).setLevel(logging.ERROR)

import streamlit as st

st.set_page_config(page_title="SmartNotes v5", page_icon="📓",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;600&family=JetBrains+Mono:wght@400;500&display=swap');
:root{--ink:#1a1a2e;--paper:#f5f0e8;--accent:#c0392b;--gold:#e8a838;--muted:#8c7b6b;--success:#27ae60;--border:#d4c9b8;--card:#faf7f2;}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
.main .block-container{background:var(--paper);max-width:900px;padding:2rem 2.5rem 4rem;}
section[data-testid="stSidebar"]{background:var(--ink)!important;}
section[data-testid="stSidebar"] *{color:#e8e4dc!important;}
.hero{background:var(--ink);border-radius:4px;padding:2rem 2.5rem;margin-bottom:1.5rem;}
.hero h1{font-family:'DM Serif Display',serif;font-size:2.2rem;color:#f5f0e8!important;margin:0 0 .3rem;}
.hero .sub{color:#a89f94;font-size:.9rem;}
.hero .badge{background:var(--accent);color:#fff;font-size:.6rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:2px 8px;border-radius:2px;margin-left:.5rem;vertical-align:middle;}
div.stButton>button{background:var(--ink)!important;color:#f5f0e8!important;border:none!important;border-radius:3px!important;font-weight:500!important;}
div.stButton>button[kind="primary"]{background:var(--accent)!important;}
.logbox{background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:1rem 1.2rem;font-family:'JetBrains Mono',monospace;font-size:.78rem;line-height:1.8;color:#c9d1d9;max-height:500px;overflow-y:auto;white-space:pre-wrap;word-break:break-word;}
.ok{color:#3fb950;} .err{color:#f85149;} .info{color:#58a6ff;} .warn{color:#d29922;}
.sn-card{background:var(--card);border:1px solid var(--border);border-radius:4px;padding:1.2rem 1.4rem;margin-bottom:.8rem;}
.sn-info{background:#f0f4ff;border-left:3px solid #3949ab;padding:.7rem 1rem;font-size:.84rem;border-radius:0 3px 3px 0;margin:.5rem 0;}
.sn-warn{background:#fffbf0;border-left:3px solid var(--gold);padding:.7rem 1rem;font-size:.84rem;border-radius:0 3px 3px 0;margin:.5rem 0;}
.done-box{background:#f2faf5;border:1px solid #b8dfc8;border-radius:4px;padding:1.2rem 1.4rem;margin:1rem 0;}
</style>
""", unsafe_allow_html=True)

# ── Import project ──────────────────────────────────────────────────────────
def _try_import():
    try:
        from constants import CFG, DOMAINS, LANG_NAME_TO_CODE, YOUTUBE_RE, PipelineState
        from agents_io import InputAgent, ModelLoaderAgent, AudioAgent
        from agents_visual import VisualAgent, FusionAgent, DiagramRenderAgent
        from agents_notes import DomainAgent, NotesGenerationAgent, QAValidatorAgent, SourceNotesAgent, PracticeQAAgent
        from pdf_builder import PDFGenerationAgent, build_practice_pdf
        return True, CFG, DOMAINS, LANG_NAME_TO_CODE, YOUTUBE_RE, PipelineState
    except Exception as e:
        return False, None, None, None, None, str(e)

_ok, CFG, DOMAINS, LANG_NAME_TO_CODE, YOUTUBE_RE, _ERR_OR_STATE = _try_import()
IMPORT_OK  = _ok
IMPORT_ERR = _ERR_OR_STATE if not _ok else None
if _ok:
    PipelineState = _ERR_OR_STATE

if not IMPORT_OK:
    DOMAINS = {"mathematics":{"label":"Mathematics"},"physics":{"label":"Physics"},"chemistry":{"label":"Chemistry"},"biology":{"label":"Biology"},"history":{"label":"History"},"economics":{"label":"Economics"},"medicine":{"label":"Medicine"},"engineering":{"label":"Engineering"},"polity":{"label":"Polity"},"law":{"label":"Law"},"general":{"label":"General"}}
    LANG_NAME_TO_CODE = {"english":"en","hindi":"hi","bengali":"bn","tamil":"ta","telugu":"te","marathi":"mr","gujarati":"gu","kannada":"kn","malayalam":"ml","punjabi":"pa","urdu":"ur","french":"fr","spanish":"es","german":"de","italian":"it","portuguese":"pt","russian":"ru","japanese":"ja","chinese":"zh-CN","korean":"ko","arabic":"ar","turkish":"tr"}

# ── Global log queue — background thread writes, UI thread reads ────────────
# Using a simple list protected by nothing (GIL is enough for append/copy)
if "log_lines" not in st.session_state:
    st.session_state["log_lines"] = []
if "running" not in st.session_state:
    st.session_state["running"] = False
if "done" not in st.session_state:
    st.session_state["done"] = False
if "output_pdf" not in st.session_state:
    st.session_state["output_pdf"] = None
if "practice_pdf" not in st.session_state:
    st.session_state["practice_pdf"] = None
if "output_path" not in st.session_state:
    st.session_state["output_path"] = "smart_notes.pdf"
if "practice_path" not in st.session_state:
    st.session_state["practice_path"] = ""
if "error" not in st.session_state:
    st.session_state["error"] = None

# ── Cross-thread shared dict (NOT session_state) ────────────────────────────
import importlib, sys
# Store in a module-level singleton so it survives Streamlit reruns
if "_sn_shared" not in sys.modules:
    import types
    _mod = types.ModuleType("_sn_shared")
    _mod.data = {
        "running": False, "done": False, "error": None,
        "result": None, "log": []
    }
    sys.modules["_sn_shared"] = _mod

_G = sys.modules["_sn_shared"].data   # shorthand

# ── Sync _G → session_state (runs on every Streamlit rerun) ────────────────
def _sync():
    st.session_state["running"]  = _G["running"]
    st.session_state["log_lines"] = list(_G["log"])   # snapshot

    if _G["error"] and not st.session_state["error"]:
        st.session_state["error"] = _G["error"]

    if _G["done"] and _G["result"] and not st.session_state["done"]:
        r = _G["result"]
        st.session_state["done"]          = True
        st.session_state["output_pdf"]    = r["output_pdf"]
        st.session_state["output_path"]   = r["output_path"]
        st.session_state["practice_pdf"]  = r["practice_pdf"]
        st.session_state["practice_path"] = r["practice_path"]
        st.session_state["domain"]        = r.get("domain","")
        st.session_state["lang"]          = r.get("lang","")

_sync()

# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""<div style="padding:1rem 0 .6rem;border-bottom:1px solid #2d2d4e;margin-bottom:1rem">
    <span style="font-family:'DM Serif Display',serif;font-size:1.4rem">SmartNotes</span>
    <span style="font-size:.7rem;color:#a89f94;display:block;letter-spacing:.1em;text-transform:uppercase">v5 · AI Study Notes</span>
    </div>""", unsafe_allow_html=True)

    lang_names    = sorted(LANG_NAME_TO_CODE.keys())
    selected_lang = st.selectbox("Target Language", lang_names,
                                  index=lang_names.index("english") if "english" in lang_names else 0)
    domain_opts   = ["auto-detect"] + list(DOMAINS.keys())
    selected_domain = st.selectbox("Domain Override", domain_opts, index=0)
    st.markdown("---")
    frame_n      = st.slider("Frame every N seconds", 1, 30, 5)
    skip_audio   = st.checkbox("Skip audio transcription", value=False)
    skip_video   = st.checkbox("Skip video frame sampling", value=False)
    no_practice  = st.checkbox("Skip practice questions PDF", value=False)
    output_name  = st.text_input("Output filename", value="smart_notes.pdf")
    if not output_name.endswith(".pdf"):
        output_name += ".pdf"

# ── Hero ─────────────────────────────────────────────────────────────────────
st.markdown("""<div class="hero">
<h1>SmartNotes <span class="badge">v5</span></h1>
<div class="sub">Lecture · PDF · YouTube → Bilingual AI Study Notes</div>
</div>""", unsafe_allow_html=True)

if not IMPORT_OK:
    st.warning(f"**Preview mode** — SmartNotes modules not found.\n\n`{IMPORT_ERR}`")

# ── Input ─────────────────────────────────────────────────────────────────────
with st.container():
    st.markdown("#### Input Source")
    input_mode = st.radio("mode", ["Upload file (video / PDF)", "YouTube URL", "Local file path"],
                           horizontal=True, label_visibility="collapsed")
    video_path_resolved = None

    if input_mode == "Upload file (video / PDF)":
        up = st.file_uploader("Upload", type=["mp4","mkv","webm","avi","mov","pdf"],
                               label_visibility="collapsed")
        if up:
            sp = os.path.join("/tmp", up.name)
            with open(sp,"wb") as f: f.write(up.read())
            video_path_resolved = sp
            kind = "PDF" if up.name.lower().endswith(".pdf") else "Video"
            st.success(f"✓ {kind} saved — {up.name} ({os.path.getsize(sp)/1e6:.1f} MB)")

    elif input_mode == "YouTube URL":
        yt = st.text_input("YouTube URL", placeholder="https://youtu.be/...")
        if yt:
            if IMPORT_OK:
                valid = bool(YOUTUBE_RE.match(yt.strip()))
            else:
                valid = "youtu" in yt
            if valid:
                video_path_resolved = yt.strip()
                st.success("✓ Valid YouTube URL")
            else:
                st.warning("⚠ Doesn't look like a valid YouTube URL")
    else:
        lp = st.text_input("File path", placeholder="/home/user/lecture.mp4")
        if lp:
            if os.path.exists(lp):
                video_path_resolved = lp
                st.success(f"✓ File found — {os.path.getsize(lp)/1e6:.1f} MB")
            else:
                st.warning(f"⚠ File not found: {lp}")

lang_code = LANG_NAME_TO_CODE.get(selected_lang.lower(), "en")

# c1,c2,c3,c4 = st.columns(4)
# c1.metric("Language",     selected_lang.capitalize())
# c2.metric("Domain",       selected_domain if selected_domain != "auto-detect" else "Auto")
# c3.metric("Frame rate",   f"1/{frame_n}s")
# c4.metric("Practice PDF", "Skip" if no_practice else "Yes")

st.divider()

# ── Background pipeline function ──────────────────────────────────────────────
def _push(line: str):
    """Append a line to the shared log."""
    _G["log"].append(line)


class _StreamlitLogHandler(logging.Handler):
    """
    Logging handler that forwards every log record from the SmartNotes
    logger into the shared _G["log"] list so the UI logbox picks it up.
    Installed only while _run_bg() is active; removed afterwards.
    """
    _LEVEL_PREFIX = {
        logging.DEBUG:    "·  ",
        logging.INFO:     "   ",
        logging.WARNING:  "\u26a0  ",
        logging.ERROR:    "\u2717  ",
        logging.CRITICAL: "\u2717  ",
    }

    def emit(self, record: logging.LogRecord) -> None:
        try:
            prefix = self._LEVEL_PREFIX.get(record.levelno, "   ")
            _push(prefix + self.format(record))
        except Exception:
            pass


_ui_log_handler = _StreamlitLogHandler()
_ui_log_handler.setFormatter(logging.Formatter("%(message)s"))
_ui_log_handler.setLevel(logging.DEBUG)


def _run_bg():
    """Runs entirely in background thread. Never touches st.session_state."""
    # Attach UI log handler so all log.info/warning/error calls from every
    # module (agents_io, agents_notes, agents_visual, etc.) appear in the
    # logbox — no changes needed in those files.
    _sn_logger = logging.getLogger("SmartNotes")
    _sn_logger.addHandler(_ui_log_handler)

    try:
        import constants as _c
        _c.FRAME_EVERY_N_SEC = frame_n
        from main import Orchestrator, cleanup

        forced_domain = None if selected_domain == "auto-detect" else selected_domain

        from constants import PipelineState as PS
        state = PS(
            video_path       = video_path_resolved,
            original_source  = video_path_resolved,
            output_path      = output_name,
            target_lang_code = lang_code,
            target_lang_name = selected_lang.capitalize(),
            skip_audio       = skip_audio,
            skip_video       = skip_video,
            forced_domain    = forced_domain,
        )

        # Patch record() so each agent completion gets logged
        _orig = state.record
        def _rec(result):
            try: _orig(result)
            except: pass
            name   = result.agent_name
            status = result.status.name
            dur    = result.duration_s
            icons  = {"SUCCESS":"✓","FAILED":"✗","SKIPPED":"⊘","RUNNING":"⋯"}
            icon   = icons.get(status,"?")
            dur_s  = f"  {dur:.1f}s" if dur else ""
            err    = f"\n    ↳ {result.error}" if result.error else ""
            _push(f"{icon}  {name:<30} [{status}]{dur_s}{err}")
        state.record = _rec

        _push("▶  Pipeline starting…")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        orch = Orchestrator()
        loop.run_until_complete(orch.run(state, skip_practice=no_practice))
        loop.close()

        # Read output files
        out_bytes  = open(state.output_path,"rb").read() if os.path.exists(state.output_path) else None
        prac_path  = getattr(state,"practice_pdf_path","") or ""
        prac_bytes = open(prac_path,"rb").read() if prac_path and os.path.exists(prac_path) else None

        _push("─"*52)
        _push(f"✓  Main PDF    : {state.output_path}")
        if prac_path: _push(f"✓  Practice    : {prac_path}")
        _push(f"   Domain      : {getattr(state,'domain','')}")
        _push(f"   Language    : {getattr(state,'detected_lang','')}")
        _push("─"*52)

        _G["result"] = {
            "output_pdf":   out_bytes,
            "output_path":  state.output_path,
            "practice_pdf": prac_bytes,
            "practice_path":prac_path,
            "domain":       getattr(state,"domain",""),
            "lang":         getattr(state,"detected_lang",""),
        }
        _G["done"]  = True
        _G["error"] = None

        try: cleanup(state)
        except: pass

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        _push(f"✗  ERROR: {exc}")
        _push(tb)
        _G["error"] = str(exc)
        _G["done"]  = False
    finally:
        _G["running"] = False
        # Detach the UI log handler so it doesn't stack on the next run
        logging.getLogger("SmartNotes").removeHandler(_ui_log_handler)

# ── Generate Notes button ─────────────────────────────────────────────────────
btn_disabled = st.session_state["running"] or not video_path_resolved or not IMPORT_OK

if st.button("▶  Generate Notes", type="primary",
             disabled=btn_disabled, use_container_width=True):
    # Reset global state
    _G["running"] = True
    _G["done"]    = False
    _G["error"]   = None
    _G["result"]  = None
    _G["log"]     = []
    # Reset session state
    st.session_state["running"]     = True
    st.session_state["done"]        = False
    st.session_state["error"]       = None
    st.session_state["log_lines"]   = []
    st.session_state["output_pdf"]  = None
    st.session_state["practice_pdf"]= None
    threading.Thread(target=_run_bg, daemon=True).start()
    time.sleep(0.3)   # tiny pause so thread starts before first rerun
    st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# ── Log display ───────────────────────────────────────────────────────────────
log_lines = st.session_state.get("log_lines", [])

if st.session_state["running"] or log_lines:
    st.markdown("**Pipeline Output**")

    def _color(line):
        l = line.lower()
        if any(x in l for x in ("✗","error","failed","traceback","exception")):
            css = "err"
        elif any(x in l for x in ("✓","success","main pdf","practice :")):
            css = "ok"
        elif any(x in l for x in ("▶","⋯","running","starting")):
            css = "info"
        elif any(x in l for x in ("⊘","skipped","warning","warn","─")):
            css = "warn"
        else:
            css = ""
        safe = line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        return f'<span class="{css}">{safe}</span>' if css else safe

    body = "\n".join(_color(l) for l in log_lines)
    if st.session_state["running"]:
        body += '\n<span class="info">⋯  running…</span>'

    st.markdown(f'<div class="logbox">{body}</div>', unsafe_allow_html=True)

# ── Error ─────────────────────────────────────────────────────────────────────
if st.session_state.get("error"):
    st.error(f"Pipeline failed: {st.session_state['error']}")

# ── Download section (same page, appears when done) ──────────────────────────
if st.session_state["done"]:
    st.markdown("""<div class="done-box">
    <b style="color:#27ae60;font-size:1.05rem">✓  Notes generated successfully!</b>
    </div>""", unsafe_allow_html=True)

    st.divider()
    m1,m2 = st.columns(2)
    m1.metric("Domain",   st.session_state.get("domain","—") or "—")
    m2.metric("Language", st.session_state.get("lang","—")   or "—")
    st.markdown("")

    dl1, dl2 = st.columns(2)

    with dl1:
        st.markdown('<div class="sn-card">', unsafe_allow_html=True)
        st.markdown("**📘 Study Notes PDF**")
        if st.session_state["output_pdf"]:
            fname = Path(st.session_state["output_path"]).name
            st.download_button("⬇  Download Notes PDF",
                data=st.session_state["output_pdf"], file_name=fname,
                mime="application/pdf", use_container_width=True)
            st.caption(f"{fname} · {len(st.session_state['output_pdf'])//1000} KB")
        else:
            st.warning("PDF file not found on disk.")
        st.markdown('</div>', unsafe_allow_html=True)

    with dl2:
        st.markdown('<div class="sn-card">', unsafe_allow_html=True)
        st.markdown("**📝 Practice Questions PDF**")
        if st.session_state["practice_pdf"]:
            fname2 = Path(st.session_state["practice_path"]).name
            st.download_button("⬇  Download Practice PDF",
                data=st.session_state["practice_pdf"], file_name=fname2,
                mime="application/pdf", use_container_width=True)
            st.caption(f"{fname2} · {len(st.session_state['practice_pdf'])//1000} KB")
        elif no_practice:
            st.info("Skipped in settings.")
        else:
            st.warning("Practice PDF not found.")
        st.markdown('</div>', unsafe_allow_html=True)

# ── Polling heartbeat — ALWAYS at the very bottom ─────────────────────────────
if st.session_state["running"]:
    time.sleep(1.0)
    st.rerun()
elif _G["done"] and not st.session_state["done"]:
    st.rerun()
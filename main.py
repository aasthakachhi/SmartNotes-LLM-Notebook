"""
main.py
=======
SmartNotes v5 — entry point.

NEW IN THIS VERSION
-------------------
  1. Interactive chat bot — after notes are generated, students can ask
     questions about the lecture. Type 'exit' / 'quit' to stop.
     Use --no-chat to skip.

  2. Practice questions PDF — a separate PDF (<name>_practice.pdf) is
     generated automatically in the target language with MCQ, short-answer,
     long-answer, true/false, and fill-in-the-blank sections.
     Use --no-practice to skip.

  3. PDF input — pass a PDF file via --pdf-input (or --video with a .pdf
     path) and the pipeline extracts text, skips audio/video agents, and
     generates notes exactly as it would for a video lecture.

Usage:
  python3 main.py --video lecture.mp4 --target-lang hindi
  python3 main.py --video "https://youtu.be/XXXX" --target-lang english
  python3 main.py --pdf-input notes.pdf --target-lang marathi
  python3 main.py --video lecture.mp4 --target-lang hindi --no-chat
  python3 main.py --video lecture.mp4 --domain biology --no-practice

Requirements:
  sudo apt install ffmpeg
  pip install pyyaml transformers torch accelerate librosa soundfile \\
              opencv-python pillow reportlab matplotlib numpy yt-dlp pymupdf
"""

import argparse
import asyncio
import logging
import os
from typing import Tuple

from constants import (
    CFG, DOMAINS, LANG_NAME_TO_CODE, YOUTUBE_RE,
    AgentResult, AgentStatus, PipelineState,
)
from agents_io import InputAgent, ModelLoaderAgent, AudioAgent
from agents_visual import VisualAgent, FusionAgent, DiagramRenderAgent
from agents_notes import (
    DomainAgent, NotesGenerationAgent, QAValidatorAgent, SourceNotesAgent,
    PracticeQAAgent,
)
from pdf_builder import PDFGenerationAgent, build_practice_pdf

log = logging.getLogger("SmartNotes")


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

class Orchestrator:
    def __init__(self):
        self.input_agent     = InputAgent()
        self.model_agent     = ModelLoaderAgent()
        self.audio_agent     = AudioAgent()
        self.visual_agent    = VisualAgent()
        self.fusion_agent    = FusionAgent()
        self.domain_agent    = DomainAgent()
        self.notes_agent     = NotesGenerationAgent()
        self.qa_agent        = QAValidatorAgent()
        self.src_agent       = SourceNotesAgent()
        self.diagram_agent   = DiagramRenderAgent()
        self.pdf_agent       = PDFGenerationAgent()
        self.practice_agent  = PracticeQAAgent()

    async def run(self, state: PipelineState, skip_practice: bool = False):
        log.info("=" * 60)
        log.info("SMART NOTES v5 — START")
        log.info("=" * 60)
        t0 = asyncio.get_event_loop().time()

        # ── Stage 0: validate / download input ───────────────────────────────
        self._req(await self.input_agent.run(state), "InputAgent")

        # ── Stage 1: load model ───────────────────────────────────────────────
        self._req(await self.model_agent.run(state), "ModelLoaderAgent")

        # ── Stage 2: audio + visual in parallel ──────────────────────────────
        # For PDF inputs, both agents are skipped automatically via state flags.
        log.info("AudioAgent + VisualAgent (parallel) …")
        results = await asyncio.gather(
            asyncio.create_task(self.audio_agent.run(state)),
            asyncio.create_task(self.visual_agent.run(state)),
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                log.error(f"Parallel agent error: {res}")

        if not state.transcription and not state.artifacts:
            raise RuntimeError(
                "Both AudioAgent and VisualAgent produced no output. "
                "Check your input file.")

        # ── Stage 3: fuse audio + visual timeline ────────────────────────────
        self._req(await self.fusion_agent.run(state), "FusionAgent")

        # ── Stage 4: detect domain ────────────────────────────────────────────
        self._req(await self.domain_agent.run(state), "DomainAgent")

        # ── Stage 5: notes generation with QA retry loop ─────────────────────
        from constants import MAX_RETRIES
        state.qa_repair_hint = ""
        for attempt in range(MAX_RETRIES):
            state.retry_count = attempt
            self._req(
                await self.notes_agent.run(state), "NotesGenerationAgent")
            qa_r = await self.qa_agent.run(state)
            if qa_r.status == AgentStatus.SUCCESS and qa_r.output is True:
                break
            if attempt < MAX_RETRIES - 1:
                log.warning(f"QA retry {attempt + 1}/{MAX_RETRIES - 1} …")
            else:
                log.warning("QA never passed — using best available notes.")

        # ── Stage 6: source notes + diagram render (parallel) ─────────────────
        log.info("SourceNotesAgent + DiagramRenderAgent (parallel) …")
        results = await asyncio.gather(
            asyncio.create_task(self.src_agent.run(state)),
            asyncio.create_task(self.diagram_agent.run(state)),
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                log.error(f"Parallel agent error: {res}")

        # ── Stage 7: main PDF ─────────────────────────────────────────────────
        self._req(await self.pdf_agent.run(state), "PDFGenerationAgent")

        # ── Stage 8: practice questions PDF ──────────────────────────────────
        if not skip_practice:
            await self.practice_agent.run(state)
            if getattr(state, "practice_questions", "").strip():
                try:
                    build_practice_pdf(state)
                    log.info(f"Practice PDF → {state.practice_pdf_path}")
                except Exception as exc:
                    log.warning(f"Practice PDF generation failed: {exc}")
            else:
                log.warning(
                    "PracticeQAAgent returned no content — skipping PDF.")
        else:
            log.info("Practice questions PDF skipped (--no-practice).")

        elapsed = asyncio.get_event_loop().time() - t0
        log.info("=" * 60)
        log.info(f"DONE  →  {state.output_path}  ({elapsed:.1f}s)")
        log.info("=" * 60)
        self._summary(state)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _req(result: AgentResult, name: str):
        if result.status == AgentStatus.FAILED:
            raise RuntimeError(
                f"Required agent '{name}' failed: {result.error}")

    @staticmethod
    def _summary(state: PipelineState):
        print("\n" + "─" * 60)
        print("AGENT SUMMARY")
        print("─" * 60)
        for name, r in state.agent_results.items():
            icon = {
                "SUCCESS": "✓", "FAILED": "✗",
                "SKIPPED": "⊘", "RUNNING": "⋯", "PENDING": "○",
            }.get(r.status.name, "?")
            dur = f"{r.duration_s:.1f}s" if r.duration_s else ""
            err = f"  ← {r.error}" if r.error else ""
            print(f"  {icon}  {name:<32} {dur:<8}{err}")
        print("─" * 60)
        print(f"  Main PDF   : {state.output_path}")
        if getattr(state, "practice_pdf_path", ""):
            print(f"  Practice   : {state.practice_pdf_path}")
        print(f"  Domain     : {state.domain}"
              f" ({DOMAINS[state.domain]['label']})")
        print(f"  Language   : {state.target_lang_name}"
              f" ({state.target_lang_code})")
        print(f"  Artifacts  : {len(state.artifacts)}")
        print("─" * 60 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# LANGUAGE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def resolve_lang(lang_input: str) -> Tuple[str, str]:
    """Return (bcp47_code, display_name) for a language name or code."""
    lo = lang_input.strip().lower()
    if lo in LANG_NAME_TO_CODE:
        return LANG_NAME_TO_CODE[lo], lo.capitalize()
    rev = {v: k for k, v in LANG_NAME_TO_CODE.items()}
    if lo in rev:
        return lo, rev[lo].capitalize()
    raise ValueError(
        f"Unknown language: {lang_input!r}\n"
        f"Supported: {', '.join(sorted(LANG_NAME_TO_CODE.keys()))}")


# ─────────────────────────────────────────────────────────────────────────────
# INTERACTIVE PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

def ask_video_input() -> str:
    """Interactive prompt for video / PDF path or YouTube URL."""
    print()
    print("┌" + "─" * 58 + "┐")
    print("│" + "  📹  SMART NOTES v5".center(58) + "│")
    print("│" + "  Lecture → Bilingual AI Study Notes".center(58) + "│")
    print("└" + "─" * 58 + "┘")
    print()
    print("  Enter a local video/PDF file path  OR  a YouTube URL.")
    print("  Examples:")
    print("    /home/user/lecture.mp4")
    print("    /home/user/slides.pdf")
    print("    https://youtu.be/XXXX")
    print()
    while True:
        src = input("  File / URL: ").strip()
        if not src:
            print("  ✗  Please enter a path or URL.")
            continue
        if YOUTUBE_RE.match(src):
            print("  ✓  YouTube URL detected.")
            return src
        if os.path.exists(src):
            size_mb = os.path.getsize(src) / 1e6
            kind    = "PDF" if src.lower().endswith(".pdf") else "File"
            print(f"  ✓  {kind} found  ({size_mb:.1f} MB)")
            return src
        print(f"  ✗  File not found: {src!r}  — try again.")


def ask_target_language() -> Tuple[str, str]:
    """Interactive prompt to pick the output language."""
    print()
    print("─" * 60)
    print("  Available languages:")
    print()
    names = sorted(LANG_NAME_TO_CODE.keys())
    cols, col_w = 5, 14
    for i in range(0, len(names), cols):
        print("  " + "".join(f"{n:<{col_w}}" for n in names[i:i + cols]))
    print()
    while True:
        lang = input("  Target language: ").strip()
        if not lang:
            continue
        try:
            code, name = resolve_lang(lang)
            print(f"  ✓  Notes will be written in: {name} ({code})")
            return code, name
        except ValueError as e:
            print(f"  ✗  {e}")


def ask_output_path() -> str:
    """Interactive prompt for output PDF path."""
    default = CFG["defaults"]["output_path"]
    print()
    print(f"  Output PDF path  (press Enter for default: {default!r})")
    path = input("  Output file: ").strip()
    if not path:
        return default
    if not path.endswith(".pdf"):
        path += ".pdf"
    print(f"  ✓  Will save to: {path}")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────────────────────────────────────

def cleanup(state: PipelineState):
    for path in [state.audio_path]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                log.info(f"Cleaned: {path}")
            except OSError:
                pass
    if (state.original_source
            and YOUTUBE_RE.match(state.original_source.strip())
            and state.video_path
            and os.path.exists(state.video_path)):
        try:
            os.remove(state.video_path)
            log.info(f"Cleaned: {state.video_path}")
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Smart Notes v5 — lecture / PDF → clean bilingual PDF.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--video", default=None,
        help=(
            "Video/audio file path, PDF path, or YouTube URL.\n"
            "Omit to be prompted interactively."
        ),
    )
    parser.add_argument(
        "--pdf-input", default=None,
        help="Path to a PDF file to process (same as --video for .pdf files).",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output PDF path (default from config.yaml).",
    )
    parser.add_argument(
        "--target-lang", default=None,
        help="Target language name or BCP-47 code, e.g. 'hindi', 'en'.\n"
             "Omit to be prompted interactively.",
    )
    parser.add_argument(
        "--domain", default=CFG["defaults"].get("domain"),
        help=f"Force domain. Options: {', '.join(DOMAINS.keys())}",
    )
    parser.add_argument(
        "--fps", type=int, default=CFG["video"]["frame_every_n_sec"],
        help="Sample one video frame every N seconds (default: from config).",
    )
    parser.add_argument(
        "--skip-audio", action="store_true",
        help="Skip audio extraction and transcription.",
    )
    parser.add_argument(
        "--skip-video", action="store_true",
        help="Skip video frame sampling.",
    )
    parser.add_argument(
        "--no-practice", action="store_true",
        help="Skip practice questions PDF generation.",
    )
    args = parser.parse_args()

    # ── Resolve input ─────────────────────────────────────────────────────────
    if args.pdf_input:
        video_path = args.pdf_input
    elif args.video:
        video_path = args.video
    else:
        video_path = ask_video_input()

    # ── Resolve language ──────────────────────────────────────────────────────
    if args.target_lang:
        tgt_code, tgt_name = resolve_lang(args.target_lang)
    else:
        tgt_code, tgt_name = ask_target_language()

    # ── Resolve output path ───────────────────────────────────────────────────
    output_path = args.output if args.output else ask_output_path()

    # ── Resolve domain ────────────────────────────────────────────────────────
    forced_domain = None
    if args.domain:
        if args.domain not in DOMAINS:
            print(f"  ✗  Unknown domain '{args.domain}'. "
                  f"Valid: {', '.join(DOMAINS.keys())}")
            return
        forced_domain = args.domain

    # ── Pre-run summary ───────────────────────────────────────────────────────
    input_kind = (
        "PDF"     if str(video_path).lower().endswith(".pdf") else
        "YouTube" if YOUTUBE_RE.match(video_path) else
        "Video"
    )
    print()
    print("─" * 60)
    print("  STARTING PIPELINE")
    print("─" * 60)
    print(f"  Input    : {video_path}  [{input_kind}]")
    print(f"  Language : {tgt_name} ({tgt_code})")
    print(f"  Output   : {output_path}")
    if forced_domain:
        print(f"  Domain   : {forced_domain} (forced)")
    print(f"  Practice : {'skipped' if args.no_practice else 'yes → _practice.pdf'}")
    print("─" * 60 + "\n")

    # Override frame rate from config if CLI flag given
    import constants as _c
    _c.FRAME_EVERY_N_SEC = args.fps

    state = PipelineState(
        video_path       = video_path,
        original_source  = video_path,
        output_path      = output_path,
        target_lang_code = tgt_code,
        target_lang_name = tgt_name,
        skip_audio       = args.skip_audio,
        skip_video       = args.skip_video,
        forced_domain    = forced_domain,
    )

    orchestrator = Orchestrator()
    try:
        asyncio.run(
            orchestrator.run(state, skip_practice=args.no_practice))
    except KeyboardInterrupt:
        print("\n  Pipeline interrupted by user.")
    finally:
        cleanup(state)



if __name__ == "__main__":
    main()
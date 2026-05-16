"""
pdf_builder.py
==============
PDF generation agents for SmartNotes v5:
  - PDFGenerationAgent   (renders the main study-notes PDF)
  - build_practice_pdf() (renders the practice-questions PDF)

Both use ReportLab.  A plain-text fallback is provided for environments
where ReportLab is unavailable or crashes.

Font support
------------
Noto fonts are loaded from FONT_CACHE (see constants.py / config.yaml).
If a font file is missing the builder falls back to Helvetica so the PDF
is still produced.  Download fonts with:
    pip install google-noto-fonts   # or grab TTFs from fonts.google.com
"""

import io
import logging
import os
import re
import textwrap
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from constants import PipelineState

log = logging.getLogger("SmartNotes")


# ─────────────────────────────────────────────────────────────────────────────
# FONT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _hex_to_color(hex_str: str):
    from reportlab.lib import colors
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return colors.Color(r / 255, g / 255, b / 255)


def _register_font(lang_code: str):
    """
    Try to register the Noto font for lang_code.
    Returns (body_font_name, title_font_name).
    Falls back to ('Helvetica', 'Helvetica-Bold') on any failure.
    """
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from constants import NOTO_FONT_MAP, FONT_CACHE

        if lang_code not in NOTO_FONT_MAP:
            return "Helvetica", "Helvetica-Bold"

        font_name, font_file = NOTO_FONT_MAP[lang_code]
        font_path = os.path.join(FONT_CACHE, font_file)
        if not os.path.exists(font_path):
            log.debug(f"Font file not found: {font_path} — using Helvetica")
            return "Helvetica", "Helvetica-Bold"

        # Register regular variant
        pdfmetrics.registerFont(TTFont(font_name, font_path))

        # Try bold variant (e.g. NotoSansDevanagari-Bold.ttf)
        bold_file = font_file.replace("-Regular", "-Bold")
        bold_path = os.path.join(FONT_CACHE, bold_file)
        bold_name = font_name + "-Bold"
        if os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont(bold_name, bold_path))
        else:
            bold_name = font_name          # fall back to same font for bold

        return font_name, bold_name

    except Exception as exc:
        log.debug(f"Font registration skipped ({exc}) — using Helvetica")
        return "Helvetica", "Helvetica-Bold"


# ─────────────────────────────────────────────────────────────────────────────
# NOTES MARKDOWN → REPORTLAB FLOWABLES
# ─────────────────────────────────────────────────────────────────────────────

_SECTION_RE    = re.compile(r'^([A-Z][A-Z0-9 &/()\-]+):$')
_HIGHLIGHT_RE  = re.compile(r'^HIGHLIGHT:\s*(.+)', re.IGNORECASE)
_TERM_RE       = re.compile(r'^TERM:\s*(.+?)\s*—\s*(.+)', re.IGNORECASE)
_TIMELINE_RE   = re.compile(r'^TIMELINE:', re.IGNORECASE)
_COMPARISON_RE = re.compile(r'^COMPARISON TABLE:', re.IGNORECASE)
_PIPE_ROW_RE   = re.compile(r'^\s*(.+?)\s*\|\s*(.+)')
_BULLET_RE     = re.compile(r'^[-•]\s+(.+)')
_NUMBERED_RE   = re.compile(r'^\d+\.\s+(.+)')
_SUBSEC_RE     = re.compile(r'^##\s+(.+)')


def _notes_to_flowables(notes: str, styles: dict, theme: dict,
                         body_font: str, title_font: str) -> list:
    """
    Convert the raw notes string (with SmartNotes markers) into a list of
    ReportLab Flowable objects.
    """
    from reportlab.platypus import (
        Paragraph, Spacer, HRFlowable, Table, TableStyle, KeepTogether,
    )
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    primary   = _hex_to_color(theme["primary"])
    accent_bg = _hex_to_color(theme["accent_bg"])

    flowables = []
    lines     = notes.splitlines()
    i         = 0

    while i < len(lines):
        line = lines[i]

        # ── Empty line ────────────────────────────────────────────────────────
        if not line.strip():
            flowables.append(Spacer(1, 0.15 * cm))
            i += 1
            continue

        # ── Section header ────────────────────────────────────────────────────
        m = _SECTION_RE.match(line.strip())
        if m:
            header = m.group(1).strip()
            flowables.append(Spacer(1, 0.3 * cm))
            flowables.append(HRFlowable(
                width="100%", thickness=1.5,
                color=primary, spaceAfter=3))
            flowables.append(Paragraph(
                f'<font color="{theme["primary"]}">'
                f'<b>{_esc(header)}</b></font>',
                styles["section_header"]))
            i += 1
            continue

        # ── Subsection ## ─────────────────────────────────────────────────────
        m = _SUBSEC_RE.match(line.strip())
        if m:
            flowables.append(Paragraph(
                f'<b>{_esc(m.group(1))}</b>', styles["subsection"]))
            i += 1
            continue

        # ── HIGHLIGHT: ────────────────────────────────────────────────────────
        m = _HIGHLIGHT_RE.match(line.strip())
        if m:
            text = m.group(1).strip()
            tbl  = Table(
                [[Paragraph(f"⭐  {_esc(text)}", styles["highlight"])]],
                colWidths=["100%"])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), accent_bg),
                ("BOX",        (0, 0), (-1, -1), 0.8, primary),
                ("LEFTPADDING",  (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING",   (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ]))
            flowables.append(tbl)
            flowables.append(Spacer(1, 0.2 * cm))
            i += 1
            continue

        # ── TERM: name — definition ───────────────────────────────────────────
        m = _TERM_RE.match(line.strip())
        if m:
            term, defn = m.group(1).strip(), m.group(2).strip()
            flowables.append(Paragraph(
                f'<b>{_esc(term)}</b>: {_esc(defn)}',
                styles["term"]))
            i += 1
            continue

        # ── TIMELINE: block ───────────────────────────────────────────────────
        if _TIMELINE_RE.match(line.strip()):
            i += 1
            rows = []
            while i < len(lines) and _PIPE_ROW_RE.match(lines[i]):
                m2 = _PIPE_ROW_RE.match(lines[i])
                rows.append([
                    Paragraph(f'<b>{_esc(m2.group(1))}</b>',
                              styles["table_cell"]),
                    Paragraph(_esc(m2.group(2)), styles["table_cell"]),
                ])
                i += 1
            if rows:
                tbl = Table(rows, colWidths=[3 * cm, None])
                tbl.setStyle(TableStyle([
                    ("BACKGROUND",   (0, 0), (0, -1), accent_bg),
                    ("GRID",         (0, 0), (-1, -1), 0.4, colors.lightgrey),
                    ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING",   (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                    ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                ]))
                flowables.append(tbl)
                flowables.append(Spacer(1, 0.2 * cm))
            continue

        # ── COMPARISON TABLE: block ───────────────────────────────────────────
        if _COMPARISON_RE.match(line.strip()):
            i += 1
            table_rows = []
            header_done = False
            while i < len(lines) and "|" in lines[i]:
                cols = [c.strip() for c in lines[i].split("|") if c.strip()]
                if not cols:
                    i += 1
                    continue
                para_cols = [Paragraph(_esc(c), styles["table_cell"])
                             for c in cols]
                table_rows.append(para_cols)
                i += 1
            if table_rows:
                tbl = Table(table_rows)
                style_cmds = [
                    ("GRID",         (0, 0), (-1, -1), 0.4, colors.lightgrey),
                    ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING",   (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                    ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                ]
                if len(table_rows) > 1:
                    style_cmds += [
                        ("BACKGROUND",  (0, 0), (-1, 0), primary),
                        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
                        ("FONTNAME",    (0, 0), (-1, 0), title_font),
                    ]
                tbl.setStyle(TableStyle(style_cmds))
                flowables.append(tbl)
                flowables.append(Spacer(1, 0.2 * cm))
            continue

        # ── Bullet ────────────────────────────────────────────────────────────
        m = _BULLET_RE.match(line.strip())
        if m:
            flowables.append(Paragraph(
                f"• &nbsp; {_esc(m.group(1))}", styles["bullet"]))
            i += 1
            continue

        # ── Numbered ─────────────────────────────────────────────────────────
        m = _NUMBERED_RE.match(line.strip())
        if m:
            num  = line.strip().split(".")[0]
            rest = line.strip()[len(num) + 1:].strip()
            flowables.append(Paragraph(
                f'<b>{_esc(num)}.</b> &nbsp; {_esc(rest)}',
                styles["numbered"]))
            i += 1
            continue

        # ── Plain paragraph ───────────────────────────────────────────────────
        flowables.append(Paragraph(_esc(line.strip()), styles["body"]))
        i += 1

    return flowables


def _esc(text: str) -> str:
    """Escape XML special characters for ReportLab Paragraph."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


# ─────────────────────────────────────────────────────────────────────────────
# STYLE FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def _make_styles(body_font: str, title_font: str, theme: dict) -> dict:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    primary = _hex_to_color(theme["primary"])

    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            fontName=title_font, fontSize=28, leading=36,
            textColor=primary, spaceAfter=6, alignment=1),   # centred

        "cover_sub": ParagraphStyle(
            "CoverSub",
            fontName=body_font, fontSize=13, leading=18,
            textColor=colors.grey, spaceAfter=24, alignment=1),

        "cover_meta": ParagraphStyle(
            "CoverMeta",
            fontName=body_font, fontSize=10, leading=14,
            textColor=colors.grey, spaceAfter=6, alignment=1),

        "section_header": ParagraphStyle(
            "SectionHeader",
            fontName=title_font, fontSize=13, leading=17,
            spaceBefore=10, spaceAfter=5),

        "subsection": ParagraphStyle(
            "Subsection",
            fontName=title_font, fontSize=11, leading=15,
            spaceBefore=6, spaceAfter=3,
            textColor=_hex_to_color(theme["secondary"])),

        "body": ParagraphStyle(
            "Body",
            fontName=body_font, fontSize=10, leading=15, spaceAfter=3),

        "bullet": ParagraphStyle(
            "Bullet",
            fontName=body_font, fontSize=10, leading=15,
            leftIndent=14, spaceAfter=2),

        "numbered": ParagraphStyle(
            "Numbered",
            fontName=body_font, fontSize=10, leading=15,
            leftIndent=14, spaceAfter=2),

        "highlight": ParagraphStyle(
            "Highlight",
            fontName=title_font, fontSize=10, leading=14),

        "term": ParagraphStyle(
            "Term",
            fontName=body_font, fontSize=10, leading=14,
            leftIndent=10, spaceAfter=2),

        "table_cell": ParagraphStyle(
            "TableCell",
            fontName=body_font, fontSize=9, leading=13),

        # ── Practice-PDF styles ───────────────────────────────────────────────
        "prac_cover_title": ParagraphStyle(
            "PracCoverTitle",
            fontName=title_font, fontSize=24, leading=30,
            textColor=primary, spaceAfter=6),

        "prac_cover_sub": ParagraphStyle(
            "PracCoverSub",
            fontName=body_font, fontSize=12, leading=17,
            textColor=colors.grey, spaceAfter=20),

        "prac_section": ParagraphStyle(
            "PracSection",
            fontName=title_font, fontSize=13, leading=18,
            textColor=primary, spaceBefore=16, spaceAfter=5),

        "prac_body": ParagraphStyle(
            "PracBody",
            fontName=body_font, fontSize=10, leading=15,
            leftIndent=10, spaceAfter=3),

        "prac_note": ParagraphStyle(
            "PracNote",
            fontName=body_font, fontSize=8, leading=11,
            textColor=colors.grey, spaceAfter=2),

        "prac_answer": ParagraphStyle(
            "PracAnswer",
            fontName=body_font, fontSize=9, leading=13,
            leftIndent=20, textColor=colors.darkgreen, spaceAfter=4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# VISUAL ARTIFACT → FLOWABLE
# ─────────────────────────────────────────────────────────────────────────────

def _artifact_flowable(art, styles: dict, theme: dict,
                        max_w_cm: float) -> list:
    """Return a list of flowables representing one VisualArtifact."""
    from reportlab.platypus import (
        Paragraph, Spacer, Image as RLImage, KeepTogether,
    )
    from reportlab.lib.units import cm

    primary = _hex_to_color(theme["primary"])
    out = []

    # Rendered PNG image (chart / timeline / table)
    if art.rendered_img:
        try:
            img_io = io.BytesIO(art.rendered_img)
            rl_img = RLImage(img_io,
                             width=max_w_cm * cm,
                             height=max_w_cm * cm * 0.55,
                             kind="proportional")
            out.append(KeepTogether([
                rl_img,
                Paragraph(
                    f'<i>[{art.atype.value} @ {art.timestamp}]</i>',
                    styles["prac_note"]),
                Spacer(1, 0.2 * cm),
            ]))
        except Exception as e:
            log.debug(f"Skipping rendered image: {e}")

    # Textual description
    if art.raw_desc:
        snippet = art.raw_desc[:600]
        out.append(Paragraph(
            f'<i>Visual [{art.atype.value}] @ {art.timestamp}:</i> '
            f'{_esc(snippet)}', styles["prac_note"]))
        out.append(Spacer(1, 0.1 * cm))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# AGENT — PDF GENERATION AGENT
# ─────────────────────────────────────────────────────────────────────────────

try:
    from agents_io import BaseAgent
    from constants import AgentStatus, AgentResult, PipelineState as _PS
    _HAS_BASE = True
except ImportError:
    _HAS_BASE = False


if _HAS_BASE:
    class PDFGenerationAgent(BaseAgent):
        name = "PDFGenerationAgent"

        async def execute(self, state: "PipelineState") -> str:
            import asyncio
            return await asyncio.get_event_loop().run_in_executor(
                None, _build_main_pdf, state)
else:
    class PDFGenerationAgent:          # type: ignore[no-redef]
        name = "PDFGenerationAgent"

        async def execute(self, state) -> str:
            import asyncio
            return await asyncio.get_event_loop().run_in_executor(
                None, _build_main_pdf, state)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN NOTES PDF
# ─────────────────────────────────────────────────────────────────────────────

def _build_main_pdf(state) -> str:
    try:
        return _main_pdf_reportlab(state)
    except Exception as exc:
        log.warning(f"Main PDF ReportLab error ({exc}); writing plain text.")
        return _main_pdf_plain(state)


def _main_pdf_reportlab(state) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
        PageBreak, Image as RLImage, KeepTogether,
    )
    from constants import DOMAINS, DIAGRAM_MAX_W_CM

    dinfo  = DOMAINS.get(state.domain, DOMAINS["general"])
    theme  = dinfo["theme"]
    primary = _hex_to_color(theme["primary"])

    body_font, title_font = _register_font(state.target_lang_code)
    styles = _make_styles(body_font, title_font, theme)

    doc = SimpleDocTemplate(
        state.output_path,
        pagesize=A4,
        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
        topMargin=2.5 * cm,  bottomMargin=2.5 * cm,
        title=state.title, author="SmartNotes v5",
    )

    story: list = []

    # ── Cover page ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph(_esc(state.title), styles["cover_title"]))
    story.append(Paragraph(
        f"Domain: {dinfo['label']}  ·  Language: {state.target_lang_name}",
        styles["cover_sub"]))
    if state.detected_lang and state.detected_lang != "Unknown":
        story.append(Paragraph(
            f"Lecture language: {state.detected_lang}", styles["cover_meta"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(
        width="100%", thickness=3, color=primary, spaceAfter=10))
    story.append(Paragraph(
        "Generated by SmartNotes v5 · AI-powered lecture notes",
        styles["cover_meta"]))
    story.append(PageBreak())

    # ── Target-language notes ─────────────────────────────────────────────────
    story.append(Paragraph(
        f'<font color="{theme["primary"]}"><b>'
        f'Study Notes — {_esc(state.target_lang_name)}</b></font>',
        styles["section_header"]))
    story.append(HRFlowable(
        width="100%", thickness=2, color=primary, spaceAfter=8))
    story += _notes_to_flowables(
        state.target_notes, styles, theme, body_font, title_font)

    # ── Visual artifacts ──────────────────────────────────────────────────────
    rendered_arts = [a for a in state.artifacts if a.rendered_img]
    if rendered_arts:
        story.append(PageBreak())
        story.append(Paragraph(
            f'<font color="{theme["primary"]}"><b>Visual Diagrams</b></font>',
            styles["section_header"]))
        story.append(HRFlowable(
            width="100%", thickness=2, color=primary, spaceAfter=8))
        for art in rendered_arts:
            story += _artifact_flowable(art, styles, theme, DIAGRAM_MAX_W_CM)

    # ── Source-language notes (if different) ──────────────────────────────────
    if (state.source_notes
            and state.source_notes != state.target_notes
            and state.detected_lang not in ("Unknown", "")):
        story.append(PageBreak())
        story.append(Paragraph(
            f'<font color="{theme["primary"]}"><b>'
            f'Source Notes — {_esc(state.detected_lang)}</b></font>',
            styles["section_header"]))
        story.append(HRFlowable(
            width="100%", thickness=2, color=primary, spaceAfter=8))
        body_src, title_src = _register_font(state.detected_lang_code)
        styles_src = _make_styles(body_src, title_src, theme)
        story += _notes_to_flowables(
            state.source_notes, styles_src, theme, body_src, title_src)

    doc.build(story)
    log.info(f"Main PDF saved → {state.output_path}")
    return state.output_path


def _main_pdf_plain(state) -> str:
    """Fallback: write notes as UTF-8 text file."""
    txt = os.path.splitext(state.output_path)[0] + ".txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write(f"SMART NOTES v5\n{'=' * 60}\n")
        f.write(f"Title  : {state.title}\n")
        f.write(f"Domain : {state.domain}\n")
        f.write(f"Lang   : {state.target_lang_name}\n")
        f.write(f"{'=' * 60}\n\n")
        f.write(state.target_notes)
        if state.source_notes and state.source_notes != state.target_notes:
            f.write(f"\n\n{'=' * 60}\n")
            f.write(f"SOURCE NOTES ({state.detected_lang})\n")
            f.write(f"{'=' * 60}\n\n")
            f.write(state.source_notes)
    state.output_path = txt
    log.info(f"Plain-text notes saved → {txt}")
    return txt


# ─────────────────────────────────────────────────────────────────────────────
# PRACTICE QUESTIONS PDF  (MCQ only — no answers shown)
# ─────────────────────────────────────────────────────────────────────────────

# Regex helpers
_Q_NUM_RE  = re.compile(r'^(Q?\d+[\.\)])\s*(.+)')          # "1." or "Q1."
_OPT_RE    = re.compile(r'^([A-D][.)]\s*)(.+)')             # "A) text"
_ANSWER_RE = re.compile(                                     # lines to drop
    r'^\s*(answer\s*[:：]|correct\s*[:：]|ans\s*[:：])',
    re.IGNORECASE,
)
_JUNK_RE   = re.compile(                                     # section headings to drop
    r'^(MCQ|MULTIPLE CHOICE|SHORT ANSWER|LONG ANSWER|TRUE OR FALSE'
    r'|FILL IN THE BLANK|PRACTICE QUESTION|QUESTIONS?)\s*[:：]?\s*$',
    re.IGNORECASE,
)


def _clean_mcq_text(raw: str) -> str:
    """
    Strip any answer lines and stray section headings the model may have
    leaked despite the prompt, then return the cleaned string.
    """
    out = []
    for line in raw.splitlines():
        if _ANSWER_RE.match(line):
            continue
        if _JUNK_RE.match(line.strip()):
            continue
        out.append(line)
    cleaned = "\n".join(out)
    # collapse runs of 3+ blank lines → 2
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def build_practice_pdf(state) -> str:
    """
    Render state.practice_questions as an MCQ-only PDF (no answers).

    Output: <base>_practice.pdf  (sibling of state.output_path).
    Sets state.practice_pdf_path and returns the path.
    """
    base, ext = os.path.splitext(state.output_path)
    out_path  = f"{base}_practice{ext or '.pdf'}"

    try:
        _mcq_pdf_reportlab(state, out_path)
    except Exception as exc:
        log.warning(f"Practice PDF ReportLab error ({exc}); falling back to text.")
        _mcq_pdf_plain(state, out_path)

    state.practice_pdf_path = out_path
    log.info(f"Practice PDF (MCQ only) saved → {out_path}")
    return out_path


def _mcq_pdf_reportlab(state, out_path: str):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
        KeepTogether, Table, TableStyle,
    )
    from constants import DOMAINS

    dinfo   = DOMAINS.get(state.domain, DOMAINS["general"])
    theme   = dinfo["theme"]
    primary = _hex_to_color(theme["primary"])
    accent  = _hex_to_color(theme["accent_bg"])

    body_font, title_font = _register_font(state.target_lang_code)
    styles = _make_styles(body_font, title_font, theme)

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
        topMargin=2.5 * cm,  bottomMargin=2.5 * cm,
        title=f"MCQ Practice — {state.title}",
        author="SmartNotes v5",
    )

    story: list = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("📝  MCQ Practice Quiz", styles["prac_cover_title"]))
    story.append(Paragraph(
        f"{_esc(state.title)}  ·  {_esc(state.target_lang_name)}",
        styles["prac_cover_sub"]))
    story.append(HRFlowable(
        width="100%", thickness=2.5, color=primary, spaceAfter=8))

    # ── Instructions box ──────────────────────────────────────────────────────
    instr = (
        f"<b>Instructions:</b> Each question has four options (A – D). "
        f"Circle or tick the ONE best answer. "
        f"There are 15 questions. All questions are based on the lecture notes. "
        f"Total marks: 15."
    )
    instr_tbl = Table(
        [[Paragraph(instr, styles["prac_body"])]],
        colWidths=["100%"])
    instr_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), accent),
        ("BOX",           (0, 0), (-1, -1), 0.8, primary),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(instr_tbl)
    story.append(Spacer(1, 0.5 * cm))

    # ── Parse and render MCQs ─────────────────────────────────────────────────
    clean_text = _clean_mcq_text(state.practice_questions)
    lines      = clean_text.splitlines()

    # Group lines into question blocks: one block = question + its 4 options
    # A block starts whenever we hit a numbered line.
    blocks: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _Q_NUM_RE.match(stripped) and current:
            blocks.append(current)
            current = [stripped]
        else:
            current.append(stripped)
    if current:
        blocks.append(current)

    for block in blocks:
        if not block:
            continue

        q_flowables: list = []

        for i, line in enumerate(block):
            line = line.strip()
            if not line:
                continue

            # ── Question stem ─────────────────────────────────────────────────
            qm = _Q_NUM_RE.match(line)
            if qm and i == 0:
                q_flowables.append(Paragraph(
                    f'<b>{_esc(qm.group(1))}</b>&nbsp; {_esc(qm.group(2))}',
                    styles["prac_body"]))
                continue

            # ── Option line A) B) C) D) ───────────────────────────────────────
            om = _OPT_RE.match(line)
            if om:
                label = om.group(1).strip()   # e.g. "A)"
                text  = om.group(2).strip()

                # Bubble circle ○ + label + text in a compact 2-col mini table
                bubble_tbl = Table(
                    [[
                        Paragraph(
                            f'<font size="13">○</font> <b>{_esc(label)}</b>',
                            styles["prac_body"]),
                        Paragraph(_esc(text), styles["prac_body"]),
                    ]],
                    colWidths=[1.3 * cm, None],
                )
                bubble_tbl.setStyle(TableStyle([
                    ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING",   (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
                ]))
                q_flowables.append(bubble_tbl)
                continue

            # ── Any other line (continuation of question text) ─────────────
            q_flowables.append(
                Paragraph(_esc(line), styles["prac_body"]))

        # Wrap each question block so it doesn't split across pages
        q_flowables.append(Spacer(1, 0.35 * cm))
        story.append(KeepTogether(q_flowables))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.8 * cm))
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=colors.lightgrey, spaceAfter=5))
    story.append(Paragraph(
        "— End of MCQ Quiz  ·  SmartNotes v5 —",
        styles["prac_note"]))

    doc.build(story)


def _mcq_pdf_plain(state, out_path: str):
    """Plain-text fallback — writes MCQs (no answers) to a .txt file."""
    txt_path = os.path.splitext(out_path)[0] + ".txt"
    clean    = _clean_mcq_text(state.practice_questions)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("MCQ PRACTICE QUIZ\n")
        f.write("=" * 60 + "\n")
        f.write(f"Topic   : {state.title}\n")
        f.write(f"Language: {state.target_lang_name}\n")
        f.write(f"Domain  : {state.domain}\n")
        f.write(f"Questions: 15  (circle the best answer: A / B / C / D)\n")
        f.write("=" * 60 + "\n\n")
        f.write(clean)
        f.write("\n\n— End of MCQ Quiz —\n")
    state.practice_pdf_path = txt_path
    log.info(f"Practice plain-text (MCQ) saved → {txt_path}")
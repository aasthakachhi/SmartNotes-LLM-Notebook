"""
agents_visual.py
================
Visual processing agents for SmartNotes LLM Notebook:
  - VisualAgent       (sample frames, classify, extract content, skip ads)
  - FusionAgent       (align transcription segments with visual artifacts)
  - DiagramRenderAgent(render charts / timelines / tables as PNG via matplotlib)
"""

import asyncio
import io
import json
import logging
import os
import re
import subprocess
import textwrap
from typing import Dict, List, Optional

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from constants import (
    AD_KEYWORDS, DIAGRAM_DPI, DOMAINS, DUP_THRESHOLD, FRAME_EVERY_N_SEC,
    AgentResult, AgentStatus, ArtifactType, FusedSegment,
    PipelineState, VisualArtifact,
)
from agents_io import BaseAgent, run_image

log = logging.getLogger("SmartNotes")


# ─────────────────────────────────────────────────────────────────────────────
# FRAME CLASSIFICATION / EXTRACTION PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

_CLASSIFY_PROMPT = """Look at this video frame. Classify the PRIMARY content type.

Choose EXACTLY ONE from:
  equation      — mathematical expression, formula, or derivation on board/slide
  geometry      — geometric figure: triangle, circle, coordinate axes, etc.
  chart         — bar chart, line graph, pie chart, histogram with data
  flowchart     — boxes and arrows showing a process or decision tree
  timeline      — chronological sequence of events
  table         — rows and columns of data
  science_diag  — circuit, ray diagram, cell, chemical structure, atomic model
  map_desc      — geographical map or regional diagram
  text_slide    — text-only slide or bullet points
  unknown       — face/person only, empty screen, promotional overlay, or unclear

Reply with ONLY the type keyword, nothing else."""

_EXTRACT_PROMPTS: Dict[str, str] = {
    "equation": (
        "Extract ALL mathematical content from this frame.\n"
        "Write every equation/expression in LaTeX ($...$ inline, $$...$$ display).\n"
        "Output ONLY the extracted LaTeX content, nothing else."
    ),
    "geometry": (
        "Describe this geometric figure as JSON.\n"
        "Keys: shape_type, vertices (list of {label, x?, y?}), "
        "angles (list of {label, value}), sides (list of {label, length?}), "
        "equations (list of LaTeX strings), description (one sentence).\n"
        "Output ONLY valid JSON."
    ),
    "chart": (
        "Extract this chart as JSON.\n"
        "Keys: chart_type, title, x_axis ({label, unit, values}), "
        "y_axis ({label, unit}), series (list of {name, data_points}), "
        "key_observations (list of strings).\n"
        "Output ONLY valid JSON."
    ),
    "flowchart": (
        "Extract this flowchart as JSON.\n"
        "Keys: title, nodes (list of {id, label, shape}), "
        "edges (list of {from_id, to_id, label?}).\n"
        "Output ONLY valid JSON."
    ),
    "timeline": (
        "Extract this timeline as JSON.\n"
        "Keys: title, events (list of {date, event_name, description?}).\n"
        "Output ONLY valid JSON."
    ),
    "table": (
        "Extract this table as JSON.\n"
        "Keys: title, headers (list of strings), rows (list of string lists).\n"
        "Output ONLY valid JSON."
    ),
    "science_diag": (
        "Describe this science diagram as JSON.\n"
        "Keys: diagram_subtype, components (list of {name, description}), "
        "labels (list of strings), equations (list of LaTeX strings), "
        "description (two sentences).\n"
        "Output ONLY valid JSON."
    ),
    "map_desc": (
        "Extract key geographic information from this map as JSON.\n"
        "Keys: region_name, highlighted_areas (list), "
        "labels_visible (list), key_facts (list of factual strings).\n"
        "Output ONLY valid JSON."
    ),
    "text_slide": (
        "Extract ALL text from this slide as JSON.\n"
        "Keys: title, bullet_points (list of strings), "
        "equations (list of LaTeX strings).\n"
        "Output ONLY valid JSON."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 3 — VISUAL AGENT
# ─────────────────────────────────────────────────────────────────────────────

class VisualAgent(BaseAgent):
    name = "VisualAgent"

    async def execute(self, state: PipelineState) -> List[VisualArtifact]:
        if state.skip_video:
            state.record(AgentResult("VisualAgent", AgentStatus.SKIPPED))
            return []

        loop    = asyncio.get_event_loop()
        vc_path = await loop.run_in_executor(
            None, self._transcode, state.video_path)

        cap   = cv2.VideoCapture(vc_path)
        fps   = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        dur   = total / fps if fps > 0 else 0
        intv  = max(1, int(fps * FRAME_EVERY_N_SEC))
        log.info(f"Video: {dur:.0f}s  fps={fps:.1f}  "
                 f"sampling every {FRAME_EVERY_N_SEC}s")

        artifacts: List[VisualArtifact] = []
        prev_desc = ""
        frame_idx = 0

        while True:
            ret, frame = await loop.run_in_executor(None, cap.read)
            if not ret:
                break
            if frame_idx % intv == 0:
                ts    = frame_idx / fps if fps > 0 else 0
                label = f"{int(ts // 60):02d}:{int(ts % 60):02d}"
                if self._has_content(frame):
                    pil = Image.fromarray(
                        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    art = await self._process_frame(state, pil, label,
                                                    original_pil=pil)
                    if art and not self._is_dup(art.raw_desc, prev_desc):
                        artifacts.append(art)
                        prev_desc = art.raw_desc
                        log.info(f"  [{label}] {art.atype.value} "
                                 f"conf={art.confidence:.1f}")
            frame_idx += 1

        cap.release()
        if vc_path != state.video_path and os.path.exists(vc_path):
            os.remove(vc_path)

        state.artifacts = artifacts
        log.info(f"Visual artifacts: {len(artifacts)}")
        return artifacts

    @staticmethod
    def _transcode(src: str) -> str:
        base, _ = os.path.splitext(src)
        out = base + "_opencv.mp4"
        if os.path.exists(out):
            os.remove(out)
        log.info(f"Transcoding to H.264: {src} → {out}")
        r = subprocess.run(
            ["ffmpeg", "-i", src, "-c:v", "libx264",
             "-preset", "fast", "-crf", "23", "-an", "-y", out],
            capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg transcode failed:\n"
                f"{r.stderr.decode(errors='replace')}")
        return out

    @staticmethod
    def _is_ad_or_overlay(raw_desc: str) -> bool:
        """Return True if extracted content looks like a promotional overlay."""
        text = raw_desc.lower()
        hits = sum(1 for kw in AD_KEYWORDS if kw in text)
        return hits >= 2

    @staticmethod
    async def _process_frame(state: PipelineState, pil: Image.Image,
                              label: str,
                              original_pil: Optional[Image.Image] = None,
                              ) -> Optional[VisualArtifact]:
        raw_type  = await run_image(state, pil, _CLASSIFY_PROMPT, max_tokens=10)
        atype_key = raw_type.strip().lower().split()[0]
        try:
            atype = ArtifactType(atype_key)
        except ValueError:
            atype = ArtifactType.UNKNOWN
        if atype == ArtifactType.UNKNOWN:
            return None

        extract_p = _EXTRACT_PROMPTS.get(atype_key, _EXTRACT_PROMPTS["text_slide"])
        raw_desc  = await run_image(state, pil, extract_p, max_tokens=700)

        if VisualAgent._is_ad_or_overlay(raw_desc):
            log.info(f"  [{label}] Skipped — promotional overlay detected")
            return None

        structured: Dict = {}
        confidence = 1.0
        if atype not in (ArtifactType.EQUATION,):
            try:
                m = re.search(r'\{[\s\S]*\}', raw_desc)
                if m:
                    structured = json.loads(m.group())
            except Exception:
                confidence = 0.6
        else:
            structured = {"raw": raw_desc}

        if "[handwritten]" in raw_desc.lower():
            confidence = min(confidence, 0.7)

        # ── Store a compressed JPEG of the original frame ─────────────────────
        # Only for content-rich types; skip text_slide and low-confidence
        # artifacts to keep PDF size reasonable.
        FRAME_WORTHY = {
            ArtifactType.EQUATION,    ArtifactType.GEOMETRY,
            ArtifactType.CHART,       ArtifactType.FLOWCHART,
            ArtifactType.TIMELINE,    ArtifactType.TABLE,
            ArtifactType.SCIENCE_DIAG, ArtifactType.MAP_DESC,
        }
        frame_img: Optional[bytes] = None
        if atype in FRAME_WORTHY and confidence >= 0.6 and original_pil is not None:
            img = original_pil.copy()
            img.thumbnail((900, 600), Image.LANCZOS)  # cap at ~900 px wide
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=72, optimize=True)
            frame_img = buf.getvalue()

        return VisualArtifact(
            timestamp=label, atype=atype,
            raw_desc=raw_desc, structured=structured,
            confidence=confidence, frame_img=frame_img)

    @staticmethod
    def _has_content(frame: np.ndarray) -> bool:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if np.mean(gray) < 10 or np.mean(gray) > 248:
            return False
        if np.std(gray) < 8:
            return False
        dark  = np.sum(gray < 80)  / gray.size
        light = np.sum(gray > 180) / gray.size
        edges = np.count_nonzero(cv2.Canny(gray, 50, 150)) / gray.size
        return dark > 0.20 or light > 0.30 or edges > 0.03

    @staticmethod
    def _is_dup(current: str, previous: str) -> bool:
        if not previous:
            return False
        length  = max(len(current), len(previous))
        matches = sum(a == b for a, b in zip(current, previous))
        return (matches / length) > DUP_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 4 — FUSION AGENT
# ─────────────────────────────────────────────────────────────────────────────

class FusionAgent(BaseAgent):
    name = "FusionAgent"

    async def execute(self, state: PipelineState) -> List[FusedSegment]:
        if not state.transcription and not state.artifacts:
            raise RuntimeError("No audio or visual content to fuse.")

        if state.transcription and state.artifacts:
            segments = self._time_fuse(state.transcription, state.artifacts)
        elif state.transcription:
            segments = [FusedSegment("00:00", state.transcription, [])]
        else:
            segments = [FusedSegment(a.timestamp, "", [a])
                        for a in state.artifacts]

        state.fused_segments = segments
        vis_count = sum(len(s.visuals) for s in segments)
        log.info(f"Fused {len(segments)} segments, {vis_count} visuals placed")
        return segments

    @staticmethod
    def _time_fuse(transcription: str,
                   artifacts: List[VisualArtifact]) -> List[FusedSegment]:
        paragraphs = [p.strip() for p in
                      re.split(r'\n{2,}', transcription) if p.strip()]
        if not paragraphs:
            return [FusedSegment(a.timestamp, "", [a]) for a in artifacts]

        n_p = len(paragraphs)
        n_a = len(artifacts)
        art_to_paras: Dict[int, List[str]] = {i: [] for i in range(n_a)}
        for pi, para in enumerate(paragraphs):
            ai = min(int(pi / n_p * n_a), n_a - 1)
            art_to_paras[ai].append(para)

        segments: List[FusedSegment] = []
        for ai, art in enumerate(artifacts):
            seg = FusedSegment(
                timestamp=art.timestamp,
                transcript="\n\n".join(art_to_paras[ai]),
                visuals=[art])
            segments.append(seg)
        return segments


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 9 — DIAGRAM RENDER AGENT
# ─────────────────────────────────────────────────────────────────────────────

class DiagramRenderAgent(BaseAgent):
    name = "DiagramRenderAgent"

    async def execute(self, state: PipelineState) -> int:
        loop     = asyncio.get_event_loop()
        primary  = DOMAINS[state.domain]["theme"]["primary"]
        rendered = 0
        for art in state.artifacts:
            try:
                png = await loop.run_in_executor(
                    None, self._render, art, primary)
                if png:
                    art.rendered_img = png
                    rendered += 1
            except Exception as e:
                log.warning(f"Render failed [{art.timestamp}]: {e}")
        log.info(f"Rendered {rendered}/{len(state.artifacts)} diagrams")
        return rendered

    @staticmethod
    def _render(art: VisualArtifact, primary: str) -> Optional[bytes]:
        if art.atype == ArtifactType.CHART:
            return DiagramRenderAgent._chart(art, primary)
        if art.atype == ArtifactType.TIMELINE:
            return DiagramRenderAgent._timeline(art, primary)
        if art.atype == ArtifactType.TABLE:
            return DiagramRenderAgent._table(art, primary)
        return None

    @staticmethod
    def _fig_to_png(fig) -> bytes:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=DIAGRAM_DPI,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    @staticmethod
    def _chart(art: VisualArtifact, color: str) -> Optional[bytes]:
        d      = art.structured
        ctype  = str(d.get("chart_type", "bar")).lower()
        title  = d.get("title", "")
        series = d.get("series", [])
        x_info = d.get("x_axis", {})
        y_info = d.get("y_axis", {})

        fig, ax = plt.subplots(figsize=(8, 4))
        fig.patch.set_facecolor("#fafafa")
        ax.set_facecolor("#fafafa")

        if not series:
            ax.text(0.5, 0.5, "No chart data extracted",
                    ha="center", va="center",
                    transform=ax.transAxes, color="#aaaaaa")
        elif "pie" in ctype:
            labels = [str(s.get("name", i)) for i, s in enumerate(series)]
            vals   = [float((s.get("data_points") or [1])[0]) for s in series]
            ax.pie(vals, labels=labels, autopct="%1.1f%%",
                   colors=plt.cm.Set3.colors[:len(vals)])
        elif "line" in ctype:
            x_vals = x_info.get("values", []) if isinstance(x_info, dict) else []
            for s in series:
                pts = [float(p) for p in (s.get("data_points") or [])]
                xs  = x_vals[:len(pts)] if x_vals else list(range(len(pts)))
                ax.plot(xs, pts, marker="o", label=s.get("name", ""))
            ax.legend()
        else:
            x_vals = x_info.get("values", []) if isinstance(x_info, dict) else []
            for si, s in enumerate(series):
                pts = [float(p) for p in (s.get("data_points") or [])]
                lbs = x_vals[:len(pts)] if x_vals else list(range(len(pts)))
                off = si * 0.3
                ax.bar([i + off for i in range(len(pts))], pts,
                       width=0.3, label=s.get("name", ""),
                       color=plt.cm.tab10.colors[si % 10])
            ax.legend()

        if isinstance(x_info, dict) and x_info.get("label"):
            ax.set_xlabel(x_info["label"])
        if isinstance(y_info, dict) and y_info.get("label"):
            ax.set_ylabel(y_info["label"])
        if title:
            ax.set_title(title, fontsize=11, color=color)
        plt.tight_layout()
        return DiagramRenderAgent._fig_to_png(fig)

    @staticmethod
    def _timeline(art: VisualArtifact, color: str) -> Optional[bytes]:
        d      = art.structured
        events = d.get("events", [])
        title  = d.get("title", "Timeline")
        if not events:
            return None
        n   = len(events)
        fig, ax = plt.subplots(figsize=(11, max(3, n * 0.85)))
        ax.axis("off")
        fig.patch.set_facecolor("#fffdf5")
        ax.axhline(0.5, xmin=0.05, xmax=0.95,
                   color=color, linewidth=2.5, transform=ax.transAxes)
        for i, ev in enumerate(events):
            x = 0.05 + (i / max(n - 1, 1)) * 0.90
            ax.plot(x, 0.5, "o", color=color, ms=11,
                    transform=ax.transAxes, zorder=3)
            y_text  = 0.74 if i % 2 == 0 else 0.22
            date    = str(ev.get("date", ""))
            name    = str(ev.get("event_name", ev.get("name", "")))
            label   = f"{date}\n{name}" if date else name
            wrapped = "\n".join(textwrap.wrap(label, 16))
            ax.text(x, y_text, wrapped, ha="center", va="center",
                    fontsize=8, color="#222222", transform=ax.transAxes,
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                              edgecolor=color, linewidth=0.8))
        ax.set_title(title, fontsize=12, color=color, pad=10)
        plt.tight_layout()
        return DiagramRenderAgent._fig_to_png(fig)

    @staticmethod
    def _table(art: VisualArtifact, color: str) -> Optional[bytes]:
        d       = art.structured
        headers = d.get("headers", [])
        rows    = d.get("rows", [])
        title   = d.get("title", "")
        if not rows:
            return None
        all_rows = ([headers] if headers else []) + rows
        n_r = len(all_rows)
        n_c = max(len(r) for r in all_rows)
        all_rows = [r + [""] * (n_c - len(r)) for r in all_rows]

        fig, ax = plt.subplots(
            figsize=(min(n_c * 2.3 + 0.5, 14), min(n_r * 0.55 + 0.9, 12)))
        ax.axis("off")
        tbl = ax.table(
            cellText=all_rows[1:] if headers else all_rows,
            colLabels=headers if headers else None,
            loc="center", cellLoc="center")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1, 1.5)
        if headers:
            for j in range(n_c):
                tbl[(0, j)].set_facecolor(color)
                tbl[(0, j)].set_text_props(color="white", fontweight="bold")
        if title:
            ax.set_title(title, fontsize=11, color=color, pad=6)
        plt.tight_layout()
        return DiagramRenderAgent._fig_to_png(fig)

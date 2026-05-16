"""
agents_io.py
============
Input / IO agents for SmartNotes v5:
  - BaseAgent        (abstract base all agents share)
  - ModelInference   (sync + async helpers for text / image / audio inference)
  - InputAgent       (validate path or download YouTube video)
  - ModelLoaderAgent (load Gemma model + processor)
  - AudioAgent       (extract audio, transcribe, detect language)
"""

import asyncio
import logging
import os
import subprocess
import traceback
from abc import ABC, abstractmethod
from typing import Any, Tuple

import fitz  # PyMuPDF — for PDF text extraction

import librosa
import numpy as np
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForImageTextToText, TextStreamer

from constants import (
    MODEL_ID, AUDIO_SR, MAX_AUDIO_SEC,
    YOUTUBE_RE, AgentResult, AgentStatus, PipelineState,
)

log = logging.getLogger("SmartNotes")


# ─────────────────────────────────────────────────────────────────────────────
# BASE AGENT
# ─────────────────────────────────────────────────────────────────────────────

class BaseAgent(ABC):
    name: str = "BaseAgent"

    async def run(self, state: PipelineState) -> AgentResult:
        t0 = asyncio.get_event_loop().time()
        state.record(AgentResult(self.name, AgentStatus.RUNNING))
        try:
            output = await self.execute(state)
            dur    = asyncio.get_event_loop().time() - t0
            result = AgentResult(self.name, AgentStatus.SUCCESS,
                                 output=output, duration_s=dur)
        except Exception as exc:
            dur    = asyncio.get_event_loop().time() - t0
            result = AgentResult(self.name, AgentStatus.FAILED,
                                 error=str(exc), duration_s=dur)
            log.error(f"{self.name} failed:\n{traceback.format_exc()}")
        state.record(result)
        return result

    @abstractmethod
    async def execute(self, state: PipelineState) -> Any: ...


# ─────────────────────────────────────────────────────────────────────────────
# MODEL INFERENCE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

class ColorStreamer(TextStreamer):
    CYAN   = "\033[96m"
    YELLOW = "\033[93m"
    GREEN  = "\033[92m"
    RESET  = "\033[0m"

    def __init__(self, tokenizer, color="\033[96m", **kwargs):
        super().__init__(tokenizer, skip_prompt=True,
                         skip_special_tokens=True, **kwargs)
        self.color = color

    def on_finalized_text(self, text: str, stream_end: bool = False):
        print(f"{self.color}{text}{self.RESET}",
              end="" if not stream_end else "\n", flush=True)


def _run_text_sync(model, processor, prompt: str, max_tokens: int) -> str:
    msgs   = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    inputs = processor.apply_chat_template(
        msgs, add_generation_prompt=True,
        tokenize=True, return_dict=True, return_tensors="pt"
    ).to(model.device)
    streamer = ColorStreamer(processor, color="\033[96m")
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=max_tokens,
                             do_sample=False, streamer=streamer)
    return processor.batch_decode(
        out[:, inputs["input_ids"].shape[1]:],
        skip_special_tokens=True, clean_up_tokenization_spaces=False
    )[0].strip()


def _run_image_sync(model, processor, image: Image.Image,
                    prompt: str, max_tokens: int) -> str:
    msgs   = [{"role": "user", "content": [
        {"type": "image", "image": image},
        {"type": "text",  "text": prompt},
    ]}]
    inputs = processor.apply_chat_template(
        msgs, add_generation_prompt=True,
        tokenize=True, return_dict=True, return_tensors="pt"
    ).to(model.device)
    streamer = ColorStreamer(processor, color="\033[93m")
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=max_tokens,
                             do_sample=False, streamer=streamer)
    return processor.batch_decode(
        out[:, inputs["input_ids"].shape[1]:],
        skip_special_tokens=True, clean_up_tokenization_spaces=False
    )[0].strip()


def _run_audio_sync(model, processor, audio: np.ndarray,
                    sr: int, prompt: str, max_tokens: int) -> str:
    msgs   = [{"role": "user", "content": [
        {"type": "audio", "audio": audio, "sampling_rate": sr},
        {"type": "text",  "text": prompt},
    ]}]
    inputs = processor.apply_chat_template(
        msgs, add_generation_prompt=True,
        tokenize=True, return_dict=True, return_tensors="pt"
    ).to(model.device)
    streamer = ColorStreamer(processor, color="\033[92m")
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=max_tokens,
                             do_sample=False, streamer=streamer)
    return processor.batch_decode(
        out[:, inputs["input_ids"].shape[1]:],
        skip_special_tokens=True, clean_up_tokenization_spaces=False
    )[0].strip()


async def run_text(state: PipelineState, prompt: str,
                   max_tokens: int = 2048) -> str:
    return await asyncio.get_event_loop().run_in_executor(
        None, _run_text_sync, state.model, state.processor, prompt, max_tokens)


async def run_image(state: PipelineState, image: Image.Image,
                    prompt: str, max_tokens: int = 768) -> str:
    return await asyncio.get_event_loop().run_in_executor(
        None, _run_image_sync, state.model, state.processor,
        image, prompt, max_tokens)


async def run_audio(state: PipelineState, audio: np.ndarray,
                    sr: int, prompt: str, max_tokens: int = 2048) -> str:
    return await asyncio.get_event_loop().run_in_executor(
        None, _run_audio_sync, state.model, state.processor,
        audio, sr, prompt, max_tokens)


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 0 — INPUT AGENT
# ─────────────────────────────────────────────────────────────────────────────

class InputAgent(BaseAgent):
    name = "InputAgent"

    async def execute(self, state: PipelineState) -> str:
        path = state.video_path.strip()

        # ── PDF input ─────────────────────────────────────────────────────────
        if path.lower().endswith(".pdf"):
            if not os.path.exists(path):
                raise FileNotFoundError(f"PDF not found: {path!r}")
            log.info(f"PDF input detected — extracting text …")
            text = await asyncio.get_event_loop().run_in_executor(
                None, self._extract_pdf_text, path)
            if not text.strip():
                raise ValueError("PDF has no extractable text (scanned PDF not supported).")
            state.transcription  = text
            state.input_type     = "pdf"
            state.skip_audio     = True
            state.skip_video     = True
            state.detected_lang  = "Unknown"
            state.detected_lang_code = "en"
            sz = os.path.getsize(path) / 1e6
            log.info(f"PDF: {path}  ({sz:.1f} MB)  {len(text)} chars extracted")
            return path

        # ── YouTube URL ───────────────────────────────────────────────────────
        if YOUTUBE_RE.match(path):
            log.info("YouTube URL — downloading …")
            dl_path = await asyncio.get_event_loop().run_in_executor(
                None, self._download_yt, path)
            state.video_path = dl_path
            state.input_type = "video"
        elif not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path!r}")
        else:
            state.input_type = "video"

        sz = os.path.getsize(state.video_path) / 1e6
        log.info(f"Input: {state.video_path}  ({sz:.1f} MB)")
        return state.video_path

    @staticmethod
    def _extract_pdf_text(pdf_path: str) -> str:
        """Extract all text from a PDF using PyMuPDF page by page."""
        doc   = fitz.open(pdf_path)
        parts = []
        for page_num, page in enumerate(doc, 1):
            text = page.get_text("text").strip()
            if text:
                parts.append(f"[Page {page_num}]\n{text}")
        doc.close()
        return "\n\n".join(parts)

    @staticmethod
    def _download_yt(url: str) -> str:
        try:
            import yt_dlp
        except ImportError:
            raise ImportError("pip install yt-dlp")
        opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": "yt_video.%(ext)s",
            "merge_output_format": "mp4",
            "quiet": False, "geo_bypass": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            if not path.endswith(".mp4"):
                path = os.path.splitext(path)[0] + ".mp4"
        if not os.path.exists(path):
            raise FileNotFoundError(f"YT download failed: {path!r}")
        return path


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1 — MODEL LOADER
# ─────────────────────────────────────────────────────────────────────────────

class ModelLoaderAgent(BaseAgent):
    name = "ModelLoaderAgent"

    async def execute(self, state: PipelineState):
        log.info(f"Loading {MODEL_ID} …")
        model, proc = await asyncio.get_event_loop().run_in_executor(
            None, self._load)
        state.model     = model
        state.processor = proc
        params = sum(p.numel() for p in model.parameters()) / 1e9
        log.info(f"Model ready  device={model.device}  params≈{params:.1f}B")
        return {"device": str(model.device), "params_B": round(params, 1)}

    @staticmethod
    def _load():
        model = AutoModelForImageTextToText.from_pretrained(
            MODEL_ID, torch_dtype=torch.bfloat16, device_map="auto")
        proc  = AutoProcessor.from_pretrained(MODEL_ID)
        model.eval()
        return model, proc


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 2 — AUDIO AGENT
# ─────────────────────────────────────────────────────────────────────────────

class AudioAgent(BaseAgent):
    name = "AudioAgent"

    PROMPT = (
        "Transcribe this audio accurately and completely.\n"
        "1. Write every word spoken, including equations, code, and technical terms.\n"
        "2. Use proper punctuation and paragraph breaks at topic changes.\n"
        "3. Output ONLY the transcription — no commentary, no timestamps."
    )

    async def execute(self, state: PipelineState) -> str:
        if state.skip_audio:
            state.record(AgentResult("AudioAgent", AgentStatus.SKIPPED))
            return ""

        audio_wav = "extracted_audio.wav"
        log.info("Extracting audio …")
        await asyncio.get_event_loop().run_in_executor(
            None, self._extract, state.video_path, audio_wav)
        state.audio_path = audio_wav

        audio, sr = await asyncio.get_event_loop().run_in_executor(
            None, lambda: librosa.load(audio_wav, sr=AUDIO_SR))

        duration  = len(audio) / sr
        chunk_s   = MAX_AUDIO_SEC * sr
        chunks    = [audio[i:i + chunk_s]
                     for i in range(0, len(audio), chunk_s)]
        log.info(f"Audio: {duration:.1f}s  ({len(chunks)} chunks)")

        parts = []
        for idx, chunk in enumerate(chunks, 1):
            log.info(f"  Transcribing chunk {idx}/{len(chunks)} …")
            parts.append(await run_audio(state, chunk, AUDIO_SR, self.PROMPT))

        state.transcription = "\n\n".join(parts)
        log.info(f"Transcription complete: {len(state.transcription)} chars")

        if state.transcription.strip():
            state.detected_lang, state.detected_lang_code = \
                await self._detect_lang(state)
            log.info(f"Source language: {state.detected_lang} "
                     f"({state.detected_lang_code})")
        return state.transcription

    @staticmethod
    def _extract(video_path: str, out: str):
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-vn",
             "-acodec", "pcm_s16le", "-ar", str(AUDIO_SR), "-ac", "1",
             "-y", out],
            check=True, capture_output=True)

    @staticmethod
    async def _detect_lang(state: PipelineState) -> Tuple[str, str]:
        sample = state.transcription[:800]
        result = await run_text(
            state,
            f"Identify the language of this text.\n"
            f"Reply with exactly two items separated by '|':\n"
            f"1. Language name in English (e.g. Hindi, Gujarati, Tamil)\n"
            f"2. BCP-47 code (e.g. hi, gu, ta)\n\n"
            f"TEXT:\n{sample}\n\nAnswer:",
            max_tokens=30)
        parts = result.strip().split("|")
        name  = parts[0].strip(".:,\"' \n").split("\n")[0].strip()
        code  = parts[1].strip(".:,\"' \n").lower() if len(parts) > 1 else "und"
        return name, code

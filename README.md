# SmartNotes LLM Notebook

**Turn any lecture video, audio, or PDF into clean, bilingual, domain-aware study notes — automatically.**

SmartNotes LLM Notebook is a fully async, multi-agent AI pipeline that ingests a lecture video (local file or YouTube URL) or a PDF, transcribes the audio, extracts and classifies every meaningful frame, fuses both streams together, auto-detects the academic domain, and generates structured, publication-ready PDF study notes in any target language — with built-in QA retry loops to guarantee quality.

A **Streamlit web UI** (`app.py`) is included for a point-and-click experience, in addition to the full CLI.

---

## Features

- **Multi-modal understanding** — audio transcription + visual frame extraction run in parallel
- **PDF input support** — feed a PDF directly; text is extracted and notes are generated without any audio/video processing
- **Smart visual classification** — equations, diagrams, charts, flowcharts, timelines, tables, and more
- **Auto domain detection** — 13 academic domains (Mathematics, Physics, Chemistry, Biology, CS, History, Economics, Medicine, Engineering, Polity, Law, Geography, General)
- **Bilingual PDF output** — notes in your chosen target language plus the original lecture language
- **Practice questions PDF** — auto-generated MCQ quiz in the target language.
- **Built-in QA + retry loop** — validates every section for completeness, LaTeX presence, and prompt leakage; retries automatically up to 3 times
- **YouTube support** — paste any YouTube URL directly
- **Streamlit web UI** — browser-based interface via `streamlit run app.py`
- **Fully configurable** via `config.yaml` — no code changes needed for tuning

---

## Architecture

```
InputAgent  →  ModelLoaderAgent
                     ↓
         ┌───────────┴───────────┐
     AudioAgent            VisualAgent        (parallel)
         └───────────┬───────────┘
                FusionAgent
                     ↓
               DomainAgent
                     ↓
          NotesGenerationAgent ←──── QAValidatorAgent (retry loop)
                     ↓
    ┌────────────────┼────────────────┐
SourceNotesAgent  DiagramRenderAgent  PracticeQAAgent   (parallel)
    └────────────────┬────────────────┘
               PDF Generation Agent
                   
```

| Agent | Role |
|---|---|
| `InputAgent` | Validates file path, extracts PDF text, or downloads YouTube video |
| `ModelLoaderAgent` | Loads Gemma 4 model + processor onto GPU |
| `AudioAgent` | Extracts audio, chunks it, transcribes, detects language |
| `VisualAgent` | Samples frames every N seconds, classifies and extracts content |
| `FusionAgent` | Time-aligns transcript paragraphs with visual artifacts |
| `DomainAgent` | Detects primary + secondary academic domain from content |
| `NotesGenerationAgent` | Generates structured bilingual study notes |
| `QAValidatorAgent` | Checks required sections, LaTeX, code blocks, prompt leakage |
| `SourceNotesAgent` | Generates notes in the original lecture language |
| `DiagramRenderAgent` | Renders charts, timelines, and tables as PNG via matplotlib |
| `PracticeQAAgent` | Generates a tiered MCQ + mixed-format practice quiz |
| `PDFGenerationAgent` | Assembles final bilingual PDF with Noto font support |


---

## Requirements

### System dependency
```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html and add to PATH
```

### Python dependencies
```bash
pip install -r requirements.txt
```

> **GPU recommended.** The pipeline uses `google/gemma-4-E2B-it` via HuggingFace Transformers with `bfloat16` and `device_map="auto"`. A GPU with ≥16 GB VRAM (e.g. A100, RTX 4090) is ideal. CPU inference is possible but very slow.

### HuggingFace model access
The model `google/gemma-4-E2B-it` requires accepting Google's terms on HuggingFace. Log in before running:
```bash
huggingface-cli login
```

---

## Installation

```bash
git clone <your-repo-url>
cd smartnotes-llm-notebook

# Install Python packages
pip install -r requirements.txt

# Install ffmpeg (see above)
```

No additional setup is required — `config.yaml` is loaded automatically from the project root.

---

## Usage

### Streamlit Web UI
```bash
streamlit run app.py
```
Opens a browser-based interface where you can upload a video or PDF, choose a language, and watch the pipeline run — no terminal needed.

### CLI — Basic
```bash
python3 main.py --video lecture.mp4 --target-lang hindi
```

### CLI — YouTube URL
```bash
python3 main.py --video "https://youtu.be/XXXX" --target-lang english
```

### CLI — PDF Input
```bash
python3 main.py --pdf-input lecture_slides.pdf --target-lang gujarati
# or equivalently:
python3 main.py --video lecture_slides.pdf --target-lang gujarati
```

---

## CLI Reference

| Flag | Default | Description |
|---|---|---|
| `--video` | *(required)* | Local video/audio/PDF path or YouTube URL |
| `--pdf-input` | — | Path to a PDF file (alternative to `--video` for PDFs) |
| `--target-lang` | `english` | Output language name or BCP-47 code |
| `--output` | `smart_notes.pdf` | Output PDF file path |
| `--domain` | auto-detect | Force domain (see list below) |
| `--fps` | `5` | Sample one video frame every N seconds |
| `--skip-audio` | `false` | Skip audio transcription |
| `--skip-video` | `false` | Skip visual frame extraction |
| `--no-practice` | `false` | Skip practice questions PDF generation |

### Supported domains
`mathematics`, `physics`, `chemistry`, `biology`, `computer_science`, `history`, `economics`, `medicine`, `engineering`, `polity`, `law`, `geography`, `general`



---

## Output

### Notes PDF (`smart_notes.pdf`)
1. **Cover page** — lecture title, domain, target language, and source language
2. **Target language notes** — full structured notes in the chosen output language
3. **Source language notes** — notes in the original lecture language (skipped if same as target)
4. **Visual artifacts** — rendered diagrams, charts, timelines, and tables extracted from frames; content-rich visuals include the original video frame as a JPEG above the extracted content

Each section follows a domain-specific template (e.g. Mathematics includes *Theorems & Proofs*, *Worked Examples*, *Important Formulas*; Medicine includes *Pathophysiology*, *Diagnosis & Symptoms*, *Treatment & Management*).

### Practice Questions PDF (`<name>_practice.pdf`)
Auto-generated quiz in the target language. 

---

## File Structure

```
smartnotes-llm-notebook/
├── main.py                    # CLI entry point + Orchestrator
├── app.py                     # Streamlit web UI
├── constants.py               # Config loader, DOMAINS, enums, dataclasses
├── agents_io.py               # BaseAgent, model inference, InputAgent, ModelLoaderAgent, AudioAgent
├── agents_visual.py           # VisualAgent, FusionAgent, DiagramRenderAgent
├── agents_notes.py            # DomainAgent, NotesGenerationAgent, QAValidatorAgent,
│                              #   SourceNotesAgent, PracticeQAAgent
├── pdf_builder.py             # PDFGenerationAgent + build_practice_pdf
├── pdf_frame_embed_patch.py   # Helper: embed original video frames in PDF artifacts
├── config.yaml                # All runtime configuration
└── requirements.txt           # Python dependencies
```

---

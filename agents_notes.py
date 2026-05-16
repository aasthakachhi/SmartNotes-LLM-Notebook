# """
# agents_notes.py
# ===============
# Notes generation agents for SmartNotes v5:
#   - DomainAgent            (detect or force academic domain)
#   - NotesGenerationAgent   (generate structured bilingual study notes)
#   - QAValidatorAgent       (validate notes quality, detect prompt leakage)
#   - SourceNotesAgent       (generate notes in original lecture language)
# """

# import json
# import logging
# import re
# from typing import Dict, List

# from constants import (
#     DOMAINS, MAX_RETRIES, QA_MIN_WORDS,
#     AgentResult, AgentStatus, PipelineState,
# )
# from agents_io import BaseAgent, run_text

# log = logging.getLogger("SmartNotes")


# # ─────────────────────────────────────────────────────────────────────────────
# # AGENT 5 — DOMAIN AGENT
# # ─────────────────────────────────────────────────────────────────────────────

# class DomainAgent(BaseAgent):
#     name = "DomainAgent"

#     async def execute(self, state: PipelineState) -> str:
#         if state.forced_domain:
#             state.domain        = state.forced_domain
#             state.domain_scores = {state.forced_domain: 1.0}
#             log.info(f"Domain forced: {state.domain}")
#             return state.domain

#         sample_audio  = state.transcription[:1200] if state.transcription else "(none)"
#         sample_visual = "\n".join(
#             a.raw_desc[:150] for a in state.artifacts[:3]
#         ) if state.artifacts else "(none)"
#         domain_list   = "\n".join(
#             f"- {k}: {v['label']}" for k, v in DOMAINS.items())

#         prompt = (
#             f"Identify the top-2 academic domains of this lecture.\n\n"
#             f"AUDIO SAMPLE:\n{sample_audio}\n\n"
#             f"VISUAL SAMPLE:\n{sample_visual}\n\n"
#             f"DOMAIN LIST:\n{domain_list}\n\n"
#             f"Reply with EXACTLY this JSON and nothing else:\n"
#             f'{{"primary":"<key>","primary_score":0.9,'
#             f'"secondary":"<key>","secondary_score":0.3}}\n'
#             f"Use secondary_score < 0.3 if clearly single-domain.\nJSON:"
#         )
#         raw = await run_text(state, prompt, max_tokens=70)

#         primary, secondary, sec_score = "general", None, 0.0
#         try:
#             m = re.search(r'\{.*?\}', raw, re.DOTALL)
#             if m:
#                 parsed    = json.loads(m.group())
#                 primary   = parsed.get("primary", "general").strip().lower()
#                 sec_score = float(parsed.get("secondary_score", 0.0))
#                 sec_raw   = parsed.get("secondary", "").strip().lower()
#                 secondary = sec_raw if sec_raw and sec_raw != primary else None
#         except Exception as e:
#             log.warning(f"Domain parse failed ({e}) — using 'general'")

#         if primary not in DOMAINS:
#             primary = "general"
#         if secondary and secondary not in DOMAINS:
#             secondary = None

#         state.domain        = primary
#         state.domain_scores = {primary: 1.0}

#         if secondary and sec_score >= 0.3:
#             state.domain_scores[secondary] = sec_score
#             pri_secs  = list(DOMAINS[primary]["sections"])
#             extra     = [s for s in DOMAINS[secondary]["sections"]
#                          if s not in set(pri_secs)]
#             ins       = next((i for i, s in enumerate(pri_secs)
#                               if s == "SUMMARY"), len(pri_secs))
#             merged_secs = pri_secs[:ins] + extra + pri_secs[ins:]
#             merged_qa   = list(dict.fromkeys(
#                 DOMAINS[primary].get("qa_checks", []) +
#                 DOMAINS[secondary].get("qa_checks", [])))
#             DOMAINS[primary] = dict(DOMAINS[primary])
#             DOMAINS[primary]["sections"]  = merged_secs
#             DOMAINS[primary]["qa_checks"] = merged_qa
#             log.info(f"Domain: {primary}(1.0) + {secondary}({sec_score:.2f})")
#         else:
#             log.info(f"Domain: {primary} ({DOMAINS[primary]['label']})")

#         return primary


# # ─────────────────────────────────────────────────────────────────────────────
# # AGENT 6 — NOTES GENERATION AGENT
# # ─────────────────────────────────────────────────────────────────────────────

# class NotesGenerationAgent(BaseAgent):
#     name = "NotesGenerationAgent"

#     async def execute(self, state: PipelineState) -> str:
#         dinfo    = DOMAINS[state.domain]
#         template = "\n\n".join(f"{s}:\n" for s in dinfo["sections"])

#         repair_block = ""
#         if state.qa_repair_hint:
#             repair_block = (
#                 f"\n\nISSUES TO FIX FROM PREVIOUS ATTEMPT:\n"
#                 f"{state.qa_repair_hint}\n")

#         prompt = self._build_prompt(state, dinfo, template, repair_block)

#         log.info(f"Generating {state.target_lang_name} notes "
#                  f"(attempt {state.retry_count + 1}) …")
#         notes = await run_text(state, prompt, max_tokens=3500)
#         log.info(f"Notes: {len(notes)} chars")

#         state.target_notes = notes

#         state.title = f"{dinfo['label']} — {state.target_lang_name}"
#         for line in notes.split("\n"):
#             s = line.strip()
#             if s.upper().startswith("TITLE:"):
#                 state.title = s.split(":", 1)[1].strip()
#                 break
#         return notes

#     @staticmethod
#     def _build_prompt(state: PipelineState, dinfo: dict,
#                       template: str, repair_block: str) -> str:
#         content    = NotesGenerationAgent._build_content_block(state)
#         latex_note = (
#             "Use LaTeX for all equations: $inline$ or $$display$$."
#             if dinfo.get("expects_latex") else "")
#         code_note = (
#             "Put all code in fenced blocks: ```lang\\n...\\n```."
#             if state.domain == "computer_science" else "")

#         return f"""You are an expert educator writing study notes from a lecture.

# TARGET LANGUAGE: {state.target_lang_name}
# DOMAIN: {dinfo['label']}
# DOMAIN GUIDANCE: {dinfo['prompt_hint']}
# {latex_note}
# {code_note}

# LECTURE CONTENT (audio and on-screen visuals):
# {content}
# {repair_block}
# ─────────────────────────────────────────────────────────
# YOUR TASK: Write comprehensive study notes using the section template below.
# Fill in each section with content from the lecture above.

# IMPORTANT — READ CAREFULLY:
# - Write ONLY the notes. Do NOT copy this task description into your output.
# - Use ONLY information present in the lecture content above.
# - Do NOT add facts, statistics, or explanations from outside the lecture.
# - Write entirely in {state.target_lang_name}.
# - Section headers stay in the ALL-CAPS template format shown.
# - Use these special markers for richer formatting:
#     HIGHLIGHT: [one important fact worth remembering]
#     TERM: [term name] — [its definition as explained in the lecture]
#     TIMELINE:
#     [DATE] | [EVENT]
#     [DATE] | [EVENT]
#     COMPARISON TABLE:
#     [COLUMN A] | [COLUMN B] | [COLUMN C]
#     [row value] | [row value] | [row value]
# - Use bullet points (- item) for lists.
# - Use numbered points (1. item) for steps.
# - Use ## for subsection headings within a section.
# ─────────────────────────────────────────────────────────
# SECTION TEMPLATE (fill this in — do not reproduce these instructions):
# {template}
# """

#     @staticmethod
#     def _build_content_block(state: PipelineState) -> str:
#         if not state.fused_segments:
#             return state.transcription or "(no content)"
#         parts = []
#         for seg in state.fused_segments:
#             block = f"[{seg.timestamp}]\n"
#             if seg.transcript:
#                 block += f"SPOKEN: {seg.transcript}\n"
#             for art in seg.visuals:
#                 block += (f"VISUAL ({art.atype.value}): "
#                           f"{art.raw_desc[:400]}\n")
#             parts.append(block)
#         return "\n\n".join(parts)


# # ─────────────────────────────────────────────────────────────────────────────
# # AGENT 7 — QA VALIDATOR  (surgical per-check repair)
# # ─────────────────────────────────────────────────────────────────────────────

# class QAValidatorAgent(BaseAgent):
#     """
#     Validates notes quality section-by-section.

#     When a check fails the agent repairs ONLY that specific part instead of
#     regenerating the whole notes document:

#       • Missing section      → generate that section alone and append it
#       • Thin section         → regenerate just that section's content
#       • No LaTeX             → ask model to enrich notes with equations only
#       • No code blocks       → ask model to add code examples only
#       • Notes too short      → ask model to expand the thinnest sections only
#       • Prompt leakage       → strip leakage lines and ask model to rewrite
#                                only the affected paragraphs
#     """

#     name = "QAValidatorAgent"

#     # Patterns that indicate the model copied instructions into its output
#     LEAKAGE_PATTERNS = [
#         r"do not copy this",
#         r"read carefully",
#         r"write only the notes",
#         r"section template",
#         r"fill this in",
#         r"important —",
#         r"your task:",
#         r"use only information",
#         r"\bdo not add facts\b",
#         r"special markers for",
#     ]

#     # ── public entry-point ────────────────────────────────────────────────────

#     async def execute(self, state: PipelineState) -> bool:
#         """
#         Run all checks.  For every failed check attempt a targeted repair
#         in-place.  Returns True only when all checks pass (or pass after repair).
#         """
#         notes = state.target_notes
#         dinfo = DOMAINS[state.domain]
#         remaining_issues: List[str] = []

#         # ── 1. Required sections ──────────────────────────────────────────────
#         sec_map = self._section_map(notes)
#         for section in dinfo.get("qa_checks", []):
#             key   = section.upper()
#             match = next((k for k in sec_map if k.upper() == key), None)

#             if not match:
#                 log.warning(f"QA: missing section '{section}' — repairing…")
#                 notes = await self._repair_missing_section(state, notes, section)
#                 sec_map = self._section_map(notes)          # refresh after patch
#                 match   = next((k for k in sec_map if k.upper() == key), None)
#                 if not match:
#                     remaining_issues.append(f"Missing required section: {section}")
#                 continue

#             wc = len(sec_map[match].split())
#             if wc < QA_MIN_WORDS:
#                 log.warning(
#                     f"QA: section '{section}' too thin ({wc} words) — repairing…")
#                 notes = await self._repair_thin_section(
#                     state, notes, section, sec_map[match])
#                 sec_map = self._section_map(notes)
#                 new_wc  = len(sec_map.get(match, "").split())
#                 if new_wc < QA_MIN_WORDS:
#                     remaining_issues.append(
#                         f"Section '{section}' still too thin after repair "
#                         f"({new_wc} words, need ≥{QA_MIN_WORDS}).")

#         # ── 2. Domain-specific checks ─────────────────────────────────────────
#         if dinfo.get("expects_latex") and "$" not in notes:
#             log.warning("QA: no LaTeX found — repairing…")
#             notes = await self._repair_latex(state, notes)
#             if "$" not in notes:
#                 remaining_issues.append(
#                     "No LaTeX equations found — required for this domain.")

#         if state.domain == "computer_science" and "```" not in notes:
#             log.warning("QA: no code blocks found — repairing…")
#             notes = await self._repair_code_blocks(state, notes)
#             if "```" not in notes:
#                 remaining_issues.append(
#                     "No code blocks found — required for CS.")

#         if len(notes) < 500:
#             log.warning(f"QA: notes too short ({len(notes)} chars) — repairing…")
#             notes = await self._repair_too_short(state, notes)
#             if len(notes) < 500:
#                 remaining_issues.append(
#                     f"Notes too short after repair ({len(notes)} chars).")

#         # ── 3. Prompt leakage ─────────────────────────────────────────────────
#         notes_lower = notes.lower()
#         leakage_found = any(
#             re.search(p, notes_lower) for p in self.LEAKAGE_PATTERNS)
#         if leakage_found:
#             log.warning("QA: prompt leakage detected — repairing…")
#             notes = await self._repair_leakage(state, notes)
#             notes_lower = notes.lower()
#             if any(re.search(p, notes_lower) for p in self.LEAKAGE_PATTERNS):
#                 remaining_issues.append(
#                     "Prompt leakage still present after repair.")

#         # Commit the (possibly patched) notes back to state
#         state.target_notes = notes

#         if remaining_issues:
#             log.warning(
#                 f"QA FAILED after targeted repairs "
#                 f"({len(remaining_issues)} issues): {remaining_issues}")
#             state.qa_repair_hint = "\n".join(f"- {i}" for i in remaining_issues)
#             state.qa_issues      = remaining_issues
#             return False

#         log.info("QA PASSED")
#         state.qa_repair_hint = ""
#         state.qa_issues      = []
#         return True

#     # ── targeted repair helpers ───────────────────────────────────────────────

#     async def _repair_missing_section(
#             self, state: PipelineState, notes: str, section: str) -> str:
#         """Generate the missing section from scratch and append it."""
#         content = NotesGenerationAgent._build_content_block(state)
#         dinfo   = DOMAINS[state.domain]
#         prompt  = (
#             f"The study notes below are missing the '{section}' section.\n"
#             f"Write ONLY the content for that section (no other sections).\n"
#             f"Language: {state.target_lang_name}. "
#             f"Domain: {dinfo['label']}.\n\n"
#             f"LECTURE CONTENT:\n{content[:2000]}\n\n"
#             f"Start your response with the header line:\n"
#             f"{section.upper()}:\n"
#             f"then write the section content."
#         )
#         log.info(f"Repair: generating missing section '{section}'")
#         patch = await run_text(state, prompt, max_tokens=600)
#         return notes.rstrip() + "\n\n" + patch.strip()

#     async def _repair_thin_section(
#             self, state: PipelineState, notes: str,
#             section: str, existing_content: str) -> str:
#         """Regenerate only the body of an under-populated section."""
#         content = NotesGenerationAgent._build_content_block(state)
#         dinfo   = DOMAINS[state.domain]
#         prompt  = (
#             f"The '{section}' section of these study notes is too brief.\n"
#             f"Rewrite and expand ONLY that section's content "
#             f"(do NOT include any other section).\n"
#             f"Language: {state.target_lang_name}. "
#             f"Domain: {dinfo['label']}.\n\n"
#             f"CURRENT (too thin) CONTENT:\n{existing_content}\n\n"
#             f"LECTURE CONTENT:\n{content[:2000]}\n\n"
#             f"Output ONLY the expanded body text — no section header."
#         )
#         log.info(f"Repair: expanding thin section '{section}'")
#         expanded = await run_text(state, prompt, max_tokens=700)
#         return self._replace_section_body(notes, section, expanded.strip())

#     async def _repair_latex(
#             self, state: PipelineState, notes: str) -> str:
#         """Ask the model to insert LaTeX equations where appropriate."""
#         prompt  = (
#             f"The study notes below contain mathematical concepts but no LaTeX.\n"
#             f"Add LaTeX equations ($inline$ or $$display$$) wherever appropriate.\n"
#             f"Return the COMPLETE notes with equations inserted — "
#             f"do not change any other text.\n\n"
#             f"NOTES:\n{notes}"
#         )
#         log.info("Repair: inserting LaTeX equations")
#         return await run_text(state, prompt, max_tokens=3800)

#     async def _repair_code_blocks(
#             self, state: PipelineState, notes: str) -> str:
#         """Ask the model to add fenced code examples where appropriate."""
#         prompt  = (
#             f"The study notes below are for a Computer Science lecture but "
#             f"contain no code examples.\n"
#             f"Add fenced code blocks (```lang\\n...\\n```) wherever relevant.\n"
#             f"Return the COMPLETE notes with code blocks added — "
#             f"do not change any other text.\n\n"
#             f"NOTES:\n{notes}"
#         )
#         log.info("Repair: inserting code blocks")
#         return await run_text(state, prompt, max_tokens=3800)

#     async def _repair_too_short(
#             self, state: PipelineState, notes: str) -> str:
#         """Expand the thinnest sections to bring total length up."""
#         sec_map = self._section_map(notes)
#         content = NotesGenerationAgent._build_content_block(state)
#         dinfo   = DOMAINS[state.domain]

#         # Pick the two shortest sections to expand
#         sorted_secs = sorted(sec_map.items(), key=lambda kv: len(kv[1].split()))
#         thin_names  = [k for k, _ in sorted_secs[:2]]
#         thin_list   = "\n".join(
#             f"- {k}: {sec_map[k][:200]}" for k in thin_names)

#         prompt = (
#             f"These study notes are too short overall.\n"
#             f"Expand the following thin sections using ONLY the lecture content below.\n"
#             f"Language: {state.target_lang_name}. Domain: {dinfo['label']}.\n\n"
#             f"THIN SECTIONS TO EXPAND:\n{thin_list}\n\n"
#             f"LECTURE CONTENT:\n{content[:2000]}\n\n"
#             f"For each section output:\n"
#             f"SECTION_NAME:\n<expanded body>\n\n"
#             f"Output ONLY the expanded sections, nothing else."
#         )
#         log.info("Repair: expanding short notes")
#         patches = await run_text(state, prompt, max_tokens=1200)

#         # Patch each returned section back into notes
#         patch_map = self._section_map(patches)
#         for sec_key, new_body in patch_map.items():
#             original_key = next(
#                 (k for k in sec_map if k.upper() == sec_key.upper()), None)
#             if original_key:
#                 notes = self._replace_section_body(notes, original_key, new_body)
#         return notes

#     async def _repair_leakage(
#             self, state: PipelineState, notes: str) -> str:
#         """Strip leaked instruction lines and ask the model to fill gaps."""
#         # First pass: remove lines that match leakage patterns
#         clean_lines = []
#         leakage_re  = re.compile(
#             "|".join(self.LEAKAGE_PATTERNS), re.IGNORECASE)
#         for line in notes.splitlines():
#             if leakage_re.search(line):
#                 log.debug(f"Leakage stripped: {line!r}")
#             else:
#                 clean_lines.append(line)
#         cleaned = "\n".join(clean_lines)

#         # Second pass: ask model to rewrite any awkward gaps left behind
#         prompt  = (
#             f"The study notes below had some instruction text accidentally "
#             f"included and then removed, leaving gaps.\n"
#             f"Rewrite the notes so they read naturally — fix only the "
#             f"sentences/paragraphs that are broken or incomplete.\n"
#             f"Language: {state.target_lang_name}.\n"
#             f"Return the COMPLETE corrected notes.\n\n"
#             f"NOTES:\n{cleaned}"
#         )
#         log.info("Repair: cleaning prompt leakage")
#         return await run_text(state, prompt, max_tokens=3800)

#     # ── static helpers ────────────────────────────────────────────────────────

#     @staticmethod
#     def _section_map(notes: str) -> Dict[str, str]:
#         header_re = re.compile(r'^([A-Z][A-Z0-9 &/()\-]+):$', re.MULTILINE)
#         result: Dict[str, str] = {}
#         matches = list(header_re.finditer(notes))
#         for i, m in enumerate(matches):
#             key   = m.group(1).strip()
#             start = m.end()
#             end   = matches[i + 1].start() if i + 1 < len(matches) else len(notes)
#             result[key] = notes[start:end].strip()
#         return result

#     @staticmethod
#     def _replace_section_body(notes: str, section: str, new_body: str) -> str:
#         """
#         Replace the body of *section* in *notes* with *new_body*.
#         The section header line is preserved; everything up to the next
#         ALL-CAPS header (or end-of-string) is swapped out.
#         """
#         header_re = re.compile(r'^([A-Z][A-Z0-9 &/()\-]+):$', re.MULTILINE)
#         matches   = list(header_re.finditer(notes))
#         for i, m in enumerate(matches):
#             if m.group(1).strip().upper() == section.upper():
#                 body_start = m.end()
#                 body_end   = (matches[i + 1].start()
#                               if i + 1 < len(matches) else len(notes))
#                 return (
#                     notes[:body_start]
#                     + "\n" + new_body + "\n\n"
#                     + notes[body_end:]
#                 )
#         # Section header not found — just return notes unchanged
#         return notes


# # ─────────────────────────────────────────────────────────────────────────────
# # AGENT 8 — SOURCE NOTES AGENT
# # ─────────────────────────────────────────────────────────────────────────────

# class SourceNotesAgent(BaseAgent):
#     name = "SourceNotesAgent"

#     async def execute(self, state: PipelineState) -> str:
#         if state.detected_lang_code == state.target_lang_code:
#             state.source_notes = state.target_notes
#             log.info("Source == target language — reusing target notes.")
#             return state.source_notes

#         dinfo    = DOMAINS[state.domain]
#         template = "\n\n".join(f"{s}:\n" for s in dinfo["sections"])

#         prompt = NotesGenerationAgent._build_prompt(
#             state, dinfo, template, "")
#         prompt = prompt.replace(
#             f"TARGET LANGUAGE: {state.target_lang_name}",
#             f"TARGET LANGUAGE: {state.detected_lang}")
#         prompt = prompt.replace(
#             f"Write entirely in {state.target_lang_name}.",
#             f"Write entirely in {state.detected_lang}.")

#         log.info(f"Generating {state.detected_lang} source notes …")
#         notes = await run_text(state, prompt, max_tokens=3000)
#         log.info(f"Source notes: {len(notes)} chars")
#         state.source_notes = notes
#         return notes


# # ─────────────────────────────────────────────────────────────────────────────
# # AGENT 9 — PRACTICE QUESTIONS AGENT
# # ─────────────────────────────────────────────────────────────────────────────

# class PracticeQAAgent(BaseAgent):
#     name = "PracticeQAAgent"

#     async def execute(self, state: PipelineState) -> str:
#         dinfo = DOMAINS[state.domain]

#         prompt = f"""You are an expert educator creating a multiple-choice quiz.

# LANGUAGE: {state.target_lang_name}
# DOMAIN: {dinfo['label']}

# LECTURE NOTES:
# {state.target_notes[:3000]}

# ─────────────────────────────────────────────────────────
# YOUR TASK:
# Generate exactly 15 multiple-choice questions (MCQ) based strictly on the
# lecture notes above. Write entirely in {state.target_lang_name}.

# STRICT RULES — follow every one:
# 1. Output ONLY the 5 MCQs. Nothing else. No headings, no preamble, no
#    section labels, no answers, no answer keys.
# 2. Every question must have exactly 4 options labelled A) B) C) D).
# 3. Do NOT include the correct answer anywhere — not inline, not at the end,
#    not as a comment. The student will choose their own answer.
# 4. Number each question: 1. 2. 3. ... 5.
# 5. Base every question on facts explicitly stated in the lecture notes.
# 6. Vary question difficulty level.

# FORMAT (repeat for all 5):
# 1. [Question text]
# A) [option]
# B) [option]
# C) [option]
# D) [option]

# ─────────────────────────────────────────────────────────
# BEGIN OUTPUT (5 MCQs only, no answers):
# """

#         log.info(f"Generating MCQ practice questions in {state.target_lang_name} …")
#         questions = await run_text(state, prompt, max_tokens=2500)
#         log.info(f"Practice MCQs: {len(questions)} chars")

#         # Strip any accidental "Answer:" lines the model may have leaked
#         cleaned = _strip_answers(questions)
#         state.practice_questions = cleaned
#         return cleaned


# def _strip_answers(text: str) -> str:
#     """Remove any answer-key lines from MCQ output (model leak guard)."""
#     answer_re = re.compile(
#         r'^\s*(answer\s*[:：]\s*\w.*|correct\s*[:：].*|ans\s*[:：].*)$',
#         re.IGNORECASE | re.MULTILINE,
#     )
#     cleaned = answer_re.sub("", text)
#     # Collapse multiple blank lines left by removal
#     cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
#     return cleaned.strip()


# # ─────────────────────────────────────────────────────────────────────────────
# # AGENT 10 — INTERACTIVE CHAT AGENT
# # ─────────────────────────────────────────────────────────────────────────────

# class ChatAgent(BaseAgent):
#     name = "ChatAgent"

#     SYSTEM_CONTEXT = """You are a helpful study tutor. A student has just received lecture notes and wants to ask questions about the topic.

# Use ONLY the information from the lecture notes and transcription provided as context.
# Answer clearly and helpfully in the same language the student uses to ask.
# If something is not covered in the notes, say so honestly.
# Keep answers concise but complete.

# LECTURE NOTES:
# {notes}

# TRANSCRIPTION SUMMARY:
# {transcript}
# """

#     async def execute(self, state: PipelineState) -> str:
#         """Non-interactive execute — just validates context is ready."""
#         return "ChatAgent ready"

#     async def chat(self, state: PipelineState, user_message: str) -> str:
#         """Process one message from the student and return a response."""
#         context = self.SYSTEM_CONTEXT.format(
#             notes=state.target_notes[:4000],
#             transcript=state.transcription[:1500] if state.transcription else "(PDF input — no audio transcript)",
#         )

#         # Build conversation history
#         history_text = ""
#         for turn in state.chat_history[-6:]:   # keep last 3 exchanges
#             history_text += f"Student: {turn['user']}\nTutor: {turn['assistant']}\n\n"

#         prompt = f"""{context}

# CONVERSATION SO FAR:
# {history_text}
# Student: {user_message}
# Tutor:"""

#         response = await run_text(state, prompt, max_tokens=512)
#         response = response.strip()

#         # Save to history
#         state.chat_history.append({
#             "user": user_message,
#             "assistant": response,
#         })
#         return response


# def run_chat_loop(state: PipelineState, chat_agent: ChatAgent):
#     """Blocking interactive chat loop — runs after pipeline completes."""
#     import asyncio

#     CYAN  = "\033[96m"
#     GREEN = "\033[92m"
#     RESET = "\033[0m"
#     BOLD  = "\033[1m"

#     print()
#     print("─" * 60)
#     print(f"{BOLD}  📚 SMART NOTES — INTERACTIVE TUTOR{RESET}")
#     print(f"  Ask anything about the lecture notes.")
#     print(f"  Type {BOLD}'exit'{RESET} or {BOLD}'quit'{RESET} to stop.")
#     print("─" * 60)
#     print()

#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)

#     try:
#         while True:
#             try:
#                 user_input = input(f"{GREEN}You: {RESET}").strip()
#             except (EOFError, KeyboardInterrupt):
#                 print("\n  Exiting chat. Good luck with your studies! 👋")
#                 break

#             if not user_input:
#                 continue
#             if user_input.lower() in ("exit", "quit", "bye", "q"):
#                 print("  Exiting chat. Good luck with your studies! 👋")
#                 break

#             print(f"{CYAN}Tutor: {RESET}", end="", flush=True)
#             try:
#                 response = loop.run_until_complete(
#                     chat_agent.chat(state, user_input))
#                 print(f"{CYAN}{response}{RESET}\n")
#             except Exception as e:
#                 print(f"[Error: {e}]\n")
#     finally:
#         loop.close()

"""
agents_notes.py
===============
Notes generation agents for SmartNotes v5:
  - DomainAgent            (detect or force academic domain)
  - NotesGenerationAgent   (generate structured bilingual study notes)
  - QAValidatorAgent       (validate notes quality, detect prompt leakage)
  - SourceNotesAgent       (generate notes in original lecture language)
"""

import json
import logging
import re
from typing import Dict, List

from constants import (
    DOMAINS, MAX_RETRIES, QA_MIN_WORDS,
    AgentResult, AgentStatus, PipelineState,
)
from agents_io import BaseAgent, run_text

log = logging.getLogger("SmartNotes")


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 5 — DOMAIN AGENT
# ─────────────────────────────────────────────────────────────────────────────

class DomainAgent(BaseAgent):
    name = "DomainAgent"

    async def execute(self, state: PipelineState) -> str:
        if state.forced_domain:
            state.domain        = state.forced_domain
            state.domain_scores = {state.forced_domain: 1.0}
            log.info(f"Domain forced: {state.domain}")
            return state.domain

        sample_audio  = state.transcription[:1200] if state.transcription else "(none)"
        sample_visual = "\n".join(
            a.raw_desc[:150] for a in state.artifacts[:3]
        ) if state.artifacts else "(none)"
        domain_list   = "\n".join(
            f"- {k}: {v['label']}" for k, v in DOMAINS.items())

        prompt = (
            f"Identify the top-2 academic domains of this lecture.\n\n"
            f"AUDIO SAMPLE:\n{sample_audio}\n\n"
            f"VISUAL SAMPLE:\n{sample_visual}\n\n"
            f"DOMAIN LIST:\n{domain_list}\n\n"
            f"Reply with EXACTLY this JSON and nothing else:\n"
            f'{{"primary":"<key>","primary_score":0.9,'
            f'"secondary":"<key>","secondary_score":0.3}}\n'
            f"Use secondary_score < 0.3 if clearly single-domain.\nJSON:"
        )
        raw = await run_text(state, prompt, max_tokens=70)

        primary, secondary, sec_score = "general", None, 0.0
        try:
            m = re.search(r'\{.*?\}', raw, re.DOTALL)
            if m:
                parsed    = json.loads(m.group())
                primary   = parsed.get("primary", "general").strip().lower()
                sec_score = float(parsed.get("secondary_score", 0.0))
                sec_raw   = parsed.get("secondary", "").strip().lower()
                secondary = sec_raw if sec_raw and sec_raw != primary else None
        except Exception as e:
            log.warning(f"Domain parse failed ({e}) — using 'general'")

        if primary not in DOMAINS:
            primary = "general"
        if secondary and secondary not in DOMAINS:
            secondary = None

        state.domain        = primary
        state.domain_scores = {primary: 1.0}

        if secondary and sec_score >= 0.3:
            state.domain_scores[secondary] = sec_score
            pri_secs  = list(DOMAINS[primary]["sections"])
            extra     = [s for s in DOMAINS[secondary]["sections"]
                         if s not in set(pri_secs)]
            ins       = next((i for i, s in enumerate(pri_secs)
                              if s == "SUMMARY"), len(pri_secs))
            merged_secs = pri_secs[:ins] + extra + pri_secs[ins:]
            merged_qa   = list(dict.fromkeys(
                DOMAINS[primary].get("qa_checks", []) +
                DOMAINS[secondary].get("qa_checks", [])))
            DOMAINS[primary] = dict(DOMAINS[primary])
            DOMAINS[primary]["sections"]  = merged_secs
            DOMAINS[primary]["qa_checks"] = merged_qa
            log.info(f"Domain: {primary}(1.0) + {secondary}({sec_score:.2f})")
        else:
            log.info(f"Domain: {primary} ({DOMAINS[primary]['label']})")

        return primary


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 6 — NOTES GENERATION AGENT
# ─────────────────────────────────────────────────────────────────────────────

class NotesGenerationAgent(BaseAgent):
    name = "NotesGenerationAgent"

    async def execute(self, state: PipelineState) -> str:
        dinfo    = DOMAINS[state.domain]
        template = "\n\n".join(f"{s}:\n" for s in dinfo["sections"])

        repair_block = ""
        if state.qa_repair_hint:
            repair_block = (
                f"\n\nISSUES TO FIX FROM PREVIOUS ATTEMPT:\n"
                f"{state.qa_repair_hint}\n")

        prompt = self._build_prompt(state, dinfo, template, repair_block)

        log.info(f"Generating {state.target_lang_name} notes "
                 f"(attempt {state.retry_count + 1}) …")
        notes = await run_text(state, prompt, max_tokens=3500)
        log.info(f"Notes: {len(notes)} chars")

        state.target_notes = notes

        state.title = f"{dinfo['label']} — {state.target_lang_name}"
        for line in notes.split("\n"):
            s = line.strip()
            if s.upper().startswith("TITLE:"):
                state.title = s.split(":", 1)[1].strip()
                break
        return notes

    @staticmethod
    def _build_prompt(state: PipelineState, dinfo: dict,
                      template: str, repair_block: str) -> str:
        content    = NotesGenerationAgent._build_content_block(state)
        latex_note = (
            "Use LaTeX for all equations: $inline$ or $$display$$."
            if dinfo.get("expects_latex") else "")
        code_note = (
            "Put all code in fenced blocks: ```lang\\n...\\n```."
            if state.domain == "computer_science" else "")

        return f"""You are an expert educator writing study notes from a lecture.

TARGET LANGUAGE: {state.target_lang_name}
DOMAIN: {dinfo['label']}
DOMAIN GUIDANCE: {dinfo['prompt_hint']}
{latex_note}
{code_note}

LECTURE CONTENT (audio and on-screen visuals):
{content}
{repair_block}
─────────────────────────────────────────────────────────
YOUR TASK: Write comprehensive study notes using the section template below.
Fill in each section with content from the lecture above.

IMPORTANT — READ CAREFULLY:
- Write ONLY the notes. Do NOT copy this task description into your output.
- Use ONLY information present in the lecture content above.
- Do NOT add facts, statistics, or explanations from outside the lecture.
- Write entirely in {state.target_lang_name}.
- Section headers stay in the ALL-CAPS template format shown.
- Use these special markers for richer formatting:
    HIGHLIGHT: [one important fact worth remembering]
    TERM: [term name] — [its definition as explained in the lecture]
    TIMELINE:
    [DATE] | [EVENT]
    [DATE] | [EVENT]
    COMPARISON TABLE:
    [COLUMN A] | [COLUMN B] | [COLUMN C]
    [row value] | [row value] | [row value]
- Use bullet points (- item) for lists.
- Use numbered points (1. item) for steps.
- Use ## for subsection headings within a section.
─────────────────────────────────────────────────────────
SECTION TEMPLATE (fill this in — do not reproduce these instructions):
{template}
"""

    @staticmethod
    def _build_content_block(state: PipelineState) -> str:
        if not state.fused_segments:
            return state.transcription or "(no content)"
        parts = []
        for seg in state.fused_segments:
            block = f"[{seg.timestamp}]\n"
            if seg.transcript:
                block += f"SPOKEN: {seg.transcript}\n"
            for art in seg.visuals:
                block += (f"VISUAL ({art.atype.value}): "
                          f"{art.raw_desc[:400]}\n")
            parts.append(block)
        return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 7 — QA VALIDATOR  (surgical per-check repair)
# ─────────────────────────────────────────────────────────────────────────────

class QAValidatorAgent(BaseAgent):
    """
    Validates notes quality section-by-section.

    When a check fails the agent repairs ONLY that specific part instead of
    regenerating the whole notes document:

      • Missing section      → generate that section alone and append it
      • Thin section         → regenerate just that section's content
      • No LaTeX             → ask model to enrich notes with equations only
      • No code blocks       → ask model to add code examples only
      • Notes too short      → ask model to expand the thinnest sections only
      • Prompt leakage       → strip leakage lines and ask model to rewrite
                               only the affected paragraphs
    """

    name = "QAValidatorAgent"

    # Patterns that indicate the model copied instructions into its output
    LEAKAGE_PATTERNS = [
        r"do not copy this",
        r"read carefully",
        r"write only the notes",
        r"section template",
        r"fill this in",
        r"important —",
        r"your task:",
        r"use only information",
        r"\bdo not add facts\b",
        r"special markers for",
    ]

    # Hard limit: QA runs at most this many times across the whole pipeline
    MAX_QA_ATTEMPTS = 2

    # ── public entry-point ────────────────────────────────────────────────────

    async def execute(self, state: PipelineState) -> bool:
        """
        Run all checks.  For every failed check attempt a targeted repair
        in-place.  Returns True only when all checks pass (or pass after repair).

        Hard cap: if this is already the 2nd QA attempt (state.retry_count >= 1),
        skip all repairs, accept the notes as-is, and return True so the
        pipeline moves on regardless of remaining issues.
        """
        # ── Hard attempt cap ─────────────────────────────────────────────────
        if state.retry_count >= self.MAX_QA_ATTEMPTS:
            log.warning(
                f"QA: reached max attempts ({self.MAX_QA_ATTEMPTS}) — "
                f"accepting notes as-is and moving on.")
            state.qa_repair_hint = ""   # stop orchestrator from retrying
            state.qa_issues      = []
            return True

        notes = state.target_notes
        dinfo = DOMAINS[state.domain]
        remaining_issues: List[str] = []

        # ── 1. Required sections ──────────────────────────────────────────────
        sec_map = self._section_map(notes)
        for section in dinfo.get("qa_checks", []):
            key   = section.upper()
            match = next((k for k in sec_map if k.upper() == key), None)

            if not match:
                log.warning(f"QA: missing section '{section}' — repairing…")
                notes = await self._repair_missing_section(state, notes, section)
                sec_map = self._section_map(notes)          # refresh after patch
                match   = next((k for k in sec_map if k.upper() == key), None)
                if not match:
                    remaining_issues.append(f"Missing required section: {section}")
                continue

            wc = len(sec_map[match].split())
            if wc < QA_MIN_WORDS:
                log.warning(
                    f"QA: section '{section}' too thin ({wc} words) — repairing…")
                notes = await self._repair_thin_section(
                    state, notes, section, sec_map[match])
                sec_map = self._section_map(notes)
                new_wc  = len(sec_map.get(match, "").split())
                if new_wc < QA_MIN_WORDS:
                    remaining_issues.append(
                        f"Section '{section}' still too thin after repair "
                        f"({new_wc} words, need ≥{QA_MIN_WORDS}).")

        # ── 2. Domain-specific checks ─────────────────────────────────────────
        if dinfo.get("expects_latex") and "$" not in notes:
            log.warning("QA: no LaTeX found — repairing…")
            notes = await self._repair_latex(state, notes)
            if "$" not in notes:
                remaining_issues.append(
                    "No LaTeX equations found — required for this domain.")

        if state.domain == "computer_science" and "```" not in notes:
            log.warning("QA: no code blocks found — repairing…")
            notes = await self._repair_code_blocks(state, notes)
            if "```" not in notes:
                remaining_issues.append(
                    "No code blocks found — required for CS.")

        if len(notes) < 500:
            log.warning(f"QA: notes too short ({len(notes)} chars) — repairing…")
            notes = await self._repair_too_short(state, notes)
            if len(notes) < 500:
                remaining_issues.append(
                    f"Notes too short after repair ({len(notes)} chars).")

        # ── 3. Prompt leakage ─────────────────────────────────────────────────
        notes_lower = notes.lower()
        leakage_found = any(
            re.search(p, notes_lower) for p in self.LEAKAGE_PATTERNS)
        if leakage_found:
            log.warning("QA: prompt leakage detected — repairing…")
            notes = await self._repair_leakage(state, notes)
            notes_lower = notes.lower()
            if any(re.search(p, notes_lower) for p in self.LEAKAGE_PATTERNS):
                remaining_issues.append(
                    "Prompt leakage still present after repair.")

        # Commit the (possibly patched) notes back to state
        state.target_notes = notes

        if remaining_issues:
            log.warning(
                f"QA FAILED after targeted repairs "
                f"({len(remaining_issues)} issues): {remaining_issues}")
            state.qa_repair_hint = "\n".join(f"- {i}" for i in remaining_issues)
            state.qa_issues      = remaining_issues
            return False

        log.info("QA PASSED")
        state.qa_repair_hint = ""
        state.qa_issues      = []
        return True

    # ── targeted repair helpers ───────────────────────────────────────────────

    async def _repair_missing_section(
            self, state: PipelineState, notes: str, section: str) -> str:
        """Generate the missing section from scratch and append it."""
        content = NotesGenerationAgent._build_content_block(state)
        dinfo   = DOMAINS[state.domain]
        prompt  = (
            f"The study notes below are missing the '{section}' section.\n"
            f"Write ONLY the content for that section (no other sections).\n"
            f"Language: {state.target_lang_name}. "
            f"Domain: {dinfo['label']}.\n\n"
            f"LECTURE CONTENT:\n{content[:2000]}\n\n"
            f"Start your response with the header line:\n"
            f"{section.upper()}:\n"
            f"then write the section content."
        )
        log.info(f"Repair: generating missing section '{section}'")
        patch = await run_text(state, prompt, max_tokens=600)
        return notes.rstrip() + "\n\n" + patch.strip()

    async def _repair_thin_section(
            self, state: PipelineState, notes: str,
            section: str, existing_content: str) -> str:
        """Regenerate only the body of an under-populated section."""
        content = NotesGenerationAgent._build_content_block(state)
        dinfo   = DOMAINS[state.domain]
        prompt  = (
            f"The '{section}' section of these study notes is too brief.\n"
            f"Rewrite and expand ONLY that section's content "
            f"(do NOT include any other section).\n"
            f"Language: {state.target_lang_name}. "
            f"Domain: {dinfo['label']}.\n\n"
            f"CURRENT (too thin) CONTENT:\n{existing_content}\n\n"
            f"LECTURE CONTENT:\n{content[:2000]}\n\n"
            f"Output ONLY the expanded body text — no section header."
        )
        log.info(f"Repair: expanding thin section '{section}'")
        expanded = await run_text(state, prompt, max_tokens=700)
        return self._replace_section_body(notes, section, expanded.strip())

    async def _repair_latex(
            self, state: PipelineState, notes: str) -> str:
        """Ask the model to insert LaTeX equations where appropriate."""
        prompt  = (
            f"The study notes below contain mathematical concepts but no LaTeX.\n"
            f"Add LaTeX equations ($inline$ or $$display$$) wherever appropriate.\n"
            f"Return the COMPLETE notes with equations inserted — "
            f"do not change any other text.\n\n"
            f"NOTES:\n{notes}"
        )
        log.info("Repair: inserting LaTeX equations")
        return await run_text(state, prompt, max_tokens=3800)

    async def _repair_code_blocks(
            self, state: PipelineState, notes: str) -> str:
        """Ask the model to add fenced code examples where appropriate."""
        prompt  = (
            f"The study notes below are for a Computer Science lecture but "
            f"contain no code examples.\n"
            f"Add fenced code blocks (```lang\\n...\\n```) wherever relevant.\n"
            f"Return the COMPLETE notes with code blocks added — "
            f"do not change any other text.\n\n"
            f"NOTES:\n{notes}"
        )
        log.info("Repair: inserting code blocks")
        return await run_text(state, prompt, max_tokens=3800)

    async def _repair_too_short(
            self, state: PipelineState, notes: str) -> str:
        """Expand the thinnest sections to bring total length up."""
        sec_map = self._section_map(notes)
        content = NotesGenerationAgent._build_content_block(state)
        dinfo   = DOMAINS[state.domain]

        # Pick the two shortest sections to expand
        sorted_secs = sorted(sec_map.items(), key=lambda kv: len(kv[1].split()))
        thin_names  = [k for k, _ in sorted_secs[:2]]
        thin_list   = "\n".join(
            f"- {k}: {sec_map[k][:200]}" for k in thin_names)

        prompt = (
            f"These study notes are too short overall.\n"
            f"Expand the following thin sections using ONLY the lecture content below.\n"
            f"Language: {state.target_lang_name}. Domain: {dinfo['label']}.\n\n"
            f"THIN SECTIONS TO EXPAND:\n{thin_list}\n\n"
            f"LECTURE CONTENT:\n{content[:2000]}\n\n"
            f"For each section output:\n"
            f"SECTION_NAME:\n<expanded body>\n\n"
            f"Output ONLY the expanded sections, nothing else."
        )
        log.info("Repair: expanding short notes")
        patches = await run_text(state, prompt, max_tokens=1200)

        # Patch each returned section back into notes
        patch_map = self._section_map(patches)
        for sec_key, new_body in patch_map.items():
            original_key = next(
                (k for k in sec_map if k.upper() == sec_key.upper()), None)
            if original_key:
                notes = self._replace_section_body(notes, original_key, new_body)
        return notes

    async def _repair_leakage(
            self, state: PipelineState, notes: str) -> str:
        """Strip leaked instruction lines and ask the model to fill gaps."""
        # First pass: remove lines that match leakage patterns
        clean_lines = []
        leakage_re  = re.compile(
            "|".join(self.LEAKAGE_PATTERNS), re.IGNORECASE)
        for line in notes.splitlines():
            if leakage_re.search(line):
                log.debug(f"Leakage stripped: {line!r}")
            else:
                clean_lines.append(line)
        cleaned = "\n".join(clean_lines)

        # Second pass: ask model to rewrite any awkward gaps left behind
        prompt  = (
            f"The study notes below had some instruction text accidentally "
            f"included and then removed, leaving gaps.\n"
            f"Rewrite the notes so they read naturally — fix only the "
            f"sentences/paragraphs that are broken or incomplete.\n"
            f"Language: {state.target_lang_name}.\n"
            f"Return the COMPLETE corrected notes.\n\n"
            f"NOTES:\n{cleaned}"
        )
        log.info("Repair: cleaning prompt leakage")
        return await run_text(state, prompt, max_tokens=3800)

    # ── static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _section_map(notes: str) -> Dict[str, str]:
        header_re = re.compile(r'^([A-Z][A-Z0-9 &/()\-]+):$', re.MULTILINE)
        result: Dict[str, str] = {}
        matches = list(header_re.finditer(notes))
        for i, m in enumerate(matches):
            key   = m.group(1).strip()
            start = m.end()
            end   = matches[i + 1].start() if i + 1 < len(matches) else len(notes)
            result[key] = notes[start:end].strip()
        return result

    @staticmethod
    def _replace_section_body(notes: str, section: str, new_body: str) -> str:
        """
        Replace the body of *section* in *notes* with *new_body*.
        The section header line is preserved; everything up to the next
        ALL-CAPS header (or end-of-string) is swapped out.
        """
        header_re = re.compile(r'^([A-Z][A-Z0-9 &/()\-]+):$', re.MULTILINE)
        matches   = list(header_re.finditer(notes))
        for i, m in enumerate(matches):
            if m.group(1).strip().upper() == section.upper():
                body_start = m.end()
                body_end   = (matches[i + 1].start()
                              if i + 1 < len(matches) else len(notes))
                return (
                    notes[:body_start]
                    + "\n" + new_body + "\n\n"
                    + notes[body_end:]
                )
        # Section header not found — just return notes unchanged
        return notes


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 8 — SOURCE NOTES AGENT
# ─────────────────────────────────────────────────────────────────────────────

class SourceNotesAgent(BaseAgent):
    name = "SourceNotesAgent"

    async def execute(self, state: PipelineState) -> str:
        if state.detected_lang_code == state.target_lang_code:
            state.source_notes = state.target_notes
            log.info("Source == target language — reusing target notes.")
            return state.source_notes

        dinfo    = DOMAINS[state.domain]
        template = "\n\n".join(f"{s}:\n" for s in dinfo["sections"])

        prompt = NotesGenerationAgent._build_prompt(
            state, dinfo, template, "")
        prompt = prompt.replace(
            f"TARGET LANGUAGE: {state.target_lang_name}",
            f"TARGET LANGUAGE: {state.detected_lang}")
        prompt = prompt.replace(
            f"Write entirely in {state.target_lang_name}.",
            f"Write entirely in {state.detected_lang}.")

        log.info(f"Generating {state.detected_lang} source notes …")
        notes = await run_text(state, prompt, max_tokens=3000)
        log.info(f"Source notes: {len(notes)} chars")
        state.source_notes = notes
        return notes


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 9 — PRACTICE QUESTIONS AGENT
# ─────────────────────────────────────────────────────────────────────────────

class PracticeQAAgent(BaseAgent):
    name = "PracticeQAAgent"

    # ── Question count thresholds (in seconds) ────────────────────────────────
    _SHORT_VIDEO_MAX_SECS  = 2.5 * 60   # < 2.5 min  ->  5 questions
    _MEDIUM_VIDEO_MAX_SECS = 7.5 * 60   # 2.5-7.5 min -> 10 questions
    #                                    # > 7.5 min  -> 15 questions

    @staticmethod
    def _question_count(duration_secs):
        """
        Return (n_questions, difficulty_split) based on video length.

          < 2.5 min  ->  5 questions  (2 easy, 2 medium, 1 hard)
          2.5-7.5 min -> 10 questions  (3 easy, 4 medium, 3 hard)
          > 7.5 min  -> 15 questions  (5 easy, 5 medium, 5 hard)

        If duration is unknown, defaults to 15.
        """
        if duration_secs is None:
            return 15, "5 easy, 5 medium, 5 hard"
        if duration_secs < PracticeQAAgent._SHORT_VIDEO_MAX_SECS:
            return 5, "2 easy, 2 medium, 1 hard"
        elif duration_secs <= PracticeQAAgent._MEDIUM_VIDEO_MAX_SECS:
            return 10, "3 easy, 4 medium, 3 hard"
        else:
            return 15, "5 easy, 5 medium, 5 hard"

    async def execute(self, state: PipelineState) -> str:
        dinfo = DOMAINS[state.domain]

        # Resolve question count from video duration stored on state
        # (state.video_duration_secs is expected to be float | None)
        duration_secs = getattr(state, "video_duration_secs", None)
        n_questions, difficulty_split = self._question_count(duration_secs)

        log.info(
            f"PracticeQA: video duration={duration_secs}s -> "
            f"{n_questions} questions ({difficulty_split})")

        # Build a sample FORMAT block showing the first 3 as examples
        format_example = "\n\n".join(
            f"{i}. [Question text]\nA) [option]\nB) [option]\nC) [option]\nD) [option]"
            for i in range(1, min(n_questions, 3) + 1)
        )

        prompt = f"""You are an expert educator creating a multiple-choice quiz.

LANGUAGE: {state.target_lang_name}
DOMAIN: {dinfo['label']}

LECTURE NOTES:
{state.target_notes[:3000]}

# ─────────────────────────────────────────────────────────
# YOUR TASK:
# Generate exactly 15 multiple-choice questions (MCQ) based strictly on the
# lecture notes above. Write entirely in {state.target_lang_name}.

# STRICT RULES — follow every one:
# 1. Output ONLY the 5 MCQs. Nothing else. No headings, no preamble, no
#    section labels, no answers, no answer keys.
# 2. Every question must have exactly 4 options labelled A) B) C) D).
# 3. Do NOT include the correct answer anywhere — not inline, not at the end,
#    not as a comment. The student will choose their own answer.
# 4. Number each question: 1. 2. 3. ... 5.
# 5. Base every question on facts explicitly stated in the lecture notes.
# 6. Vary question difficulty level.

# FORMAT (repeat for all 5):
# 1. [Question text]
# A) [option]
# B) [option]
# C) [option]
# D) [option]

# ─────────────────────────────────────────────────────────
# BEGIN OUTPUT (5 MCQs only, no answers):
# """

        log.info(f"Generating {n_questions} MCQ practice questions "
                 f"in {state.target_lang_name} ...")
        questions = await run_text(state, prompt, max_tokens=2500)
        log.info(f"Practice MCQs: {len(questions)} chars")

        # Strip any accidental "Answer:" lines the model may have leaked
        cleaned = _strip_answers(questions)
        state.practice_questions = cleaned
        return cleaned


def _strip_answers(text: str) -> str:
    """Remove any answer-key lines from MCQ output (model leak guard)."""
    answer_re = re.compile(
        r'^\s*(answer\s*[:：]\s*\w.*|correct\s*[:：].*|ans\s*[:：].*)$',
        re.IGNORECASE | re.MULTILINE,
    )
    cleaned = answer_re.sub("", text)
    # Collapse multiple blank lines left by removal
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 10 — INTERACTIVE CHAT AGENT
# ─────────────────────────────────────────────────────────────────────────────

class ChatAgent(BaseAgent):
    name = "ChatAgent"

    SYSTEM_CONTEXT = """You are a helpful study tutor. A student has just received lecture notes and wants to ask questions about the topic.

Use ONLY the information from the lecture notes and transcription provided as context.
Answer clearly and helpfully in the same language the student uses to ask.
If something is not covered in the notes, say so honestly.
Keep answers concise but complete.

LECTURE NOTES:
{notes}

TRANSCRIPTION SUMMARY:
{transcript}
"""

    async def execute(self, state: PipelineState) -> str:
        """Non-interactive execute — just validates context is ready."""
        return "ChatAgent ready"

    async def chat(self, state: PipelineState, user_message: str) -> str:
        """Process one message from the student and return a response."""
        context = self.SYSTEM_CONTEXT.format(
            notes=state.target_notes[:4000],
            transcript=state.transcription[:1500] if state.transcription else "(PDF input — no audio transcript)",
        )

        # Build conversation history
        history_text = ""
        for turn in state.chat_history[-6:]:   # keep last 3 exchanges
            history_text += f"Student: {turn['user']}\nTutor: {turn['assistant']}\n\n"

        prompt = f"""{context}

CONVERSATION SO FAR:
{history_text}
Student: {user_message}
Tutor:"""

        response = await run_text(state, prompt, max_tokens=512)
        response = response.strip()

        # Save to history
        state.chat_history.append({
            "user": user_message,
            "assistant": response,
        })
        return response


def run_chat_loop(state: PipelineState, chat_agent: ChatAgent):
    """Blocking interactive chat loop — runs after pipeline completes."""
    import asyncio

    CYAN  = "\033[96m"
    GREEN = "\033[92m"
    RESET = "\033[0m"
    BOLD  = "\033[1m"

    print()
    print("─" * 60)
    print(f"{BOLD}  📚 SMART NOTES — INTERACTIVE TUTOR{RESET}")
    print(f"  Ask anything about the lecture notes.")
    print(f"  Type {BOLD}'exit'{RESET} or {BOLD}'quit'{RESET} to stop.")
    print("─" * 60)
    print()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        while True:
            try:
                user_input = input(f"{GREEN}You: {RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Exiting chat. Good luck with your studies! 👋")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "bye", "q"):
                print("  Exiting chat. Good luck with your studies! 👋")
                break

            print(f"{CYAN}Tutor: {RESET}", end="", flush=True)
            try:
                response = loop.run_until_complete(
                    chat_agent.chat(state, user_input))
                print(f"{CYAN}{response}{RESET}\n")
            except Exception as e:
                print(f"[Error: {e}]\n")
    finally:
        loop.close()
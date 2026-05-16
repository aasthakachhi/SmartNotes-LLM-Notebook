"""
pdf_frame_embed_patch.py
========================
Drop this helper into pdf_builder.py and call it from wherever your
PDFGenerationAgent renders each VisualArtifact section.

Requires: reportlab (already a project dependency)

Usage inside your artifact rendering loop:
─────────────────────────────────────────
    for art in state.artifacts:
        embed_frame_image(story, art, max_width_cm=DIAGRAM_MAX_W_CM)
        # ... then render structured / rendered_img as before ...
─────────────────────────────────────────
"""

import io
from reportlab.platypus import Image as RLImage, Paragraph, Spacer
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet

_styles = getSampleStyleSheet()

# Artifact types that get a frame image embedded above their content.
# Matches the FRAME_WORTHY set in agents_visual._process_frame.
_FRAME_WORTHY_LABELS = {
    "equation", "geometry", "chart", "flowchart",
    "timeline", "table", "science_diag", "map_desc",
}

_CAPTION_STYLE = _styles["Italic"]   # small grey caption under image


def embed_frame_image(story: list, art, max_width_cm: float = 14.0) -> None:
    """
    If `art.frame_img` is set and the artifact type is content-rich,
    prepend the original video frame as a JPEG above the artifact content.

    Parameters
    ----------
    story        : ReportLab Flowable list being built for the PDF
    art          : VisualArtifact dataclass instance
    max_width_cm : Maximum image width in centimetres (mirrors config.yaml)
    """
    if not art.frame_img:
        return
    if art.atype.value not in _FRAME_WORTHY_LABELS:
        return

    # Load JPEG bytes into a PIL Image to get natural dimensions
    from PIL import Image as PILImage
    pil = PILImage.open(io.BytesIO(art.frame_img))
    nat_w, nat_h = pil.size                      # pixels

    # Scale to max_width_cm, preserving aspect ratio
    max_w_pts = max_width_cm * cm
    scale     = max_w_pts / nat_w
    disp_w    = max_w_pts
    disp_h    = nat_h * scale

    # Wrap bytes in a BytesIO so ReportLab can seek it
    img_buf = io.BytesIO(art.frame_img)
    rl_img  = RLImage(img_buf, width=disp_w, height=disp_h)

    caption_text = (
        f"<i>Frame [{art.timestamp}] — "
        f"{art.atype.value.replace('_', ' ').title()}</i>"
    )
    caption = Paragraph(caption_text, _CAPTION_STYLE)

    story.append(Spacer(1, 0.25 * cm))
    story.append(rl_img)
    story.append(caption)
    story.append(Spacer(1, 0.2 * cm))

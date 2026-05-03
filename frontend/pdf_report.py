"""PDF report generation for evaluation results."""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Palette ────────────────────────────────────────────────────────────────────
DARK_BLUE = colors.HexColor("#1E3A5F")
MID_BLUE = colors.HexColor("#2E6DA4")
LIGHT_BLUE = colors.HexColor("#D6E8F7")
GREEN = colors.HexColor("#2D8653")
AMBER = colors.HexColor("#C47A1E")
RED = colors.HexColor("#B83232")
LIGHT_GREY = colors.HexColor("#F5F5F5")
MID_GREY = colors.HexColor("#CCCCCC")
TEXT = colors.HexColor("#222222")

W, H = A4
MARGIN = 18 * mm


def _score_color(score: float) -> colors.Color:
    if score >= 7.5:
        return GREEN
    if score >= 5:
        return AMBER
    return RED


def _styles():
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20,
                             textColor=DARK_BLUE, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13,
                             textColor=DARK_BLUE, spaceBefore=10, spaceAfter=4),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11,
                             textColor=MID_BLUE, spaceBefore=6, spaceAfter=2),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9,
                               textColor=TEXT, leading=14, spaceAfter=4),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8,
                                textColor=colors.grey, leading=12),
        "mono": ParagraphStyle("mono", fontName="Courier", fontSize=8,
                               textColor=TEXT, leading=12),
        "center": ParagraphStyle("center", fontName="Helvetica", fontSize=9,
                                 alignment=TA_CENTER, textColor=TEXT),
    }


def _score_table(report: dict) -> Table:
    """Score card — 4 or 5 columns depending on whether ownership is present."""
    labels = ["Overall", "Objective", "Code", "UI"]
    keys = ["overall_score", "objective_score", "code_score", "ui_score"]
    if report.get("ownership_score") is not None:
        labels.append("Ownership")
        keys.append("ownership_score")
    header = [Paragraph(f"<b>{l}</b>", ParagraphStyle(
        "sh", fontName="Helvetica-Bold", fontSize=9,
        alignment=TA_CENTER, textColor=colors.white)) for l in labels]
    values = []
    bg_colors = []
    for i, k in enumerate(keys):
        score = report.get(k)
        if score is not None:
            text = f"{score}/10"
            bg = _score_color(float(score))
        else:
            text = "—"
            bg = MID_GREY
        values.append(Paragraph(f"<b>{text}</b>", ParagraphStyle(
            "sv", fontName="Helvetica-Bold", fontSize=16,
            alignment=TA_CENTER, textColor=colors.white)))
        bg_colors.append(("BACKGROUND", (i, 1), (i, 1), bg))

    n_cols = len(labels)
    col_w = (W - 2 * MARGIN) / n_cols
    t = Table([header, values], colWidths=[col_w] * n_cols, rowHeights=[18, 32])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROUNDEDCORNERS", [4]),
    ] + bg_colors
    t.setStyle(TableStyle(style))
    return t


def _provenance_table(data: dict, prov: dict, styles: dict) -> Table:
    snap = data.get("input_snapshot", {})
    rows = [
        ["Evaluation ID", data.get("evaluation_id", "—")],
        ["Triggered by", data.get("triggered_by", "—")],
        ["Created at", data.get("created_at", "—")],
        ["Project", snap.get("project_name", "—")],
        ["Participant", snap.get("participant", "—")],
        ["Repo URL", snap.get("repo_url", "—")],
        ["Commit SHA", snap.get("repo_commit_sha", "—")],
        ["UI URL", snap.get("ui_url", "—") or "—"],
        ["System version", prov.get("system_version", "—")],
    ]
    cell_style = styles["small"]
    table_data = [[Paragraph(f"<b>{r[0]}</b>", cell_style),
                   Paragraph(str(r[1]), styles["mono"])] for r in rows]
    col_w = W - 2 * MARGIN
    t = Table(table_data, colWidths=[col_w * 0.28, col_w * 0.72])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BLUE),
        ("BACKGROUND", (1, 0), (1, -1), LIGHT_GREY),
        ("GRID", (0, 0), (-1, -1), 0.3, MID_GREY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _sub_scores_table(sub_scores: dict, styles: dict) -> Table:
    header = [Paragraph("<b>Dimension</b>", styles["small"]),
              Paragraph("<b>Score</b>", styles["small"]),
              Paragraph("<b>Reasoning</b>", styles["small"])]
    rows = [header]
    for dim, sub in sub_scores.items():
        rows.append([
            Paragraph(dim.replace("_", " ").title(), styles["small"]),
            Paragraph(f"{sub['score']}/10", styles["small"]),
            Paragraph(sub.get("reasoning", "—"), styles["small"]),
        ])
    col_w = W - 2 * MARGIN
    t = Table(rows, colWidths=[col_w * 0.22, col_w * 0.10, col_w * 0.68])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT_GREY, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.3, MID_GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def generate_pdf(
    evaluation_id: str,
    report: dict,
    agents: dict | None = None,
    data: dict | None = None,
    prov: dict | None = None,
) -> bytes:
    """Return a PDF as bytes.

    Args:
        evaluation_id: The evaluation ID.
        report: Aggregated scores dict (overall_score, objective_score, etc.).
        agents: Per-agent analysis dict keyed by agent name.
        data: Full report response from the API (used for provenance/overrides).
        prov: Provenance response from the API.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Evaluation Report – {evaluation_id}",
        author="AI Project Evaluator",
    )

    styles = _styles()
    story = []

    # ── Header ─────────────────────────────────────────────────────────────────
    story.append(Paragraph("AI Project Evaluator", styles["h1"]))
    story.append(Paragraph("Evaluation Report", ParagraphStyle(
        "sub", fontName="Helvetica", fontSize=12, textColor=MID_BLUE, spaceAfter=2)))

    snap = (data or {}).get("input_snapshot", {})
    project_name = snap.get("project_name", "")
    participant = snap.get("participant", "")
    created_at = (data or {}).get("created_at", datetime.utcnow().isoformat())[:19]

    meta_parts = []
    if project_name:
        meta_parts.append(f"<b>Project:</b> {project_name}")
    if participant:
        meta_parts.append(f"<b>Participant:</b> {participant}")
    meta_parts.append(f"<b>ID:</b> {evaluation_id}")
    meta_parts.append(f"<b>Generated:</b> {created_at}")
    story.append(Paragraph("   |   ".join(meta_parts), styles["small"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=DARK_BLUE, spaceAfter=8))

    # ── Scores ─────────────────────────────────────────────────────────────────
    story.append(Paragraph("Scores", styles["h2"]))
    story.append(_score_table(report))
    story.append(Spacer(1, 6))

    # ── Flags ──────────────────────────────────────────────────────────────────
    flags = report.get("flags", [])
    if flags:
        story.append(Paragraph(
            f"⚠ Flags: {', '.join(flags)}",
            ParagraphStyle("flag", fontName="Helvetica-Bold", fontSize=9,
                           textColor=AMBER, spaceAfter=4)))

    # ── Summary ────────────────────────────────────────────────────────────────
    summary = report.get("summary", "")
    if summary:
        story.append(Paragraph("Summary", styles["h2"]))
        story.append(Paragraph(summary, styles["body"]))

    # ── Provenance ─────────────────────────────────────────────────────────────
    if data:
        story.append(Paragraph("Provenance", styles["h2"]))
        story.append(_provenance_table(data, prov or {}, styles))
        story.append(Spacer(1, 4))

    # ── Code Commentary ────────────────────────────────────────────────────────
    commentary = (agents or {}).get("commentary", {})
    if commentary and commentary.get("status") == "ok":
        story.append(Paragraph("Code Commentary", styles["h2"]))

        story.append(Paragraph("<b>Project structure</b>", styles["body"]))
        story.append(Paragraph(commentary.get("structure_overview", ""), styles["body"]))
        story.append(Spacer(1, 4))

        file_summaries = commentary.get("file_summaries", [])
        if file_summaries:
            story.append(Paragraph("<b>Files &amp; classes</b>", styles["body"]))
            fs_header = [
                Paragraph("<b>File</b>", styles["small"]),
                Paragraph("<b>Purpose</b>", styles["small"]),
                Paragraph("<b>Key elements</b>", styles["small"]),
            ]
            fs_rows = [fs_header]
            for fs in file_summaries:
                fs_rows.append([
                    Paragraph(fs.get("path", ""), styles["mono"]),
                    Paragraph(fs.get("purpose", ""), styles["small"]),
                    Paragraph(fs.get("key_elements", ""), styles["small"]),
                ])
            col_w = W - 2 * MARGIN
            fs_table = Table(
                fs_rows,
                colWidths=[col_w * 0.25, col_w * 0.30, col_w * 0.45],
            )
            fs_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT_GREY, colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.3, MID_GREY),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(fs_table)
            story.append(Spacer(1, 6))

        story.append(Paragraph("<b>Execution flow</b>", styles["body"]))
        story.append(Paragraph(commentary.get("execution_flow", ""), styles["body"]))
        story.append(Spacer(1, 4))

    # ── Agent Analysis ─────────────────────────────────────────────────────────
    if agents:
        story.append(Paragraph("Agent Analysis", styles["h2"]))
        for agent_name in ("objective", "code", "ui"):
            result = agents.get(agent_name, {})
            if not result:
                continue
            story.append(Paragraph(
                f"{agent_name.title()} Agent",
                styles["h3"]))
            if result.get("status") == "failed":
                story.append(Paragraph(
                    f"Agent failed: {result.get('error', 'unknown')}",
                    ParagraphStyle("err", fontName="Helvetica", fontSize=9,
                                   textColor=RED)))
                continue
            score = result.get("score", "—")
            conf = result.get("confidence", "—")
            story.append(Paragraph(
                f"<b>Score:</b> {score}/10 &nbsp;&nbsp; <b>Confidence:</b> {conf}",
                styles["body"]))
            reasoning = result.get("reasoning", "")
            if reasoning:
                story.append(Paragraph(f"<b>Reasoning:</b> {reasoning}", styles["body"]))
            if agent_name == "code" and result.get("sub_scores"):
                story.append(Paragraph("Sub-dimension scores:", styles["small"]))
                story.append(_sub_scores_table(result["sub_scores"], styles))
            story.append(Spacer(1, 4))

    # ── Interview Guide ────────────────────────────────────────────────────────
    ownership = (agents or {}).get("ownership", {})
    if ownership and ownership.get("status") == "ok":
        key_decisions = ownership.get("key_decisions", [])
        if key_decisions:
            story.append(Paragraph("Interview Guide", styles["h2"]))
            story.append(Paragraph(
                f"<b>Ownership score:</b> {ownership.get('score')}/10 "
                f"&nbsp;&nbsp; <b>Confidence:</b> {ownership.get('confidence', '—')}",
                styles["body"]))
            if ownership.get("reasoning"):
                story.append(Paragraph(ownership["reasoning"], styles["body"]))
            story.append(Spacer(1, 4))

            guide_header = [
                Paragraph("<b>#</b>", styles["small"]),
                Paragraph("<b>Decision</b>", styles["small"]),
                Paragraph("<b>Signal observed</b>", styles["small"]),
                Paragraph("<b>Question to ask</b>", styles["small"]),
            ]
            guide_rows = [guide_header]
            for i, kd in enumerate(key_decisions, 1):
                guide_rows.append([
                    Paragraph(str(i), styles["small"]),
                    Paragraph(kd.get("decision", ""), styles["small"]),
                    Paragraph(kd.get("ownership_signal", ""), styles["small"]),
                    Paragraph(kd.get("question", ""), styles["small"]),
                ])
            col_w = W - 2 * MARGIN
            guide_table = Table(
                guide_rows,
                colWidths=[col_w * 0.04, col_w * 0.22, col_w * 0.32, col_w * 0.42],
            )
            guide_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT_GREY, colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.3, MID_GREY),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(guide_table)
            story.append(Spacer(1, 4))

    # ── Judge Overrides ────────────────────────────────────────────────────────
    overrides = (data or {}).get("judge_overrides", [])
    if overrides:
        story.append(Paragraph("Judge Overrides", styles["h2"]))
        header = [Paragraph(f"<b>{h}</b>", styles["small"])
                  for h in ["Agent", "Original", "Override", "By", "Reason"]]
        rows = [header]
        for o in overrides:
            rows.append([
                Paragraph(o.get("agent", "—").title(), styles["small"]),
                Paragraph(str(o.get("original_score", "—")), styles["small"]),
                Paragraph(str(o.get("override_score", "—")), styles["small"]),
                Paragraph(o.get("overridden_by", "—"), styles["small"]),
                Paragraph(o.get("reason", "—"), styles["small"]),
            ])
        col_w = W - 2 * MARGIN
        ov_table = Table(rows, colWidths=[
            col_w * 0.12, col_w * 0.10, col_w * 0.10, col_w * 0.18, col_w * 0.50])
        ov_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT_GREY, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.3, MID_GREY),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(ov_table)

    # ── Footer ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GREY))
    story.append(Paragraph(
        f"Generated by AI Project Evaluator · {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
        ParagraphStyle("footer", fontName="Helvetica", fontSize=7,
                       textColor=colors.grey, alignment=TA_CENTER, spaceBefore=4)))

    doc.build(story)
    return buf.getvalue()

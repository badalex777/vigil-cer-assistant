"""
Vigil - Markdown -> Word (.docx) export.

The document generators in outputs.py produce regulator-ready Markdown. This module
renders that same content as professional .docx using python-docx (pure Python, so it
installs via pip on Replit with no system binaries). Content is unchanged - only the
format. Tables, headings, bullet lists, bold spans, the AI-draft disclaimer, and the
PRRC placeholder blocks are all carried across with Vigil styling.

Public API:
    md_to_docx_bytes(markdown_text, title) -> bytes   # one document
"""
import io
import re

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# Vigil palette
NAVY = RGBColor(0x1F, 0x2D, 0x4D)
BROWN = RGBColor(0x4A, 0x3B, 0x2E)
INK = RGBColor(0x1A, 0x1A, 0x1A)
SLATE = RGBColor(0x5C, 0x64, 0x70)


def _set_cell_bg(cell, hex_fill):
    """Shade a table cell background."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _add_runs_with_bold(paragraph, text):
    """Add text to a paragraph, honouring **bold** spans from Markdown."""
    parts = re.split(r"(\*\*.+?\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part:
            paragraph.add_run(part)


def _style_base(doc):
    """Set the default font and heading colours."""
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    for lvl, color, size in [("Heading 1", NAVY, 16), ("Heading 2", NAVY, 13),
                             ("Heading 3", BROWN, 11.5)]:
        try:
            stl = doc.styles[lvl]
            stl.font.color.rgb = color
            stl.font.size = Pt(size)
            stl.font.name = "Calibri"
        except KeyError:
            pass


def _is_table_sep(line):
    return bool(re.match(r"^\s*\|?[\s:|-]+\|?\s*$", line)) and "-" in line


def _split_row(line):
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def md_to_docx_bytes(markdown_text: str, title: str = "") -> bytes:
    """Render Vigil Markdown as a styled .docx and return the file bytes."""
    doc = Document()
    _style_base(doc)
    for section in doc.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)

    lines = markdown_text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # blank line
        if not stripped:
            i += 1
            continue

        # horizontal rule
        if re.match(r"^\s*([-*_])\1{2,}\s*$", stripped):
            i += 1
            continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            h = doc.add_heading(level=min(level, 3))
            _add_runs_with_bold(h, text)
            i += 1
            continue

        # tables: a header row followed by a separator row
        if "|" in line and i + 1 < n and _is_table_sep(lines[i + 1]):
            header = _split_row(line)
            rows = []
            j = i + 2
            while j < n and "|" in lines[j] and lines[j].strip():
                rows.append(_split_row(lines[j]))
                j += 1
            ncols = len(header)
            table = doc.add_table(rows=1, cols=ncols)
            table.alignment = WD_TABLE_ALIGNMENT.LEFT
            table.style = "Table Grid"
            hdr_cells = table.rows[0].cells
            for k in range(ncols):
                hdr_cells[k].text = ""
                p = hdr_cells[k].paragraphs[0]
                _add_runs_with_bold(p, header[k] if k < len(header) else "")
                for run in p.runs:
                    run.bold = True
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                _set_cell_bg(hdr_cells[k], "1F2D4D")
            for row in rows:
                cells = table.add_row().cells
                for k in range(ncols):
                    cells[k].text = ""
                    p = cells[k].paragraphs[0]
                    _add_runs_with_bold(p, row[k] if k < len(row) else "")
            doc.add_paragraph()
            i = j
            continue

        # blockquote (used for the disclaimer / notes)
        if stripped.startswith(">"):
            text = stripped.lstrip(">").strip()
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.25)
            _add_runs_with_bold(p, text)
            for run in p.runs:
                run.font.color.rgb = BROWN
                run.italic = True
            i += 1
            continue

        # bullet list
        if re.match(r"^\s*[-*]\s+", line):
            text = re.sub(r"^\s*[-*]\s+", "", line)
            p = doc.add_paragraph(style="List Bullet")
            _add_runs_with_bold(p, text)
            i += 1
            continue

        # numbered list
        if re.match(r"^\s*\d+\.\s+", line):
            text = re.sub(r"^\s*\d+\.\s+", "", line)
            p = doc.add_paragraph(style="List Number")
            _add_runs_with_bold(p, text)
            i += 1
            continue

        # PRRC placeholder lines often look like "**[PRRC ...]**" - keep them bold/brown
        p = doc.add_paragraph()
        _add_runs_with_bold(p, stripped)
        if "PRRC" in stripped and "[" in stripped:
            for run in p.runs:
                run.font.color.rgb = BROWN
        i += 1

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

"""Render the asynckb code change notes as a formatted Word document."""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/kes-testing/asynckb代码修改说明.md"
OUTPUT = ROOT / "docs/kes-testing/asynckb代码修改说明.docx"


def set_font(run, name, size, *, bold=False, color=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)


def shade(cell, fill):
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def add_table(document, rows):
    table = document.add_table(rows=0, cols=len(rows[0]))
    table.style = "Table Grid"
    table.autofit = True
    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for cell, value in zip(cells, values):
            cell.text = value.strip()
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    set_font(run, "宋体", 9,
                             bold=(row_index == 0),
                             color=(255, 255, 255) if row_index == 0 else None)
            if row_index == 0:
                shade(cell, "1F4E78")
            elif row_index % 2 == 0:
                shade(cell, "EAF1F8")
    document.add_paragraph()


def render():
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.2)

    normal = document.styles["Normal"]
    normal.font.name = "宋体"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(10)
    for style_name, size in (("Heading 1", 16), ("Heading 2", 13),
                             ("Heading 3", 11)):
        style = document.styles[style_name]
        style.font.name = "黑体"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(31, 78, 121)

    first_title = True
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            block = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index])
                index += 1
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Cm(0.35)
            paragraph.paragraph_format.right_indent = Cm(0.2)
            paragraph.paragraph_format.space_before = Pt(3)
            paragraph.paragraph_format.space_after = Pt(8)
            for code_index, text in enumerate(block):
                run = paragraph.add_run(text)
                set_font(run, "Consolas", 8.5)
                if code_index < len(block) - 1:
                    run.add_break()
            properties = paragraph._p.get_or_add_pPr()
            fill = OxmlElement("w:shd")
            fill.set(qn("w:fill"), "F2F4F7")
            properties.append(fill)
        elif line.startswith("|"):
            table_rows = []
            while index < len(lines) and lines[index].startswith("|"):
                values = [value.strip() for value in lines[index].strip("|").split("|")]
                if not all(set(value) <= {"-", ":", " "} for value in values):
                    table_rows.append(values)
                index += 1
            if table_rows:
                add_table(document, table_rows)
            continue
        elif line.startswith("# "):
            title = line[2:].strip()
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_before = Pt(36 if first_title else 12)
            run = paragraph.add_run(title)
            set_font(run, "黑体", 22 if first_title else 16,
                     bold=True, color=(31, 78, 121))
            first_title = False
        elif line.startswith("## "):
            paragraph = document.add_heading(line[3:].strip(), level=1)
            paragraph.paragraph_format.keep_with_next = True
        elif line.startswith("### "):
            paragraph = document.add_heading(line[4:].strip(), level=2)
            paragraph.paragraph_format.keep_with_next = True
        elif line.startswith("- "):
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.add_run(line[2:].strip())
        else:
            paragraph = document.add_paragraph(line)
            paragraph.paragraph_format.space_after = Pt(6)
        index += 1

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("asynckb 代码修改说明  |  2026-11-18")
    set_font(run, "宋体", 8, color=(100, 100, 100))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    render()

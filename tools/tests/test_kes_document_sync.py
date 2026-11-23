"""Pruning must preserve adjacent content and the supplied document styles."""

import importlib.util
from pathlib import Path
import unittest

from docx import Document
from docx.oxml import OxmlElement


class DocumentSyncTests(unittest.TestCase):
    def test_removes_only_retired_point_and_its_body(self):
        path = Path(__file__).resolve().parents[1] / "sync_kes_test_docs.py"
        self.assertTrue(path.exists(), "document synchronizer not implemented")
        spec = importlib.util.spec_from_file_location("doc_sync", path)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        doc = Document()
        doc.add_heading("8 模块", level=1)
        doc.add_heading("KB-CONN-001 保留", level=4)
        doc.add_paragraph("保留正文")
        doc.add_heading("KB-CONN-002 删除", level=4)
        doc.add_paragraph("删除正文")
        doc.add_heading("8.2 下个模块", level=2)
        doc.add_heading("KB-TYPE-001 保留", level=4)
        doc.add_paragraph("另一段正文")
        tool.prune_points(doc, {"KB-CONN-002"})
        self.assertEqual([p.text for p in doc.paragraphs], [
            "8 模块", "KB-CONN-001 保留", "保留正文", "8.2 下个模块",
            "KB-TYPE-001 保留", "另一段正文"])
        self.assertEqual(doc.paragraphs[1].style.name, "Heading 4")

    def test_replacing_text_retains_run_format_and_paragraph_style(self):
        path = Path(__file__).resolve().parents[1] / "sync_kes_test_docs.py"
        self.assertTrue(path.exists(), "document synchronizer not implemented")
        spec = importlib.util.spec_from_file_location("doc_sync_replace", path)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        doc = Document()
        paragraph = doc.add_heading("旧文字", level=2)
        paragraph.runs[0].bold = True
        tool.set_text(paragraph, "新文字")
        self.assertEqual(paragraph.text, "新文字")
        self.assertEqual(paragraph.style.name, "Heading 2")
        self.assertTrue(paragraph.runs[0].bold)

    def test_replaces_hyperlinked_contents_entry_without_duplication(self):
        from tools import sync_kes_test_docs as tool
        doc = Document()
        paragraph = doc.add_paragraph()
        hyperlink = OxmlElement("w:hyperlink")
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "旧目录文字"
        run.append(text)
        hyperlink.append(run)
        paragraph._p.append(hyperlink)
        tool.set_text(paragraph, "新目录文字")
        self.assertEqual(paragraph.text, "新目录文字")


if __name__ == "__main__":
    unittest.main()

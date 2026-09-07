"""Regression tests for field annotation structural safety."""

from __future__ import annotations

import unittest

from .fields import annotate_fields
from .llm import HeuristicBatchNamer
from .syntax_check import validate_latex
from .reconcile import field_segments
from .tex_tables import transform_tex


class FieldAnnotationTests(unittest.TestCase):
    def test_multiline_field_keeps_every_paragraph_inside_value(self) -> None:
        source = (
            "\\begin{tabular}{|p{2cm}|p{10cm}|}\n"
            "Label & Details\\\\\\hline\n"
            "Investigation &\n"
            "% #VALUE_ID: LEX-P0007-V0005\n"
            "% #FIELD_VALUE: Investigation\n"
            "\\fieldvalue{First paragraph.\\par\n"
            "Second paragraph with \\textbf{nested {content}}.\\par\n"
            "Final paragraph with \\{escaped braces\\}.}\n"
            "\\\\\\hline\n"
            "Result &\n"
            "% #VALUE_ID: LEX-P0007-V0006\n"
            "% #FIELD_VALUE: Result\n"
            "\\fieldvalue{Unchanged}\\\\\n"
            "\\end{tabular}\n"
        )
        annotated, records, _ = annotate_fields(
            transform_tex(source, anchor=False), namer=HeuristicBatchNamer()
        )
        before, after = field_segments(source), field_segments(annotated)
        self.assertEqual(set(before), set(after))
        for fid in before:
            self.assertEqual(before[fid]["payload"], after[fid]["payload"])
        self.assertIn("Final paragraph", records[0].value)
        self.assertIn(r"\hwfield{LEX-P0007-V0005}{\fieldvalue{First", annotated)
        self.assertEqual([], [issue for issue in validate_latex(
            annotated, require_sync_safe=False) if issue.severity == "error"])

    def test_tabularnewline_stays_outside_field_wrapper(self) -> None:
        source = (
            "\\begin{tabular}{|l|l|}\n"
            "\\SA{}plain &\n"
            "% #VALUE_ID: LEX-P0001-V0001\n"
            "% #FIELD_VALUE: left\n"
            "\\SA{}\\fieldvalue{one}\\tabularnewline\n"
            "\\SA{}plain &\n"
            "% #VALUE_ID: LEX-P0001-V0002\n"
            "% #FIELD_VALUE: right\n"
            "\\SA{}\\fieldvalue{two}\\tabularnewline\n"
            "\\end{tabular}\n"
        )

        annotated, records, _ = annotate_fields(
            source, namer=HeuristicBatchNamer()
        )
        errors = [
            issue for issue in validate_latex(annotated, require_sync_safe=False)
            if issue.severity == "error"
        ]

        self.assertEqual(2, len(records))
        self.assertNotIn(r"\tabularnewline}", annotated)
        self.assertEqual([], errors)

    def test_trailing_backslash_does_not_escape_hwfield_closing_brace(self) -> None:
        source = (
            "\\begin{tabular}{|l|}\n"
            "% #VALUE_ID: LEX-P0001-V0001\n"
            "% #FIELD_VALUE: start time\n"
            "\\fieldvalue{11:22}\\ \\textasciitilde\\\n"
            "\\\\ \\hline\n"
            "\\end{tabular}\n"
        )

        annotated, records, _ = annotate_fields(
            source, namer=HeuristicBatchNamer()
        )
        errors = [
            issue for issue in validate_latex(annotated, require_sync_safe=False)
            if issue.severity == "error"
        ]

        self.assertEqual(1, len(records))
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()

"""Regression tests for field annotation structural safety."""

from __future__ import annotations

import unittest

from .fields import annotate_fields
from .llm import HeuristicBatchNamer
from .syntax_check import validate_latex


class FieldAnnotationTests(unittest.TestCase):
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

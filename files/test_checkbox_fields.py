"""Regression tests for editable checkbox extraction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .json_extractor import extract_fields
from .preamble import BLOCK
from .patch_lexoid_checkbox_prompt import (
    CHECKBOX_RULES,
    NEW_TABLE_RULE,
    patch_source,
)


class CheckboxFieldTests(unittest.TestCase):
    def test_checkbox_macro_uses_state_instead_of_raw_square(self) -> None:
        self.assertIn(r"\checkboxfield", BLOCK)
        self.assertNotIn(r"\square", BLOCK)

    def test_lexoid_rule_prefers_plain_tabular(self) -> None:
        self.assertIn("prefer plain tabular", NEW_TABLE_RULE)
        self.assertIn("Do not use X columns", NEW_TABLE_RULE)

    def test_prompt_patch_tolerates_upstream_table_wording_change(self) -> None:
        source = r'''PROMPT = r"""
- Tables: use whichever LaTeX environment best preserves the source layout.
- Handwritten-entry annotation is MANDATORY:
"""
PREAMBLE = r"""
\newcommand{{\handwritten}}[1]{{#1}}
"""
'''
        patched = patch_source(source)
        self.assertIn(CHECKBOX_RULES.strip(), patched)
        self.assertIn(NEW_TABLE_RULE.strip(), patched)
        self.assertIn(r"\newcommand{{\checkboxfield}}", patched)
        self.assertNotIn("use whichever LaTeX environment", patched)
        self.assertEqual(patch_source(patched), patched)

    def test_prompt_patch_rejects_ambiguous_table_rule(self) -> None:
        source = r'''- Tables: first rule
- Tables: second rule
- Handwritten-entry annotation is MANDATORY:
\newcommand{{\handwritten}}[1]{{#1}}
'''
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            patch_source(source)

    def test_checked_and_unchecked_are_boolean_fields(self) -> None:
        source = (
            "% #VALUE_ID: LEX-P0001-C0001\n"
            "% #FIELD_VALUE: 正常检验\n"
            "\\checkboxfield{LEX-P0001-C0001}{checked}{正常检验}\n"
            "% #VALUE_ID: LEX-P0001-C0002\n"
            "% #FIELD_VALUE: 复检\n"
            "\\checkboxfield{LEX-P0001-C0002}{unchecked}{复检}\n"
            "% LEXOID_PAGE_COMPLETED: 1/1\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkbox.tex"
            path.write_text(source, "utf-8")
            report = extract_fields(path)
        self.assertEqual(len(report.fields), 2)
        self.assertEqual(
            [(f.field_type, f.checked, f.value) for f in report.fields],
            [("checkbox", True, "checked"),
             ("checkbox", False, "unchecked")],
        )
        self.assertEqual([f.label for f in report.fields], ["正常检验", "复检"])


if __name__ == "__main__":
    unittest.main()

"""Physical PDF pagination regressions; these tests run the real XeLaTeX engine."""

import json
import shutil

import pytest

from . import cli


SOURCE = r"""\documentclass{article}
\usepackage[a4paper,margin=16mm]{geometry}
\begin{document}
Company header\par
\title{Record {A}}
\date{}
\maketitle
First page body.
% LEXOID_PAGE_COMPLETED: 1/2
\newpage
Second page body.
% LEXOID_PAGE_COMPLETED: 2/2
\end{document}
"""


def evidence():
    return {"schema": "recognition/v1", "pages": [
        {"page": 1, "render": {"dpi": 72, "width": 842, "height": 595, "rotation": 90}},
        {"page": 2, "render": {"dpi": 72, "width": 595, "height": 842, "rotation": 0}},
    ]}


def test_title_and_mixed_orientation_have_one_output_page_per_source(tmp_path):
    from .page_layout import prepare_layout

    if not shutil.which("xelatex"):
        pytest.skip("XeLaTeX is required")
    original = tmp_path / "original.tex"
    original.write_text(SOURCE)
    ok, log = cli._compile_latex(original, tmp_path, "xelatex", 60)
    assert ok and "(3 pages)" in log

    source, report = prepare_layout(SOURCE, evidence())
    target = tmp_path / "fixed.tex"
    target.write_text(source)
    ok, log = cli._compile_latex(target, tmp_path, "xelatex", 60, layout_report=report)
    assert ok, log
    assert report["ok"] is True
    assert report["actual_pages"] == 2
    assert report["page_map"] == [
        {"source_page": 1, "start": 1, "end": 1},
        {"source_page": 2, "start": 2, "end": 2},
    ]
    assert report["actual_sizes"] == pytest.approx([(842, 595), (595, 842)], abs=1)
    assert target.with_suffix(".layout.pdf").is_file()


def test_extra_break_is_reported_but_does_not_fail_compilation(tmp_path):
    from .page_layout import prepare_layout

    if not shutil.which("xelatex"):
        pytest.skip("XeLaTeX is required")
    src = SOURCE.replace("First page body.", "First page body.\\newpage\nUnexpected spill.")
    source, report = prepare_layout(src, evidence())
    target = tmp_path / "overflow.tex"
    target.write_text(source)
    ok, log = cli._compile_latex(target, tmp_path, "xelatex", 60, layout_report=report)
    assert ok
    assert report["actual_pages"] == 3
    assert report["page_map"][0] == {"source_page": 1, "start": 1, "end": 2}
    assert report["ok"] is False
    assert report["errors"]


@pytest.mark.parametrize("author", ["Alice", r"Alice \and Bob"])
def test_layout_preserves_explicit_preamble_title_authors_and_date(tmp_path, author):
    import pypdfium2 as pdfium
    from .page_layout import prepare_layout

    src = SOURCE.replace(r"\begin{document}",
        "\\title{Record {A}}\n\\author{" + author + "}\n\\date{2026-09-05}\n\\begin{document}")
    src = src.replace("\\title{Record {A}}\n\\date{}\n", "")
    fixed, report = prepare_layout(src, evidence())
    target = tmp_path / "metadata.tex"
    target.write_text(fixed)
    ok, log = cli._compile_latex(target, tmp_path, "xelatex", 60, layout_report=report)
    assert ok, log
    document = pdfium.PdfDocument(str(target.with_suffix(".layout.pdf")))
    try:
        page = document[0]
        textpage = page.get_textpage()
        text = textpage.get_text_bounded()
        assert "Record A" in text and "Alice" in text and "2026-09-05" in text
        if "Bob" in author:
            assert "Bob" in text
        textpage.close()
        page.close()
    finally:
        document.close()


def test_same_total_with_wrong_page_assignment_is_rejected():
    from .page_layout import validate_page_map

    errors = validate_page_map(2, [(1, "start", 1), (1, "end", 2),
                                   (2, "start", 2), (2, "end", 2)], 2)
    assert errors


def test_layout_preserves_field_bytes_and_is_repeatable():
    from .page_layout import prepare_layout

    field = "% #VALUE_ID: LEX-P0001-V0001\n% #HANDWRITTEN: A\n\\fieldvalue{A}"
    source = SOURCE.replace("First page body.", field)
    first, _ = prepare_layout(source, evidence())
    second, _ = prepare_layout(first, evidence())
    assert field in first
    assert second == first


def test_evidence_pages_must_match_tex():
    from .page_layout import prepare_layout

    wrong = evidence()
    wrong["pages"].reverse()
    with pytest.raises(ValueError, match="page"):
        prepare_layout(SOURCE, wrong)


def test_optimizer_enforces_layout_with_existing_cached_tex(tmp_path):
    source = tmp_path / "input.tex"
    source.write_text(SOURCE)
    ev = tmp_path / "evidence.json"
    ev.write_text(json.dumps(evidence()))
    report = tmp_path / "report.json"
    result = cli.main(["optimise", str(source), "-o", str(tmp_path / "out.tex"),
        "--no-llm", "--page-layout-evidence", str(ev), "--report", str(report)])
    assert result == 0
    details = json.loads(report.read_text())
    assert details["compile_check"]["passes"] == 2
    assert details["layout_check"]["actual_pages"] == 2
    assert details["layout_check"]["ok"] is True
    assert details["tables"] == 0


def test_optimizer_keeps_pagination_findings_advisory(tmp_path):
    source = tmp_path / "input.tex"
    source.write_text(SOURCE.replace("First page body.", "Before\\newpage\nAfter"))
    ev = tmp_path / "evidence.json"
    ev.write_text(json.dumps(evidence()))
    report = tmp_path / "report.json"
    result = cli.main(["optimise", str(source), "-o", str(tmp_path / "out.tex"),
        "--no-llm", "--page-layout-evidence", str(ev), "--report", str(report)])
    assert result == 0
    details = json.loads(report.read_text())
    assert details["layout_check"]["ok"] is False
    assert details["layout_check"]["actual_pages"] == 3
    assert details["layout_check"]["attempts"] == 1


def test_pipeline_accepts_compile_success_without_strict_layout_validation(tmp_path):
    from .stages import StageCommand, _validate

    tex = tmp_path / "output.tex"
    tex.write_text("% LEXOID_PAGE_COMPLETED: 1/1\n")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"compile_check": {"ok": True, "passes": 2}}))
    stage = StageCommand("optimise", [], (), (tex, report), "test")
    _validate(stage, 1)

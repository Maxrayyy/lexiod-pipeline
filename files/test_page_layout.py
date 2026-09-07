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


def test_landscape_overflow_keeps_size_until_next_source_page(tmp_path):
    from .page_layout import prepare_layout

    if not shutil.which("xelatex"):
        pytest.skip("XeLaTeX is required")
    src = SOURCE.replace("First page body.",
        r"First page body.\newpage\noindent\makebox[\linewidth][r]{RIGHT EDGE}")
    source, report = prepare_layout(src, evidence())
    target = tmp_path / "landscape-spill.tex"
    target.write_text(source)
    ok, log = cli._compile_latex(target, tmp_path, "xelatex", 60, layout_report=report)
    assert ok, log
    assert report["actual_sizes"] == pytest.approx([(842, 595), (842, 595), (595, 842)], abs=1)
    assert report["outside_pages"] == []


@pytest.mark.parametrize("header", ["", r"\section*{Process log}\noindent Exported: 2026-09-07\par\vspace{20pt}"])
def test_tall_two_column_log_has_no_blank_or_clipped_page(tmp_path, header):
    import pypdfium2 as pdfium
    from .page_layout import prepare_layout

    if not shutil.which("xelatex"):
        pytest.skip("XeLaTeX is required")
    rows = "\n".join(rf"18:{i:02}:00 & Event {i}\\" for i in range(40))
    column = (r"\begin{minipage}[t]{0.47\linewidth}"
              r"\begin{tabular}{@{}ll@{}}" + rows +
              r"\end{tabular}\end{minipage}")
    body = header + r"\renewcommand{\arraystretch}{1.2}\noindent" + column + r"\hfill" + column + "\n\n\\hfill 5/8\n"
    src = SOURCE.replace("First page body.", body).replace(
        "Company header\\par\n\\title{Record {A}}\n\\date{}\n\\maketitle\n", "")
    source, report = prepare_layout(src, evidence())
    target = tmp_path / "two-column-log.tex"
    target.write_text(source)
    ok, log = cli._compile_latex(target, tmp_path, "xelatex", 60, layout_report=report)
    assert ok, log
    assert report["actual_pages"] == 2
    assert report["outside_pages"] == []
    doc = pdfium.PdfDocument(str(target.with_suffix(".layout.pdf")))
    try:
        page = doc[0]
        textpage = page.get_textpage()
        text = textpage.get_text_bounded()
        for i in range(40):
            assert text.count(f"18:{i:02}:00") == 2
        assert "5/8" in text
        textpage.close()
        page.close()
    finally:
        doc.close()


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


def test_dimension_check_covers_spill_pages_when_page_count_differs(tmp_path):
    import pypdfium2 as pdfium
    from .page_layout import inspect_layout

    pdf = tmp_path / "wrong-spill.pdf"
    doc = pdfium.PdfDocument.new()
    try:
        for width, height in [(842, 595), (595, 842), (595, 842)]:
            page = doc.new_page(width, height)
            page.close()
        doc.save(str(pdf))
    finally:
        doc.close()
    pdf.with_suffix(".lxp").write_text("1,start,1\n1,end,2\n2,start,3\n2,end,3\n")
    report = {"expected_pages": 2, "expected_sizes": [(842, 595), (595, 842)]}
    inspect_layout(pdf, report)
    assert "Output page dimensions differ from source reading orientation" in report["errors"]


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

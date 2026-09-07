import json

import pytest

from .page_fallback import compile_page, upgrade_pages
from .test_page_fallback import sample


@pytest.mark.parametrize("body", [
    r"\fbox{\begin{minipage}{3cm}\centering Original\\\hline Copy\end{minipage}}",
    r"\begin{tikzpicture}\draw (0,0) rectangle (1,1);\end{tikzpicture}",
    r"\begin{tabular}{p{2cm}p{2cm}}a & \raggedleft b\\\hline c & d\\\end{tabular}",
])
def test_known_local_errors_are_repaired_before_any_paid_upgrade(tmp_path, body):
    source, raw, evidence = sample(tmp_path)
    original = (r"\documentclass{article}\begin{document}" + "\n" + body +
                "\n% LEXOID_PAGE_COMPLETED: 1/3\n"
                "healthy\n% LEXOID_PAGE_COMPLETED: 2/3\n"
                "healthy\n% LEXOID_PAGE_COMPLETED: 3/3\n\\end{document}\n")
    assert any(i.severity == "error" for i in compile_page(original, tmp_path / "before"))
    raw.write_text(original)
    calls = []

    def recognize(*args):
        calls.append(1)
        raise AssertionError("Local syntax must not trigger model recognition")

    report = upgrade_pages(source, raw, evidence, tmp_path / "cache", "gpt-5.6-sol",
                           "gpt-6-astra", recognize=recognize, renderer=lambda *args: None)
    assert calls == []
    assert report["upgraded"] == []
    assert report["local_repaired"] == [1]
    assert not compile_page(raw.read_text(), tmp_path / "after")
    checkpoints = list((tmp_path / "cache").rglob("local-repair.json"))
    assert checkpoints
    audit = json.loads(checkpoints[0].read_text())
    assert audit["rules"] and audit["original_sha256"] != audit["normalized_sha256"]


def test_shared_normalization_is_idempotent_and_keeps_fields_and_nested_tables():
    from .local_tex import normalize_tex

    fields = "% #VALUE_ID: LEX-P0001-V0001\n% #FIELD_VALUE: Original label\n\\fieldvalue{23.5}"
    table = r"\begin{tabular}{ll}a & \begin{tabular}{l}b\\\hline c\end{tabular}\\\hline\end{tabular}"
    src = (r"\documentclass{article}\begin{document}" + "\n" + fields + table +
           "\n% LEXOID_PAGE_COMPLETED: 1/1\n\\end{document}\n")
    fixed, changes = normalize_tex(src)
    assert fields in fixed and table in fixed
    assert changes
    assert normalize_tex(fixed)[0] == fixed


def test_dependencies_discovered_on_later_page_are_added_to_final_preamble(tmp_path):
    source, raw, evidence = sample(tmp_path)
    original = (r"\documentclass{article}\begin{document}" +
        "\nfirst\n% LEXOID_PAGE_COMPLETED: 1/3\n" +
        r"\begin{tikzpicture}\draw (0,0) rectangle (1,1);\end{tikzpicture}" +
        "\n% LEXOID_PAGE_COMPLETED: 2/3\nlast\n% LEXOID_PAGE_COMPLETED: 3/3\n\\end{document}\n")
    raw.write_text(original)
    calls = []
    result = upgrade_pages(source, raw, evidence, tmp_path / "cache", "gpt-5.6-sol",
                           "gpt-6-astra", recognize=lambda *args: calls.append(1),
                           renderer=lambda *args: None)
    assert calls == [] and result["unresolved"] == []
    assert not compile_page(raw.read_text(), tmp_path / "final")

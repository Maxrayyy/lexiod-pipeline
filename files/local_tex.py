"""Shared, deterministic repairs before vision escalation and final optimization."""

from __future__ import annotations

import re

from pylatexenc.latexwalker import LatexWalker, LatexEnvironmentNode, LatexMacroNode

from .syntax_check import _mask_verbatim
from .syntax_repair import (normalize_control_word_boundaries, normalize_math_blank_lines,
                            normalize_multicolumn_linebreaks, normalize_text_mode_math_symbols)
from .tex_tables import iter_structural, mask_comments, split_align_body


VERSION = "local-tex-v1"
SUPPORT_BEGIN = "% >>> lexoid local support >>>"
SUPPORT_END = "% <<< lexoid local support <<<"


def normalize_panel_rules(source):
    """A hline directly inside a minipage is a visible rule, not a table row."""
    edits = []

    def visit(nodes, environment=""):
        for node in nodes or []:
            if isinstance(node, LatexEnvironmentNode):
                visit(node.nodelist, node.environmentname)
            elif isinstance(node, LatexMacroNode):
                if node.macroname == "hline" and environment == "minipage":
                    edits.append((node.pos, node.pos + len(r"\hline")))
                if node.macroname not in {"newcommand", "renewcommand", "providecommand", "def"}:
                    for arg in getattr(node.nodeargd, "argnlist", []) or []:
                        if arg is not None:
                            visit(getattr(arg, "nodelist", []), environment)
            else:
                visit(getattr(node, "nodelist", []), environment)

    # Mask comments and verbatim text but retain offsets for exact local edits.
    nodes, _, _ = LatexWalker(_mask_verbatim(mask_comments(source))).get_latex_nodes()
    visit(nodes)
    for start, end in reversed(edits):
        source = source[:start] + r"\par\noindent\rule{\linewidth}{0.4pt}\par " + source[end:]
    return source, len(edits)


def normalize_table_row_endings(source):
    """Restore row endings overridden by an ungrouped paragraph alignment command."""
    edits = []

    def direct_alignment(text):
        depth = 0
        for token in re.finditer(r"\\[a-zA-Z@]+|\\[\s\S]|[{}]", mask_comments(text)):
            value = token.group()
            if value == "{":
                depth += 1
            elif value == "}":
                depth -= 1
            elif depth == 0 and value in {r"\centering", r"\raggedleft", r"\raggedright"}:
                return True
        return False

    def scan(segment, base=0):
        tokens = iter(iter_structural(mask_comments(segment)))
        for begin in tokens:
            if begin.kind != "align_begin":
                continue
            end = next((t for t in tokens if t.kind == "align_end"), None)
            if end is None:
                continue
            body = segment[begin.body_start:end.start]
            offset = base + begin.body_start
            for row in split_align_body(body):
                for cell in row.cells:
                    scan(cell.text, offset)
                    if cell.sep.startswith(r"\\") and direct_alignment(cell.text):
                        edits.append((offset + len(cell.text), offset + len(cell.text) + 2))
                    offset += len(cell.text) + len(cell.sep)

    scan(source)
    for start, end in sorted(edits, reverse=True):
        source = source[:start] + r"\tabularnewline" + source[end:]
    return source, len(edits)


PACKAGE_USES = {
    "array": r"\\(?:arraybackslash|newcolumntype)\b|\\begin\{array\}",
    "amsmath": r"\\(?:text|overset|underset|dfrac|tfrac)\b|\\begin\{(?:aligned|align\*?|gather\*?)\}",
    "amssymb": r"\\(?:diagup|diagdown|checkmark|square|boxtimes)\b",
    "graphicx": r"\\(?:includegraphics|resizebox|rotatebox|scalebox)\b",
    "multirow": r"\\multirow\b",
    "booktabs": r"\\(?:toprule|midrule|bottomrule|cmidrule)\b",
    "makecell": r"\\(?:makecell|thead)\b",
    "tabularx": r"\\begin\{tabularx\}",
    "longtable": r"\\begin\{longtable\}",
    "tikz": r"\\begin\{tikzpicture\}|\\tikz\b",
    "ragged2e": r"\\(?:RaggedRight|RaggedLeft|Centering|justifying)\b",
    "enumitem": r"\\setlist\b",
    "xcolor": r"\\(?:textcolor|color|definecolor)\b",
    "ulem": r"\\sout\b",
}


def inject_support(source):
    """Add only known, missing dependencies to a complete document's preamble."""
    original = source
    prior = re.search(re.escape(SUPPORT_BEGIN) + r"(.*?)" + re.escape(SUPPORT_END), source, re.S)
    prior_support = prior[1] if prior else ""
    source = re.sub(re.escape(SUPPORT_BEGIN) + r".*?" + re.escape(SUPPORT_END) + r"\n?",
                    "", source, flags=re.S)
    masked = _mask_verbatim(mask_comments(source))
    begin = re.search(r"\\begin\{document\}", masked)
    if begin is None:
        return original, 0
    preamble = masked[:begin.start()]
    packages = {part.strip() for m in re.finditer(
        r"\\(?:usepackage|RequirePackage)(?:\[[^]]*\])?\{([^}]+)\}", preamble)
        for part in m[1].split(",")}
    lines = []
    for package, pattern in PACKAGE_USES.items():
        if package not in packages and (re.search(pattern, masked)
                or rf"\@ifpackageloaded{{{package}}}" in prior_support):
            options = "[normalem]" if package == "ulem" else ""
            lines.append(rf"\@ifpackageloaded{{{package}}}{{}}{{\RequirePackage{options}{{{package}}}}}")
    for macro in ("fieldvalue", "handwritten"):
        defined = re.search(r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{?\\" + macro + r"\b|\\def\s*\\" + macro + r"\b", preamble)
        if not defined and (re.search(r"\\" + macro + r"\b", masked[begin.end():])
                or rf"\providecommand{{\{macro}}}" in prior_support):
            lines.append(rf"\providecommand{{\{macro}}}[1]{{#1}}")
    if lines:
        block = (SUPPORT_BEGIN + "\n\\makeatletter\n" + "\n".join(lines) +
                 "\n\\makeatother\n" + SUPPORT_END + "\n")
        source = source[:begin.start()] + block + source[begin.start():]
    return source, int(source != original)


def normalize_tex(source):
    changes = {}
    for name, operation in (
        ("control_word_boundaries", normalize_control_word_boundaries),
        ("text_math_symbols", normalize_text_mode_math_symbols),
        ("multicolumn_linebreaks", normalize_multicolumn_linebreaks),
        ("math_blank_lines", normalize_math_blank_lines),
        ("panel_rules", normalize_panel_rules),
        ("table_row_endings", normalize_table_row_endings),
        ("missing_support", inject_support),
    ):
        source, count = operation(source)
        if count:
            changes[name] = count
    return source, changes

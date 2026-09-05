"""Inject the macros the optimiser relies on, idempotently and without touching
anything the converter already put in the preamble."""

from __future__ import annotations

import re

MARK_BEGIN = "% >>> lexoid-texopt (auto-generated, safe to regenerate) >>>"
MARK_END = "% <<< lexoid-texopt <<<"

# NOTE on \SA:
#   \leavevmode\hbox{}  ->  zero width/height/depth, no glue, no mode change.
#   * In l/c/r columns we are already in restricted horizontal mode -> \leavevmode is
#     a no-op.
#   * In p/m/b columns \leavevmode starts the paragraph exactly as the first character
#     would have; \parindent is 0pt there because of \@parboxrestore.
#   The empty \hbox is what forces SyncTeX to open a box record on THIS source line.
BLOCK = r"""
%% --- sync anchor: zero-size box that gives SyncTeX a per-cell record -------------
\providecommand{\SA}{\leavevmode\hbox{}\relax}

%% --- handwritten field: renders #2 unchanged, registers #1 ----------------------
\makeatletter
\newif\ifhwf@dest   \hwf@desttrue      % set \hwf@destfalse to disable PDF anchors
\newwrite\hwf@out
\immediate\openout\hwf@out=\jobname.hwf\relax
\providecommand{\hwfield}[2]{%
  \SA%
  \begingroup
    \write\hwf@out{#1\string\t\noexpand\thepage}%  page = OUTPUT pdf page, at shipout
  \endgroup
  \ifhwf@dest\@ifundefined{hypertarget}{}{\hypertarget{fld:#1}{}}\fi
  #2%
}
%% --- editable checkbox: stable ID + boolean state + separate visible label -------
%% State must be exactly `checked` or `unchecked`; JSON extraction records it as a
%% boolean.  The box is drawn here, so source documents never need raw square marks.
\def\cb@checked{checked}
\providecommand{\checkboxfield}[3]{}%
\renewcommand{\checkboxfield}[3]{%
  \hwfield{#1}{%
    \begingroup
      \def\cb@state{#2}%
      \ifx\cb@state\cb@checked
        \fbox{\makebox[1.1ex][c]{\raisebox{.1ex}{\scriptsize\sffamily x}}}%
      \else
        \fbox{\makebox[1.1ex][c]{\strut}}%
      \fi
    \endgroup
    \,#3%
  }%
}
\AtEndDocument{\immediate\closeout\hwf@out}
\makeatother
"""


def inject(tex: str) -> str:
    """Insert (or refresh) the macro block just before \\begin{document}."""
    block = f"{MARK_BEGIN}\n{BLOCK.strip()}\n{MARK_END}\n"

    if MARK_BEGIN in tex and MARK_END in tex:
        return re.sub(
            re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END) + r"\n?",
            lambda _: block, tex, count=1, flags=re.S)

    m = re.search(r"^\s*\\begin\{document\}", tex, re.M)
    if m:
        return tex[:m.start()] + block + tex[m.start():]

    # Fragment without a preamble (e.g. \input-ed page file): prepend.
    return block + tex

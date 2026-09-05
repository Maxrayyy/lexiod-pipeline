"""
Semantic naming of tables and handwritten fields, done by an LLM, one call per TABLE.

WHY PER-TABLE AND NOT PER-CELL
------------------------------
  * Field names inside one table must be mutually distinct. A per-cell call cannot see
    its siblings, so it happily returns `value` three times.
  * The table slug and its field slugs should agree in vocabulary
    (`inspection_record` / `outer_diameter_measured`, not `jianyan` / `od_meas`).
  * One call per table instead of one per cell is ~10-30x cheaper on a form-heavy doc.

DETERMINISM
-----------
The whole request is hashed and the whole response cached. Re-running the optimiser on
an unchanged document reproduces byte-identical field IDs -- required, because these
IDs are consumed downstream.

NO NETWORK REQUIRED
-------------------
HeuristicBatchNamer is a complete offline implementation. It produces positional names
(`r01c02`) for CJK input, which are stable and greppable but not meaningful -- use it
only as a fallback, and the report will tell you how many fields ended up on it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field as dc_field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from .fields import is_hashy, slug, tex_to_plain

DEFAULT_MODEL = os.environ.get("TEXOPT_MODEL", "claude-sonnet-5")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def openai_api_url() -> str:
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    return f"{base_url.rstrip('/')}/chat/completions"


def _is_openai_model(model: str) -> bool:
    m = model.lower()
    return m.startswith(("gpt", "o1", "o3", "o4"))


# --------------------------------------------------------------------------- #
# request / response shapes
# --------------------------------------------------------------------------- #

@dataclass
class FieldSpec:
    key: str            # stable positional key, e.g. "r01c02"
    row_header: str
    col_header: str
    value: str
    label: str = ""       # Lexoid #FIELD_VALUE; strongest semantic signal


@dataclass
class TableNameRequest:
    page: int
    section: str = ""          # nearest preceding \section*{...}
    bold_title: str = ""       # nearest preceding \textbf{...} sitting above the table
    caption: str = ""
    ordinal: int = 0           # 1-based index of this table within the document
    headers: List[str] = dc_field(default_factory=list)
    sample_rows: List[List[str]] = dc_field(default_factory=list)
    fields: List[FieldSpec] = dc_field(default_factory=list)

    def payload(self) -> dict:
        return {
            "page": self.page,
            "table_index_in_document": self.ordinal,
            "section_heading": tex_to_plain(self.section),
            "bold_title_above_table": tex_to_plain(self.bold_title),
            "caption": tex_to_plain(self.caption),
            "column_headers": [tex_to_plain(h) for h in self.headers],
            "sample_rows": [[tex_to_plain(c) for c in r] for r in self.sample_rows[:4]],
            "fields": [{"key": f.key,
                        "field_label": tex_to_plain(f.label),
                        "row_label": tex_to_plain(f.row_header),
                        "column_label": tex_to_plain(f.col_header),
                        "value": tex_to_plain(f.value)} for f in self.fields],
        }

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.payload(), ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:20]


@dataclass
class TableNaming:
    table: str
    fields: Dict[str, str]
    source: str = "llm"          # llm | cache | heuristic


class BatchNamer(Protocol):
    def name_table(self, req: TableNameRequest) -> TableNaming: ...


# --------------------------------------------------------------------------- #
# offline fallback
# --------------------------------------------------------------------------- #

def _ok(s: str) -> str:
    return "" if (not s or s == "field" or is_hashy(s)) else s


class HeuristicBatchNamer:
    """Deterministic, no network. Meaningful only when the source text is ASCII."""

    def name_table(self, req: TableNameRequest) -> TableNaming:
        table = ""
        for cand in (req.bold_title, req.caption, req.section):
            table = _ok(slug(cand, 30))
            if table:
                break
        # Without a derivable title, two CJK-titled tables on the same page would
        # collide on `tab_p076`. Disambiguate by document ordinal.
        table = table or (f"tab_p{req.page:03d}_t{req.ordinal}" if req.ordinal
                          else f"tab_p{req.page:03d}")

        out, used = {}, set()
        for f in req.fields:
            label = _ok(slug(f.label, 40))
            parts = ([label] if label else
                     [p for p in (_ok(slug(f.row_header, 24)),
                                  _ok(slug(f.col_header, 20))) if p])
            name = "_".join(dict.fromkeys(parts)) or f.key
            while name in used:
                name = f"{name}_{f.key}"
            used.add(name)
            out[f.key] = name
        return TableNaming(table=table, fields=out, source="heuristic")


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #

SYSTEM = (
    "You name form fields extracted from scanned engineering / administrative "
    "documents. You output ONLY JSON. Never explain."
)

PROMPT = """\
Below is one table from a document, as JSON. Some cells hold handwritten values that
need machine-readable identifiers.

{payload}

Return JSON with exactly this shape:
{{"table": "<slug>", "fields": {{"<key>": "<slug>", ...}}}}

Rules:
- Every slug is lowercase ASCII snake_case, 2-4 words, no digits unless the source
  text has them, no prefixes, no units.
- "table" describes what the table IS, derived from bold_title_above_table first,
  then caption, then section_heading. Example: "inspection_record", "vendor_details".
- Each field slug describes what the VALUE MEANS. Prefer field_label when present,
  then use row_label and column_label.
  Example row_label "外径" + column_label "实测值" -> "outer_diameter_measured".
- Translate non-English source text into English. Do not transliterate.
- Field slugs must be mutually distinct within this table.
- Include every key from "fields". Do not invent keys.
"""


class LLMBatchNamer:
    """
    Anthropic Messages API, one call per table, cached on disk by request fingerprint.
    Falls back to HeuristicBatchNamer on any error -- naming must never block the
    optimisation, but the report records which tables fell back.
    """

    def __init__(self, cache_path: Path, model: str = DEFAULT_MODEL,
                 api_key: Optional[str] = None, max_retries: int = 2,
                 timeout: int = 60) -> None:
        self.cache_path = Path(cache_path)
        self.model = model
        self.is_openai = _is_openai_model(model)
        if self.is_openai:
            self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        else:
            self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.max_retries = max_retries
        self.timeout = timeout
        self.fallback = HeuristicBatchNamer()
        self.cache: Dict[str, dict] = {}
        self.stats: Dict[str, int] = {"cache": 0, "llm": 0, "heuristic": 0}
        if self.cache_path.exists():
            try:
                self.cache = json.loads(self.cache_path.read_text("utf-8"))
            except Exception:
                self.cache = {}

    # ---- public ---------------------------------------------------------- #
    def name_table(self, req: TableNameRequest) -> TableNaming:
        fp = req.fingerprint()
        if fp in self.cache:
            self.stats["cache"] += 1
            c = self.cache[fp]
            return self._finish(req, c.get("table", ""), c.get("fields", {}), "cache")

        raw = self._call(req) if self.api_key else None
        if raw is None:
            self.stats["heuristic"] += 1
            return self.fallback.name_table(req)

        self.stats["llm"] += 1
        self.cache[fp] = raw
        self._flush()
        return self._finish(req, raw.get("table", ""), raw.get("fields", {}), "llm")

    # ---- internals ------------------------------------------------------- #
    def _finish(self, req: TableNameRequest, table: str, fields: dict,
                source: str) -> TableNaming:
        """Sanitise whatever came back; never trust the model's formatting."""
        fb = self.fallback.name_table(req)
        table = _ok(slug(table, 30)) or fb.table

        out, used = {}, set()
        for f in req.fields:
            cand = _ok(slug(str(fields.get(f.key, "")), 40)) or fb.fields[f.key]
            base, i = cand, 2
            while cand in used:               # model returned duplicates
                cand = f"{base}_{i}"
                i += 1
            used.add(cand)
            out[f.key] = cand
        return TableNaming(table=table, fields=out, source=source)

    def _call(self, req: TableNameRequest) -> Optional[dict]:
        if self.is_openai:
            return self._call_openai(req)
        return self._call_anthropic(req)

    def _call_openai(self, req: TableNameRequest) -> Optional[dict]:
        body = json.dumps({
            "model": self.model,
            "max_completion_tokens": 1000,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": PROMPT.format(
                    payload=json.dumps(req.payload(), ensure_ascii=False, indent=2))},
            ],
        }).encode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                rq = urllib.request.Request(openai_api_url(), data=body, method="POST", headers={
                    "content-type": "application/json",
                    "authorization": f"Bearer {self.api_key}",
                })
                with urllib.request.urlopen(rq, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"]
                return self._parse(text)
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                if attempt == self.max_retries:
                    return None
        return None

    def _call_anthropic(self, req: TableNameRequest) -> Optional[dict]:
        body = json.dumps({
            "model": self.model,
            "max_tokens": 1000,
            "temperature": 0,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": PROMPT.format(
                payload=json.dumps(req.payload(), ensure_ascii=False, indent=2))}],
        }).encode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                rq = urllib.request.Request(ANTHROPIC_API_URL, data=body, method="POST", headers={
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                })
                with urllib.request.urlopen(rq, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                text = "".join(b.get("text", "") for b in data.get("content", [])
                               if b.get("type") == "text")
                return self._parse(text)
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                if attempt == self.max_retries:
                    return None
        return None

    @staticmethod
    def _parse(text: str) -> Optional[dict]:
        t = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.M).strip()
        try:
            obj = json.loads(t)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", t, re.S)          # model added prose anyway
            if not m:
                return None
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return obj if isinstance(obj, dict) and isinstance(obj.get("fields"), dict) else None

    def _flush(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, self.cache_path)

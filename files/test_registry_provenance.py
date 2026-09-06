import json
from pathlib import Path

import pytest

from .fields import FieldRecord, write_registry


def test_registry_keeps_review_history_and_checks_tex_value(tmp_path):
    incoming = tmp_path / "reconciled.fields.json"
    field = {"field_id": "LEX-P0001-V0001", "value": "Zhang", "needs_review": True,
             "paddle_text": "Chang", "model_guess": "Zhang", "confidence": 0.7,
             "history": [{"stage": "reconcile", "from": "Chang", "to": "Zhang", "reason": "crop"}]}
    incoming.write_text(json.dumps({"fields": [field]}))
    output = tmp_path / "optimized.fields.json"
    record = FieldRecord(field["field_id"], "operator", 1, "table", "operator", "", "",
                         "Zhang", 12, "fp")
    tex = "% #VALUE_ID: LEX-P0001-V0001\n% #TODO #HANDWRITTEN: Zhang\n\\fieldvalue{\\handwritten{Zhang}}"
    write_registry([record], output, provenance_path=incoming, tex=tex)
    got = json.loads(output.read_text())["fields"][0]
    assert got["history"] == field["history"]
    assert got["needs_review"] is True
    assert got["semantic_alias"] == "operator"
    with pytest.raises(ValueError, match="value"):
        write_registry([record], output, provenance_path=incoming, tex=tex.replace("{Zhang}", "{Changed}"))

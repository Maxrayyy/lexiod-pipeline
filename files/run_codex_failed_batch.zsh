#!/bin/zsh

# Repair incomplete/failed Lexoid TeX cases with Codex, then retry texopt.
# Original source files are never modified; Codex only edits isolated copies.

project_root="${0:A:h}"
if [[ -f "$project_root/.env" ]]; then
  # Read only the settings this script needs. Do not source .env: some values
  # contain spaces and are dotenv syntax rather than shell assignments.
  for dotenv_name in OPENAI_API_KEY OPENAI_BASE_URL TEXOPT_MODEL \
    CODEX_MODEL_PROVIDER CODEX_MODEL CODEX_NETWORK_ACCESS; do
    if [[ -z "${(P)dotenv_name}" ]]; then
      dotenv_value="$(sed -n "s/^${dotenv_name}=//p" "$project_root/.env" | tail -n 1)"
      [[ -n "$dotenv_value" ]] && export "$dotenv_name=$dotenv_value"
    fi
  done
fi

set -u

source_root="${1:-/Users/lanyu/Desktop/输出目录/02-lexoid-tex}"
metadata_root="${2:-/Users/lanyu/Desktop/优化tex}"
reviewed_tex_root="${3:-/Users/lanyu/Desktop/输出目录/04-reviewed-tex}"
repair_root="${CODEX_REPAIR_ROOT:-$project_root/codex-repairs}"
texopt_bin="${TEXOPT_BIN:-/opt/anaconda3/bin/texopt}"
python_bin="${TEXOPT_PYTHON:-/opt/anaconda3/bin/python}"
codex_bin="${CODEX_BIN:-/Applications/ChatGPT.app/Contents/Resources/codex}"
model="${TEXOPT_MODEL:-gpt-5.5}"
codex_model="${CODEX_MODEL:-gpt-5.5}"
codex_provider_id="${CODEX_MODEL_PROVIDER:-lexiod_openai}"
openai_base_url="${OPENAI_BASE_URL:-}"
codex_network_access="${CODEX_NETWORK_ACCESS:-true}"
allow_layout_payload_changes="${CODEX_ALLOW_LAYOUT_PAYLOAD_CHANGES:-1}"

for executable in "$texopt_bin" "$python_bin" "$codex_bin"; do
  if [[ ! -x "$executable" ]]; then
    print -u2 "ERROR: executable not found: $executable"
    exit 1
  fi
done

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  print -u2 "ERROR: OPENAI_API_KEY is not set in $project_root/.env or the environment"
  exit 1
fi

typeset -a codex_provider_args
codex_provider_args=(
  -m "$codex_model"
  -c "sandbox_workspace_write.network_access=$codex_network_access"
  --enable goals
)
if [[ -n "$openai_base_url" ]]; then
  codex_provider_args+=(
    -c "model_provider=\"$codex_provider_id\""
    -c "model_providers.$codex_provider_id.name=\"OpenAI-compatible project provider\""
    -c "model_providers.$codex_provider_id.base_url=\"$openai_base_url\""
    -c "model_providers.$codex_provider_id.wire_api=\"responses\""
    -c "model_providers.$codex_provider_id.env_key=\"OPENAI_API_KEY\""
  )
fi

mkdir -p "$repair_root"
state_dir="$metadata_root/.texopt-local-state"
mkdir -p "$state_dir"
name_cache="$state_dir/texopt-names.json"
repair_cache="$state_dir/texopt-syntax-repairs.json"

typeset -a failures
while IFS= read -r -d '' input; do
  relative="${input#$source_root/}"
  relative_dir="${relative:h}"
  stem="${relative:t:r}"
  if [[ "$relative_dir" == "." ]]; then
    metadata_dir="$metadata_root"
    reviewed_dir="$reviewed_tex_root"
  else
    metadata_dir="$metadata_root/$relative_dir"
    reviewed_dir="$reviewed_tex_root/$relative_dir"
  fi
  output="$reviewed_dir/$stem.optimized.tex"
  json_dir="$metadata_dir/${output:t}+json"
  if [[ ! -s "$output" || ! -s "$json_dir/$stem.optimized.fields.json" || ! -s "$json_dir/$stem.optimized.report.json" ]]; then
    failures+=("$input")
  fi
done < <(find "$source_root" -type f -name '*.tex' \
  ! -name '.*' ! -name '*.optimized.tex' ! -name '*.before-syntax-fix.tex' \
  -print0 | sort -z)

total=${#failures[@]}
if (( total == 0 )); then
  print "No failed or incomplete cases found."
  exit 0
fi

print "Found $total failed or incomplete case(s) for Codex repair."
integer index=0
integer succeeded=0
integer failed=0

for input in "${failures[@]}"; do
  (( index += 1 ))
  relative="${input#$source_root/}"
  relative_dir="${relative:h}"
  stem="${relative:t:r}"
  if [[ "$relative_dir" == "." ]]; then
    metadata_dir="$metadata_root"
    reviewed_dir="$reviewed_tex_root"
  else
    metadata_dir="$metadata_root/$relative_dir"
    reviewed_dir="$reviewed_tex_root/$relative_dir"
  fi

  repair_dir="$repair_root/$relative_dir"
  repair_file="$repair_dir/$stem.codex-repaired.tex"
  retry_failed_marker="$repair_file.retry-failed"
  source_log="$metadata_dir/$stem.optimized.optimizer.log"
  codex_log="$metadata_dir/$stem.optimized.codex-repair.log"
  output="$reviewed_dir/$stem.optimized.tex"
  json_dir="$metadata_dir/${output:t}+json"
  registry="$json_dir/$stem.optimized.fields.json"
  report="$json_dir/$stem.optimized.report.json"
  optimizer_log="$metadata_dir/$stem.optimized.optimizer.log"
  mkdir -p "$repair_dir" "$reviewed_dir" "$json_dir" "$metadata_dir"
  # Preserve a prior Codex repair so an interrupted batch can resume its work.
  [[ -s "$repair_file" ]] || cp "$input" "$repair_file"

  repair_is_valid=0
  if [[ ! -e "$retry_failed_marker" ]]; then
    "$python_bin" -c 'import sys; from pathlib import Path; from texopt.syntax_check import validate_latex; issues=[i for i in validate_latex(Path(sys.argv[1]).read_text(encoding="utf-8"), require_sync_safe=False) if i.severity=="error"]; raise SystemExit(bool(issues))' "$repair_file" >/dev/null 2>&1 && repair_is_valid=1
  fi

  if (( repair_is_valid == 0 )); then
    print "[$index/$total] Codex repairing: $relative"
    prompt="You are repairing one failed Lexoid-generated XeLaTeX file.

Edit only this repair copy:
$repair_file

Read the previous optimizer log for concrete failure evidence:
$source_log

Goal: make the repair copy structurally valid and allow texopt to measure and convert every tabularx table. Make the smallest syntax-only edits needed. Fix unmatched braces, broken begin/end nesting, alignment delimiters, math delimiters, and malformed table rows that cause the reported probe or validation errors.

If the latest optimizer log ends in CONVERT_RETRY_BLOCKED, structural validity alone is insufficient: inspect the first real XeLaTeX errors that prevented the reported table columns from being measured and repair those compile-level defects too.

Hard invariants:
- Layout-only edits inside field payloads are authorized (for example \\ to \\newline, or adding/removing math-mode wrappers). Never change visible field values, VALUE_ID, FIELD_VALUE, HANDWRITTEN, checkbox IDs/states/labels, page checkpoint comments, or business text.
- Never remove a table, row, cell, or field to make compilation pass.
- Do not edit the original input, project Python code, caches, logs, or generated outputs.
- Do not guess measured column widths and do not convert tabularx yourself; texopt will do that after repair.
- Inspect the whole repair file when delimiter imbalance may originate before the reported line.

Before finishing, run this structural validator from $project_root and keep repairing until it prints VALID:
$python_bin -c 'from pathlib import Path; from texopt.syntax_check import validate_latex; p=Path(r\"$repair_file\"); issues=[i for i in validate_latex(p.read_text(encoding=\"utf-8\"), require_sync_safe=False) if i.severity==\"error\"]; print(\"VALID\" if not issues else \"\\n\".join(str(i.payload()) for i in issues)); raise SystemExit(bool(issues))'

Also run this protected-content comparison against the original and keep repairing until it prints INVARIANTS_OK:
$python_bin -c 'from pathlib import Path; from texopt.syntax_repair import repair_invariant_violations; before=Path(r\"$input\").read_text(encoding=\"utf-8\"); after=Path(r\"$repair_file\").read_text(encoding=\"utf-8\"); baseline=set(repair_invariant_violations(before, before)); allowed={\"field_payloads_changed\"} if r\"$allow_layout_payload_changes\" == \"1\" else set(); violations=[v for v in repair_invariant_violations(before, after) if v not in baseline and v not in allowed]; print(\"INVARIANTS_OK\" if not violations else \"\\n\".join(violations)); raise SystemExit(bool(violations))'

Finish with a concise summary of exact edits and validation performed."

    "$codex_bin" exec "${codex_provider_args[@]}" --ephemeral --skip-git-repo-check \
      --approve-for-me \
      --cd "$project_root" --add-dir "$repair_root" \
      "$prompt" >| "$codex_log" 2>&1
    codex_exit=$?
    if (( codex_exit != 0 )); then
      (( failed += 1 ))
      print -u2 "[$index/$total] CODEX FAILED (exit $codex_exit): $relative"
      continue
    fi
  else
    print "[$index/$total] Reusing structurally valid Codex repair: $relative"
  fi

  "$python_bin" -c 'import sys; from pathlib import Path; from texopt.syntax_check import validate_latex; issues=[i for i in validate_latex(Path(sys.argv[1]).read_text(encoding="utf-8"), require_sync_safe=False) if i.severity=="error"]; [print(i.payload()) for i in issues]; raise SystemExit(bool(issues))' "$repair_file" >> "$codex_log" 2>&1
  validate_exit=$?
  if (( validate_exit != 0 )); then
    (( failed += 1 ))
    print -u2 "[$index/$total] CODEX REPAIR REJECTED by validator: $relative"
    continue
  fi

  "$python_bin" -c 'import sys; from pathlib import Path; from texopt.syntax_repair import repair_invariant_violations; before=Path(sys.argv[1]).read_text(encoding="utf-8"); after=Path(sys.argv[2]).read_text(encoding="utf-8"); baseline=set(repair_invariant_violations(before, before)); allowed={"field_payloads_changed"} if sys.argv[3] == "1" else set(); violations=[v for v in repair_invariant_violations(before, after) if v not in baseline and v not in allowed]; [print(v) for v in violations]; raise SystemExit(bool(violations))' "$input" "$repair_file" "$allow_layout_payload_changes" >> "$codex_log" 2>&1
  invariant_exit=$?
  if (( invariant_exit != 0 )); then
    (( failed += 1 ))
    print -u2 "[$index/$total] CODEX REPAIR REJECTED by protected-content audit: $relative"
    continue
  fi

  print "[$index/$total] Retrying texopt: $relative"
  "$texopt_bin" optimise "$repair_file" \
    -o "$output" --registry "$registry" --report "$report" \
    --log-file "$optimizer_log" --llm-model "$model" \
    --name-cache "$name_cache"
  retry_exit=$?
  if (( retry_exit == 0 || retry_exit == 2 )); then
    rm -f "$retry_failed_marker"
    (( succeeded += 1 ))
    print "[$index/$total] RECOVERED (exit $retry_exit): $relative"
  else
    print 'texopt retry failed; Codex must inspect the latest optimizer log again' >| "$retry_failed_marker"
    (( failed += 1 ))
    print -u2 "[$index/$total] RETRY FAILED (exit $retry_exit): $relative"
  fi
done

print "Codex repair batch finished: recovered=$succeeded failed=$failed total=$total"
(( failed == 0 ))

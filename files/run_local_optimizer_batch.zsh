#!/bin/zsh

# Batch-optimize completed Lexoid .tex files while preserving their relative tree.
# A failed item is recorded and does not prevent later inputs from running.

project_root="${0:A:h}"
if [[ -f "$project_root/.env" ]]; then
  for dotenv_name in OPENAI_API_KEY OPENAI_BASE_URL TEXOPT_MODEL TEXOPT_REPAIR_MODEL; do
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
texopt_bin="${TEXOPT_BIN:-/opt/anaconda3/bin/texopt}"
model="${TEXOPT_MODEL:?Set TEXOPT_MODEL in .env or environment}"

if [[ ! -x "$texopt_bin" ]]; then
  print -u2 "ERROR: texopt executable not found: $texopt_bin"
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  print -u2 "ERROR: OPENAI_API_KEY is not set and was not found in .env"
  exit 1
fi

state_dir="$metadata_root/.texopt-local-state"
mkdir -p "$state_dir"
name_cache="$state_dir/texopt-names.json"
repair_cache="$state_dir/texopt-syntax-repairs.json"

# Seed private local caches once, avoiding concurrent writes to Docker's caches.
shared_state="/Users/lanyu/Desktop/输出目录/state"
if [[ ! -e "$name_cache" && -f "$shared_state/texopt-names.json" ]]; then
  cp "$shared_state/texopt-names.json" "$name_cache"
fi
if [[ ! -e "$repair_cache" && -f "$shared_state/texopt-syntax-repairs.json" ]]; then
  cp "$shared_state/texopt-syntax-repairs.json" "$repair_cache"
fi

typeset -a inputs
while IFS= read -r -d '' input; do
  inputs+=("$input")
done < <(find "$source_root" -type f -name '*.tex' \
  ! -name '.*' \
  ! -name '*.optimized.tex' \
  ! -name '*.before-syntax-fix.tex' \
  -print0 | sort -z)

total=${#inputs[@]}
if (( total == 0 )); then
  print "No completed .tex files found under $source_root"
  exit 0
fi

print "Found $total completed .tex file(s)."
integer index=0
integer succeeded=0
integer failed=0
integer skipped=0

for input in "${inputs[@]}"; do
  (( index += 1 ))
  relative="${input#$source_root/}"
  relative_dir="${relative:h}"
  filename="${relative:t}"
  stem="${filename%.tex}"
  if [[ "$relative_dir" == "." ]]; then
    metadata_dir="$metadata_root"
    reviewed_tex_dir="$reviewed_tex_root"
  else
    metadata_dir="$metadata_root/$relative_dir"
    reviewed_tex_dir="$reviewed_tex_root/$relative_dir"
  fi

  output="$reviewed_tex_dir/$stem.optimized.tex"
  json_dir="$metadata_dir/${output:t}+json"
  registry="$json_dir/$stem.optimized.fields.json"
  report="$json_dir/$stem.optimized.report.json"
  optimizer_log="$metadata_dir/$stem.optimized.optimizer.log"
  mkdir -p "$reviewed_tex_dir" "$json_dir"

  if [[ -s "$output" && -s "$registry" && -s "$report" ]]; then
    (( skipped += 1 ))
    print "[$index/$total] Skipped (complete outputs exist): $relative"
    continue
  fi

  print "[$index/$total] Optimizing: $relative"
  "$texopt_bin" optimise "$input" \
    -o "$output" \
    --registry "$registry" \
    --report "$report" \
    --log-file "$optimizer_log" \
    --llm-model "$model" \
    --name-cache "$name_cache"
  exit_code=$?

  # Exit 2 means a usable output was written but opaque tables remain.
  if (( exit_code == 0 || exit_code == 2 )); then
    (( succeeded += 1 ))
    print "[$index/$total] Completed (exit $exit_code): $output"
  else
    (( failed += 1 ))
    print -u2 "[$index/$total] FAILED (exit $exit_code): $relative"
  fi
done

print "Batch finished: succeeded=$succeeded skipped=$skipped failed=$failed total=$total"
(( failed == 0 ))

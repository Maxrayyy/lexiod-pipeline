"""Resumable directory batch runner for ``lexoid latex``."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional


CHECKPOINT_RE = re.compile(
    r"(?m)^% LEXOID_PAGE_COMPLETED: (?P<page>\d+)/(?P<total>\d+)\s*$"
)


def discover_pdfs(source_root: Path) -> list[Path]:
    source_root = Path(source_root)
    files = []
    for path in source_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        relative = path.relative_to(source_root)
        if path.name.startswith("._") or any(part.startswith(".") for part in relative.parts):
            continue
        files.append(path)
    return sorted(files, key=lambda path: str(path.relative_to(source_root)))


def output_path_for(source: Path, source_root: Path, output_root: Path) -> Path:
    relative = Path(source).relative_to(source_root)
    name = f"{relative.stem}.optimized.tex"
    return Path(output_root) / "optimized" / relative.parent / name


def legacy_output_path_for(
    source: Path, source_root: Path, output_root: Path
) -> Path:
    return Path(output_root) / Path(source).relative_to(source_root).with_suffix(".tex")


def working_path_for(source: Path, source_root: Path, work_root: Path) -> Path:
    return Path(work_root) / Path(source).relative_to(source_root).with_suffix(".tex")


def optimized_work_path_for(raw_output: Path) -> Path:
    return Path(raw_output).with_name(f"{Path(raw_output).stem}.optimized.tex")


def _artifact_path_for(
    final_output: Path, output_root: Path, directory: str, suffix: str
) -> Path:
    relative = Path(final_output).relative_to(Path(output_root) / "optimized")
    stem = relative.name.removesuffix(".optimized.tex")
    return Path(output_root) / directory / relative.parent / f"{stem}{suffix}"


def publish_file(source: Path, destination: Path) -> None:
    """Publish across mounts while keeping the final replacement atomic."""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    shutil.copy2(source, temporary)
    temporary.replace(destination)
    source.unlink()


def read_checkpoint(output: Path) -> Optional[tuple[int, int]]:
    if not Path(output).exists():
        return None
    matches = list(CHECKPOINT_RE.finditer(Path(output).read_text("utf-8", errors="replace")))
    if not matches:
        return None
    match = matches[-1]
    return int(match.group("page")), int(match.group("total"))


def build_lexoid_command(source: Path, output: Path, model: str) -> list[str]:
    command = [
        "lexoid",
        "latex",
        "--input",
        str(source),
        "--output",
        str(output),
        "--model",
        model,
        "--auto-orient",
    ]
    checkpoint = read_checkpoint(output)
    if checkpoint and checkpoint[0] < checkpoint[1]:
        command.extend(["--start-page", str(checkpoint[0] + 1)])
    return command


def build_optimizer_command(
    raw_output: Path,
    final_output: Path,
    output_root: Path,
    model: str,
) -> list[str]:
    raw_output = Path(raw_output)
    final_output = Path(final_output)
    output_root = Path(output_root)
    log_path = _artifact_path_for(
        final_output, output_root, "_logs", ".texopt.log"
    )
    state_root = output_root / "_state"
    return [
        "texopt",
        "optimise",
        str(raw_output),
        "-o",
        str(optimized_work_path_for(raw_output)),
        "--registry",
        str(raw_output.with_suffix(".fields.json")),
        "--report",
        str(raw_output.with_suffix(".report.json")),
        "--log-file",
        str(log_path),
        "--llm-model",
        model,
        "--name-cache",
        str(state_root / "texopt-names.json"),
        "--llm-syntax-repair",
        "--syntax-repair-cache",
        str(state_root / "texopt-syntax-repairs.json"),
        "--llm-repair-on-failure",
        "--no-probe",
        "--allow-opaque",
    ]


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _page_count(path: Path) -> int:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        return len(document)
    finally:
        document.close()


def _run_one(command: list[str], log_path: Path, label: str) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[{time.strftime('%Y-%m-%dT%H:%M:%S')}] starting {label}\n")
        log.flush()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            if "Progress:" in line or "Error:" in line:
                print(f"[{label}] {line.rstrip()}", flush=True)
        return process.wait()


def run_batch(
    source_root: Path,
    output_root: Path,
    work_root: Path,
    model: str,
) -> int:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    work_root = work_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"

    sources = discover_pdfs(source_root)
    manifest = {
        "source_root": str(source_root),
        "output_root": str(output_root),
        "work_root": str(work_root),
        "model": model,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": [],
    }

    print(f"Preflight: {len(sources)} PDF files", flush=True)
    total_pages = 0
    for source in sources:
        relative = str(source.relative_to(source_root))
        output = output_path_for(source, source_root, output_root)
        work_output = working_path_for(source, source_root, work_root)
        entry = {
            "source": relative,
            "output": str(output.relative_to(output_root)),
            "work_output": str(work_output.relative_to(work_root)),
            "size": source.stat().st_size,
            "mtime_ns": source.stat().st_mtime_ns,
            "status": "pending",
            "attempts": [],
        }
        try:
            entry["pages"] = _page_count(source)
            total_pages += entry["pages"]
        except Exception as exc:
            entry["status"] = "invalid"
            entry["error"] = str(exc)
        manifest["files"].append(entry)
        _write_manifest(manifest_path, manifest)

    manifest["total_files"] = len(sources)
    manifest["total_pages"] = total_pages
    manifest["invalid_files"] = sum(
        entry["status"] == "invalid" for entry in manifest["files"]
    )
    _write_manifest(manifest_path, manifest)
    print(
        f"Preflight complete: {total_pages} readable pages, "
        f"{manifest['invalid_files']} invalid files",
        flush=True,
    )

    conversion_failures = 0
    optimization_failures = 0
    for index, entry in enumerate(manifest["files"], start=1):
        if entry["status"] == "invalid":
            continue
        source = source_root / entry["source"]
        final_output = output_root / entry["output"]
        final_report = _artifact_path_for(
            final_output, output_root, "_metadata", ".report.json"
        )
        final_registry = _artifact_path_for(
            final_output, output_root, "_metadata", ".fields.json"
        )
        if final_output.exists() and final_report.exists():
            entry["status"] = "done"
            entry["completed_pages"] = entry["pages"]
            entry["optimized"] = True
            _write_manifest(manifest_path, manifest)
            continue

        raw_output = work_root / entry["work_output"]
        legacy_output = legacy_output_path_for(source, source_root, output_root)
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        final_output.parent.mkdir(parents=True, exist_ok=True)
        checkpoint = read_checkpoint(raw_output)
        legacy_checkpoint = read_checkpoint(legacy_output)
        if checkpoint != (entry["pages"], entry["pages"]):
            if legacy_checkpoint == (entry["pages"], entry["pages"]):
                shutil.copy2(legacy_output, raw_output)
                checkpoint = legacy_checkpoint

        log_path = output_root / "_logs" / Path(entry["source"]).with_suffix(".log")
        label = f"{index}/{len(sources)} {entry['source']}"
        if checkpoint != (entry["pages"], entry["pages"]):
            command = build_lexoid_command(source, raw_output, model)
            entry["status"] = "converting"
            entry["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _write_manifest(manifest_path, manifest)
            print(f"Converting {label}", flush=True)

            started = time.time()
            return_code = _run_one(command, log_path, label)
            entry["attempts"].append(
                {
                    "stage": "conversion",
                    "return_code": return_code,
                    "seconds": round(time.time() - started, 1),
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
            checkpoint = read_checkpoint(raw_output)
            entry["completed_pages"] = checkpoint[0] if checkpoint else 0
            if return_code != 0 or checkpoint != (entry["pages"], entry["pages"]):
                entry["status"] = "conversion_failed"
                conversion_failures += 1
                _write_manifest(manifest_path, manifest)
                continue

        optimizer_command = build_optimizer_command(
            raw_output, final_output, output_root, model
        )
        optimizer_log = (
            output_root / "_logs" / Path(entry["source"]).with_suffix(".optimizer.log")
        )
        entry["status"] = "optimizing"
        _write_manifest(manifest_path, manifest)
        print(f"Optimizing {label}", flush=True)

        started = time.time()
        return_code = _run_one(optimizer_command, optimizer_log, label)
        entry["attempts"].append(
            {
                "stage": "optimization",
                "return_code": return_code,
                "seconds": round(time.time() - started, 1),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )
        optimized_work = optimized_work_path_for(raw_output)
        work_report = raw_output.with_suffix(".report.json")
        work_registry = raw_output.with_suffix(".fields.json")
        if return_code == 0 and optimized_work.exists() and work_report.exists():
            publish_file(optimized_work, final_output)
            if work_registry.exists():
                publish_file(work_registry, final_registry)
            publish_file(work_report, final_report)
            raw_output.unlink(missing_ok=True)
            entry["status"] = "done"
            entry["optimized"] = True
        else:
            entry["status"] = "optimization_failed"
            entry["optimized"] = False
            optimization_failures += 1
        _write_manifest(manifest_path, manifest)

    manifest["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    manifest["conversion_failures"] = conversion_failures
    manifest["optimization_failures"] = optimization_failures
    manifest["failed_files"] = conversion_failures + optimization_failures
    _write_manifest(manifest_path, manifest)
    print(
        "Batch finished with "
        f"{conversion_failures} conversion failures and "
        f"{optimization_failures} optimization failures",
        flush=True,
    )
    return 1 if conversion_failures or optimization_failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6-luna")
    args = parser.parse_args()
    return run_batch(args.source_root, args.output_root, args.work_root, args.model)


if __name__ == "__main__":
    raise SystemExit(main())

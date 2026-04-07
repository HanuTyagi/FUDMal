"""
fudmal.manifest
~~~~~~~~~~~~~~~

Non-invasive run-artefact logging helper.

Usage (in a builder function, after a successful PyInstaller run)::

    from fudmal.manifest import write_manifest

    manifest_path = write_manifest(
        tool="dropper_gen",
        inputs={"url": url, "download_path": download_path, "filename": filename},
        outputs=[output_exe_path],
    )
    print(f"[INFO] Manifest saved to: {manifest_path}")

The manifest is written as a JSON file under ``runs/<timestamp>-<run_id>/manifest.json``
relative to the current working directory.  It records:

- Run ID and timestamp (UTC).
- Python version and (if available) PyInstaller version.
- Input parameters supplied to the builder.
- SHA-256 hashes and sizes of every output file.

This does **not** change any core build behaviour; it only appends observability
data after a build completes.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: str | Path) -> str:
    """Return the hex SHA-256 digest of a file, or an empty string on error."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _file_entry(path: str | Path) -> dict[str, Any]:
    """Return a dict with name, size_bytes, and sha256 for *path*."""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError:
        size = -1
    return {
        "name": p.name,
        "path": str(p.resolve()),
        "size_bytes": size,
        "sha256": _sha256(p),
    }


def _pyinstaller_version() -> str:
    """Return the installed PyInstaller version, or 'unavailable'."""
    try:
        import importlib.metadata

        return importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def write_manifest(
    tool: str,
    inputs: dict[str, Any],
    outputs: list[str | Path],
    *,
    runs_root: str | Path | None = None,
) -> Path:
    """Write a JSON manifest for a build run and return its path.

    Parameters
    ----------
    tool:
        Short name of the builder tab / tool (e.g. ``"dropper_gen"``).
    inputs:
        Dictionary of user-supplied configuration values (URL, filenames, etc.).
        Avoid logging secrets – pass only what is safe to store on disk.
    outputs:
        List of paths to output files produced by the build.
    runs_root:
        Directory under which the ``runs/`` folder is created.  Defaults to the
        current working directory.

    Returns
    -------
    Path
        Absolute path to the written ``manifest.json``.
    """
    run_id = uuid.uuid4().hex[:12]
    ts = datetime.now(tz=timezone.utc)
    ts_str = ts.strftime("%Y%m%dT%H%M%SZ")

    base = Path(runs_root or os.getcwd()) / "runs" / f"{ts_str}-{run_id}"
    base.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "timestamp_utc": ts.isoformat(),
        "tool": tool,
        "environment": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "pyinstaller_version": _pyinstaller_version(),
        },
        "inputs": inputs,
        "outputs": [_file_entry(p) for p in outputs],
    }

    manifest_path = base / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path

"""Tests for fudmal.manifest – run-artefact logging helper."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fudmal.manifest import _file_entry, _sha256, write_manifest

# ---------------------------------------------------------------------------
# _sha256 helpers
# ---------------------------------------------------------------------------


def test_sha256_known_content(tmp_path: Path) -> None:
    """SHA-256 of known content must match reference digest."""
    data = b"hello world"
    expected = hashlib.sha256(data).hexdigest()

    p = tmp_path / "test.bin"
    p.write_bytes(data)

    assert _sha256(p) == expected


def test_sha256_missing_file_returns_empty_string() -> None:
    """_sha256 must not raise on a missing file; it returns an empty string."""
    assert _sha256("/nonexistent/path/file.bin") == ""


def test_sha256_empty_file(tmp_path: Path) -> None:
    """SHA-256 of an empty file equals the known empty-digest constant."""
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    expected = hashlib.sha256(b"").hexdigest()
    assert _sha256(p) == expected


# ---------------------------------------------------------------------------
# _file_entry helpers
# ---------------------------------------------------------------------------


def test_file_entry_existing(tmp_path: Path) -> None:
    """_file_entry returns correct name, size, and hash for a real file."""
    content = b"test content for file entry"
    p = tmp_path / "artefact.exe"
    p.write_bytes(content)

    entry = _file_entry(p)

    assert entry["name"] == "artefact.exe"
    assert entry["size_bytes"] == len(content)
    assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    assert "path" in entry


def test_file_entry_missing_file() -> None:
    """_file_entry on a non-existent path returns size_bytes == -1."""
    entry = _file_entry("/nonexistent/artefact.exe")
    assert entry["size_bytes"] == -1
    # sha256 should be empty string (not raise)
    assert entry["sha256"] == ""


# ---------------------------------------------------------------------------
# write_manifest
# ---------------------------------------------------------------------------


def test_write_manifest_creates_json(tmp_path: Path) -> None:
    """write_manifest must create a valid JSON file inside runs/."""
    # Create a dummy output file
    dummy_output = tmp_path / "payload.exe"
    dummy_output.write_bytes(b"\x00" * 16)

    manifest_path = write_manifest(
        tool="test_tool",
        inputs={"url": "http://lab.local/payload.exe", "filename": "payload.exe"},
        outputs=[dummy_output],
        runs_root=tmp_path,
    )

    assert manifest_path.exists(), "manifest.json was not created"
    assert manifest_path.name == "manifest.json"

    # Must be valid JSON
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert data["tool"] == "test_tool"
    assert "run_id" in data
    assert "timestamp_utc" in data
    assert isinstance(data["outputs"], list)
    assert len(data["outputs"]) == 1
    assert data["outputs"][0]["name"] == "payload.exe"


def test_write_manifest_nested_under_runs(tmp_path: Path) -> None:
    """The manifest must be nested under runs/<timestamp>-<run_id>/."""
    manifest_path = write_manifest(
        tool="sfx_builder",
        inputs={},
        outputs=[],
        runs_root=tmp_path,
    )

    # runs_root / runs / <ts-runid> / manifest.json
    # Verify that "runs" appears somewhere in the manifest path's parents
    assert any(part == "runs" for part in manifest_path.parts)


def test_write_manifest_records_environment(tmp_path: Path) -> None:
    """The manifest must include environment metadata."""
    manifest_path = write_manifest(
        tool="obfuscator",
        inputs={"version_key": "1.2.3"},
        outputs=[],
        runs_root=tmp_path,
    )

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    env = data["environment"]

    assert "python_version" in env
    assert "platform" in env
    assert "pyinstaller_version" in env


def test_write_manifest_multiple_outputs(tmp_path: Path) -> None:
    """write_manifest must record each output file individually."""
    out1 = tmp_path / "a.exe"
    out2 = tmp_path / "b.exe"
    out1.write_bytes(b"aaa")
    out2.write_bytes(b"bbb")

    manifest_path = write_manifest(
        tool="dropper_gen",
        inputs={},
        outputs=[out1, out2],
        runs_root=tmp_path,
    )

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(data["outputs"]) == 2
    names = {e["name"] for e in data["outputs"]}
    assert names == {"a.exe", "b.exe"}


def test_write_manifest_unique_run_ids(tmp_path: Path) -> None:
    """Each call to write_manifest must produce a unique run_id."""
    ids = set()
    for _ in range(5):
        mp = write_manifest(tool="t", inputs={}, outputs=[], runs_root=tmp_path)
        data = json.loads(mp.read_text())
        ids.add(data["run_id"])

    assert len(ids) == 5, "run_ids are not unique across runs"

# FUDMal — Enhancement Roadmap

This document captures the prioritised plan for evolving FUDMal into a
well-maintained, safe, and educationally valuable adversary-emulation lab.
All proposed changes must stay within the project's [non-goals](../README.md#non-goals).

---

## Phase 1 – Foundation (completed in initial PR)

| Item | Status |
|------|--------|
| Rewrite README with defensive framing, safety requirements, and non-goals | ✅ Done |
| Add `.gitignore` for Python/PyInstaller artefacts | ✅ Done |
| Add `pyproject.toml` with packaging metadata, optional extras, ruff config | ✅ Done |
| Add `requirements.txt` | ✅ Done |
| Create `fudmal/` package with `manifest.py` run-artefact logging helper | ✅ Done |
| Add `tests/` scaffold with cipher and manifest tests | ✅ Done |
| Add GitHub Actions CI workflow (ruff + pytest, Python 3.10–3.12) | ✅ Done |

---

## Phase 2 – Code Quality & Safety Framing  *(next milestone)*

### 2.1 Rename "Anti-Sandbox" labels to "Lab Guardrail"

**Priority:** High  
**Effort:** Small (UI text / variable names only)

The VM-detection checkbox in each tab is currently labelled  
*"Enable Anti-Sandbox (VM Detection)"*.  
For an educational defensive tool this framing is misleading.  Rename it to  
*"Enable Lab Guardrail (run only in detected VM)"* and update the underlying
variable names (`c_vm`, `s_vm`, `o_vm`, `p_vm`) to `c_guardrail`, etc.

This is a pure UI/label change with **no behaviour change**.

### 2.2 Integrate `fudmal.manifest` into each builder tab

**Priority:** High  
**Effort:** Small (add ~5 lines per tab after the PyInstaller `subprocess.run` call)

After every successful build in `main.py` (all four tabs), call:

```python
from fudmal.manifest import write_manifest

write_manifest(
    tool="dropper_gen",          # or sfx_builder / obfuscator / pdf_dropper
    inputs={...},                # sanitised user inputs (no secrets)
    outputs=[output_exe_path],
)
```

This gives students a JSON artefact they can ingest into a SIEM or parse
manually to understand what was built.

### 2.3 Fix `subprocess.run(shell=True)` instances

**Priority:** Medium  
**Effort:** Small

Several template strings embedded in `main.py` call `subprocess.run(..., shell=True)`.
Replace all `shell=True` invocations in the **builder tool itself** (not in generated
templates, which are a separate concern) with list-form commands.

### 2.4 Fix broad `except:` clauses

**Priority:** Medium  
**Effort:** Small

Replace bare `except:` with `except Exception:` throughout all modules and
log the exception text to the GUI log widget rather than silently swallowing it.
This helps students diagnose issues in a lab environment.

---

## Phase 3 – Architecture Refactor

### 3.1 Extract shared logic into `fudmal/core/`

**Priority:** Medium  
**Effort:** Medium (2–4 hours)

The four standalone modules (`dropper.py`, `SFX.py`, `obfus.py`, `pdf.py`) and
`main.py` all duplicate:
- `IORedirector` class
- `build_dropper` / `create_executor_script` logic
- PyInstaller command construction and cleanup
- `VM_CHECK_CODE` / `VM_CHECK_FUNCTION` string constant

Proposed layout:

```
fudmal/
├── __init__.py
├── __main__.py
├── manifest.py          (already done)
├── core/
│   ├── __init__.py
│   ├── io_redirector.py  # IORedirector shared class
│   ├── pyinstaller.py    # build_onefile_exe(spec) → BuildResult
│   ├── cipher.py         # encode_bytes / decode_bytes (extracted from obfus.py)
│   └── templates.py      # PS_TEMPLATE and script-body constants
└── gui/
    ├── __init__.py
    ├── app.py            # UnifiedBuilderApp (main window + notebook)
    └── tabs/
        ├── dropper.py
        ├── sfx.py
        ├── obfuscator.py
        └── pdf_dropper.py
```

Benefits:
- Removes duplication across five files.
- Makes every builder independently unit-testable without launching Tkinter.
- Provides a CLI (`fudmal --headless --tool dropper_gen --config cfg.yaml`)
  path for CI-based exercises.

### 3.2 Add `BuildSpec` / `BuildResult` dataclasses

**Priority:** Low  
**Effort:** Small

Replace positional-argument functions with typed dataclasses:

```python
@dataclass
class BuildSpec:
    tool: str
    payload_path: Path
    decoy_path: Path | None
    output_path: Path
    enable_guardrail: bool
    ...

@dataclass
class BuildResult:
    success: bool
    output_path: Path | None
    manifest_path: Path | None
    error: str | None
```

---

## Phase 4 – Observability & Lab Value

### 4.1 Structured build log file

**Priority:** Medium  
**Effort:** Small

Alongside `manifest.json`, write a `build.log` with the full stdout/stderr
from PyInstaller (currently only shown in the GUI text area and lost on close).

### 4.2 MITRE ATT&CK documentation annotations

**Priority:** Low  
**Effort:** Small (docs-only)

Add a `docs/techniques.md` file that maps each tool tab to the relevant
ATT&CK technique IDs **at a documentation level only** (no code changes).
Example:
- Dropper Gen → T1059.001 (PowerShell), T1105 (Ingress Tool Transfer)
- Obfuscator → T1027 (Obfuscated Files or Information)
- SFX/PDF Dropper → T1036.007 (Masquerading: Double File Extension)

This helps blue-team students relate lab exercises to real-world detection priorities.

### 4.3 "Dry-run" mode

**Priority:** Low  
**Effort:** Medium

Add a `--dry-run` flag (CLI) and a checkbox (GUI) that prints what the tool
would do (PyInstaller command, temporary paths, expected output path) **without
actually executing anything**.  Useful for students reviewing the build process.

---

## Phase 5 – Developer Experience

### 5.1 `devcontainer.json` / Docker image

Provide a pre-configured VS Code Dev Container (or Dockerfile) with Python,
ruff, pytest, and a mock PyInstaller stub so contributors can develop on any OS.

### 5.2 Pre-commit hooks

Add a `.pre-commit-config.yaml` that runs ruff and the test suite before each
commit.

### 5.3 Contributing guide

Add `CONTRIBUTING.md` with:
- Lab-setup instructions (VM requirements)
- Code-review checklist (non-goals check)
- How to add a new scenario / builder tab

---

## Deferred / Out of Scope

The following are explicitly out of scope and will not be accepted:

- Improving effectiveness of AV evasion.
- Adding persistence, privilege escalation, or lateral-movement capabilities.
- Network-based C2 or propagation features.
- Any change whose primary purpose is to reduce detection by security tools.

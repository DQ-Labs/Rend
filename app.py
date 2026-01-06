import os
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox
import demucs.api
import torch
import soundfile as sf

# Force Dark Mode and Blue Theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

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
            separator = demucs.api.Separator(
                model=self.model_name,
                device="cpu",
                progress=True,
                callback=self.handle_progress
            )

            # 2. Start Separation
            self.callback(f"Loading {self.model_name}... (First run takes time)", 0.1)
            # shifts=1 is default, >1 is slower but better
            origin, separated = separator.separate_audio_file(self.input_file, shifts=self.shifts)

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
        self.title("Rend")
        self.geometry("600x650")
        self.resizable(False, False)
        self.file_path = None
        
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
            values=["htdemucs", "htdemucs_ft", "htdemucs_6s", "hdemucs_mmi", "mdx", "mdx_extra", "mdx_q"],
            width=140
        )
        self.opt_model.grid(row=0, column=1, padx=10, sticky="w")
        self.opt_model.set("htdemucs")

        # Quality Checkbox
        self.chk_quality = ctk.CTkCheckBox(self.frm_options, text="High Quality (Slow)")
        self.chk_quality.grid(row=1, column=0, columnspan=2, pady=(10, 5))
        
        # Karaoke Checkbox
        self.chk_karaoke = ctk.CTkCheckBox(self.frm_options, text="Karaoke Mode (2-Stems)")
        self.chk_karaoke.grid(row=2, column=0, columnspan=2, pady=5)

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
        self.progress_bar.grid(row=7, column=0, pady=(0, 40))

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

if __name__ == "__main__":
    app = App()
    app.mainloop()
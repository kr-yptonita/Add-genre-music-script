import os
import sys
import threading
import subprocess
import customtkinter as ctk
from tkinter import filedialog
from PIL import Image

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class TaggerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Mutagen Genre Tagger")
        self.geometry("700x650")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        # Header with Logo
        self.logo_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.logo_frame.grid(row=0, column=0, pady=(20, 10))
        
        try:
            logo_image = Image.open("Logo.png")
            # Redimensionar manteniendo la relación de aspecto
            logo_image.thumbnail((500, 150))
            self.logo = ctk.CTkImage(light_image=logo_image, dark_image=logo_image, size=logo_image.size)
            self.logo_label = ctk.CTkLabel(self.logo_frame, image=self.logo, text="")
            self.logo_label.pack()
        except Exception as e:
            print("Logo.png no encontrado o hubo un error al cargar:", e)

        # Folder selection
        self.folder_frame = ctk.CTkFrame(self)
        self.folder_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        self.folder_frame.grid_columnconfigure(1, weight=1)
        
        self.btn_select_folder = ctk.CTkButton(self.folder_frame, text="Seleccionar Carpeta", command=self.select_folder)
        self.btn_select_folder.grid(row=0, column=0, padx=10, pady=10)
        
        self.lbl_folder_path = ctk.CTkLabel(self.folder_frame, text="Ninguna carpeta seleccionada", anchor="w")
        self.lbl_folder_path.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.selected_path = ""

        # Options
        self.options_frame = ctk.CTkFrame(self)
        self.options_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        
        self.chk_subdirs = ctk.CTkCheckBox(self.options_frame, text="Buscar en subdirectorios")
        self.chk_subdirs.grid(row=0, column=0, padx=10, pady=10)
        self.chk_subdirs.select() # Default to recursive

        self.btn_theme = ctk.CTkButton(self.options_frame, text="Cambiar a Tema Claro", command=self.toggle_theme)
        self.btn_theme.grid(row=0, column=1, padx=20, pady=10)

        # Process button and progress
        self.btn_start = ctk.CTkButton(self, text="Iniciar Procesamiento", font=("Arial", 16, "bold"), height=40, command=self.start_processing)
        self.btn_start.grid(row=3, column=0, padx=20, pady=10)

        self.lbl_progress = ctk.CTkLabel(self, text="Esperando...", text_color="gray")
        self.lbl_progress.grid(row=4, column=0, padx=20, pady=5)

        # Summary text box
        self.summary_box = ctk.CTkTextbox(self, wrap="word", font=("Courier", 12))
        self.summary_box.grid(row=5, column=0, padx=20, pady=(10, 20), sticky="nsew")
        self.summary_box.insert("0.0", "--- Resumen de Resultados ---\n")
        self.summary_box.configure(state="disabled")

        self.process_thread = None

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.selected_path = folder
            self.lbl_folder_path.configure(text=folder)

    def toggle_theme(self):
        current = ctk.get_appearance_mode()
        if current == "Dark":
            ctk.set_appearance_mode("Light")
            self.btn_theme.configure(text="Cambiar a Tema Oscuro")
        else:
            ctk.set_appearance_mode("Dark")
            self.btn_theme.configure(text="Cambiar a Tema Claro")

    def append_summary(self, text):
        self.summary_box.configure(state="normal")
        self.summary_box.insert("end", text + "\n")
        self.summary_box.see("end")
        self.summary_box.configure(state="disabled")

    def start_processing(self):
        if not self.selected_path:
            self.lbl_progress.configure(text="Por favor, selecciona una carpeta primero.", text_color="red")
            return

        self.btn_start.configure(state="disabled")
        self.btn_select_folder.configure(state="disabled")
        self.chk_subdirs.configure(state="disabled")
        
        self.summary_box.configure(state="normal")
        self.summary_box.delete("0.0", "end")
        self.summary_box.insert("0.0", "--- Iniciando Procesamiento ---\n")
        self.summary_box.configure(state="disabled")

        self.lbl_progress.configure(text="Iniciando...", text_color="white")

        # Iniciar thread
        self.process_thread = threading.Thread(target=self.run_tagger, daemon=True)
        self.process_thread.start()

    def run_tagger(self):
        cmd = [sys.executable, "mutagen-tagger.py", "-p", self.selected_path]
        if not self.chk_subdirs.get():
            cmd.append("--no-recurse")

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        # Leemos output en tiempo real
        for line in iter(process.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
                
            # Parse output for progress updates
            if line.startswith("INFO: Found:"):
                # Mostrar archivo actual en la barra de progreso
                filepath = line.split("INFO: Found: ")[1]
                filename = os.path.basename(filepath)
                self.after(0, self.lbl_progress.configure, {"text": f"Procesando: {filename}", "text_color": "yellow"})
            
            # Enviar la línea al resumen
            self.after(0, self.append_summary, line)

        process.stdout.close()
        process.wait()

        self.after(0, self.processing_finished)

    def processing_finished(self):
        self.lbl_progress.configure(text="Procesamiento completado.", text_color="green")
        self.btn_start.configure(state="normal")
        self.btn_select_folder.configure(state="normal")
        self.chk_subdirs.configure(state="normal")
        self.append_summary("\n--- Procesamiento Completado ---")

if __name__ == "__main__":
    app = TaggerApp()
    # Inicializar estado correcto del botón de tema
    if ctk.get_appearance_mode() == "Dark":
        app.btn_theme.configure(text="Cambiar a Tema Claro")
    else:
        app.btn_theme.configure(text="Cambiar a Tema Oscuro")
    app.mainloop()

import tkinter as Tk
from tkinter import messagebox
from .widgets import integer_entry_box, float_entry_box, string_entry_box

class LocoConfigWindow(Tk.Toplevel):
    def __init__(self, parent, current_config, save_callback):
        super().__init__(parent)
        self.title("Locomotive Configuration")
        self.resizable(False, False)
        
        # Keep window pinned modally on top of the main app workspace
        self.transient(parent)  
        self.grab_set()         
        
        self.save_callback = save_callback
        self.entries = {}
        
        form_frame = Tk.Frame(self, padx=15, pady=15)
        form_frame.pack(fill=Tk.BOTH, expand=True)
        
        # Comprehensive layout mapping tracking all 12 core variables
        fields = [
            ("Locomotive Name:", string_entry_box, "loco_name", 
             {"max_length": 20, "tooltip": "Enter a name/number for the loco (Max 20 chars)"}),
            
            ("DCC Address:", integer_entry_box, "dcc_address", 
             {"min_val": 1, "max_val": 10239, "tooltip": "DCC address (Range: 1-10239)"}),
            
            ("DCC Speed Scaling:", float_entry_box, "dcc_speed_scaling",
             {"min_val": 0.1, "max_val": 1.0, "tooltip": "Top-end speed ceiling multiplier (0.1 - 1.0). 1.0 = full 127 steps, 0.5 = approx 64 steps max."}),
            
            ("Horsepower:", integer_entry_box, "loco_horsepower",
             {"min_val": 100, "max_val": 10000, "tooltip": "Authentic prime mover engine brake horsepower (BHP)"}),
            
            ("Weight (Tonnes):", integer_entry_box, "loco_mass", 
             {"min_val": 1, "max_val": 5000, "tooltip": "Total unladen mass plus scheduled rolling stock weight (Tonnes)"}),
            
            ("Max Speed (MPH):", integer_entry_box, "loco_max_speed", 
             {"min_val": 5, "max_val": 200, "tooltip": "Maximum physics limits governing dashboard dial gauge layout"}),
            
            ("Max Tractive Effort (lbf):", integer_entry_box, "max_tractive_effort", 
             {"min_val": 1000, "max_val": 200000, "tooltip": "Available locomotive starting torque specified in Pounds-force"}),
            
            ("Traction Responsiveness:", float_entry_box, "traction_responsiveness", 
             {"min_val": 0.001, "max_val": 1.0, "tooltip": "Power throttle engine spool-up delays (Typical: 0.01 - 0.1)"}),
            
            ("Brake Responsiveness:", float_entry_box, "brake_responsiveness", 
             {"min_val": 0.001, "max_val": 1.0, "tooltip": "Pneumatic cylinder drop responsiveness rates (Typical: 0.01 - 0.1)"}),
            
            ("Axle Offsets (ft, comma separated):", string_entry_box, "axle_offsets", 
             {"max_length": 100, "tooltip": "Axle positions from nose in feet to synchronize track-clack clicks"}),
            
            ("Forward Stream URL:", string_entry_box, "fwd_stream_url", 
             {"max_length": 255, "tooltip": "Forward ESPHome cab camera endpoint address (e.g., http://192.168.1.149:8080)"}),
             
            ("Reverse Stream URL:", string_entry_box, "rev_stream_url", 
             {"max_length": 255, "tooltip": "Reverse/Rear-facing cab camera endpoint address (e.g., http://192.168.1.150:8080)"}),
        ]
        
        # Render the input fields dynamically
        for row, (label_text, widget_class, key, extra_args) in enumerate(fields):
            Tk.Label(form_frame, text=label_text, anchor="w").grid(row=row, column=0, sticky="ew", pady=4, padx=(0, 10))
            
            width = 35 if widget_class == string_entry_box else 12
            widget = widget_class(form_frame, width=width, **extra_args)
            widget.grid(row=row, column=1, sticky="w" if width == 12 else "ew", pady=4)
            
            val = current_config.get(key, "")
            if key == "axle_offsets" and isinstance(val, list):
                val = ", ".join(map(str, val))
            widget.set(val)
            
            self.entries[key] = widget

        # --- Audio Options Row (Appended underneath the dynamically sized grid) ---
        audio_row = len(fields)
        Tk.Label(form_frame, text="Audio System Effects:", anchor="w").grid(row=audio_row, column=0, sticky="ew", pady=4, padx=(0, 10))
        
        self.sound_enabled_var = Tk.BooleanVar(value=current_config.get("sound_enabled", True))
        audio_check = Tk.Checkbutton(form_frame, text="Sound Enabled", variable=self.sound_enabled_var, highlightthickness=0)
        audio_check.grid(row=audio_row, column=1, sticky="w", pady=4)

        # Bottom Action Control Bar
        btn_frame = Tk.Frame(self, pady=10, bg="#f0f0f0")
        btn_frame.pack(fill=Tk.X, side=Tk.BOTTOM)
        
        Tk.Button(btn_frame, text="Cancel", width=10, command=self.destroy).pack(side=Tk.RIGHT, padx=10)
        Tk.Button(btn_frame, text="Apply Changes", width=12, command=self.validate_and_save).pack(side=Tk.RIGHT)

    def validate_and_save(self):
        # Programmatically trip FocusOut validations on all entry boxes to check for red text errors
        for field in self.entries.values():
            field.entry_box_updated()
            if field.cget('fg') == 'red':
                messagebox.showerror("Validation Error", "Please correct highlighted errors before saving.")
                return

        # Parse axle offsets back into a valid list of floats
        raw_axles = self.entries["axle_offsets"].get()
        try:
            axle_list = [float(x.strip()) for x in raw_axles.split(",") if x.strip() != ""]
        except ValueError:
            messagebox.showerror("Validation Error", "Axle offsets must be a clean list of numbers separated by commas.")
            return

        # Compile structural output payload safely matching your main dictionary requirements
        updated_config = {
            "loco_name": self.entries["loco_name"].get(),
            "dcc_address": self.entries["dcc_address"].get(),
            "dcc_speed_scaling": float(self.entries["dcc_speed_scaling"].get()),
            "loco_horsepower": int(self.entries["loco_horsepower"].get()),
            "loco_mass": int(self.entries["loco_mass"].get()),
            "loco_max_speed": int(self.entries["loco_max_speed"].get()),
            "max_tractive_effort": int(self.entries["max_tractive_effort"].get()),
            "traction_responsiveness": float(self.entries["traction_responsiveness"].get()),
            "brake_responsiveness": float(self.entries["brake_responsiveness"].get()),
            "axle_offsets": axle_list,
            "fwd_stream_url": self.entries["fwd_stream_url"].get(),
            "rev_stream_url": self.entries["rev_stream_url"].get(),
            "sound_enabled": self.sound_enabled_var.get()
        }
        
        self.save_callback(updated_config)
        self.destroy()
###############################################################################################
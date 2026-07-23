import tkinter as Tk
import threading
import time
import socket
import cv2
from PIL import Image, ImageTk
from zeroconf import Zeroconf, ServiceBrowser
from tkinter import ttk

from .widgets import integer_entry_box, float_entry_box, string_entry_box, axle_entry_box
from .widgets import ConfigControlBar

#----------------------------------------------------------------------------------------------------
# Loco Config Window
#----------------------------------------------------------------------------------------------------

class LocoConfigWindow(Tk.Toplevel):
    # Track singleton instance so only one non-modal config window can exist at a time.
    _active_instance = None

    @classmethod
    def open_or_focus(cls, parent, current_config, save_callback):
        # If window already exists, just raise and focus it.
        existing = cls._active_instance
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_force()
                    return existing
            except Exception:
                pass
        # Otherwise create a new one.
        window = cls(parent, current_config, save_callback)
        cls._active_instance = window
        return window

    def __init__(self, parent, current_config, save_callback):
        super().__init__(parent)
        self.title("Locomotive Configuration")
        self.resizable(False, False)
        # Non-modal behaviour (main app remains responsive), but keep window linked to parent.
        self.transient(parent)
        self.save_callback = save_callback
        self.initial_config = current_config
        self.entries = {}
        # Tracking dictionaries for discovered cameras
        self.discovered_cameras = {
            "None": "", "Manual URL Entry": ""}
        self.preview_thread_running = False
        self.current_preview_url = ""
        self.last_preview_selection_label = "None"
        self.last_preview_selection_url = ""
        self.preview_thread = None
        self.preview_generation = 0
        self.preview_token = 0
        # Outer Layout Split Frame
        main_layout = Tk.Frame(self)
        main_layout.pack(fill=Tk.BOTH, expand=True)
        # Left Side Form Layout
        form_frame = Tk.Frame(main_layout, padx=15, pady=10)
        form_frame.pack(side=Tk.LEFT, fill=Tk.BOTH, expand=True)
        # Right Side Preview Panel
        preview_frame = Tk.LabelFrame(main_layout, text="Live Camera Preview", padx=10, pady=10)
        preview_frame.pack(side=Tk.RIGHT, fill=Tk.BOTH, expand=True, padx=(0, 15), pady=10)
        self.preview_selection_label = Tk.Label(preview_frame, text="Selected Feed: None", fg="gray")
        self.preview_selection_label.pack(pady=(0, 5))
        self.preview_canvas = Tk.Canvas(preview_frame, width=320, height=240, bg="black")
        self.preview_canvas.pack()
        self.preview_image_id = self.preview_canvas.create_image(0, 0, anchor=Tk.NW, image=None)
        self.status_label = Tk.Label(preview_frame, text="Select a camera to preview", fg="gray")
        self.status_label.pack(pady=(5, 0))
        # Field configurations (Using custom types for streams)
        fields = [
            ("Locomotive Name:", string_entry_box, "loco_name",
             {"max_length": 20, "tooltip": "Enter a name/number for the locomotive (Max 20 chars)"}),
            ("DCC Address:", integer_entry_box, "dcc_address",
             {"min_val": 0, "max_val": 10239, "tooltip": "Enter the DCC address of the locomotive (Range: 1-10239)"}),
            ("DCC Speed Scaling:", float_entry_box, "dcc_speed_scaling",
             {"min_val": 0.1, "max_val": 1.0, "tooltip": "Top-end speed scaling factor (0.1-1.0). "+
                                                 "e.g. 1.0 for a full speed of 127 speed steps, "+
                                                 "e.g. 0.5 for a full speed of 64 speed steps"}),
            ("Horsepower:", integer_entry_box, "loco_horsepower",
             {"min_val": 100, "max_val": 10000, "tooltip": "Enter the engine brake horsepower of the locomotive (Range: 100-10000 BHP)"}),
            ("Weight (Tonnes):", integer_entry_box, "loco_mass_tonnes",
             {"min_val": 1, "max_val": 5000, "tooltip": "Enter the total unladen mass of the locomotive (Range: 1-5000 Tonnes)"}),
            ("Max Speed (MPH):", integer_entry_box, "loco_max_speed_mph",
             {"min_val": 5, "max_val": 200, "tooltip": "Enter the locomotive Maximum speed (Range: 5-200 MPH)"}),
            ("Max Tractive Effort (lbf):", integer_entry_box, "max_tractive_effort_lbf",
             {"min_val": 1000, "max_val": 200000, "tooltip": "Enter the available locomotive starting torque (Range: 1000-200000 lbf)"}),
            ("Traction Responsiveness:", float_entry_box, "traction_responsiveness",
             {"min_val": 0.001, "max_val": 1.0, "tooltip": "Power throttle engine spool-up delays (Typical: 0.01 - 0.1)"}),
            ("Brake Responsiveness:", float_entry_box, "brake_responsiveness",
             {"min_val": 0.001, "max_val": 1.0, "tooltip": "Air pressure drop responsiveness rate (Typical: 0.01 - 0.1)"}),
            ("Axle Offsets (ft, comma separated):", axle_entry_box, "axle_offsets_ft",
             {"max_length": 100, "tooltip": "Axle positions from front of the locomotive (in feet) to synchronize track-clack clicks "+
                                            "(e.g. 0.0, 7.0, 14.0, 40.0, 47.0, 54.0 for a Class 47 Co-Co)"}),
            ("Forward Stream URL:", "fwd_combo", "fwd_stream_url",
             {"max_length": 255, "tooltip": "Forward facing cab camera IP address/port (e.g. http://192.168.1.149:8080)"}),
            ("Reverse Stream URL:", "rev_combo", "rev_stream_url",
             {"max_length": 255, "tooltip": "Rear facing cab camera local IP address/port (e.g. http://192.168.1.150:8080)"})]
        # Render the input fields
        for row, (label_text, widget_class, key, extra_args) in enumerate(fields):
            Tk.Label(form_frame, text=label_text, anchor="w").grid(row=row, column=0, sticky="ew", pady=4, padx=(0, 10))
            val = current_config.get(key, "")
            if isinstance(widget_class, str):
                # Handle streaming dropdown elements
                widget = ttk.Combobox(form_frame, width=32, state="normal")
                widget.grid(row=row, column=1, sticky="ew", pady=4)
                widget.bind("<<ComboboxSelected>>", lambda e, k=key: self.on_camera_selected(k))
                widget.bind("<KeyRelease>", lambda e, k=key: self.on_camera_typed(k))
                widget.set(val)  # Set raw string URL initially as a fallback
            else:
                # Handle standard entry fields cleanly
                width = 40 if widget_class in (string_entry_box, axle_entry_box) else 12
                widget = widget_class(form_frame, width=width, **extra_args)
                widget.grid(row=row, column=1, sticky="w" if width == 12 else "ew", pady=4)
                widget.set(val)
            self.entries[key] = widget
        control_bar = ConfigControlBar(self,
            on_ok=lambda: self.validate_and_save(close_window=True),
            on_apply=lambda: self.validate_and_save(close_window=False),
            on_reset=self.reset_to_original,
            on_cancel=self.close_window)
        control_bar.pack(fill=Tk.X, pady=10, side=Tk.BOTTOM)
        # Trigger clean network discovery thread
        threading.Thread(target=self.scan_network, daemon=True).start()
        # Handle close cleanup to stop streaming threads safely
        self.protocol("WM_DELETE_WINDOW", self.close_window)

    # -------------------------------------------------------------------------
    # Safely shut down everything on window close
    # -------------------------------------------------------------------------

    def close_window(self):
        self.stop_preview_stream()
        self.current_preview_url = ""
        # 1. Break the loop inside stream_worker instantly
        self.preview_thread_running = False
        self.preview_generation += 1
        # 2. Reset tracking variables
        self.current_preview_url = ""
        # 3. Clear canvas image references to free up memory buffers
        try:
            self.preview_canvas.itemconfig(self.preview_image_id, image="")
            self.preview_canvas.delete("preview_text")
            self.preview_canvas.image = None
        except Exception:
            pass # UI widgets might already be closing, pass safely
        # 4. Clear active-instance tracker
        if LocoConfigWindow._active_instance is self:
            LocoConfigWindow._active_instance = None
        # 5. Destroy the Toplevel window block completely
        self.destroy()

    # -------------------------------------------------------------------------
    # Network Scanning Logic
    # -------------------------------------------------------------------------

    def scan_network(self):
        class ESPHomeDiscovery:
            def __init__(self, callback):
                self.callback = callback
            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name)
                if info:
                    for address in info.addresses:
                        try:
                            ip = socket.inet_ntoa(address)
                        except Exception:
                            continue
                        clean_name = name.split('.')[0]
                        # ESPHome camera default streaming port is 8080
                        url = f"http://{ip}:8080"
                        self.callback(clean_name, url)
            def update_service(self, zc, type_, name):
                pass

            def remove_service(self, zc, type_, name):
                pass
        zeroconf = Zeroconf()
        listener = ESPHomeDiscovery(self.register_discovered_camera)
        # Use the underscore to silence the pyflakes warning about unused variable
        _ = ServiceBrowser(zeroconf, ["_esphomelib._tcp.local.", "_http._tcp.local."], listener)
        time.sleep(2.0)  # Scan broadcasts for 2 seconds
        zeroconf.close()

    def register_discovered_camera(self, name, url):
        display_label = f"{name} ({url})"
        self.discovered_cameras[display_label] = url
        # Safely update the combo selections inside the main Tkinter thread loop
        self.after(0, self.update_camera_dropdown_values)

    def update_camera_dropdown_values(self):
        options = list(self.discovered_cameras.keys())
        for key in ["fwd_stream_url", "rev_stream_url"]:
            combo = self.entries[key]
            current_val = combo.get()
            combo['values'] = options
            # Map backwards if the saved config matches an IP we just discovered
            for label, url in self.discovered_cameras.items():
                if current_val == url:
                    combo.set(label)
                    break

    # -------------------------------------------------------------------------
    # Preview Handler
    # -------------------------------------------------------------------------

    def set_last_preview_selection(self, label, url):
        self.last_preview_selection_label = label if label else "None"
        self.last_preview_selection_url = url.strip() if isinstance(url, str) else ""
        if hasattr(self, "preview_selection_label") and self.preview_selection_label.winfo_exists():
            self.preview_selection_label.config(text=f"{self.last_preview_selection_label}")
            
    def show_no_feed_preview(self, message="No feed selected"):
        self.stop_preview_stream()
        try:
            self.preview_canvas.itemconfig(self.preview_image_id, image="")
            self.preview_canvas.delete("preview_text")
            self.preview_canvas.create_text(160, 120, text=message, fill="white", font=("Arial", 12), tags="preview_text")
            self.preview_canvas.image = None
        except Exception:
            pass
        if hasattr(self, "status_label") and self.status_label.winfo_exists():
            self.status_label.config(text=message, fg="gray")
            
    def stop_preview_stream(self, wait=False, timeout=1.5):
        self.preview_thread_running = False
        self.preview_generation += 1
        self.preview_token += 1   # invalidate all queued UI callbacks from old stream
        if wait and self.preview_thread is not None and self.preview_thread.is_alive():
            try:
                self.preview_thread.join(timeout=timeout)
            except Exception:
                pass
        self.preview_thread = None
        
    def on_camera_selected(self, key):
        selected_label = self.entries[key].get().strip()
        target_url = self.discovered_cameras.get(selected_label, selected_label).strip()
        self.set_last_preview_selection(selected_label if selected_label else "None", target_url)
        if target_url:
            if target_url != self.current_preview_url:
                self.current_preview_url = target_url
                self.start_preview_stream(target_url)
        else:
            self.current_preview_url = ""
            self.show_no_feed_preview("No feed selected")
            
    def on_camera_typed(self, key):
        typed_url = self.entries[key].get().strip()
        self.set_last_preview_selection("Custom / Manual", typed_url)
        if typed_url.startswith("http://") or typed_url.startswith("rtsp://") or typed_url.startswith("https://"):
            if typed_url != self.current_preview_url:
                self.current_preview_url = typed_url
                self.start_preview_stream(typed_url)
        elif typed_url == "":
            self.current_preview_url = ""
            self.show_no_feed_preview("No feed selected")
            
    def start_preview_stream(self, url):
        self.stop_preview_stream(wait=True)
        self.status_label.config(text="Connecting to stream...", fg="orange")
        self.current_preview_url = url
        self.preview_thread_running = True
        self.preview_generation += 1
        this_generation = self.preview_generation
        this_token = self.preview_token
        self.preview_thread = threading.Thread(target=self.stream_worker, args=(url, this_generation, this_token), daemon=True)
        self.preview_thread.start()

    def stream_worker(self, url, generation, token):
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        try: cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 1200)
        except Exception: pass
        try: cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 400)
        except Exception: pass
        try: cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception: pass
        if cap is None or not cap.isOpened():
            self.after(0, lambda g=generation, t=token:
                self._safe_preview_status("Unable to open stream", "red", g, t))
            try: cap.release()
            except Exception: pass
            return
        while self.preview_thread_running and generation == self.preview_generation and url == self.current_preview_url:
            ret, frame = cap.read()
            if not ret:
                self.after(0, lambda g=generation, t=token:
                    self._safe_preview_status("Stream disconnected or unavailable", "red", g, t))
                break
            self.after(0, lambda g=generation, t=token:
                self._safe_preview_status("Streaming Active", "green", g, t))
            frame = cv2.resize(frame, (320, 240))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img_tk = ImageTk.PhotoImage(image=Image.fromarray(frame))
            self.after(0, lambda image=img_tk, g=generation, t=token:
                self.draw_frame(image, g, t))
            time.sleep(0.05)
        cap.release()

    def _safe_preview_status(self, text, color, generation, token):
        if token != self.preview_token: return
        if generation != self.preview_generation: return
        if hasattr(self, "status_label") and self.status_label.winfo_exists():
            self.status_label.config(text=text, fg=color)
            
    def draw_frame(self, img_tk, generation, token):
        if token != self.preview_token:
            return
        if generation != self.preview_generation:
            return
        if self.preview_thread_running:
            self.preview_canvas.delete("preview_text")
            self.preview_canvas.itemconfig(self.preview_image_id, image=img_tk)
            self.preview_canvas.image = img_tk

    # -------------------------------------------------------------------------
    # Data Validation and Pipeline Handling
    # -------------------------------------------------------------------------

    def validate_and_save(self, close_window=True):
        # Run validators for custom entries (new baseline widgets expose validate()).
        for key, field in self.entries.items():
            # Skip combobox stream fields (manual validation handled below)
            if key in ("fwd_stream_url", "rev_stream_url"):
                continue
            if hasattr(field, 'validate'):
                if not field.validate():
                    return
            elif hasattr(field, 'entry_box_updated'):
                # Backward compatibility fallback
                field.entry_box_updated()
                if field.cget('fg') == 'red':
                    return
        # Manual validation for stream URLs (allow blank; if set, must look like URL)
        fwd_label = self.entries["fwd_stream_url"].get().strip()
        rev_label = self.entries["rev_stream_url"].get().strip()
        fwd_url = self.discovered_cameras.get(fwd_label, fwd_label).strip()
        rev_url = self.discovered_cameras.get(rev_label, rev_label).strip()
        if fwd_url and not (fwd_url.startswith("http://") or fwd_url.startswith("https://") or fwd_url.startswith("rtsp://")):
            self.status_label.config(text="Forward stream URL must start with http://, https://, or rtsp://", fg="red")
            return
        if rev_url and not (rev_url.startswith("http://") or rev_url.startswith("https://") or rev_url.startswith("rtsp://")):
            self.status_label.config(text="Reverse stream URL must start with http://, https://, or rtsp://", fg="red")
            return
        updated_config = {
            "loco_name": self.entries["loco_name"].get(),
            "dcc_address": self.entries["dcc_address"].get(),
            "dcc_speed_scaling": self.entries["dcc_speed_scaling"].get(),
            "loco_horsepower": self.entries["loco_horsepower"].get(),
            "loco_mass_tonnes": self.entries["loco_mass_tonnes"].get(),
            "loco_max_speed_mph": self.entries["loco_max_speed_mph"].get(),
            "max_tractive_effort_lbf": self.entries["max_tractive_effort_lbf"].get(),
            "traction_responsiveness": self.entries["traction_responsiveness"].get(),
            "brake_responsiveness": self.entries["brake_responsiveness"].get(),
            "axle_offsets_ft": self.entries["axle_offsets_ft"].get(),
            "fwd_stream_url": fwd_url,
            "rev_stream_url": rev_url}
        # Disconnect preview stream before saving, so main app can take the feed immediately.
        self.stop_preview_stream(wait=True)
        self.current_preview_url = ""
        self.status_label.config(text="Stream Released", fg="gray")
        self.preview_canvas.itemconfig(self.preview_image_id, image="")
        self.preview_canvas.delete("preview_text")
        self.preview_canvas.create_text(160, 120, text="Preview paused", fill="white", font=("Arial", 12), tags="preview_text")
        self.preview_canvas.image = None
        # Save the updated config
        self.save_callback(updated_config)
        if close_window:
            self.close_window()

    def reset_to_original(self):
        for key, widget in self.entries.items():
            original_val = self.initial_config.get(key, "")
            widget.set(original_val)
            if hasattr(widget, 'validate'):
                widget.validate()
            elif hasattr(widget, 'entry_box_updated'):
                widget.entry_box_updated()

###############################################################################################
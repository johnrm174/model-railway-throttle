import copy
import os
import threading
import subprocess
import tempfile
import yaml
import shutil
import queue
import tkinter as Tk
from tkinter import filedialog, messagebox, ttk
from importlib import resources
import serial.tools.list_ports
from .widgets import dropdown_box, string_entry_box, check_box

# -----------------------------------------------------------------------------
# ESPHome YAML Wrapper -Small model wrapper around the ESPHome YAML dictionary.
#   - Holds original template and current editable data
#   - Exposes property accessors used by the UI layer
# -----------------------------------------------------------------------------

class ESPHomeYaml:
    def __init__(self, template_dictionary):
        # Keep an immutable-ish copy of the template and a working mutable copy.
        self.template = copy.deepcopy(template_dictionary)
        self.filename = None
        self.data = copy.deepcopy(self.template)

    def new(self):
        # Reset current in-memory config back to packaged template defaults.
        self.data = copy.deepcopy(self.template)
        self.filename = None

    def load(self, filename):
        # Load YAML from disk into current working data.
        with open(filename, "r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}
        self.filename = filename

    def save(self, filename=None):
        # Save current working data to disk.
        if filename is not None:
            self.filename = filename
        if self.filename is None:
            raise RuntimeError("No filename has been specified.")
        with open(self.filename, "w", encoding="utf-8") as f:
            yaml.dump(self.data, f, sort_keys=False)

    # -----------------------------
    # WiFi properties
    # -----------------------------
    
    @property
    def ssid(self):
        return self.data.get("wifi", {}).get("ssid", "")

    @ssid.setter
    def ssid(self, value):
        self.data.setdefault("wifi", {})
        self.data["wifi"]["ssid"] = value

    @property
    def device_name(self):
        return self.data.get("esphome", {}).get("name", "")

    @device_name.setter
    def device_name(self, value):
        self.data.setdefault("esphome", {})
        self.data["esphome"]["name"] = value

    @property
    def friendly_name(self):
        return self.data.get("esphome", {}).get("friendly_name", "")

    @friendly_name.setter
    def friendly_name(self, value):
        self.data.setdefault("esphome", {})
        self.data["esphome"]["friendly_name"] = value

    @property
    def password(self):
        return self.data.get("wifi", {}).get("password", "")

    @password.setter
    def password(self, value):
        self.data.setdefault("wifi", {})
        self.data["wifi"]["password"] = value

    # -----------------------------
    # Camera properties
    # -----------------------------
    
    @property
    def resolution(self):
        return self.data.get("esp32_camera", {}).get("resolution", "")

    @resolution.setter
    def resolution(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["resolution"] = value

    @property
    def frame_rate(self):
        # ESPHome stores frame rate text like "10 fps" in this field.
        txt = str(self.data.get("esp32_camera", {}).get("max_framerate", "0 fps"))
        return int(txt.split()[0]) if txt else 0

    @frame_rate.setter
    def frame_rate(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["max_framerate"] = f"{int(value)} fps"

    @property
    def jpeg_quality(self):
        return self.data.get("esp32_camera", {}).get("jpeg_quality", 10)

    @jpeg_quality.setter
    def jpeg_quality(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["jpeg_quality"] = int(value)

    @property
    def frame_buffers(self):
        return self.data.get("esp32_camera", {}).get("frame_buffer_count", 1)

    @frame_buffers.setter
    def frame_buffers(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["frame_buffer_count"] = int(value)

    @property
    def vertical_flip(self):
        return self.data.get("esp32_camera", {}).get("vertical_flip", False)

    @vertical_flip.setter
    def vertical_flip(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["vertical_flip"] = bool(value)

    @property
    def horizontal_mirror(self):
        return self.data.get("esp32_camera", {}).get("horizontal_mirror", False)

    @horizontal_mirror.setter
    def horizontal_mirror(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["horizontal_mirror"] = bool(value)

# -----------------------------------------------------------------------------
# Camera Configuration Window - Non-modal Toplevel editor for ESPHome camera YAML.
#   - Single instance window with open_or_focus()
#   - Main app remains usable while this window is open
#   - Launches esphome run in background thread
#   - Streams CLI output to Tk text log via queue
# -----------------------------------------------------------------------------

class CameraConfigUtility(Tk.Toplevel):
    _instance = None
    _NO_PORTS_SENTINEL = "No ports detected"

    @classmethod
    def open_or_focus(cls, parent):
        # Enforce a single window instance:
        # if already open, bring it to the front and focus.
        if cls._instance is not None and cls._instance.winfo_exists():
            w = cls._instance
            w.deiconify()
            w.lift()
            w.focus_force()
            return w
        cls._instance = cls(parent)
        return cls._instance

    def __init__(self, parent):
        super().__init__(parent)
        # Window setup:
        # - Non-modal (no grab_set), so main app remains interactive.
        # - transient(parent) keeps window related to parent in window manager.
        self.title("ESPHome Camera Configuration")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Load packaged default template:
        # Expected path: video_throttle/resources/esphome_template.yaml
        resource_path = resources.files('video_throttle').joinpath('resources', 'esphome_template.yaml')
        with resource_path.open('r', encoding='utf-8') as f:
            template_data = yaml.safe_load(f) or {}
        self.yaml = ESPHomeYaml(template_data)
        # Track a temporary file used when flashing an unsaved config.
        self._temp_flash_config_path = None
        # Build root form container.
        self.entries = {}
        form_frame = Tk.Frame(self, padx=10, pady=10)
        form_frame.pack(fill=Tk.BOTH, expand=True)
        # ---------------------------------------------------------
        # Configuration File group
        # ---------------------------------------------------------
        file_group = Tk.LabelFrame(form_frame, text="Configuration File", padx=10, pady=8)
        file_group.pack(fill=Tk.X, pady=(0, 8))
        Tk.Label(file_group, text="Current File:").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.filename_var = Tk.StringVar(value="None")
        Tk.Label(file_group, textvariable=self.filename_var, width=40, anchor="w").grid(row=0, column=1, columnspan=3, sticky="w")
        self.new_button = Tk.Button(file_group, text="New", width=10, command=self.new_file)
        self.new_button.grid(row=1, column=0, pady=(8, 0))
        self.load_button = Tk.Button(file_group, text="Load...", width=10, command=self.load_file)
        self.load_button.grid(row=1, column=1, pady=(8, 0), padx=5)
        self.save_button = Tk.Button(file_group, text="Save...", width=10, command=lambda: self.save_file(save_as=False))
        self.save_button.grid(row=1, column=2, pady=(8, 0), padx=5)
        self.save_as_button = Tk.Button(file_group, text="Save as...", width=14, command=lambda: self.save_file(save_as=True))
        self.save_as_button.grid(row=1, column=3, pady=(8, 0), padx=(5, 0))
        # ---------------------------------------------------------
        # WiFi group
        # ---------------------------------------------------------
        wifi_group = Tk.LabelFrame(form_frame, text="WiFi Settings", padx=10, pady=10)
        wifi_group.pack(fill=Tk.X, pady=(0, 10))
        wifi_fields = [("SSID:", string_entry_box, "ssid", {"max_length": 32, "tooltip": "Wireless network name."}), ("Password:", string_entry_box, "password", {"max_length": 64, "tooltip": "Wireless password."})]
        self.render_fields(wifi_group, wifi_fields)
        # ---------------------------------------------------------
        # Device metadata group
        # ---------------------------------------------------------
        metadata_group = Tk.LabelFrame(form_frame, text="Device Metadata", padx=10, pady=10)
        metadata_group.pack(fill=Tk.X, pady=(0, 10))
        metadata_fields = [("Device Name:", string_entry_box, "device_name", {"max_length": 10, "tooltip": "Device identifier (lowercase, no spaces, max 10 characters)"}), ("Friendly Name:", string_entry_box, "friendly_name", {"max_length": 50, "tooltip": "Human-readable name"})]
        self.render_fields(metadata_group, metadata_fields)
        # ---------------------------------------------------------
        # Camera settings group
        # ---------------------------------------------------------
        camera_group = Tk.LabelFrame(form_frame, text="Camera Settings", padx=10, pady=10)
        camera_group.pack(fill=Tk.X)
        RESOLUTION_OPTIONS = ["1600x1200", "1280x1024", "1024x768", "800x600", "640x480", "400x296", "320x240", "240x176", "160x120"]
        FRAME_RATE_OPTIONS = ["1", "5", "10", "15", "20", "25", "30", "60"]
        JPEG_QUALITY_OPTIONS = [str(i) for i in range(10, 64, 5)]
        FRAME_BUFFER_OPTIONS = ["1", "2", "3", "4"]
        camera_fields = [("Resolution:", dropdown_box, "resolution", {"values": RESOLUTION_OPTIONS, "tooltip": "Frame resolution (UXGA down to QQVGA)"}), ("Frame Rate:", dropdown_box, "frame_rate", {"values": FRAME_RATE_OPTIONS, "tooltip": "Maximum camera frame rate (fps)"}), ("JPEG Quality:", dropdown_box, "jpeg_quality", {"values": JPEG_QUALITY_OPTIONS, "tooltip": "JPEG quality (10 is best quality, 63 is lowest)"}), ("Frame Buffers:", dropdown_box, "frame_buffers", {"values": FRAME_BUFFER_OPTIONS, "tooltip": "Number of camera frame buffers in PSRAM"})]
        self.render_fields(camera_group, camera_fields)
        self.vflip = check_box(camera_group, width=30, label="Vertical Flip", tooltip="Flip image vertically.")
        self.vflip.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.entries["vertical_flip"] = self.vflip
        self.hmirror = check_box(camera_group, width=30, label="Horizontal Mirror", tooltip="Mirror image horizontally.")
        self.hmirror.grid(row=5, column=0, columnspan=2, sticky="w")
        self.entries["horizontal_mirror"] = self.hmirror
        # ---------------------------------------------------------
        # Flash/build + log group
        # ---------------------------------------------------------
        flash_group = Tk.LabelFrame(form_frame, text="Flash / Build", padx=10, pady=10)
        flash_group.pack(fill=Tk.Y, pady=(10, 0), expand=True)
        flash_group.rowconfigure(1, weight=1)
        flash_group.columnconfigure(0, weight=0)
        top_row = Tk.Frame(flash_group)
        top_row.grid(row=0, column=0, sticky="w")
        self.auto_ports_button = Tk.Button(top_row, text="Detect Ports", command=self.detect_ports)
        self.auto_ports_button.pack(side=Tk.LEFT)
        Tk.Label(top_row, text="Device Port:").pack(side=Tk.LEFT, padx=(10, 4))
        self.device_var = Tk.StringVar()
        self.device_combobox = ttk.Combobox(top_row, textvariable=self.device_var, state="readonly", width=20)
        self.device_combobox.pack(side=Tk.LEFT)
        self.flash_button = Tk.Button(top_row, text="Flash Camera", command=self.flash_device, bg="#4caf50", fg="white")
        self.flash_button.pack(side=Tk.LEFT, padx=(10, 8))
        self.abort_button = Tk.Button(top_row, text="Abort", command=self.abort_flash, state="disabled")
        self.abort_button.pack(side=Tk.LEFT)     
        # Log widget container with both scrollbars:
        # - vertical: track long output
        # - horizontal: preserve unwrapped lines for CLI readability
        log_container = Tk.Frame(flash_group)
        log_container.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.log_text = Tk.Text(log_container, width=60, height=12, wrap="none")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(log_container, orient="vertical", command=self.log_text.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=y_scroll.set)
        x_scroll = ttk.Scrollbar(log_container, orient="horizontal", command=self.log_text.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(xscrollcommand=x_scroll.set)
        log_container.rowconfigure(0, weight=1)
        log_container.columnconfigure(0, weight=1)
        flash_group.rowconfigure(1, weight=1)
        self.log_text.insert(Tk.END, "Logs will appear here...\n")
        # Thread/process/log queue coordination state.
        self._flash_thread = None
        self._flash_proc = None
        self._log_queue = queue.Queue()
        self._log_poller_running = False
        # Initialize UI from template and detect connected ports now.
        self.update_ui()
        self.detect_ports()

    def _on_close(self):
        # If flashing is active, confirm before closing.
        # All dialogs are parented to this window to keep them above this Toplevel.
        if self._flash_proc is not None:
            if not messagebox.askyesno("Flash in progress", "Flashing/build is in progress. Close this window anyway?", parent=self):
                return
            self.abort_flash()
        self._cleanup_temp_flash_file()
        CameraConfigUtility._instance = None
        self.destroy()

    def render_fields(self, container, fields):
        # Shared dynamic field renderer for text/dropdown rows.
        container.columnconfigure(1, weight=1)
        for row, (label_text, widget_class, key, extra_args) in enumerate(fields):
            Tk.Label(container, text=label_text, anchor="w").grid(row=row, column=0, sticky="ew", padx=(0, 10), pady=4)
            width = 30 if widget_class == string_entry_box else 8
            widget = widget_class(container, width=width, **extra_args)
            widget.grid(row=row, column=1, sticky="w", pady=4)
            self.entries[key] = widget

    def _is_widget_valid(self, widget):
        # Preferred path: widget supplies explicit is_valid().
        if hasattr(widget, "is_valid") and callable(widget.is_valid):
            try:
                return bool(widget.is_valid())
            except Exception:
                return False
        # Compatibility path: trigger widget internal update hook.
        if hasattr(widget, "entry_box_updated") and callable(widget.entry_box_updated):
            try:
                widget.entry_box_updated()
            except Exception:
                pass
        # Legacy fallback: red foreground means invalid.
        if hasattr(widget, "cget"):
            try:
                return widget.cget("fg") != "red"
            except Exception:
                return True
        return True

    def update_ui(self):
        # Push model values -> UI controls.
        self.entries["ssid"].set(self.yaml.ssid)
        self.entries["password"].set(self.yaml.password)
        self.entries["resolution"].set(self.yaml.resolution)
        self.entries["frame_rate"].set(self.yaml.frame_rate)
        self.entries["jpeg_quality"].set(self.yaml.jpeg_quality)
        self.entries["frame_buffers"].set(self.yaml.frame_buffers)
        self.entries["vertical_flip"].set(self.yaml.vertical_flip)
        self.entries["horizontal_mirror"].set(self.yaml.horizontal_mirror)
        self.entries["device_name"].set(self.yaml.device_name)
        self.entries["friendly_name"].set(self.yaml.friendly_name)
        self.filename_var.set(os.path.basename(self.yaml.filename) if self.yaml.filename else "None")

    def update_yaml(self):
        # Push UI control values -> model.
        self.yaml.ssid = self.entries["ssid"].get()
        self.yaml.password = self.entries["password"].get()
        self.yaml.resolution = self.entries["resolution"].get()
        try:
            self.yaml.frame_rate = int(self.entries["frame_rate"].get())
        except Exception:
            self.yaml.frame_rate = 0
        try:
            self.yaml.jpeg_quality = int(self.entries["jpeg_quality"].get())
        except Exception:
            self.yaml.jpeg_quality = 10
        try:
            self.yaml.frame_buffers = int(self.entries["frame_buffers"].get())
        except Exception:
            self.yaml.frame_buffers = 1
        self.yaml.vertical_flip = bool(self.entries["vertical_flip"].get())
        self.yaml.device_name = self.entries["device_name"].get()
        self.yaml.friendly_name = self.entries["friendly_name"].get()
        self.yaml.horizontal_mirror = bool(self.entries["horizontal_mirror"].get())

    def new_file(self):
        # Reset to template defaults.
        self.yaml.new()
        self.update_ui()

    def load_file(self):
        # Open file chooser parented to this window to avoid z-order issues.
        filename = filedialog.askopenfilename(parent=self, title="Load ESPHome Configuration", filetypes=[("ESPHome YAML Files", "*.yaml"), ("YAML Files", "*.yml"), ("All Files", "*.*")])
        if not filename:
            return
        try:
            self.yaml.load(filename)
            self.update_ui()
        except Exception as ex:
            messagebox.showerror("Load Failed", str(ex), parent=self)

    def save_file(self, save_as: bool = False):
        # Validate before save.
        if not self.validate():
            messagebox.showwarning("Validation Failed", "Please fix invalid fields before saving.", parent=self)
            return
        self.update_yaml()
        # Resolve target filename.
        if save_as or self.yaml.filename is None or self.yaml.filename == "None":
            filename = filedialog.asksaveasfilename(parent=self, title="Save ESPHome Configuration", defaultextension=".yaml", filetypes=[("ESPHome YAML Files", "*.yaml"), ("YAML Files", "*.yml"), ("All Files", "*.*")])
            if not filename:
                return
        else:
            filename = self.yaml.filename
        # Save without success popup (requested behavior).
        try:
            self.yaml.save(filename)
            self.update_ui()
        except Exception as ex:
            messagebox.showerror("Save Failed", str(ex), parent=self)

    def validate(self):
        # Validate all known entry widgets.
        for widget in self.entries.values():
            if not self._is_widget_valid(widget):
                return False
        return True

    def detect_ports(self):
        # Enumerate currently connected serial ports and fill combobox.
        active_ports = serial.tools.list_ports.comports()
        port_list = [port.device for port in active_ports if getattr(port, "device", None)]
        if port_list:
            self.device_combobox["values"] = port_list
            # Pick a practical default:
            # Linux SBC often ttyUSB/ttyACM, Windows often COMx.
            default_port = port_list[0]
            for port in port_list:
                if "ttyUSB" in port or "ttyACM" in port or port.startswith("COM"):
                    default_port = port
                    break
            self.device_combobox.set(default_port)
        else:
            self.device_combobox["values"] = []
            self.device_combobox.set(self._NO_PORTS_SENTINEL)

    def _cleanup_temp_flash_file(self):
        # Remove temp config file created for unsaved flash runs.
        if self._temp_flash_config_path and os.path.exists(self._temp_flash_config_path):
            try:
                os.remove(self._temp_flash_config_path)
            except Exception:
                pass
        self._temp_flash_config_path = None

    def flash_device(self):
        # Validate + sync UI->model first.
        if not self.validate():
            messagebox.showwarning("Validation Failed", "Please fix invalid fields before flashing.", parent=self)
            return
        self.update_yaml()
        # Ensure config exists on disk before calling CLI.
        if self.yaml.filename is None:
            fd, tempname = tempfile.mkstemp(suffix=".yaml", prefix="esphome_")
            os.close(fd)
            try:
                self.yaml.save(tempname)
            except Exception as ex:
                self._cleanup_temp_flash_file()
                messagebox.showerror("Save Failed", str(ex), parent=self)
                return
            config_path = tempname
            self._temp_flash_config_path = tempname
        else:
            config_path = self.yaml.filename
            self._temp_flash_config_path = None
            try:
                self.yaml.save(config_path)
            except Exception as ex:
                messagebox.showerror("Save Failed", str(ex), parent=self)
                return
        # Resolve device selection.
        device = self.device_combobox.get().strip()
        if device == self._NO_PORTS_SENTINEL:
            device = ""
        if device == "":
            resp = messagebox.askyesno("No device specified", "No device port specified. Run 'esphome run' and choose device interactively?", parent=self)
            if not resp:
                self._cleanup_temp_flash_file()
                return
        # Build command.
        cmd = ["esphome", "run", config_path]
        if device:
            cmd += ["--device", device]
        # Prepare log UI and launch background worker thread.
        self.log_text.delete("1.0", Tk.END)
        self.log_text.insert(Tk.END, f"Running: {' '.join(cmd)}\n\n")
        self.flash_button.config(state="disabled")
        self.abort_button.config(state="normal")
        self._log_queue = queue.Queue()
        self._flash_thread = threading.Thread(target=self._run_subprocess, args=(cmd,), daemon=True)
        self._flash_thread.start()
        # Start log poller once.
        if not self._log_poller_running:
            self._log_poller_running = True
            self.after(100, self._poll_logs)

    def abort_flash(self):
        # Request graceful stop first.
        if self._flash_proc:
            try:
                self._log_queue.put("Abort requested. Sending terminate...\n")
                self._flash_proc.terminate()
            except Exception:
                pass
        self.abort_button.config(state="disabled")

    def _run_subprocess(self, cmd):
        # Runs in background thread - Does NOT call Tk APIs directly (communicates through queue)
        try:
            esphome_bin = shutil.which(cmd[0])
            if esphome_bin is None:
                self._log_queue.put("esphome executable not found on PATH. Please install esphome CLI (pip install esphome).\n")
                return
            self._flash_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, text=True)
            for line in self._flash_proc.stdout:
                self._log_queue.put(line)
            self._flash_proc.wait(timeout=2)
            ret = self._flash_proc.returncode
            self._log_queue.put(f"\nProcess finished with return code {ret}\n")
        except subprocess.TimeoutExpired:
            # If process ignores terminate, escalate to kill.
            try:
                self._log_queue.put("Process did not terminate in time. Sending kill...\n")
                self._flash_proc.kill()
                self._flash_proc.wait(timeout=2)
                self._log_queue.put("\nProcess killed.\n")
            except Exception as ex:
                self._log_queue.put(f"\nFailed to kill process cleanly: {ex}\n")
        except Exception as ex:
            self._log_queue.put(f"\nFlashing failed: {ex}\n")
        finally:
            self._flash_proc = None
            self._cleanup_temp_flash_file()
            self._log_queue.put("__DONE__\n")

    def _poll_logs(self):
        # Runs on Tk main thread - drains log queue, updates Text widget and finalizes button state when run is complete
        try:
            while True:
                line = self._log_queue.get_nowait()
                if line == "__DONE__\n":
                    self.flash_button.config(state="normal")
                    self.abort_button.config(state="disabled")
                    self._log_poller_running = False
                    return
                self.log_text.insert(Tk.END, line)
                self.log_text.see(Tk.END)
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)
    
###################################################################################################
    
    
    
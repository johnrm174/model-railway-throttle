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
from .widgets import dropdown_box, string_entry_box, check_box, CreateToolTip

#--------------------------------------------------------------------------------------
# ESPHome YAML Wrapper -Small model wrapper around the ESPHome YAML dictionary.
#   - Holds original template and current editable data
#   - Exposes property accessors used by the UI layer
#--------------------------------------------------------------------------------------

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
            yaml.dump(self.data, f, sort_keys=False, default_flow_style=False)

    #-----------------------------
    # Camera Metadata
    #-----------------------------
    
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

    #-----------------------------
    # WiFi properties
    #-----------------------------

    @property
    def wifi_networks(self):
        # Return list of network dicts with ssid, password, priority
        networks = self.data.get("wifi", {}).get("networks", [])
        # Ensure we always return a list (even if empty)
        return networks if isinstance(networks, list) else []

    @wifi_networks.setter
    def wifi_networks(self, value):
        self.data.setdefault("wifi", {})
        if value and isinstance(value, list):
            self.data["wifi"]["networks"] = value
        elif "networks" in self.data["wifi"]:
            del self.data["wifi"]["networks"]

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

    #-----------------------------
    # Camera properties
    #-----------------------------
    
    @property
    def resolution(self):
        return self.data.get("esp32_camera", {}).get("resolution", "")

    @resolution.setter
    def resolution(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["resolution"] = value

    @property
    def frame_rate(self):
        # FIXED: Robustly handle both "10 fps" and "10" formats
        txt = str(self.data.get("esp32_camera", {}).get("max_framerate", "0"))
        # Extract the numeric part (handles "10 fps" -> "10" or "10" -> "10")
        txt_stripped = txt.split()[0] if txt else "0"
        try:
            return int(txt_stripped)
        except ValueError:
            return 0

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
        
    @property
    def brightness(self):
        return self.data.get("esp32_camera", {}).get("brightness", 0)

    @brightness.setter
    def brightness(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["brightness"] = int(value)

    @property
    def contrast(self):
        return self.data.get("esp32_camera", {}).get("contrast", 0)

    @contrast.setter
    def contrast(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["contrast"] = int(value)

#--------------------------------------------------------------------------------------
# WiFi Network Entry Row - Single line with SSID, Password, Priority
#--------------------------------------------------------------------------------------

class wifi_network_entry(Tk.Frame):
    def __init__(self, parent_frame, tooltip_ssid="", tooltip_password="", tooltip_priority="", **kwargs):
        super().__init__(parent_frame)
        # SSID entry
        Tk.Label(self, text="SSID:").pack(side=Tk.LEFT, padx=(0, 5))
        self.ssid = string_entry_box(self, width=18, max_length=32, 
                                      tooltip=tooltip_ssid or "Network name (SSID)")
        self.ssid.pack(side=Tk.LEFT, padx=(0, 15))
        # Password entry
        Tk.Label(self, text="Password:").pack(side=Tk.LEFT, padx=(0, 5))
        self.password = string_entry_box(self, width=18, max_length=64, 
                                          tooltip=tooltip_password or "Network password")
        self.password.pack(side=Tk.LEFT, padx=(0, 15))
        # Priority dropdown
        Tk.Label(self, text="Priority:").pack(side=Tk.LEFT, padx=(0, 5))
        PRIORITY_OPTIONS = ["10", "9", "8", "7", "6", "5", "4", "3", "2", "1"]
        self.priority = dropdown_box(self, values=PRIORITY_OPTIONS, width=3,
                                      tooltip=tooltip_priority or "Connection priority (10=highest, 1=lowest)")
        self.priority.pack(side=Tk.LEFT)

    def get_value(self):
        return {'ssid': self.ssid.get(),'password': self.password.get(),
                'priority': int(self.priority.get()) if self.priority.get() else 5}

    def set_value(self, network_dict):
        if isinstance(network_dict, dict):
            self.ssid.set(network_dict.get('ssid', ''))
            self.password.set(network_dict.get('password', ''))
            priority = network_dict.get('priority', 5)
            self.priority.set(str(priority))
    
    def validate(self):
        ssid = self.ssid.get().strip()
        password = self.password.get().strip()
        # If password is filled but SSID is empty, that's invalid
        if password and not ssid:
            self.ssid.configure(fg='red')
            return False
        # SSID only (no password) is valid (open network)
        self.ssid.configure(fg='black')
        return True

#--------------------------------------------------------------------------------------
# Grid of WiFi Network Entries - Dynamically add/remove WiFi network rows
#--------------------------------------------------------------------------------------

class grid_of_wifi_networks(Tk.Frame):
    def __init__(self, parent_frame, **kwargs):
        super().__init__(parent_frame)
        self.list_of_subframes = []
        self.list_of_widgets = []
        self.list_of_buttons = []
        self.values_to_set = []

    def create_row(self, pack_after=None):
        # Create frame for this row
        row_frame = Tk.Frame(self)
        row_frame.pack(after=pack_after, fill='x', pady=(0, 4))
        self.list_of_subframes.append(row_frame)
        # Create the wifi network entry widget
        widget = wifi_network_entry(row_frame)
        widget.pack(side=Tk.LEFT, fill='x', expand=True)
        self.list_of_widgets.append(widget)
        # Set initial value if available
        if len(self.list_of_widgets) <= len(self.values_to_set):
            params_to_pass = self.values_to_set[len(self.list_of_widgets) - 1]
            widget.set_value(params_to_pass)
        # Create the "+" button for inserting rows
        add_button = Tk.Button(row_frame, text="+", height=1, width=2, padx=2, pady=0,
                               font=('Courier', 8, "normal"), 
                               command=lambda: self.create_row(pack_after=row_frame))
        add_button.pack(side=Tk.LEFT, padx=(10, 2))
        self.list_of_buttons.append(add_button)
        CreateToolTip(add_button, "Add new WiFi network (below)")
        # Create the "-" button for deleting rows (except first row)
        if len(self.list_of_subframes) > 1:
            remove_button = Tk.Button(row_frame, text="-", height=1, width=2, padx=2, pady=0,
                    font=('Courier', 8, "normal"),command=lambda: self.delete_row(row_frame))
            remove_button.pack(side=Tk.LEFT, padx=2)
            self.list_of_buttons.append(remove_button)
            CreateToolTip(remove_button, "Delete this WiFi network")

    def delete_row(self, row_frame):
        if len(self.list_of_subframes) > 1:  # Always keep at least one row
            row_frame.destroy()

    def set_values(self, values_to_set: list):
        # Destroy existing subframes
        for subframe in self.list_of_subframes:
            if subframe.winfo_exists():
                subframe.destroy()
        # Reset lists
        self.list_of_subframes = []
        self.list_of_widgets = []
        self.list_of_buttons = []
        self.values_to_set = values_to_set
        # Create at least one row, or enough rows for all values
        while len(self.list_of_widgets) < len(values_to_set) or len(self.list_of_subframes) == 0:
            self.create_row()

    def get_values(self):
        self.validate()
        networks = []
        for widget in self.list_of_widgets:
            if widget.winfo_exists():
                value = widget.get_value()
                # Only include non-empty SSIDs
                if value['ssid'].strip():
                    networks.append(value)
        # Sort by priority descending (highest first)
        networks.sort(key=lambda x: x['priority'], reverse=True)
        return networks

    def validate(self):
        valid = True
        for widget in self.list_of_widgets:
            if widget.winfo_exists():
                if not widget.validate():
                    valid = False
        return valid

#-----------------------------------------------------------------------------
# Camera Configuration Window - Non-modal Toplevel editor for ESPHome camera YAML.
#   - Single instance window with open_or_focus()
#   - Main app remains usable while this window is open
#   - Launches esphome run in background thread
#   - Streams CLI output to Tk text log via queue
#-----------------------------------------------------------------------------

class CameraConfigUtility(Tk.Toplevel):
    instance = None
    NO_PORTS_SENTINEL = "No ports detected"

    @classmethod
    def open_or_focus(cls, parent):
        # Enforce a single window instance:
        # if already open, bring it to the front and focus.
        if cls.instance is not None and cls.instance.winfo_exists():
            w = cls.instance
            w.deiconify()
            w.lift()
            w.focus_force()
            return w
        cls.instance = cls(parent)
        return cls.instance

    def __init__(self, parent):
        super().__init__(parent)
        # Window setup:
        # - Non-modal (no grab_set), so main app remains interactive.
        # - transient(parent) keeps window related to parent in window manager.
        self.title("Camera Configuration")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        # Load packaged default template:
        # Expected path: video_throttle/resources/esphome_template.yaml
        resource_path = resources.files('video_throttle').joinpath('resources', 'esphome_template.yaml')
        with resource_path.open('r', encoding='utf-8') as f:
            template_data = yaml.safe_load(f) or {}
        self.yaml = ESPHomeYaml(template_data)
        # Track a temporary file used when flashing an unsaved config.
        self.temp_flash_config_path = None
        # Thread safety for process management
        self.flash_process_lock = threading.Lock()
        self.flash_process = None
        self.flash_in_progress = False
        self.flash_completed = False
        # Unsaved changes tracking
        self.unsaved_changes = False
        # Graceful shutdown flag
        self.shutdown_requested = False
        # Build root form container.
        self.entries = {}
        form_frame = Tk.Frame(self, padx=10, pady=10)
        form_frame.pack(fill=Tk.BOTH, expand=True)
        #---------------------------------------------------------
        # Configuration File group
        #---------------------------------------------------------
        file_group = Tk.LabelFrame(form_frame, text="Configuration File", padx=10, pady=8)
        file_group.pack(fill=Tk.X, pady=(0, 8))
        self.new_button = Tk.Button(file_group, text="New", width=10, command=self.new_file)
        self.new_button.grid(row=0, column=0, pady=(8, 0))
        self.load_button = Tk.Button(file_group, text="Load...", width=10, command=self.load_file)
        self.load_button.grid(row=0, column=1, pady=(8, 0), padx=5)
        self.save_button = Tk.Button(file_group, text="Save...", width=10, command=lambda: self.save_file(save_as=False))
        self.save_button.grid(row=0, column=2, pady=(8, 0), padx=5)
        self.save_as_button = Tk.Button(file_group, text="Save as...", width=14, command=lambda: self.save_file(save_as=True))
        self.save_as_button.grid(row=0, column=3, pady=(8, 0), padx=(5, 0))
        #---------------------------------------------------------
        # WiFi Networks Group
        #---------------------------------------------------------
        wifi_group = Tk.LabelFrame(form_frame, text="WiFi Networks", padx=10, pady=10)
        wifi_group.pack(fill=Tk.BOTH, expand=True, padx=(0, 5))
        # Use the new grid_of_wifi_networks widget
        self.wifi_networks_grid = grid_of_wifi_networks(wifi_group)
        self.wifi_networks_grid.pack(fill=Tk.BOTH, expand=True)
        #---------------------------------------------------------
        # Camera settings group - LEFT HAND SIDE
        #---------------------------------------------------------
        camera_group = Tk.LabelFrame(form_frame, text="Camera Settings", padx=10, pady=10)
        camera_group.pack(fill=Tk.X)
        # Configure grid for left/right layout
        camera_group.columnconfigure(0, weight=0)  # labels (left)
        camera_group.columnconfigure(1, weight=0)  # dropdowns (left)
        camera_group.columnconfigure(2, weight=1)  # spacer
        camera_group.columnconfigure(3, weight=0)  # labels (right)
        camera_group.columnconfigure(4, weight=1)  # entries (right)
        # Define the UI Elements we need
        RESOLUTION_OPTIONS = ["1600x1200", "1280x1024", "1024x768", "800x600", "640x480", "400x296", "320x240", "240x176", "160x120"]
        FRAME_RATE_OPTIONS = ["1", "5", "10", "15", "20", "25", "30", "60"]
        JPEG_QUALITY_OPTIONS = [str(i) for i in range(10, 64, 5)]
        FRAME_BUFFER_OPTIONS = ["1", "2", "3", "4"]
        BRIGHTNESS_OPTIONS = ["-2", "-1", "0", "1", "2"]
        CONTRAST_OPTIONS = ["-2", "-1", "0", "1", "2"]
        camera_fields = [
            ("Resolution:", dropdown_box, "resolution", {"values": RESOLUTION_OPTIONS, "tooltip": "Frame resolution (UXGA down to QQVGA)"}),
            ("Frame Rate:", dropdown_box, "frame_rate", {"values": FRAME_RATE_OPTIONS, "tooltip": "Maximum camera frame rate (fps)"}),
            ("JPEG Quality:", dropdown_box, "jpeg_quality", {"values": JPEG_QUALITY_OPTIONS, "tooltip": "JPEG quality (10 is best quality, 63 is lowest)"}),
            ("Frame Buffers:", dropdown_box, "frame_buffers", {"values": FRAME_BUFFER_OPTIONS, "tooltip": "Number of camera frame buffers in PSRAM"}),
            ("Brightness:", dropdown_box, "brightness", {"values": BRIGHTNESS_OPTIONS, "tooltip": "Camera brightness adjustment (-2 to +2)"}),
            ("Contrast:", dropdown_box, "contrast", {"values": CONTRAST_OPTIONS, "tooltip": "Camera contrast adjustment (-2 to +2)"})]
        # Render camera fields (left side)
        for row, (label_text, widget_class, key, extra_args) in enumerate(camera_fields):
            Tk.Label(camera_group, text=label_text, anchor="w").grid(row=row, column=0, sticky="ew", padx=(0, 10), pady=4)
            width = 10  # field_width for dropdowns
            callback = extra_args.pop("callback", None)
            if callback is None:callback = self.mark_unsaved_changes
            widget = widget_class(camera_group, width=width, **extra_args)
            # Bind change event to callback for dropdown_box (ttk.Combobox)
            if widget_class == dropdown_box: widget.bind("<<ComboboxSelected>>", lambda e: callback())
            widget.grid(row=row, column=1, sticky="w", pady=4)
            self.entries[key] = widget
        #---------------------------------------------------------
        # Camera settings group - RIGHT HAND SIDE
        #---------------------------------------------------------
        # Device Metadata fields (right side, rows 0-1)
        Tk.Label(camera_group, text="Device Name:").grid(row=0, column=3, sticky="w", padx=(20, 10), pady=4)
        device_name_widget = string_entry_box(camera_group, width=18, max_length=10, 
                                               tooltip="Device identifier (lowercase, no spaces, max 10 characters)",
                                               callback=self.mark_unsaved_changes)
        device_name_widget.grid(row=0, column=4, sticky="ew", padx=(0, 10), pady=4)
        self.entries["device_name"] = device_name_widget
        Tk.Label(camera_group, text="Friendly Name:").grid(row=1, column=3, sticky="w", padx=(20, 10), pady=4)
        friendly_name_widget = string_entry_box(camera_group, width=18, max_length=50,
                                                 tooltip="Human-readable name",
                                                 callback=self.mark_unsaved_changes)
        friendly_name_widget.grid(row=1, column=4, sticky="ew", padx=(0, 10), pady=4)
        self.entries["friendly_name"] = friendly_name_widget
        # Checkboxes (right side, rows 2-3)
        self.vflip = check_box(camera_group, width=20, label="Vertical Flip", tooltip="Flip image vertically.")
        self.vflip.grid(row=2, column=3, columnspan=2, sticky="w", padx=(20, 10), pady=(8, 4))
        self.entries["vertical_flip"] = self.vflip
        self.hmirror = check_box(camera_group, width=20, label="Horizontal Mirror", tooltip="Mirror image horizontally.")
        self.hmirror.grid(row=3, column=3, columnspan=2, sticky="w", padx=(20, 10), pady=(4, 0))
        self.entries["horizontal_mirror"] = self.hmirror
        #---------------------------------------------------------
        # Flash/build + log group
        #---------------------------------------------------------
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
        # FIXED: Add circular log buffer to prevent memory bloat
        self.max_log_lines = 1000  # Keep last 1000 lines
        # Thread/process/log queue coordination state.
        self.flash_thread = None
        self.log_queue = queue.Queue()
        self.log_poller_running = False
        # Initialize UI from template and detect connected ports now.
        self.populate_ui()
        self.detect_ports()

    #----------------------------------------------------------------------------------
    # Function called on window close event to tidy things up gracefully
    #----------------------------------------------------------------------------------
    
    def on_close(self):
        # Check for unsaved changes before closing
        if self.unsaved_changes:
            result = messagebox.askyesno("Unsaved Changes",
                "You have unsaved changes. Are you sure you want to exit?",parent=self)
            if not result:
                return
        # Only block close while actual flash/upload phase is in progress.
        if self.flash_in_progress:
            if not messagebox.askyesno("Flash in progress",
                "Flashing is still in progress. Are you sure you want to close?", parent=self):
                return
        # Signal shutdown and try to stop background process cleanly if still running.
        self.shutdown_requested = True
        with self.flash_process_lock:
            if self.flash_process is not None and self.flash_process.poll() is None:
                try:
                    self.flash_process.terminate()
                except Exception:
                    pass
        self.cleanup_temp_flash_file()
        CameraConfigUtility.instance = None
        self.destroy()
        
    #----------------------------------------------------------------------------------
    # Function called on config changes - to set the flag for unsaved changes
    #----------------------------------------------------------------------------------
        
    def mark_unsaved_changes(self):
        # FMark configuration as modified
        self.unsaved_changes = True

    #----------------------------------------------------------------------------------
    # Function to populate the UI with the values loaded from the template/file
    #----------------------------------------------------------------------------------
            
    def populate_ui(self):
        # Populate WiFi networks grid
        wifi_networks = self.yaml.wifi_networks
        self.wifi_networks_grid.set_values(wifi_networks)
        # Update device metadata
        self.entries["device_name"].set(self.yaml.device_name)
        self.entries["friendly_name"].set(self.yaml.friendly_name)
        # Update camera settings
        self.entries["resolution"].set(self.yaml.resolution)
        self.entries["frame_rate"].set(str(self.yaml.frame_rate))
        self.entries["jpeg_quality"].set(str(self.yaml.jpeg_quality))
        self.entries["frame_buffers"].set(str(self.yaml.frame_buffers))
        self.entries["vertical_flip"].set(self.yaml.vertical_flip)
        self.entries["horizontal_mirror"].set(self.yaml.horizontal_mirror)
        self.entries["brightness"].set(str(self.yaml.brightness))
        self.entries["contrast"].set(str(self.yaml.contrast))
        # Update window title to show filename
        if self.yaml.filename:
            filename = os.path.basename(self.yaml.filename)
            self.title(f"Camera Configuration - {filename}")
        else:
            self.title("Camera Configuration")

    #----------------------------------------------------------------------------------
    # Function to populate theinternal yaml model with the current UI settings
    #----------------------------------------------------------------------------------

    def update_yaml(self):
        # Collect WiFi networks from grid
        self.yaml.wifi_networks = self.wifi_networks_grid.get_values()
        # Update device metadata
        self.yaml.device_name = self.entries["device_name"].get()
        self.yaml.friendly_name = self.entries["friendly_name"].get()
        # Update camera settings
        self.yaml.resolution = self.entries["resolution"].get()
        try:
            self.yaml.brightness = int(self.entries["brightness"].get())
        except Exception:
            self.yaml.brightness = 0
        try:
            self.yaml.contrast = int(self.entries["contrast"].get())
        except Exception:
            self.yaml.contrast = 0
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
        self.yaml.horizontal_mirror = bool(self.entries["horizontal_mirror"].get())

    #----------------------------------------------------------------------------------
    # Function to set the default yaml configuration and load into the UI 
    #----------------------------------------------------------------------------------

    def new_file(self):
        # Check for unsaved changes before creating new
        if self.unsaved_changes:
            result = messagebox.askyesno("Unsaved Changes", 
                "You have unsaved changes. Are you sure you want to create a new configuration?", 
                parent=self)
            if not result:
                return
        # Reset to template defaults.
        self.yaml.new()
        self.unsaved_changes = False
        self.populate_ui()

    #----------------------------------------------------------------------------------
    # Function to set load a previously created yaml file 
    #----------------------------------------------------------------------------------

    def load_file(self):
        # Check for unsaved changes before loading
        if self.unsaved_changes:
            result = messagebox.askyesno("Unsaved Changes", 
                "You have unsaved changes. Are you sure you want to load a different configuration?", 
                parent=self)
            if not result:
                return
        # Open file chooser parented to this window to avoid z-order issues.
        filename = filedialog.askopenfilename(parent=self, title="Load ESPHome Configuration",
                filetypes=[("ESPHome YAML Files", "*.yaml"), ("YAML Files", "*.yml"), ("All Files", "*.*")])
        if not filename:
            return
        try:
            self.yaml.load(filename)
            self.unsaved_changes = False
            self.populate_ui()
        except Exception as ex:
            messagebox.showerror("Load Failed", str(ex), parent=self)

    #----------------------------------------------------------------------------------
    # Function to create/save the yaml configuration file file 
    #----------------------------------------------------------------------------------

    def save_file(self, save_as: bool = False):
        # Validate before save.
        if not self.validate():
            messagebox.showwarning("Validation Failed", "Please fix invalid fields before saving.", parent=self)
            return
        self.update_yaml()
        # Resolve target filename.
        if save_as or self.yaml.filename is None or self.yaml.filename == "None":
            filename = filedialog.asksaveasfilename(parent=self, title="Save ESPHome Configuration", defaultextension=".yaml",
                                    filetypes=[("ESPHome YAML Files", "*.yaml"), ("YAML Files", "*.yml"), ("All Files", "*.*")])
            if not filename:
                return
        else:
            filename = self.yaml.filename
        # Save without success popup (requested behavior).
        try:
            self.yaml.save(filename)
            self.unsaved_changes = False
            self.populate_ui()
        except Exception as ex:
            messagebox.showerror("Save Failed", str(ex), parent=self)

    #----------------------------------------------------------------------------------
    # Function to validate all user inputs prior to flashing or saving
    #----------------------------------------------------------------------------------
    
    def validate(self):
        # Validate WiFi networks grid
        if not self.wifi_networks_grid.validate():
            return False
        # Validate other fields
        for widget in self.entries.values():
            # Preferred path: widget supplies explicit is_valid().
            if hasattr(widget, "is_valid") and callable(widget.is_valid):
                try:
                    if not bool(widget.is_valid):
                        return False
                except Exception:
                    return False
            # Compatibility path: trigger widget internal update hook.
            elif hasattr(widget, "validate") and callable(widget.validate):
                try:
                    if not widget.validate():
                        return False
                except Exception:
                    pass
            # Legacy fallback: red foreground means invalid.
            elif hasattr(widget, "cget"):
                try:
                    if widget.cget("fg") == "red":
                        return False
                except Exception:
                    pass
        return True
    
    #----------------------------------------------------------------------------------
    # Function to Detect USB ports that are potentially connected to a camera
    #----------------------------------------------------------------------------------

    def detect_ports(self):
        # Enumerate currently connected serial ports and fill combobox.
        active_ports = serial.tools.list_ports.comports()
        # Filter for USB serial ports
        port_list = []
        for port in active_ports:
            if not getattr(port, "device", None):
                continue
            # Prefer explicit USB metadata when available
            if getattr(port, "vid", None) is not None or getattr(port, "pid", None) is not None:
                port_list.append(port.device)
                continue
            # Fallback heuristics by platform naming/description/hwid
            dev = (getattr(port, "device", "") or "").lower()
            desc = (getattr(port, "description", "") or "").lower()
            hwid = (getattr(port, "hwid", "") or "").lower()
            usb_name_hits = ("ttyusb", "ttyacm", "cu.usb", "usbserial")
            usb_text_hits = ("usb", "cp210", "ch340", "ftdi", "silicon labs", "arduino", "esp32", "esp8266")
            if any(tok in dev for tok in usb_name_hits):
                port_list.append(port.device)
            elif any(tok in desc for tok in usb_text_hits):
                port_list.append(port.device)
            elif "usb" in hwid:
                port_list.append(port.device)
        # Populate combobox with filtered ports
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
            self.device_combobox.set(self.NO_PORTS_SENTINEL)
            
    #----------------------------------------------------------------------------------
    # Function to delete the temporary flash file
    #----------------------------------------------------------------------------------

    def cleanup_temp_flash_file(self):
        # Remove temp config file created for unsaved flash runs.
        if self.temp_flash_config_path and os.path.exists(self.temp_flash_config_path):
            try:
                os.remove(self.temp_flash_config_path)
            except Exception:
                pass
        self.temp_flash_config_path = None

    #----------------------------------------------------------------------------------
    # Function to flash the camera firmware (with the current settings)
    #----------------------------------------------------------------------------------

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
                self.cleanup_temp_flash_file()
                messagebox.showerror("Save Failed", str(ex), parent=self)
                return
            config_path = tempname
            self.temp_flash_config_path = tempname
        else:
            config_path = self.yaml.filename
            self.temp_flash_config_path = None
            try:
                self.yaml.save(config_path)
            except Exception as ex:
                messagebox.showerror("Save Failed", str(ex), parent=self)
                return
        # Resolve device selection.
        device = self.device_combobox.get().strip()
        if device == self.NO_PORTS_SENTINEL:
            device = ""
        if device == "":
            resp = messagebox.askyesno("No device specified",
                "No device port specified. Run 'esphome run' and choose device interactively?",parent=self)
            if not resp:
                self.cleanup_temp_flash_file()
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
        self.log_queue = queue.Queue()
        self.flash_in_progress = True
        self.flash_completed = False
        self.shutdown_requested = False
        self.flash_thread = threading.Thread(target=self.thread_to_run_process, args=(cmd,), daemon=True)
        self.flash_thread.start()
        # Start log poller once.
        if not self.log_poller_running:
            self.log_poller_running = True
            self.after(100, self.poll_logs)

    #----------------------------------------------------------------------------------
    # Function to abort the flashing process cleanly
    #----------------------------------------------------------------------------------

    def abort_flash(self):
        # FIXED: Thread-safe process termination
        with self.flash_process_lock:
            if self.flash_process is not None:
                try:
                    self.log_queue.put("Abort requested. Sending terminate...\n")
                    self.flash_process.terminate()
                except Exception:
                    pass
        self.abort_button.config(state="disabled")

    #----------------------------------------------------------------------------------
    # Thread to run the flashing process
    #----------------------------------------------------------------------------------

    def thread_to_run_process(self, cmd):
        try:
            esphome_bin = shutil.which(cmd[0])
            if esphome_bin is None:
                self.log_queue.put(("LOG", "----------------------------------------------------------------------\n"))
                self.log_queue.put(("LOG", "esphome executable not installed (pip install esphome).\n"))
                self.log_queue.put(("LOG", "----------------------------------------------------------------------\n"))
                self.log_queue.put(("STATUS", "DONE"))
                return
            env = dict(os.environ)
            env["PYTHONUNBUFFERED"] = "1"
            with self.flash_process_lock:
                self.flash_process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, bufsize=1, text=True, env=env)
            proc = self.flash_process
            flash_ok_sent = False
            for raw_line in proc.stdout:
                line = raw_line if raw_line is not None else ""
                self.log_queue.put(("LOG", line))
                l = line.lower()
                if (not flash_ok_sent) and ("successfully uploaded program" in l):
                    flash_ok_sent = True
                    self.log_queue.put(("STATUS", "FLASH_OK"))
                    self.log_queue.put(("LOG", "----------------------------------------------------------------------\n"))
                    self.log_queue.put(("LOG", " ✓ Flash completed. Device logs continue below...\n"))
                    self.log_queue.put(("LOG", "----------------------------------------------------------------------\n"))
            ret = proc.wait()
            if ret == 0:
                self.log_queue.put(("STATUS", "SUCCESS"))
            else:
                self.log_queue.put(("LOG", "----------------------------------------------------------------------\n"))
                self.log_queue.put(("LOG", f" ✗ Process finished with return code {ret}\n"))
                self.log_queue.put(("LOG", "----------------------------------------------------------------------\n"))
                self.log_queue.put(("STATUS", "DONE"))
        except Exception as ex:
            self.log_queue.put(("LOG", "----------------------------------------------------------------------\n"))
            self.log_queue.put(("LOG", f" ✗ Flashing failed: {ex}\n"))
            self.log_queue.put(("LOG", "----------------------------------------------------------------------\n"))
            self.log_queue.put(("STATUS", "DONE"))
        finally:
            with self.flash_process_lock:
                self.flash_process = None
            self.cleanup_temp_flash_file()

    #----------------------------------------------------------------------------------
    # Function to get the logs generated by the flashing thread and populate the UI
    #----------------------------------------------------------------------------------

    def poll_logs(self):
        if self.shutdown_requested:
            self.log_poller_running = False
            return
        try:
            while True:
                item = self.log_queue.get_nowait()
                # Backward compatibility: old plain-string messages
                if isinstance(item, tuple) and len(item) == 2:
                    kind, payload = item
                elif isinstance(item, str):
                    kind, payload = "LOG", item
                else:
                    kind, payload = "LOG", str(item)
                if kind == "STATUS":
                    if payload == "FLASH_OK":
                        # Upload complete; allow close without warning and allow reflash.
                        self.flash_in_progress = False
                        self.flash_completed = True
                        self.flash_button.config(state="normal")
                        # keep abort enabled because process may still be streaming logs
                        self.abort_button.config(state="normal")
                        continue
                    if payload == "SUCCESS":
                        self.flash_in_progress = False
                        self.flash_button.config(state="normal")
                        self.abort_button.config(state="disabled")
                        self.log_poller_running = False
                        return
                    if payload == "DONE":
                        self.flash_in_progress = False
                        self.flash_button.config(state="normal")
                        self.abort_button.config(state="disabled")
                        self.log_poller_running = False
                        return
                # LOG path
                self.log_text.insert(Tk.END, str(payload))
                self.log_text.see(Tk.END)
                current_lines = int(self.log_text.index("end-1c").split(".")[0])
                if current_lines > self.max_log_lines:
                    first_line_to_keep = current_lines - self.max_log_lines + 1
                    self.log_text.delete("1.0", f"{first_line_to_keep}.0")
        except queue.Empty:
            pass
        if not self.shutdown_requested:
            self.after(100, self.poll_logs)
        else:
            self.log_poller_running = False


#########################################################################################################################################
    
    
    
##### sudo apt install python3-yaml

import copy
import os
import sys
import threading
import subprocess
import tempfile
import yaml
import shutil
import glob
import platform
import queue
import time
import tkinter as Tk
from tkinter import filedialog, messagebox, ttk
from importlib import resources
import serial.tools.list_ports
from .widgets import dropdown_box, string_entry_box, check_box

# -----------------------------------------------------------------------------
# ESPHome YAML Wrapper
# -----------------------------------------------------------------------------

class ESPHomeYaml:
    def __init__(self, template_dictionary):
        self.template = copy.deepcopy(template_dictionary)
        self.filename = None
        self.data = copy.deepcopy(self.template)

    def new(self):
        # Resets the working data back to the clean template in memory
        self.data = copy.deepcopy(self.template)
        self.filename = None

    def load(self, filename):
        with open(filename, "r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}
        self.filename = filename

    def save(self, filename=None):
        if filename is not None:
            self.filename = filename
        if self.filename is None:
            raise RuntimeError("No filename has been specified.")
        with open(self.filename, "w", encoding="utf-8") as f:
            yaml.dump(self.data, f, sort_keys=False)

    # WiFi
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

    # Camera
    @property
    def resolution(self):
        return self.data.get("esp32_camera", {}).get("resolution", "")

    @resolution.setter
    def resolution(self, value):
        self.data.setdefault("esp32_camera", {})
        self.data["esp32_camera"]["resolution"] = value

    @property
    def frame_rate(self):
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
# Camera Configuration Window
# -----------------------------------------------------------------------------

class CameraConfigWindow(Tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("ESPHome Camera Configuration")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        # Locate the resource file inside the package
        resource_path = resources.files('video_throttle').joinpath('resources', 'esphome_template.yaml')
        # Read and parse the YAML contents directly using the Traversable object
        with resource_path.open('r', encoding='utf-8') as f:
            template_data = yaml.safe_load(f) or {}
        # Pass the safe Python dictionary into your wrapper class
        self.yaml = ESPHomeYaml(template_data)
        #------------------------------------------------------------------------------------
        # Build the user interface
        #------------------------------------------------------------------------------------
        self.entries = {}
        form_frame = Tk.Frame(self, padx=10, pady=10)
        form_frame.pack(fill=Tk.BOTH, expand=True)
        #------------------------------------------------------------------------------------
        # File selection group
        #------------------------------------------------------------------------------------
        file_group = Tk.LabelFrame(form_frame, text="Configuration File", padx=10, pady=8)
        file_group.pack(fill=Tk.X, pady=(0, 8))
        Tk.Label(file_group, text="Current File:").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.filename_var = Tk.StringVar(value="None")
        Tk.Label(file_group, textvariable=self.filename_var, width=45, anchor="w").grid(row=0, column=1, columnspan=3, sticky="w")
        self.new_button = Tk.Button(file_group, text="New", width=10, command=self.new_file)
        self.new_button.grid(row=1, column=0, pady=(8,0))
        self.load_button = Tk.Button(file_group, text="Load...", width=10, command=self.load_file)
        self.load_button.grid(row=1, column=1, pady=(8,0), padx=5)
        self.save_button = Tk.Button(file_group, text="Save...", width=10, command=lambda:self.save_file(save_as=False))
        self.save_button.grid(row=1, column=2, pady=(8,0), padx=5)
        self.save_as_button = Tk.Button(file_group, text="Save as...", width=14, command=lambda:self.save_file(save_as=True))
        self.save_as_button.grid(row=1, column=3, pady=(8,0), padx=(5,0))
        #------------------------------------------------------------------------------------
        # WiFi Settings Group
        #------------------------------------------------------------------------------------
        wifi_group = Tk.LabelFrame(form_frame, text="WiFi Settings", padx=10, pady=10)
        wifi_group.pack(fill=Tk.X, pady=(0, 10))
        wifi_fields = [("SSID:", string_entry_box, "ssid", {"max_length": 32, "tooltip": "Wireless network name."}),
                      ("Password:", string_entry_box, "password", {"max_length": 64, "tooltip": "Wireless password."}) ]
        self.render_fields(wifi_group, wifi_fields)
        #------------------------------------------------------------------------------------
        # Device Metadata Group
        #------------------------------------------------------------------------------------
        metadata_group = Tk.LabelFrame(form_frame, text="Device Metadata", padx=10, pady=10)
        metadata_group.pack(fill=Tk.X, pady=(0, 10))
        metadata_fields = [
            ("Device Name:", string_entry_box, "device_name", 
             {"max_length": 10, "tooltip": "Device identifier (lowercase, no spaces, max 10 characters)"}),
            ("Friendly Name:", string_entry_box, "friendly_name", 
             {"max_length": 50, "tooltip": "Human-readable name"})]
        self.render_fields(metadata_group, metadata_fields)
        #------------------------------------------------------------------------------------
        # Camera Settings Group
        #------------------------------------------------------------------------------------
        camera_group = Tk.LabelFrame(form_frame, text="Camera Settings", padx=10, pady=10)
        camera_group.pack(fill=Tk.X)
        
        # Standard ESP32-CAM resolutions supported by ESPHome
        RESOLUTION_OPTIONS = [ "1600x1200", "1280x1024", "1024x768", "800x600", 
                            "640x480", "400x296", "320x240", "240x176", "160x120"]
        # Standard frame rates (in fps)
        FRAME_RATE_OPTIONS = ["1", "5", "10", "15", "20", "25", "30", "60"]
        # JPEG Quality choices (lower numbers mean higher quality, 10 is excellent, 63 is lowest)
        JPEG_QUALITY_OPTIONS = [str(i) for i in range(10, 64, 5)] # Generates 10, 15, 20... 60, 63
        # Typical PSRAM frame buffers (higher values allow higher resolutions/framerates)
        FRAME_BUFFER_OPTIONS = ["1", "2", "3", "4"]
        camera_fields = [("Resolution:", dropdown_box, "resolution", {"values": RESOLUTION_OPTIONS, "tooltip": "Frame resolution (UXGA down to QQVGA)"}),
                         ("Frame Rate:", dropdown_box, "frame_rate", {"values": FRAME_RATE_OPTIONS, "tooltip": "Maximum camera frame rate (fps)"}),
                         ("JPEG Quality:", dropdown_box, "jpeg_quality", {"values": JPEG_QUALITY_OPTIONS, "tooltip": "JPEG quality (10 is best quality, 63 is lowest)"}),
                         ("Frame Buffers:", dropdown_box, "frame_buffers", {"values": FRAME_BUFFER_OPTIONS, "tooltip": "Number of camera frame buffers in PSRAM"})]
        self.render_fields(camera_group, camera_fields)
        self.vflip = check_box(camera_group, width=30, label="Vertical Flip", tooltip="Flip image vertically.")
        self.vflip.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8,0))
        self.entries["vertical_flip"] = self.vflip
        self.hmirror = check_box(camera_group, width=30, label="Horizontal Mirror", tooltip="Mirror image horizontally.")
        self.hmirror.grid(row=5, column=0, columnspan=2, sticky="w")
        self.entries["horizontal_mirror"] = self.hmirror
        #------------------------------------------------------------------------------------
        # Flash controls and logging window
        #------------------------------------------------------------------------------------
        flash_group = Tk.LabelFrame(form_frame, text="Flash / Build", padx=10, pady=10)
        flash_group.pack(fill=Tk.BOTH, pady=(10, 0))
        self.auto_ports_button = Tk.Button(flash_group, text="Detect Ports", command=self.detect_ports)
        self.auto_ports_button.grid(row=0, column=0, sticky="w")
        Tk.Label(flash_group, text="Device Port:").grid(row=0, column=1, sticky="e")
        self.device_var = Tk.StringVar()
        self.device_combobox = ttk.Combobox(flash_group, textvariable=self.device_var, state="readonly") 
        self.device_combobox.grid(row=0, column=2, sticky="w", padx=(6, 10))
        self.flash_button = Tk.Button(flash_group, text="Flash (esphome run)", command=self.flash_device, bg="#4caf50", fg="white")
        self.flash_button.grid(row=0, column=3, padx=8, sticky="e")
        self.abort_button = Tk.Button(flash_group, text="Abort", command=self.abort_flash, state="disabled")
        self.abort_button.grid(row=0, column=4, sticky="e")
        self.log_text = Tk.Text(flash_group, height=12, wrap="none")
        self.log_text.grid(row=1, column=0, columnspan=5, pady=(8,0), sticky="nsew")
        flash_group.rowconfigure(1, weight=1)
        flash_group.columnconfigure(1, weight=1)
        self.log_text.insert(Tk.END, "Logs will appear here...\n")
        self._flash_thread = None
        self._flash_proc = None
        self._log_queue = queue.Queue()
        self._log_poller_running = False
        #------------------------------------------------------------------------------------
        # Initialize entries from template
        #------------------------------------------------------------------------------------
        self.update_ui()

    def render_fields(self, container, fields):
        container.columnconfigure(1, weight=1)
        for row, (label_text, widget_class, key, extra_args) in enumerate(fields):
            Tk.Label(container, text=label_text, anchor="w").grid(row=row, column=0, sticky="ew", padx=(0,10), pady=4)
            width = 30 if widget_class == string_entry_box else 8
            widget = widget_class(container, width=width, **extra_args)
            widget.grid(row=row, column=1, sticky="w", pady=4)
            self.entries[key] = widget
        return

    # Synchronise UI from YAML
    def update_ui(self):
        self.entries["ssid"].set(self.yaml.ssid)
        self.entries["password"].set(self.yaml.password)
        self.entries["resolution"].set(self.yaml.resolution)
        self.entries["frame_rate"].set(self.yaml.frame_rate)
        self.entries["jpeg_quality"].set(self.yaml.jpeg_quality)
        self.entries["frame_buffers"].set(self.yaml.frame_buffers)
        self.entries["vertical_flip"].set(self.yaml.vertical_flip)
        self.entries["horizontal_mirror"].set(self.yaml.horizontal_mirror)
        # If filename exists, extract the base name string; otherwise, default to "None"
        filename_text = os.path.basename(self.yaml.filename) if self.yaml.filename else "None"
        self.filename_var.set(filename_text)

    # Synchronise YAML from UI
    def update_yaml(self):
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
        self.yaml.horizontal_mirror = bool(self.entries["horizontal_mirror"].get())

    # File Menu Operations
    def new_file(self):
        self.yaml.new()
        self.update_ui()

    def load_file(self):
        filename = filedialog.askopenfilename(title="Load ESPHome Configuration",
                    filetypes=[("ESPHome YAML Files","*.yaml"), ("YAML Files","*.yml"), ("All Files","*.*")])
        if not filename:
            return
        try:
            self.yaml.load(filename)
            self.update_ui()
        except Exception as ex:
            messagebox.showerror("Load Failed", str(ex))
    
    def save_file(self, save_as:bool=False):
        if not self.validate():
            messagebox.showwarning("Validation Failed", "Please fix invalid fields (red) before saving.")
            return
        self.update_yaml()
        # If no filename is set then force a save as dialog
        if save_as or self.yaml.filename is None or self.yaml.filename == "None":
            filename = filedialog.asksaveasfilename(title="Save ESPHome Configuration", defaultextension=".yaml",
                                filetypes=[("ESPHome YAML Files","*.yaml"), ("YAML Files","*.yml"), ("All Files","*.*")])
            if not filename:
                return
        else:
            filename = self.yaml.filename
        try:
            self.yaml.save(filename)
            self.update_ui()
            messagebox.showinfo("Saved", f"Configuration saved to {filename}")
        except Exception as ex:
            messagebox.showerror("Save Failed", str(ex))

    def choose_template(self):
        filename = filedialog.askopenfilename(title="Choose ESPHome Template", filetypes=[("YAML Files","*.yaml;*.yml"), ("All Files","*.*")])
        if not filename:
            return
        try:
            # replace template and reset the data
            self.yaml = ESPHomeYaml(filename)
            self.yaml.new()
            self.update_ui()
        except Exception as ex:
            messagebox.showerror("Template Load Failed", str(ex))

    # Validation
    def validate(self):
        for widget in self.entries.values():
            if hasattr(widget, "entry_box_updated"):
                widget.entry_box_updated()
            if hasattr(widget, "cget"):
                try:
                    if widget.cget("fg") == "red":
                        return False
                except Exception:
                    pass
        return True

    # Port detection
    def detect_ports(self):
        # 1. Fetch only ACTIVE serial ports plugged into the machine
        active_ports = serial.tools.list_ports.comports()
        # Extract just the device paths (e.g., 'COM3' or '/dev/ttyUSB0')
        port_list = [port.device for port in active_ports]
        if port_list:
            # 2. Update your Combobox values (replace 'device_combobox' with your widget name)
            self.device_combobox['values'] = port_list
            # 3. Smart Default: Try to find a common microcontroller port, otherwise pick index 0
            default_port = port_list[0]
            for port in port_list:
                # On Linux/Pi, CH340 or CP210x adapters usually sit on ttyUSB, rarely ttyACM
                if "ttyUSB" in port:
                    default_port = port
                    break
            self.device_combobox.set(default_port)
        else:
            self.device_combobox['values'] = []
            self.device_combobox.set("No ports detected")

    # Flashing support
    def flash_device(self):
        if not self.validate():
            messagebox.showwarning("Validation Failed", "Please fix invalid fields (red) before flashing.")
            return
        self.update_yaml()
        # ensure YAML is saved somewhere (temporary file if necessary)
        if self.yaml.filename is None:
            fd, tempname = tempfile.mkstemp(suffix=".yaml", prefix="esphome_")
            os.close(fd)
            try:
                self.yaml.save(tempname)
            except Exception as ex:
                messagebox.showerror("Save Failed", str(ex))
                return
            config_path = tempname
        else:
            config_path = self.yaml.filename
            try:
                self.yaml.save(config_path)
            except Exception as ex:
                messagebox.showerror("Save Failed", str(ex))
                return

        device = self.device_combobox.get().strip()
        if device == "":
            resp = messagebox.askyesno("No device specified", "No device port specified. Do you want to run 'esphome run' and choose device interactively? (No upload will occur without a device.)")
            if not resp:
                return

        # prepare command
        cmd = ["esphome", "run", config_path]
        if device:
            cmd += ["--device", device]

        # start thread
        self.log_text.delete("1.0", Tk.END)
        self.log_text.insert(Tk.END, f"Running: {' '.join(cmd)}\n\n")
        self.flash_button.config(state="disabled")
        self.abort_button.config(state="normal")
        self._log_queue = queue.Queue()
        self._flash_thread = threading.Thread(target=self._run_subprocess, args=(cmd,), daemon=True)
        self._flash_thread.start()
        if not self._log_poller_running:
            self._log_poller_running = True
            self.after(100, self._poll_logs)

    def abort_flash(self):
        if self._flash_proc:
            try:
                self._flash_proc.kill()
                self._log_queue.put("Process aborted by user.\n")
            except Exception:
                pass
        self.abort_button.config(state="disabled")
        self.flash_button.config(state="normal")

    def _run_subprocess(self, cmd):
        try:
            # locate esphome if not on PATH
            esphome_bin = shutil.which(cmd[0])
            if esphome_bin is None:
                self._log_queue.put("esphome executable not found on PATH. Please install esphome CLI (pip install esphome).\n")
                return
            self._flash_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, text=True)
            for line in self._flash_proc.stdout:
                self._log_queue.put(line)
            self._flash_proc.wait()
            ret = self._flash_proc.returncode
            self._log_queue.put(f"\nProcess finished with return code {ret}\n")
        except Exception as ex:
            self._log_queue.put(f"\nFlashing failed: {ex}\n")
        finally:
            self._flash_proc = None
            # re-enable buttons on main thread via queue sentinel
            self._log_queue.put("__DONE__\n")

    def _poll_logs(self):
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
    
    
    
import tkinter as Tk
from tkinter import messagebox
from .widgets import integer_entry_box, float_entry_box, string_entry_box, axle_entry_box, check_box
from .widgets import RadioGroupWrapper, ConfigControlBar

import tkinter as Tk

#----------------------------------------------------------------------------------------------------
# Loco Config Window
#----------------------------------------------------------------------------------------------------

class LocoConfigWindow(Tk.Toplevel):
    def __init__(self, parent, current_config, save_callback):
        super().__init__(parent)
        self.title("Locomotive Configuration")
        self.resizable(False, False)
        # Keep window pinned modally on top of the main app workspace
        self.transient(parent)  
        self.grab_set()         
        self.save_callback = save_callback
        self.initial_config = current_config 
        self.entries = {}
        form_frame = Tk.Frame(self, padx=15, pady=10)
        form_frame.pack(fill=Tk.BOTH, expand=True)
        # Comprehensive layout mapping tracking all 12 core variables
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
            
            ("Forward Stream URL:", string_entry_box, "fwd_stream_url", 
             {"max_length": 255, "tooltip": "Forward facing cab camera IP address/port (e.g. http://192.168.1.149:8080)"}),
             
            ("Reverse Stream URL:", string_entry_box, "rev_stream_url", 
             {"max_length": 255, "tooltip": "Rear facing cab camera local IP address/port (e.g. http://192.168.1.150:8080)"}),
        ]
        
        # Render the input fields dynamically
        for row, (label_text, widget_class, key, extra_args) in enumerate(fields):
            Tk.Label(form_frame, text=label_text, anchor="w").grid(row=row, column=0, sticky="ew", pady=4, padx=(0, 10))
            width = 35 if widget_class in (string_entry_box, axle_entry_box) else 12
            widget = widget_class(form_frame, width=width, **extra_args)
            widget.grid(row=row, column=1, sticky="w" if width == 12 else "ew", pady=4)
            val = current_config.get(key, "")
            widget.set(val)            
            self.entries[key] = widget
        # Integrated Reusable Component
        control_bar = ConfigControlBar(self,
            on_ok=lambda: self.validate_and_save(close_window=True),
            on_apply=lambda: self.validate_and_save(close_window=False),
            on_reset=self.reset_to_original,
            on_cancel=self.destroy)
        control_bar.pack(fill=Tk.X, pady=10,side=Tk.BOTTOM)

    def validate_and_save(self, close_window=True):
        for field in self.entries.values():
            field.entry_box_updated()
            if field.cget('fg') == 'red':
                return
        updated_config = {
            "loco_name": self.entries["loco_name"].get(),
            "dcc_address": self.entries["dcc_address"].get(),
            "dcc_speed_scaling": float(self.entries["dcc_speed_scaling"].get()),
            "loco_horsepower": int(self.entries["loco_horsepower"].get()),
            "loco_mass_tonnes": int(self.entries["loco_mass_tonnes"].get()),
            "loco_max_speed_mph": int(self.entries["loco_max_speed_mph"].get()),
            "max_tractive_effort_lbf": int(self.entries["max_tractive_effort_lbf"].get()),
            "traction_responsiveness": float(self.entries["traction_responsiveness"].get()),
            "brake_responsiveness": float(self.entries["brake_responsiveness"].get()),
            "axle_offsets_ft": self.entries["axle_offsets_ft"].get(),
            "fwd_stream_url": self.entries["fwd_stream_url"].get(),
            "rev_stream_url": self.entries["rev_stream_url"].get(),
        }
        self.save_callback(updated_config)
        if close_window:
            self.destroy()

    def reset_to_original(self):
        for key, widget in self.entries.items():
            original_val = self.initial_config.get(key, "")
            widget.set(original_val)
            if hasattr(widget, 'entry_box_updated'):
                widget.entry_box_updated()
            
#----------------------------------------------------------------------------------------------------
# MQTT Config Window
#----------------------------------------------------------------------------------------------------

class MqttConfigWindow(Tk.Toplevel):
    def __init__(self, parent, current_config, save_callback):
        super().__init__(parent)
        self.title("MQTT Network Settings")
        self.resizable(False, False)
        
        # Pin window modally on top of the main app workspace
        self.transient(parent)  
        self.grab_set()         
        
        self.save_callback = save_callback
        self.initial_config = current_config 
        self.entries = {}
        
        form_frame = Tk.Frame(self, padx=15, pady=10)
        form_frame.pack(fill=Tk.BOTH, expand=True)
        
        # --- Section 1: Broker Configuration ---
        broker_group = Tk.LabelFrame(form_frame, text="Broker Configuration", padx=10, pady=10)
        broker_group.pack(fill=Tk.X, pady=(0, 10))
        
        broker_fields = [
            ("Address:", string_entry_box, "broker_host", 
             {"max_length": 255, "tooltip": "Specify the URL, hostname or IP address of the MQTT broker (e.g. 'localhost')"}),
            
            ("Port:", integer_entry_box, "broker_port", 
             {"min_val": 1, "max_val": 65535, "tooltip": "Specify the TCP/IP Port to use for the Broker (Default: 1883)"}),
            
            ("Username:", string_entry_box, "broker_username", 
             {"max_length": 100, "tooltip": "Specify the username for connecting to the broker (Optional)"}),
            
            ("Password:", string_entry_box, "broker_password", 
             {"max_length": 100, "tooltip": "Specify the password (WARNING: Sent over the network unencrypted)"})
        ]
        
        self._render_fields(broker_group, broker_fields, current_config)
        
        # --- Section 2: Network & Nodes Configuration ---
        network_group = Tk.LabelFrame(form_frame, text="Network & Node Configuration", padx=10, pady=10)
        network_group.pack(fill=Tk.X, pady=(0, 5))
        
        network_fields = [
            ("Network ID:", string_entry_box, "network_identifier", 
             {"max_length": 20, "tooltip": "Specify a name for this signaling network"}),
            
            ("Throttle Node ID:", string_entry_box, "throttle_node_identifier", 
             {"max_length": 10, "tooltip": "Specify a unique identifier for this throttle node on the signalling network"}),
             
            ("Command Station ID:", string_entry_box, "command_station_node_identifier", 
             {"max_length": 10, "tooltip": "Specify the target identifier for the layout's Command Station node on the signalling network"})
        ]
        
        self._render_fields(network_group, network_fields, current_config)
        
        # --- Section 3: Checkboxes (Boolean Settings) ---
        checkbox_frame = Tk.Frame(network_group)
        checkbox_frame.grid(row=len(network_fields), column=0, columnspan=2, sticky="w", pady=(8, 0))
        
        # Instantiate your custom check_box with matching parameters 
        self.debug_check = check_box(
            checkbox_frame, 
            width=32,
            label="Enhanced MQTT debug logging", 
            tooltip="Select to enable enhanced debug logging (Layout log level must also be 'debug')"
        )
        self.debug_check.pack(anchor="w", pady=2)
        
        # Load the configuration data state and map it into the entries dictionary
        val = current_config.get("enhanced_debugging", False)
        self.debug_check.set(val)
        self.entries["enhanced_debugging"] = self.debug_check
        
        # --- Control Bar Integration ---
        control_bar = ConfigControlBar(
            self,
            on_ok=lambda: self.validate_and_save(close_window=True),
            on_apply=lambda: self.validate_and_save(close_window=False),
            on_reset=self.reset_to_original,
            on_cancel=self.destroy
        )
        control_bar.pack(fill=Tk.X, pady=10, side=Tk.BOTTOM)

    def _render_fields(self, container, fields, config_source):
        """Helper method to grid input lines cleanly within targeted sub-frames"""
        container.columnconfigure(1, weight=1)
        for row, (label_text, widget_class, key, extra_args) in enumerate(fields):
            Tk.Label(container, text=label_text, anchor="w").grid(row=row, column=0, sticky="ew", pady=4, padx=(0, 10))
            
            width = 30 if widget_class == string_entry_box else 8
            widget = widget_class(container, width=width, **extra_args)
            widget.grid(row=row, column=1, sticky="w", pady=4)
            
            val = config_source.get(key, "")
            widget.set(val)            
            self.entries[key] = widget

    def validate_and_save(self, close_window=True):
        # Cyclically trips focus validations across all inputs (including the check_box seamlessly now!)
        for field in self.entries.values():
            field.entry_box_updated()
            if field.cget('fg') == 'red':
                return
            
        # Compile structured data payload directly pulling via custom widget .get() methods
        updated_config = {
            "broker_host": self.entries["broker_host"].get(),
            "broker_port": int(self.entries["broker_port"].get()),
            "broker_username": self.entries["broker_username"].get(),
            "broker_password": self.entries["broker_password"].get(),
            "network_identifier": self.entries["network_identifier"].get(),
            "throttle_node_identifier": self.entries["throttle_node_identifier"].get(),
            "enhanced_debugging": self.entries["enhanced_debugging"].get(),
            "command_station_node_identifier": self.entries["command_station_node_identifier"].get()
        }
        
        self.save_callback(updated_config)
        if close_window:
            self.destroy()

    def reset_to_original(self):
        # Restores every tracked UI widget back to initial configuration payload parameters
        for key, widget in self.entries.items():
            original_val = self.initial_config.get(key, "")
            # If entry is an int, cast it back (handles broker_port safely)
            if key == "broker_port" and original_val != "":
                original_val = int(original_val)
            widget.set(original_val)
            widget.entry_box_updated()
            
#----------------------------------------------------------------------------------------------------
# General Config Window
#----------------------------------------------------------------------------------------------------

class GeneralConfigWindow(Tk.Toplevel):
    def __init__(self, parent, current_config, save_callback):
        super().__init__(parent)
        self.title("General System Settings")
        self.resizable(False, False)
        # Pin window modally on top of the main app workspace
        self.transient(parent)  
        self.grab_set()         
        self.save_callback = save_callback
        self.initial_config = current_config 
        self.entries = {}
        form_frame = Tk.Frame(self, padx=15, pady=10)
        form_frame.pack(fill=Tk.BOTH, expand=True)
        # --- Section 1: Application Settings ---
        settings_group = Tk.LabelFrame(form_frame, text="General Options", padx=10, pady=10)
        settings_group.pack(fill=Tk.X, pady=(0, 10))
        # Sound Checkbox
        self.sound_check = check_box(
            settings_group,
            width=50,
            label="Enable simulated Audio (Engine Sound, Brake Hiss)",
            tooltip="Select to enable simulated locomotive sounds"
        )
        self.sound_check.pack(anchor="w", pady=4)
        self.entries["sound_enabled"] = self.sound_check
        # Connect Immediately Checkbox
        self.connect_check = check_box(
            settings_group,
            width=50,
            label="Connect to Broker Automatically on File Load",
            tooltip="Automatically initiate a network connection on locomotive file load"
        )
        self.connect_check.pack(anchor="w", pady=4)
        self.entries["connect_immediately"] = self.connect_check
        
        # --- Section 2: Logging Framework Configuration ---
        log_group = Tk.LabelFrame(form_frame, text="System Log Level Threshold", padx=10, pady=10)
        log_group.pack(fill=Tk.X, pady=(0, 5))
        # Standard Python logging numerical constants mapped to readable descriptions
        logging_options = [
            ("Debug (Verbose)", 10),
            ("Standard (Info)", 20),
            ("Warnings Only", 30)
        ]
        self.log_radio_group = RadioGroupWrapper(log_group, logging_options)
        self.log_radio_group.log_group = log_group  # Anchor frame reference if ever needed
        self.entries["log_level"] = self.log_radio_group
        # Initialize widget data states with dictionary values
        self.sound_check.set(current_config.get("sound_enabled", True))
        self.connect_check.set(current_config.get("connect_immediately", False))
        self.log_radio_group.set(current_config.get("log_level", 20))
        # --- Control Bar Integration ---
        control_bar = ConfigControlBar(
            self,
            on_ok=lambda: self.validate_and_save(close_window=True),
            on_apply=lambda: self.validate_and_save(close_window=False),
            on_reset=self.reset_to_original,
            on_cancel=self.destroy
        )
        control_bar.pack(fill=Tk.X, pady=10, side=Tk.BOTTOM)

    def validate_and_save(self, close_window=True):
        # Cyclically trips validations safely across entry fields, check_boxes, and radio blocks
        for field in self.entries.values():
            if hasattr(field, 'entry_box_updated'):
                field.entry_box_updated()
            if hasattr(field, 'cget') and field.cget('fg') == 'red':
                return
        # Compile final outputs smoothly translating back variable data types
        updated_config = {
            "sound_enabled": bool(self.entries["sound_enabled"].get()),
            "log_level": int(self.entries["log_level"].get()),
            "connect_immediately": bool(self.entries["connect_immediately"].get())
        }
        self.save_callback(updated_config)
        if close_window:
            self.destroy()

    def reset_to_original(self):
        # Reverts every input control group back to initial class instantiation snapshots
        for key, widget in self.entries.items():
            original_val = self.initial_config.get(key)                
            widget.set(original_val)
            if hasattr(widget, 'entry_box_updated'):
                widget.entry_box_updated()

###############################################################################################
import tkinter as Tk

from .widgets import integer_entry_box, string_entry_box, check_box
from .widgets import RadioGroupWrapper, ConfigControlBar

#----------------------------------------------------------------------------------------------------
# MQTT Settings Window
#----------------------------------------------------------------------------------------------------

class MqttSettingsWindow(Tk.Toplevel):
    # Track singleton instance so only one non-modal settings window can exist at a time.
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
        self.title("MQTT Network Settings")
        self.resizable(False, False)
        # Non-modal behaviour (main app remains responsive), but keep window linked to parent.
        self.transient(parent)
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
             {"max_length": 100, "tooltip": "Specify the password (WARNING: Sent over the network unencrypted)"})]
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
             {"max_length": 10, "tooltip": "Specify the target identifier for the layout's Command Station node on the signalling network"})]
        self._render_fields(network_group, network_fields, current_config)
        # --- Section 3: Checkboxes (Boolean Settings) ---
        checkbox_frame = Tk.Frame(network_group)
        checkbox_frame.grid(row=len(network_fields), column=0, columnspan=2, sticky="w", pady=(8, 0))
        # Instantiate the custom check_box with matching parameters
        self.debug_check = check_box(checkbox_frame, width=32, label="Enhanced MQTT debug logging",
            tooltip="Select to enable enhanced debug logging (Layout log level must also be 'debug')")
        self.debug_check.pack(anchor="w", pady=2)
        # Load the configuration data state and map it into the entries dictionary
        val = current_config.get("enhanced_debugging", False)
        self.debug_check.set(val)
        self.entries["enhanced_debugging"] = self.debug_check
        # --- Control Bar Integration ---
        control_bar = ConfigControlBar(self,
            on_ok=lambda: self.validate_and_save(close_window=True),
            on_apply=lambda: self.validate_and_save(close_window=False),
            on_reset=self.reset_to_original,
            on_cancel=self.close_window)
        control_bar.pack(fill=Tk.X, pady=10, side=Tk.BOTTOM)
        # Handle close cleanup
        self.protocol("WM_DELETE_WINDOW", self.close_window)

    def close_window(self):
        # Clear active-instance tracker
        if MqttSettingsWindow._active_instance is self:
            MqttSettingsWindow._active_instance = None
        self.destroy()

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
        # Run explicit validators for all widgets that support the new baseline validation API.
        for field in self.entries.values():
            if hasattr(field, 'validate'):
                if not field.validate():
                    return
            elif hasattr(field, 'entry_box_updated'):
                # Backward compatibility fallback
                field.entry_box_updated()
                if hasattr(field, 'cget') and field.cget('fg') == 'red':
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
            "command_station_node_identifier": self.entries["command_station_node_identifier"].get()}
        self.save_callback(updated_config)
        if close_window: self.close_window()

    def reset_to_original(self):
        # Restores every tracked UI widget back to initial configuration payload parameters
        for key, widget in self.entries.items():
            original_val = self.initial_config.get(key, "")
            # If entry is an int, cast it back (handles broker_port safely)
            if key == "broker_port" and original_val != "":
                original_val = int(original_val)
            widget.set(original_val)
            if hasattr(widget, 'validate'):
                widget.validate()
            elif hasattr(widget, 'entry_box_updated'):
                widget.entry_box_updated()

#----------------------------------------------------------------------------------------------------
# General Settings Window
#----------------------------------------------------------------------------------------------------

class GeneralSettingsWindow(Tk.Toplevel):
    # Track singleton instance so only one non-modal settings window can exist at a time.
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
        self.title("General System Settings")
        self.resizable(False, False)
        # Non-modal behaviour (main app remains responsive), but keep window linked to parent.
        self.transient(parent)
        self.save_callback = save_callback
        self.initial_config = current_config
        self.entries = {}
        form_frame = Tk.Frame(self, padx=15, pady=10)
        form_frame.pack(fill=Tk.BOTH, expand=True)
        # --- Section 1: Application Settings ---
        settings_group = Tk.LabelFrame(form_frame, text="General Options", padx=10, pady=10)
        settings_group.pack(fill=Tk.X, pady=(0, 10))
        # Sound Checkbox
        self.sound_check = check_box(settings_group, width=50, label="Enable simulated Audio (Engine Sound, Brake Hiss)",
                            tooltip="Select to enable simulated locomotive sounds")
        self.sound_check.pack(anchor="w", pady=4)
        self.entries["sound_enabled"] = self.sound_check
        # Connect Immediately Checkbox
        self.connect_check = check_box(settings_group, width=50, label="Connect to Broker Automatically on File Load",
                 tooltip="Automatically initiate a network connection on locomotive file load")
        self.connect_check.pack(anchor="w", pady=4)
        self.entries["connect_immediately"] = self.connect_check
        # --- Section 2: Logging Framework Configuration ---
        log_group = Tk.LabelFrame(form_frame, text="System Log Level Threshold", padx=10, pady=10)
        log_group.pack(fill=Tk.X, pady=(0, 5))
        # Standard Python logging numerical constants mapped to readable descriptions
        logging_options = [("Debug (Verbose)", 10), ("Standard (Info)", 20), ("Warnings Only", 30)]
        self.log_radio_group = RadioGroupWrapper(log_group, logging_options)
        self.log_radio_group.log_group = log_group  # Anchor frame reference if ever needed
        self.entries["log_level"] = self.log_radio_group
        # Initialize widget data states with dictionary values
        self.sound_check.set(current_config.get("sound_enabled", True))
        self.connect_check.set(current_config.get("connect_immediately", False))
        self.log_radio_group.set(current_config.get("log_level", 20))
        # --- Control Bar Integration ---
        control_bar = ConfigControlBar(self,
            on_ok=lambda: self.validate_and_save(close_window=True),
            on_apply=lambda: self.validate_and_save(close_window=False),
            on_reset=self.reset_to_original,
            on_cancel=self.close_window)
        control_bar.pack(fill=Tk.X, pady=10, side=Tk.BOTTOM)
        # Handle close cleanup
        self.protocol("WM_DELETE_WINDOW", self.close_window)

    def close_window(self):
        # Clear active-instance tracker
        if GeneralSettingsWindow._active_instance is self:
            GeneralSettingsWindow._active_instance = None
        self.destroy()

    def validate_and_save(self, close_window=True):
        # Run explicit validators safely across entry fields, check_boxes, and radio blocks.
        for field in self.entries.values():
            if hasattr(field, 'validate'):
                if not field.validate():
                    return
            elif hasattr(field, 'entry_box_updated'):
                # Backward compatibility fallback
                field.entry_box_updated()
                if hasattr(field, 'cget') and field.cget('fg') == 'red':
                    return
        # Compile final outputs smoothly translating back variable data types
        updated_config = {
            "sound_enabled": bool(self.entries["sound_enabled"].get()),
            "log_level": int(self.entries["log_level"].get()),
            "connect_immediately": bool(self.entries["connect_immediately"].get())}
        self.save_callback(updated_config)
        if close_window:
            self.close_window()

    def reset_to_original(self):
        # Reverts every input control group back to initial class instantiation snapshots
        for key, widget in self.entries.items():
            original_val = self.initial_config.get(key)
            widget.set(original_val)
            if hasattr(widget, 'validate'):
                widget.validate()
            elif hasattr(widget, 'entry_box_updated'):
                widget.entry_box_updated()

###############################################################################################
# Absolute package imports
from . import complex_throttle
from . import dcc_control
from .config_window import LocoConfigWindow, MqttConfigWindow, GeneralConfigWindow
from .camera_utility import CameraConfigWindow

import logging
from logging.handlers import QueueHandler, QueueListener
import tkinter as Tk
from tkinter import filedialog, messagebox
import json
import sys
import queue

class ThrottleApplication(Tk.Tk):

    #-----------------------------------------------------------------------------------------
    # Initialisation Function - creates the UI elements and sets thedefault parameters
    #-----------------------------------------------------------------------------------------

    def __init__(self):
        super().__init__()
        self.title("Cab Control Throttle System")
        # Create the main menubar
        menubar = Tk.Menu(self)
        # File Menu
        file_menu = Tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Load Locomotive...", command=self.load_throttle_file)
        file_menu.add_command(label="Save Locomotive...", command=self.save_throttle_file)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=file_menu)
        # Loco Configuration - Direct action button with no sub items
        menubar.add_command(label="Loco-Configuration", command=self.open_loco_config)
        # Settings Menu
        settings_menu = Tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="MQTT...", command=self.open_mqtt_settings)
        settings_menu.add_command(label="General...", command=self.open_general_settings)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        # Tools Menu
        tools_menu = Tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Camera Setup...", command=self.open_camera_tool)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        # Help Menu
        help_menu = Tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Help...", command=self.open_help)
        help_menu.add_command(label="About...", command=self.open_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)
        # Master container for the scroll components
        self.workspace_container = Tk.Frame(self)
        self.workspace_container.pack(fill=Tk.BOTH, expand=True)
        # Canvas viewport and the Scrollbar
        self.canvas = Tk.Canvas(self.workspace_container, borderwidth=0, highlightthickness=0)
        self.scrollbar = Tk.Scrollbar(self.workspace_container, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        # Layout positioning
        self.scrollbar.pack(side=Tk.RIGHT, fill=Tk.Y)
        self.canvas.pack(side=Tk.LEFT, fill=Tk.BOTH, expand=True)
        # Inner frame inside the Canvas
        self.workspace = Tk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.workspace, anchor="nw")
        # Dynamic size bindings to handle resizing cleanly
        self.workspace.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))
        # Trackpad and mouse wheel listeners
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        # Create the Throttle UI element & Initialise inside the scrollable workspace
        self.dcc_throttle = dcc_control.remote_dcc_throttle(root_window=self, parent_frame=self.workspace)
        self.active_throttle = complex_throttle.complex_throttle(root_window=self, parent_frame=self.workspace)
        # Set the UI with the default params
        default_config = self.get_default_configuration()
        self.dcc_throttle.set_session_callback(self.loco_session_updated)
        self.dcc_throttle.update_parameters(**default_config["mqtt_settings"])
        self.dcc_throttle.update_loco_dcc_address(default_config["locomotive"]["dcc_address"])
        self.active_throttle.update_parameters(**default_config["locomotive"])
        self.active_throttle.enable_audio(default_config["general_settings"]["sound_enabled"])
        logging.getLogger().setLevel(default_config["general_settings"]["log_level"])
        # Current configuration is the default configuration at application start
        self.current_configuration = self.get_default_configuration()
        # Dynamic Window Geometry Initialization
        self.adjust_window_geometry()

    #-----------------------------------------------------------------------------------------
    # This handles the session updated callback from DCC Control and passes it to the throttle
    #-----------------------------------------------------------------------------------------

    def loco_session_updated(self, session_id:int):
        self.active_throttle.activate_loco_session(session_id)
        
    #-----------------------------------------------------------------------------------------
    # Resize window on initialisation and file load - If the window will fit on the screen
    # fully then it aill be sized fullsize - if the window height is greater than the screen
    # height then it will made smaller to fit (with a scrollbar to access the entire window)
    #-----------------------------------------------------------------------------------------

    def adjust_window_geometry(self):
        self.update_idletasks()  # Force Tkinter to calculate total widget sizes
        # Determine how much space the widgets actually want
        req_width = self.workspace.winfo_reqwidth() + self.scrollbar.winfo_reqwidth()
        req_height = self.workspace.winfo_reqheight()
        # Get user's screen boundaries
        screen_height = self.winfo_screenheight()
        # Restrict window height to 85% of screen height to clear OS panels safely
        max_allowed_height = int(screen_height * 0.85)
        if req_height > max_allowed_height:
            final_height = max_allowed_height
        else:
            final_height = req_height
        # Temporarily unlock to apply new dimensions
        self.resizable(True, True)      
        self.geometry(f"{req_width}x{final_height}")
        self.resizable(False, False)      

    #-----------------------------------------------------------------------------------------
    # Class Method to define and return the default throttle configuration. Used on initialisation
    # and also on layout load to 'fill in' any blanks for backwards compatibility
    #-----------------------------------------------------------------------------------------

    def get_default_configuration(self):
        return {
            "locomotive": {
                "loco_name": "Class 47",
                "loco_mass_tonnes": 120,
                "loco_horsepower": 2580,
                "loco_max_speed_mph": 95,
                "max_tractive_effort_lbf": 62000,
                "traction_responsiveness": 0.05,
                "brake_responsiveness": 0.08,
                "dcc_address": 47,
                "dcc_speed_scaling": 1.0,
                "axle_offsets_ft": [0.0, 7.0, 14.0, 40.0, 47.0, 54.0],
                "fwd_stream_url": "localhost",
                "rev_stream_url": ""
            },
            "general_settings": {
                "sound_enabled": True,
                "log_level": 20,  # 20 is the standard standard-library logging.INFO level
                "connect_immediately": False
            },
            "mqtt_settings": {
                "broker_host": "localhost",
                "broker_port": 1883,
                "broker_username": "",
                "broker_password": "",
                "network_identifier": "LAYOUT",
                "throttle_node_identifier": "TH01",
                "enhanced_debugging": True,
                "command_station_node_identifier": "CS01"
            }
        }
    
    #-----------------------------------------------------------------------------------------
    # class Methods for loading and saving throttle configuration files. On loading, note that
    # any 'blanks' are filled in with the values from the default configuration (above)
    #-----------------------------------------------------------------------------------------

    def load_throttle_file(self):
        file_path = filedialog.askopenfilename(
            parent=self, defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")] )
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    loaded_config = json.load(f)
                # Fetch full structural dictionary with defaults
                final_config = self.get_default_configuration()
                # Direct block-by-block overwrite update
                for block in ["locomotive", "general_settings", "mqtt_settings"]:
                    if block in loaded_config and isinstance(loaded_config[block], dict):
                        final_config[block].update(loaded_config[block])
            except Exception as e:
                messagebox.showerror("Load Error", f"Failed to parse locomotive profile:\n{str(e)}")
            else:
                # Update configurations and pass locomotive properties downstream
                self.current_configuration = final_config
                self.active_throttle.update_parameters(**final_config["locomotive"])
                self.active_throttle.enable_audio(final_config["general_settings"]["sound_enabled"])
                self.dcc_throttle.update_loco_dcc_address(final_config["locomotive"]["dcc_address"])
                self.dcc_throttle.update_parameters(**final_config["mqtt_settings"])
                # Connect to the broker on file load if requested
                if final_config["general_settings"]["connect_immediately"]: dcc_throttle.mqtt_broker_connect()
                # Update the logging level
                logging.getLogger().setLevel(default_config["general_settings"]["log_level"])
                # Expand/shrink the window as appropriate (to pack/forget the video stream)
                self.adjust_window_geometry()

    def save_throttle_file(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")])
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    json.dump(self.current_loco_configuration, f, indent=4)
                messagebox.showinfo("Success", "Locomotive configuration saved successfully.")
            except Exception as e:
                messagebox.showerror("Save Error", f"Failed to write file:\n{str(e)}")
                
    #-----------------------------------------------------------------------------------------
    # Class methods for opening the various settings windows and then applying the changes
    #-----------------------------------------------------------------------------------------

    def open_loco_config(self):
        current_loco_config = self.current_configuration["locomotive"]
        LocoConfigWindow(self, current_loco_config, save_callback=self.apply_loco_config_changes)

    def apply_loco_config_changes(self, new_loco_config):
        self.active_throttle.update_parameters(**new_loco_config)
        self.dcc_throttle.update_loco_dcc_address(new_loco_config["dcc_address"])
        self.current_configuration["locomotive"] = new_loco_config

    def open_mqtt_settings(self):
        current_mqtt_config = self.current_configuration["mqtt_settings"]
        MqttConfigWindow(self, current_mqtt_config, save_callback=self.apply_mqtt_config_changes)

    def apply_mqtt_config_changes(self, new_mqtt_config):
        self.dcc_throttle.update_parameters(**new_mqtt_config)
        self.current_configuration["mqtt_settings"] = new_mqtt_config

    def open_general_settings(self):
        current_general_config = self.current_configuration["general_settings"]
        GeneralConfigWindow(self, current_general_config, save_callback=self.apply_general_config_changes)
        
    def apply_general_config_changes(self, new_general_config):
        self.active_throttle.enable_audio(new_general_config["sound_enabled"])
        self.current_configuration["general_settings"] = new_general_config
        logging.getLogger().setLevel(new_general_config["log_level"])

    def open_camera_tool(self):
        CameraConfigWindow(self)

    def open_help(self):
        messagebox.showinfo("Help", "Help documentation coming soon!")

    def open_about(self):
        messagebox.showinfo("About", "About System dialog coming soon!")

    #-----------------------------------------------------------------------------------------
    # Class method for performing an orderly shutdown of the application
    #-----------------------------------------------------------------------------------------

    def on_exit(self):
        self.active_throttle.on_close()
        self.dcc_throttle.on_close()
        # Completely terminate the UI mainloop, kill the application window tree and hard exit
        self.quit()
        sys.exit(0)

#---------------------------------------------------------------------------------------------
# the main application code starts here
#---------------------------------------------------------------------------------------------

def start_throttle():
    #---------------------------------------------------------------------------------
    # Set up the logging (we use queues to avoind locking problems betweeen threads)
    #---------------------------------------------------------------------------------
    # Get the root logger
    current_logger = logging.getLogger()
    # REMOVE any existing handlers to prevent duplicates
    while current_logger.handlers: current_logger.removeHandler(current_logger.handlers[0])
    # Create a queue for log records
    log_queue = queue.Queue(-1) # Infinite size
    # Set a formatter for the logs
    formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
    # Setup the Terminal Handler (StreamHandler) and file handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    # Track handlers dynamically
    listener_handlers = [console_handler]
#     file_log_handler = None
#     file_error_msg = None
#     try:
#         # Try to create the file log handler
#         file_log_handler = logging.FileHandler("model_railway_signalling.log", mode='w')
#         file_log_handler.setFormatter(formatter)
#         listener_handlers.append(file_log_handler)
#     except OSError as e:
#         # If it fails, we revert to just using the console handler
#         file_error_msg = f"Logging to file disabled: {e}"
    # Create the Listener that runs in the background, pull logs from the queue and send them to the handlers
    log_listener = QueueListener(log_queue, *listener_handlers)
    log_listener.start()
    # Configure the root logger to use the QueueHandler
    root_logger = logging.getLogger()
    root_logger.addHandler(QueueHandler(log_queue))
#     # Add a header into the file or Put out a warning message if we failed to create it
#     if file_log_handler:
#         timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
#         file_log_handler.stream.write(f"{timestamp} - Starting Model Railway Throttle application\n")
#         file_log_handler.flush()
#         try: os.fsync(file_log_handler.stream.fileno())
#         except (AttributeError, ValueError): pass
#     else:
#         logging.warning(file_error_msg)
    #---------------------------------------------------------------------------------
    # Start the application
    #---------------------------------------------------------------------------------
    application = ThrottleApplication()
    application.protocol("WM_DELETE_WINDOW", application.on_exit)
    #---------------------------------------------------------------------------------
    # Configure Tkinter to not show hidden files in the file open/save dialogs
    # Full credit to Stack Overflow for the solution to this problem
    #---------------------------------------------------------------------------------
    try:
        try:
            application.tk.call('tk_getOpenFile', '-foobarbaz')
        except Tk.TclError:
            pass
        application.tk.call('set', '::tk::dialog::file::showHiddenVar', '0')
    except:
        pass
    #---------------------------------------------------------------------------------
    # Start the Application Main Loop
    #---------------------------------------------------------------------------------
    application.mainloop()

##############################################################################################
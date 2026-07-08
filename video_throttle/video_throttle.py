# Absolute package imports
from . import complex_throttle
from . import dcc_control
from .config_window import LocoConfigWindow

import tkinter as Tk
from tkinter import filedialog, messagebox
import json
import sys
import logging

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
        file_menu.add_command(label="Load Loco Config...", command=self.load_throttle_file)
        file_menu.add_command(label="Save Loco Config...", command=self.save_throttle_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=file_menu)
        # Configuration Menu
        config_menu = Tk.Menu(menubar, tearoff=0)
        config_menu.add_command(label="Edit Loco Dynamics...", command=self.open_loco_config)
        config_menu.add_command(label="MQTT Network Settings...", command=self.open_mqtt_settings)
        menubar.add_cascade(label="Configuration", menu=config_menu)
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
        # --- Dynamic Window Geometry Initialization ---
        self.adjust_window_geometry()
        #############################################
        logging.getLogger().setLevel(logging.DEBUG)
        #############################################
        
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
    # Function to define and return the default throttle configuration. Used on initialisation
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
    # Function to load a throttle file containing the required settings and loco configuration
    # Any 'blanks' are filled in with the values from the default configuration (above)
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

    def open_loco_config(self):
        current_config = self.current_loco_configuration
        LocoConfigWindow(self, current_config, save_callback=self.apply_config_changes)

    def apply_config_changes(self, new_config):
        self.active_throttle.update_parameters(**new_config)
        self.current_loco_configuration = new_config

    def open_mqtt_settings(self):
        messagebox.showinfo("Network", "MQTT Network Configuration dialog coming soon!")
        
    def on_mqtt_message(self, message):
        pass

    def on_exit(self):
        self.active_throttle.on_close()
        self.dcc_throttle.on_close()
        # Completely terminate the UI mainloop, kill the application window tree and hard exit
        self.quit()
        sys.exit(0)

def start_throttle():
    application = ThrottleApplication()
    application.protocol("WM_DELETE_WINDOW", application.on_exit)
    application.mainloop()

####################################################################################################
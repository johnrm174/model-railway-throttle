from . import mqtt_interface
from . import common

import tkinter as Tk
from tkinter import messagebox
import logging

class remote_dcc_throttle(Tk.LabelFrame):
    
    #----------------------------------------------------------------------------------------------------
    # Init Function to create all UI Elements for the complex throttle
    #----------------------------------------------------------------------------------------------------
    
    def __init__(self, root_window, parent_frame):
        super().__init__(parent_frame)
        self.pack(fill=Tk.BOTH, expand=False)
        self.root_window = root_window
        common.set_root_window(root_window)
        # --- UI Sub-Component: Top Control Toolbar ---
        toolbar_frame = Tk.LabelFrame(self)
        toolbar_frame.pack(side=Tk.TOP, fill=Tk.X, padx=0, pady=5)
        # Create a dummy button to harvest default system colors natively across platform OS targets
        dummy = Tk.Button(self)
        self.default_bg = dummy.cget("bg")
        self.default_fg = dummy.cget("fg")
        self.default_abg = dummy.cget("activebackground")
        self.default_afg = dummy.cget("activeforeground")
        #Buttons -  Fixed width of 20 characters accommodates all state variations without resizing
        self.btn_mqtt = Tk.Button(toolbar_frame, text="MQTT: Disconnected", font=('Arial', 9, 'bold'), 
                                  width=18, command=self.toggle_mqtt_connection)
        self.btn_mqtt.pack(side=Tk.LEFT, padx=5, pady=5, expand=True, fill=Tk.X)

        self.track_power_button = Tk.Button(toolbar_frame, text="Track Power: ???", font=('Arial', 9, 'bold'), 
                                       width=18, state="disabled", command=self.toggle_dcc_power)
        self.track_power_button.pack(side=Tk.LEFT, padx=5, pady=5, expand=True, fill=Tk.X)

        self.session_button = Tk.Button(toolbar_frame, text="Get Session", font=('Arial', 9, 'bold'), 
                                     width=18, state="disabled", command=self.toggle_session)
        self.session_button.pack(side=Tk.LEFT, padx=5, pady=5, expand=True, fill=Tk.X)
        # Internal Tracking States
        self.mqtt_connected = False
        self.dcc_power_on = None
        self.dcc_address = 0
        self.session_id = 0
        # Internal Settings
        self.broker_host = "localhost"
        self.broker_port = 0
        self.broker_username = ""
        self.broker_password = ""
        self.network_identifier = ""
        self.throttle_node_identifier = ""
        self.command_station_node_identifier = ""
        self.enhanced_debugging = False
        # Callback for session updates
        self.session_callback = None
        self.session_request_sent = False
        # Scheduled events for timeout messages
        self.session_request_timeout_id = None
        self.track_power_on_timeout_id = None
        self.track_power_off_timeout_id = None
        
    #----------------------------------------------------------------------------------------------------
    # Action triggers for Toolbar Buttons
    #----------------------------------------------------------------------------------------------------

    def toggle_mqtt_connection(self):
        if not self.mqtt_connected:
            # The mqtt_broker_connect function will raise a pop up error message if it timesout
            mqtt_interface.mqtt_broker_connect(self.broker_host, self.broker_port,
                    self.mqtt_connection_state_updated, self.broker_username, self.broker_password)
        else:
            # Release any Loco sessions before disconnecting (we don't wait for a response)
            # We don't force DCC power to be turned off as other throttles might be connected
            self.release_loco_session()
            mqtt_interface.mqtt_broker_disconnect()

    def toggle_dcc_power(self):
        if not self.dcc_power_on:
            self.request_track_power_on()
        else:
            # Release any Loco sessions before turning DCC Power off (we don't wait for a response)
            self.release_loco_session()
            self.request_track_power_off()

    def toggle_session(self):
        if self.session_id == 0:
            self.request_loco_session()
        else:
            self.release_loco_session()

    #----------------------------------------------------------------------------------------------------
    # API FUNCTION to connect to the broker (following layout load)
    #----------------------------------------------------------------------------------------------------

    def mqtt_broker_connect(self):
        mqtt_interface.mqtt_broker_connect(self.broker_host, self.broker_port,
            self.mqtt_connection_state_updated, self.broker_username, self.broker_password)

    #----------------------------------------------------------------------------------------------------
    # API FUNCTIONS to update the current MQTT settings, DCC address and session callback
    #----------------------------------------------------------------------------------------------------

    def update_parameters(self, broker_host:str, broker_port:int, broker_username:str, broker_password:str, enhanced_debugging:bool,
                            network_identifier:str, throttle_node_identifier:str, command_station_node_identifier:str):
        # Internal Settings
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.broker_username = broker_username
        self.broker_password = broker_password
        self.network_identifier = network_identifier
        self.throttle_node_identifier = throttle_node_identifier
        self.command_station_node_identifier = command_station_node_identifier
        self.enhanced_debugging = enhanced_debugging
        # Configure the MQTT interface (signalling network configuration)
        mqtt_interface.configure_mqtt_client(self.network_identifier, self.throttle_node_identifier, self.enhanced_debugging)
        # Reconfigure the MQTT broker if we are already connected (if not then we just wait for the next connect)
        if self.mqtt_connected:
            # Release any Loco sessions before disconnect/reconnect
            self.release_loco_session()
            mqtt_interface.mqtt_broker_connect(self.broker_host, self.broker_port,
                    self.mqtt_connection_state_updated, self.broker_username, self.broker_password)
        # Clear down any existing subscriptions
        mqtt_interface.unsubscribe_from_message_type("dcc_locomotive_control_responses")
        # Subscribe to response messages from the specified node
        mqtt_interface.subscribe_to_mqtt_messages("dcc_locomotive_control_responses",
                    self.command_station_node_identifier, 0, self.handle_mqtt_dcc_locomotive_control_response)

    def update_loco_dcc_address(self, dcc_address:int):
        self.dcc_address = dcc_address
        
    def set_session_callback(self, session_callback):
        self.session_callback = session_callback
                      
    #----------------------------------------------------------------------------------------------------
    # Functions to Request/release loco sessions from the remote node and deal with the responses
    #----------------------------------------------------------------------------------------------------
    
    def update_session_button_state(self, session_id:int):
        if session_id > 0:
            self.session_button.configure(text="Release Session", bg="#de2a2a", fg="white",
                    activebackground="#b22020", activeforeground="white", state="normal")
        else:
            self.session_button.configure(text="Get Session", bg=self.default_bg, fg=self.default_fg,
                    activebackground=self.default_abg, activeforeground=self.default_afg, state="normal")
    
    def request_loco_session(self):
        # Cancel any pending timeout messages
        if self.session_request_timeout_id is not None:
            self.root_window.after_cancel(self.session_request_timeout_id)
            self.session_request_timeout_id = None
        # To Request a remote session we send the DCC Address with a Session ID of zero
        # We should get an acknowledgement message from the remote node
        if self.dcc_address > 0:
            # Inhibit the button until we get a response or timeout
            self.session_button.configure(state="disabled")
            mqtt_message = {"dccaddress": self.dcc_address, "sessionid": 0}
            mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=False,
                    log_message=f"Loco Control: Publishing loco control message to broker :{mqtt_message}")
            self.session_request_sent = True
            # Schedule a timeout check to generate an error message if we don't get a response within 3 seconds
            self.session_request_timeout_id = self.root_window.after(3000, self.raise_session_request_timeout_error)
        else:
            messagebox.showerror("Invalid Address", "Please specify a valid DCC address")
            
    def raise_session_request_timeout_error(self):
        messagebox.showerror("Timeout error", "Session request timeout")
        self.session_request_timeout_id = None
        self.session_button.configure(state="normal")
        self.session_request_sent = False
        
    def session_request_response_received(self, session_id:int):
        # Cancel any pending timeout messages
        if self.session_request_timeout_id:
            self.root_window.after_cancel(self.session_request_timeout_id)
            self.session_request_timeout_id = None
        # Raise an error if we have requested a session but the returned Session ID is zero
        if session_id == 0 and self.session_request_sent:
            messagebox.showerror("Session Error", f"Could not acquire session for DCC Address {self.dcc_address}")
        # process the response
        self.session_id = session_id
        self.update_session_button_state(self.session_id)
        self.session_request_sent = False
        if self.session_callback:
            self.session_callback(self.session_id)
        
    def release_loco_session(self):
        if self.session_id > 0:
            # Inhibit the button until we get a response or timeout
            self.session_button.configure(state="disabled")
            # Send a message to release the current session
            mqtt_message = {"dccaddress": 0, "sessionid": self.session_id}
            mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=False,
                        log_message=f"Loco Control: Releasing session: {mqtt_message}")
            # The above message is fire and forget - we won't get an acknowledgement so
            # We always assume the session has been successfully released by the remote node
            self.session_id = 0
            self.update_session_button_state(self.session_id)
            if self.session_callback:
                self.session_callback(self.session_id)
                     
    #----------------------------------------------------------------------------------------------------
    # Functions to handle power state requests and handle responses
    #----------------------------------------------------------------------------------------------------

    def update_power_button_state(self, dcc_power_on:bool):
        if dcc_power_on:
            self.track_power_button.configure(text="Track Power: ON", bg="#2ade7a", fg="white",
                        activebackground="#20b262", activeforeground="white", state="normal")
        else:
            self.track_power_button.configure(text="Track Power: OFF", bg=self.default_bg, fg=self.default_fg,
                        activebackground=self.default_abg, activeforeground=self.default_afg, state="normal")

    def request_track_power_on(self):
        # Cancel any pending timeout messages
        if self.track_power_on_timeout_id:
            self.root_window.after_cancel(self.track_power_on_timeout_id)
            self.track_power_on_timeout_id = None
        # Inhibit the button until we get a response or timeout
        self.track_power_button.configure(state="disabled")
        # Send the command to the remote node. We should get an acknowledgement message from the remote node
        mqtt_message = {"requestdccpower": True}
        mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=False,
                log_message=f"Loco Control: Publishing loco control message to broker :{mqtt_message}")
        # Schedule a timeout check to generate an error message if we don't get a response within 3 seconds
        self.track_power_on_timeout_id = self.root_window.after(3000, self.raise_track_power_on_timeout_error)

    def raise_track_power_on_timeout_error(self):
        messagebox.showerror("Timeout Error", "Track Power on request timeout")
        self.track_power_on_timeout_id = None
        self.track_power_button.configure(state="normal")

    def request_track_power_off(self):
        # Cancel any pending timeout messages
        if self.track_power_off_timeout_id:
            self.root_window.after_cancel(self.track_power_off_timeout_id)
            self.track_power_off_timeout_id = None
        # Inhibit the button until we get a response or timeout
        self.track_power_button.configure(state="disabled")
        # Send the command to the remote node. We should get an acknowledgement message from the remote node
        mqtt_message = {"requestdccpower": False}
        mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=False,
                log_message=f"Loco Control: Publishing loco control message to broker :{mqtt_message}")
        # Schedule a timeout check to generate an error message if we don't get a response within 3 seconds
        self.track_power_off_timeout_id = self.root_window.after(3000, self.raise_track_power_off_timeout_error)

    def raise_track_power_off_timeout_error(self):
        messagebox.showerror("Timeout Error", "Track Power off request timeout")
        self.track_power_off_timeout_id = None
        self.track_power_button.configure(state="normal")

    def track_power_response_received(self, dcc_power_state:bool):
        # Cancel any pending timeout messages
        if self.track_power_on_timeout_id:
            self.root_window.after_cancel(self.track_power_on_timeout_id)
            self.track_power_on_timeout_id = None
        if self.track_power_off_timeout_id:
            self.root_window.after_cancel(self.track_power_off_timeout_id)
            self.track_power_off_timeout_id = None
        # Handle the track power response
        self.dcc_power_on = dcc_power_state
        self.update_power_button_state(self.dcc_power_on)
        
    #----------------------------------------------------------------------------------------------------
    # State Synchronization & UI Interlock Management
    #----------------------------------------------------------------------------------------------------

    def mqtt_connection_state_updated(self, connected:bool):
        self.mqtt_connected = connected
        if self.mqtt_connected:
            self.btn_mqtt.configure(text="MQTT: Connected", bg="#2ae1de", fg="black",
                                    activebackground="#20b5b2", activeforeground="black", state="normal")
            # Enable Power and Session buttons when connected
            self.track_power_button.configure(state="normal")
            self.session_button.configure(state="normal")
        else:
            self.btn_mqtt.configure(text="MQTT: Disconnected", bg=self.default_bg, fg=self.default_fg,
                                    activebackground=self.default_abg, activeforeground=self.default_afg)
            # Disable Power and Session buttons
            self.track_power_button.configure(state="disabled")
            self.session_button.configure(state="disabled")

    #----------------------------------------------------------------------------------------------------
    # Callback for handling loco session and DCC power response messages received from the remote node
    # Example messages are as follows:
    # Track Power: {"sourceidentifier":"BOX1" , "dccpowerstate": True}
    # Failed Session Request Response: {"sourceidentifier":"BOX1" , "dccaddress": 123, "sessionid": 0}
    # Successful Session Request Response: {"sourceidentifier":"BOX1" , "dccaddress": 123, "sessionid": 10}
    #----------------------------------------------------------------------------------------------------

    def handle_mqtt_dcc_locomotive_control_response(self, message):
        if "sourceidentifier" not in message.keys():
            logging.error (f"Loco Control: Unhandled MQTT Response Message - {message}")
        else:
            # All Messages include the following mandatory elements
            source_node = message["sourceidentifier"]
            # Only process the message if the messige is from 'our' command station node
            command_station_node_identifier_to_match = self.command_station_node_identifier+"-0"
            if source_node == command_station_node_identifier_to_match:
                # The following elements are optional - if not present then the values will be set to none
                dcc_address = message.get("dccaddress")
                session_id = message.get("sessionid")
                dcc_power_state = message.get("dccpowerstate")
                # Handle a DCC Power is ON or OFF message
                if dcc_power_state is not None:
                    logging.debug(f"Loco Control: Received DCC Power State message from {source_node} "
                                       +f" - DCC Power state: {dcc_power_state}")
                    self.track_power_response_received(dcc_power_state)
                # Handle a Loco Session acknowledgement message 
                elif dcc_address == self.dcc_address and session_id is not None:
                    logging.debug(f"Loco Control: Received session acknowledgement from {source_node}: "
                                       +f"DCC Address {dcc_address}, Session ID is {session_id}")
                    self.session_request_response_received(session_id)

    #----------------------------------------------------------------------------------------------------
    # Function to gracefully shut down on window close
    #----------------------------------------------------------------------------------------------------
            
    def on_close(self):
        # Release any active sessions and disconnect from broker
        if self.mqtt_connected:
            self.release_loco_session()
            mqtt_interface.mqtt_broker_disconnect()


##############################################################################################################################
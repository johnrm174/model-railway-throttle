from . import complex_throttle
from . import mqtt_interface
from . import common

import tkinter as Tk
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

        self.btn_dcc_power = Tk.Button(toolbar_frame, text="Track Power: OFF", font=('Arial', 9, 'bold'), 
                                       width=18, state="disabled", command=self.toggle_dcc_power)
        self.btn_dcc_power.pack(side=Tk.LEFT, padx=5, pady=5, expand=True, fill=Tk.X)

        self.btn_session = Tk.Button(toolbar_frame, text="Get Session", font=('Arial', 9, 'bold'), 
                                     width=18, state="disabled", command=self.toggle_session)
        self.btn_session.pack(side=Tk.LEFT, padx=5, pady=5, expand=True, fill=Tk.X)
        # Internal Tracking States
        self.mqtt_connected = False
        self.dcc_power_on = False
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
        # Callback for session updates
        self.session_callback = None
        self.session_requested = False
        
    #----------------------------------------------------------------------------------------------------
    # Action triggers for Toolbar Buttons
    #----------------------------------------------------------------------------------------------------

    def toggle_mqtt_connection(self):
        if not self.mqtt_connected:
            mqtt_interface.mqtt_broker_connect(self.broker_host, self.broker_port,
                    self.mqtt_connection_state_updated, self.broker_username, self.broker_password)
        else:
            # Release any Loco sessions before disconnecting (we don't wait for a response
            self.release_loco_session()
            mqtt_interface.mqtt_broker_disconnect()

    def toggle_dcc_power(self):
        if not self.dcc_power_on:
            self.request_track_power_on()
        else:
            self.request_track_power_off()

    def toggle_session(self):
        if self.session_id == 0:
            self.request_loco_session()
        else:
            self.release_loco_session()

    #----------------------------------------------------------------------------------------------------
    # API FUNCTION to update the current MQTT settings
    #----------------------------------------------------------------------------------------------------

    def update_parameters(self, broker_host:str, broker_port:int, broker_username:str, broker_password:str, enhanced_debugging:bool,
                            network_identifier:str, throttle_node_identifier:str, command_station_node_identifier:str):
        # Internal Settings
        self.broker_host = "localhost"
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
            self.release_current_session()
            mqtt_interface.broker_connect(self.broker_host, self.broker_port,
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
    # Functions to Request/Release loco sessions from the remote node
    #----------------------------------------------------------------------------------------------------
    
    def request_loco_session(self):
        # To Request a remote session we send the DCC Address with a Session ID of zero
        # We should get an acknowledgement message from the remote node
        if self.dcc_address > 0:
            self.session_requested = True
            mqtt_message = {"dccaddress": self.dcc_address, "sessionid": 0}
            mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=True,
                    log_message=f"Loco Control: Publishing loco control message to broker :{mqtt_message}")
            ###################################################################################################
            ############ Neet to schedule a timeout check to generate an error message if we ##################
            ############ Don't get a response back within, say 5 seconds ######################################
            ###################################################################################################
        else:
            pass
            ###################################################################################################
            ############ Popup error message - need to specify a valid dcc address ############################
            ###################################################################################################

    def release_loco_session(self):
        if self.session_id > 0:
            # Send a fire and forget message to release the current session
            mqtt_message = {"dccaddress": 0, "sessionid": self.session_id}
            mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=True,
                        log_message=f"Loco Control: Releasing session: {mqtt_message}")
            # We always assume the session has been released
            self.session_id = 0
            self.session_response_received(self.session_id) ############################# NEED A response here
            self.session_callback(self.session_id)

    #----------------------------------------------------------------------------------------------------
    # Callbacks to handle power state requests/responses for a remote node
    #----------------------------------------------------------------------------------------------------

    def request_track_power_on(self):
        # Send the command to the remote node. We should get an acknowledgement message from the remote node
        mqtt_message = {"requestdccpower": True}
        mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=True,
                log_message=f"Loco Control: Publishing loco control message to broker :{mqtt_message}")
        ###################################################################################################
        ############ Neet to schedule a timeout check to generate an error message if we ##################
        ############ Don't get a response back within, say 5 seconds ######################################
        ###################################################################################################

    def request_track_power_off(self):
        # Send the command to the remote node. We should get an acknowledgement message from the remote node
        mqtt_message = {"requestdccpower": False}
        mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=True,
                log_message=f"Loco Control: Publishing loco control message to broker :{mqtt_message}")
        ###################################################################################################
        ############ Neet to schedule a timeout check to generate an error message if we ##################
        ############ Don't get a response back within, say 5 seconds ######################################
        ###################################################################################################

    #----------------------------------------------------------------------------------------------------
    # State Synchronization & UI Interlock Management
    #----------------------------------------------------------------------------------------------------

    def mqtt_connection_state_updated(self, connected:bool):
        self.mqtt_connected = connected
        if self.mqtt_connected:
            self.btn_mqtt.configure(text="MQTT: Connected", bg="#2ae1de", fg="black",
                                    activebackground="#20b5b2", activeforeground="black", state="normal")
            # Enable Power and Session buttons when connected
            self.btn_dcc_power.configure(state="normal")
            self.btn_session.configure(state="normal")
        else:
            self.btn_mqtt.configure(text="MQTT: Disconnected", bg=self.default_bg, fg=self.default_fg,
                                    activebackground=self.default_abg, activeforeground=self.default_afg)
            # Disable Power and Session buttons
            self.btn_dcc_power.configure(state="disabled")
            self.btn_session.configure(state="disabled")

    def dcc_power_state_updated(self, dcc_power_state:bool):
        self.dcc_power_on = dcc_power_state
        if dcc_power_state:
            self.btn_dcc_power.configure(text="Track Power: ON", bg="#2ade7a", fg="white",
                                         activebackground="#20b262", activeforeground="white")
        else:
            self.btn_dcc_power.configure(text="Track Power: OFF", bg=self.default_bg, fg=self.default_fg,
                                         activebackground=self.default_abg, activeforeground=self.default_afg)
            
    def session_response_received(self, session_id:int):
        self.session_id = session_id
        if self.session_id > 0:
            self.btn_session.configure(text="Release Session", bg="#de2a2a", fg="white",
                                       activebackground="#b22020", activeforeground="white")
        else:
            self.btn_session.configure(text="Get Session", bg=self.default_bg, fg=self.default_fg,
                                       activebackground=self.default_abg, activeforeground=self.default_afg)
        self.session_callback(self.session_id)

    #----------------------------------------------------------------------------------------------------
    # Callback for handling loco session and DCC power response messages received from the remote node
    #----------------------------------------------------------------------------------------------------

    def handle_mqtt_dcc_locomotive_control_response(self, message):
        if "sourceidentifier" not in message.keys():
            logging.error (f"Loco Control: Unhandled MQTT Response Message - {message}")
        else:
            # All Messages include the following mandatory elements
            source_node = message["sourceidentifier"]
            # The following elements are optional - if not present then the values will be set to none
            dcc_address = message.get("dccaddress")
            session_id = message.get("sessionid")
            dcc_power_state = message.get("dccpowerstate")
            # Handle a DCC Power is ON or OFF message
            if dcc_power_state is not None:
                logging.debug(f"Loco Control: Received DCC Power State message from {source_node} "
                                   +f" - DCC Power state: {dcc_power_state}")
                self.dcc_power_state_updated(dcc_power_state)
            # Handle a Loco Session acknowledgement message
            elif dcc_address == self.dcc_address and self.session_requested and session_id is not None:
                logging.debug(f"Loco Control: Received session acknowledgement from {source_node}: "
                                   +f"DCC Address {dcc_address}, Session ID is {session_id}")
                self.session_response_received(session_id)
                self.session_requested = False

    #----------------------------------------------------------------------------------------------------
    # Function to gracefully shut down on window close
    #----------------------------------------------------------------------------------------------------
            
    def on_close(self):
        # Release any active sessions and disconnect from broker
        self.release_loco_session()
        mqtt_interface.mqtt_broker_disconnect()


##############################################################################################################################
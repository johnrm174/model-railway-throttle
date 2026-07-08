complex_throttle_enabled = False
try:
    import cv2  # Open Source Computer Vision Library (for cab-view video streams)
    import sounddevice  # Cross-platform audio stream management
    from PIL import Image, ImageTk  # Handles converting OpenCV frames into Tkinter images
    complex_throttle_enabled = True
except ImportError:
    # If dependencies are missing, fallback to a disabled video/audio state gracefully
    pass

import tkinter as Tk
import logging
import threading
import math
import numpy
import os

from .widgets import integer_entry_box

#--------------------------------------------------------------------------------------------------------
# Class for a generic dial object (based on a Tkinter Canvas)
#--------------------------------------------------------------------------------------------------------

class dial(Tk.Canvas):
    def __init__(self, parent, size, label, min_val, max_val, tick_step, color="white"):
        super().__init__(parent, width=size, height=size, highlightthickness=0)
        self.size = size
        self.min_val = min_val
        self.max_val = max_val
        self.tick_step = tick_step
        self.label_text = label
        self.needle_color = color
        self.center = size / 2
        self.radius = (size / 2) * 0.85
        self.setup_dial()

    def setup_dial(self):
        # Wipe the canvas clean
        self.delete("all")
        # Draw the instrument backing bezel
        self.create_oval(self.center-self.radius, self.center-self.radius, 
                         self.center+self.radius, self.center+self.radius, 
                         fill="#1a1a1a", outline="#444", width=3)
        # Render graduations and the center text label
        self.draw_ticks()
        self.create_text(self.center, self.center + (self.radius * 0.4), 
                         text=self.label_text, fill="White", font=("Arial", int(self.size/15), "bold"))
        # Draw the physical indicator needle
        self.needle = self.create_line(self.center, self.center, self.center, self.center, 
                                       fill=self.needle_color, width=max(2, int(self.size/40)), capstyle="round")
        # Center cap hub
        self.create_oval(self.center-5, self.center-5, self.center+5, self.center+5, fill="#333")
        self.update_dial(self.min_val)

    def recalibrate(self, new_max_val, new_tick_step=None):
        self.max_val = new_max_val
        if new_tick_step:
            self.tick_step = new_tick_step
        else:
            # Smart fallback step generation based on typical speed ranges
            if self.max_val <= 30: self.tick_step = 5
            elif self.max_val <= 100: self.tick_step = 10
            else: self.tick_step = 20
        self.setup_dial()

    def draw_ticks(self):
        total_range = self.max_val - self.min_val
        num_ticks = int(total_range / self.tick_step) + 1
        for i in range(num_ticks):
            val = self.min_val + (i * self.tick_step)
            # 135 degrees is bottom-left; sweeps 270 degrees clockwise to bottom-right
            angle = 135 + ((val - self.min_val) / total_range * 270)
            rad = math.radians(angle)
            # Inner and outer coordinate pairs for tick lines
            x_outer = self.center + self.radius * 0.95 * math.cos(rad)
            y_outer = self.center + self.radius * 0.95 * math.sin(rad)
            x_inner = self.center + self.radius * 0.80 * math.cos(rad)
            y_inner = self.center + self.radius * 0.80 * math.sin(rad)
            self.create_line(x_inner, y_inner, x_outer, y_outer, fill="white", width=1)
            # Place values on every other tick mark to avoid overlapping labels
            if i % 2 == 0 or num_ticks < 10:
                x_text = self.center + self.radius * 0.65 * math.cos(rad)
                y_text = self.center + self.radius * 0.65 * math.sin(rad)
                self.create_text(x_text, y_text, text=str(int(val)), 
                                 fill="white", font=("Arial", int(self.size/15)))

    def update_dial(self, value):
        value = max(self.min_val, min(self.max_val, value))
        if self.max_val == self.min_val:
            angle = 135
        else:
            angle = 135 + ((value - self.min_val) / (self.max_val - self.min_val) * 270)
        rad = math.radians(angle)
        x = self.center + self.radius * 0.85 * math.cos(rad)
        y = self.center + self.radius * 0.85 * math.sin(rad)
        self.coords(self.needle, self.center, self.center, x, y)
        
#--------------------------------------------------------------------------------------------------------
# Class for a complex throttle Window
#--------------------------------------------------------------------------------------------------------

class complex_throttle(Tk.LabelFrame):
    
    #----------------------------------------------------------------------------------------------------
    # Init Function to create all UI Elements for the complex throttle
    #----------------------------------------------------------------------------------------------------
    
    def __init__(self, root_window, parent_frame):
        super().__init__(parent_frame)
        self.pack(fill=Tk.BOTH, expand=False)
        self.root_window = root_window
        # --- UI Sub-Component: Cab Video Frame ---
        self.video_frame = Tk.Frame(self, bg="black", width=480, height=270)
        self.video_screen = Tk.Label(self.video_frame, text="Select Direction to Start Video", 
                                     fg="white", bg="black", width=60, height=15)
        self.video_screen.pack(fill=Tk.BOTH, expand=True)
        # --- UI Sub-Component: Control Desk Base Frame ---
        self.control_desk = Tk.Frame(self)
        self.control_desk.pack(side=Tk.TOP, fill=Tk.X, padx=10, pady=5)
        # Left Column: Locomotive Power Throttle Slider (8-Notch Detents)
        left_lever_frame = Tk.Frame(self.control_desk, width=80, height=340)
        left_lever_frame.pack(side=Tk.LEFT, padx=10, fill=Tk.Y)
        left_lever_frame.pack_propagate(False) 
        Tk.Label(left_lever_frame, text="THROTTLE", font=('Arial', 10, 'bold')).pack(side=Tk.TOP)
        self.throttle_demand = Tk.DoubleVar(value=0)
        self.throttle = Tk.Scale(left_lever_frame, from_=100, to=0, orient="vertical", width=50, length=320, state="disabled",
                                 sliderlength=40, variable=self.throttle_demand, resolution=12.5, tickinterval=12.5, showvalue=0)
        self.throttle.pack(side=Tk.TOP, fill=Tk.Y)
        # Center Column: Rolling Stock Mass Config & Dashboard Dials
        center_dashboard = Tk.Frame(self.control_desk)
        center_dashboard.pack(side=Tk.LEFT, padx=5, fill=Tk.BOTH)
        # Train Weight Settings
        self.total_mass_frame = Tk.Frame(center_dashboard)
        self.total_mass_frame.pack(pady=5)
        self.mass_label_frame = Tk.Frame(self.total_mass_frame)
        self.mass_label_frame.pack(side=Tk.TOP, anchor="center")
        self.mass_text_label = Tk.Label(self.mass_label_frame, text="No Loco Selected", font=('Arial', 10, 'bold'))
        self.mass_text_label.pack()
        line2_frame = Tk.Frame(self.total_mass_frame)
        line2_frame.pack(side=Tk.TOP, anchor="center", pady=(2, 0))
        Tk.Label(line2_frame, text="Load: ").pack(side=Tk.LEFT)
        self.load_mass_entry = integer_entry_box(line2_frame, width=5, min_val=0, max_val=3000, callback=self.mass_updated)
        self.load_mass_entry.pack(side=Tk.LEFT)
        Tk.Label(line2_frame, text=" (Tonnes)").pack(side=Tk.LEFT)
        # Instrument Layout
        self.speed_dial = dial(center_dashboard, 180, "MPH", 0, 100, 10, "orange")
        self.speed_dial.pack(pady=0)
        aux_dial_frame = Tk.Frame(center_dashboard)
        aux_dial_frame.pack(pady=0)
        self.power_dial = dial(aux_dial_frame, 120, "PWR\n  %", 0, 100, 25, "cyan")
        self.power_dial.pack(side=Tk.LEFT, padx=5)
        self.brake_dial = dial(aux_dial_frame, 120, "PSI\n  %", 0, 100, 20, "red")
        self.brake_dial.pack(side=Tk.LEFT, padx=5)
        # Right Column: Train Brake Control Lever (Continuous)
        right_lever_frame = Tk.Frame(self.control_desk, width=80, height=340)
        right_lever_frame.pack(side=Tk.LEFT, padx=10, fill=Tk.Y)
        right_lever_frame.pack_propagate(False)
        Tk.Label(right_lever_frame, text="BRAKE", font=('Arial', 10, 'bold')).pack(side=Tk.TOP)
        self.brake_demand = Tk.DoubleVar(value=100)
        self.brake = Tk.Scale(right_lever_frame, from_=100, to=0, orient="vertical", width=50, length=320, state="disabled",
                               sliderlength=40, variable=self.brake_demand, resolution=5, tickinterval=20, showvalue=0)
        self.brake.pack(side=Tk.TOP, fill=Tk.Y)
        # Bottom Sub-Component: Reverser and Emergency Protection Console
        button_console = Tk.Frame(self)
        button_console.pack(side=Tk.TOP, fill=Tk.X, padx=5, pady=(5, 5), ipady=5)
        
        self.btn_rev = Tk.Button(button_console, text="REV", font=('Arial', 10, 'bold'), 
                                 width=6, height=2, state="disabled", command=lambda: self.set_direction(False))
        self.btn_rev.pack(side=Tk.LEFT, expand=True, padx=5, pady=5)
        self.btn_estop = Tk.Button(button_console, text="EMERGENCY\nSTOP", font=('Arial', 10, 'bold'), 
                                   bg="#900", fg="white", activebackground="#f00", activeforeground="white",
                                   width=14, height=2, state="disabled", command=self.trigger_emergency_stop)
        self.btn_estop.pack(side=Tk.LEFT, expand=True, padx=5, pady=5)
        
        self.btn_fwd = Tk.Button(button_console, text="FWD", font=('Arial', 10, 'bold'), 
                                 width=6, height=2, state="disabled", command=lambda: self.set_direction(True))
        self.btn_fwd.pack(side=Tk.LEFT, expand=True, padx=5, pady=5)
        # Loop and Thread Structural Targets
        self.next_physics_loop_event = None
        self.next_video_loop_event = None
        self.audio_stream = None
        self.video_capture = None
        self.video_running = False
        # Locomotive Active State Placeholders
        self.loco_name = ""
        self.loco_mass = 0
        self.loco_max_speed = 100
        self.loco_horsepower = 100
        self.max_tractive_effort = 0
        self.traction_responsiveness = 0.0
        self.brake_responsiveness = 0.0
        self.axle_offsets = None
        self.axle_joint_indices = []
        self.fwd_stream_url = ""
        self.rev_stream_url = ""
        self.load_mass = 0
        self.total_mass = 0
        self.dcc_direction = None  
        self.dcc_speed_value = 0 
        self.session_id = 0 
        self.dcc_speed_scaling = 1.0  # Master scaling factor to tame fast physical model motors
        # Running Physics States
        self.target_throttle = 0.0
        self.target_brake = 0.0
        self.actual_power = 0.0   # Engine RPM / Spool state
        self.actual_brake = 0.0   # Braking pressure state (PSI percentage)
        self.current_speed = 0.0
        self.iterations = 0
        
        # --- Audio Cache Thread-Safety primitives ---
        # Copies the brake demand double-value locally, removing the need to fetch Tk variables 
        # inside the high-priority real-time audio callback thread context.
        self.cached_brake_demand = 100.0
        
        # Procedural Audio Synth Variables
        self.sample_rate = 22050
        self.stereo_buffer = numpy.zeros((8192, 2)) 
        self.hiss_buffer_len = self.sample_rate * 2
        self.pre_baked_hiss = numpy.random.normal(0, 0.12, self.hiss_buffer_len) * 0.2
        self.audio_sample_index = 0  
        self.track_distance = 0.0
        self.joint_spacing = 120.0 # Standard prototype rail length (feet) for joint clicks
        self.clack_lock = threading.Lock()
        self.pending_clacks = [] 
        self.active_clacks = []

    #----------------------------------------------------------------------------------------------------
    # Callback Function to update the load mass (and hence the total mass) of the train
    #----------------------------------------------------------------------------------------------------

    def mass_updated(self):
        self.load_mass = self.load_mass_entry.get()
        self.total_mass = self.loco_mass + self.load_mass
        if self.loco_name:
            self.mass_text_label.configure(text=f"{self.loco_name} ({self.total_mass} Tonnes)")

    #----------------------------------------------------------------------------------------------------
    # Function to gracefully shut down the audio, video and physics loops on shutdown
    #----------------------------------------------------------------------------------------------------
            
    def on_close(self):
        # 1. Immediately flag running loops to stop re-scheduling themselves
        self.video_running = False
        # 2. Cancel video frame loop safely
        if self.next_video_loop_event: 
            try: self.after_cancel(self.next_video_loop_event)
            except Exception: pass
            self.next_video_loop_event = None
        # 3. Cancel physics loop on the root window safely
        if self.next_physics_loop_event: 
            try: self.root_window.after_cancel(self.next_physics_loop_event)
            except Exception: pass
            self.next_physics_loop_event = None
        # 4. Clean up video stream capture threads
        if self.video_capture:
            self.video_capture.release()
            self.video_capture = None
        # 5. Halt audio safely
        if self.audio_stream:
            try: self.audio_stream.abort()
            except Exception: pass
            self.audio_stream = None

    #----------------------------------------------------------------------------------------------------
    # Callback to handle direction changes (in terms of button states and video feed)
    #----------------------------------------------------------------------------------------------------

    def set_direction(self, direction):
        if self.dcc_direction == direction:
            self.dcc_direction = None
        else:
            self.dcc_direction = direction
        self.update_direction_button_visuals()
        self.update_video_stream_source()

    def update_direction_button_visuals(self):
        default_bg = "SystemButtonFace" if os.name == "nt" else "lightgray"
        if self.dcc_direction is True: # FWD
            self.btn_fwd.configure(bg="#2a7ade", fg="white")
            self.btn_rev.configure(bg=default_bg, fg="black")
        elif self.dcc_direction is False: # REV
            self.btn_fwd.configure(bg=default_bg, fg="black")
            self.btn_rev.configure(bg="#2a7ade", fg="white")
        else:
            self.btn_fwd.configure(bg=default_bg, fg="black")
            self.btn_rev.configure(bg=default_bg, fg="black")

    # --- Asynchronous Video Connection Methods ---
    # These functions shift the high latency RTSP/HTTP network lookup out of the UI pipeline.
    
    def _async_connect_video(self, url):
        """Worker thread entry point for OpenCV connection initialization."""
        cap = cv2.VideoCapture(url)
        # Push assignment and playback scheduling back onto the main Tk thread safely
        if cap.isOpened():
            self.root_window.after(0, lambda: self._on_video_connected(cap))
        else:
            self.root_window.after(0, lambda: self.video_screen.configure(text="Error: Could not open Video Stream"))

    def _on_video_connected(self, capture_object):
        """Thread callback execution target running safely within the UI thread boundary."""
        self.video_capture = capture_object
        self.video_running = True
        self.update_video_stream()

    def update_video_stream_source(self):
        self.video_running = False
        if self.next_video_loop_event:
            self.after_cancel(self.next_video_loop_event)
            self.next_video_loop_event = None
        if self.video_capture:
            self.video_capture.release()
            self.video_capture = None
        self.video_screen.configure(image="")
        
        if self.dcc_direction is None:
            self.video_screen.configure(text="Select Direction to Start Video")
            return
            
        # Unified True/False checks to eliminate directional integer string mismatches
        target_url = self.fwd_stream_url if self.dcc_direction is True else self.rev_stream_url
        direction_name = "Forward" if self.dcc_direction is True else "Reverse"
        
        if not target_url:
            self.video_screen.configure(text=f"No video stream URL specified for {direction_name}")
            return
            
        if complex_throttle_enabled:
            self.video_screen.configure(text="Connecting to Cab View...")
            # Spin up connection via background daemon thread to bypass lockups if cameras go dark
            threading.Thread(target=self._async_connect_video, args=(target_url,), daemon=True).start()
            
    #----------------------------------------------------------------------------------------------------
    # Callback to handle Loco Emergency Stop
    #----------------------------------------------------------------------------------------------------

    def trigger_emergency_stop(self):
        self.current_speed = 0.0
        self.target_throttle = 0.0
        self.actual_power = 0.0
        self.actual_brake = 0.0  
        self.throttle_demand.set(0)
        self.brake_demand.set(100)
        self.speed_dial.update_dial(0)
        self.power_dial.update_dial(0)
        self.brake_dial.update_dial(0)
        self.dcc_speed_value = 0 
        self.dcc_direction = None
        self.update_direction_button_visuals()
        self.update_video_stream_source()
        
    #----------------------------------------------------------------------------------------------------
    # Callback to "set" a new loco - resets all the ui, releases any current loco session and
    # Requests a new loco session - with an error message if it all fails
    #----------------------------------------------------------------------------------------------------

    def update_parameters(self, loco_name:str, dcc_address:int, loco_mass_tonnes:int, loco_max_speed_mph:int, max_tractive_effort_lbf:int,
                          traction_responsiveness:float, brake_responsiveness:float, dcc_speed_scaling:float, axle_offsets_ft:list, 
                          fwd_stream_url:str, rev_stream_url:str, loco_horsepower:int=2580):
        self.video_running = False
        # Kill running thread loops
        if self.next_video_loop_event:
            self.after_cancel(self.next_video_loop_event)
            self.next_video_loop_event = None
        if self.next_physics_loop_event:
            self.root_window.after_cancel(self.next_physics_loop_event)
            self.next_physics_loop_event = None
        if self.video_capture:
            self.video_capture.release()
            self.video_capture = None
        # Reset mechanical states
        self.target_throttle = 0.0
        self.target_brake = 0.0
        self.actual_power = 0.0
        self.actual_brake = 0.0  
        self.current_speed = 0.0
        self.iterations = 0
        self.track_distance = 0.0
        self.pending_clacks.clear()
        self.active_clacks.clear()
        self.throttle_demand.set(0)
        self.brake_demand.set(100)  
        self.dcc_direction = None
        self.update_direction_button_visuals()
        self.video_screen.configure(image="", text="Select Direction to Start Video")
        # Bind incoming database attributes
        self.loco_name = loco_name
        self.dcc_address = dcc_address
        self.dcc_speed_scaling = float(dcc_speed_scaling) 
        self.loco_mass = loco_mass_tonnes
        self.loco_max_speed = loco_max_speed_mph
        self.loco_horsepower = loco_horsepower 
        self.max_tractive_effort = max_tractive_effort_lbf
        self.traction_responsiveness = traction_responsiveness
        self.brake_responsiveness = brake_responsiveness
        self.axle_offsets = axle_offsets_ft
        self.fwd_stream_url = fwd_stream_url.strip() if fwd_stream_url else ""
        self.rev_stream_url = rev_stream_url.strip() if rev_stream_url else ""
        # --- Recalibrate the physical speed dial indicator max bounds ---
        self.speed_dial.recalibrate(new_max_val=self.loco_max_speed)
        self.speed_dial.update_dial(0)
        self.power_dial.update_dial(0)
        self.brake_dial.update_dial(0)
        # Handle showing or hiding the layout video widget box entirely
        if self.fwd_stream_url != "" or self.rev_stream_url != "":
            self.video_frame.pack(side=Tk.TOP, pady=5, before=self.control_desk)
        else:
            self.video_frame.pack_forget()
        # Safely pull and update tracking mass data strings
        try:
            entry_val = self.load_mass_entry.get()
            self.load_mass = int(entry_val) if entry_val is not None else 0
        except (ValueError, TypeError):
            self.load_mass = 0
        self.total_mass = self.loco_mass + self.load_mass
        self.mass_text_label.configure(text=f"{self.loco_name} ({self.total_mass} Tonnes)")
        self.btn_estop.configure(state="normal")
        # Begin cyclic physics computation loop (10Hz updates)
        self.next_physics_loop_event = self.root_window.after(100, self.update_physics)

    #----------------------------------------------------------------------------------------------------
    # Toggles the real-time sound engine and synthesizes track/joint sound profiles if active
    #----------------------------------------------------------------------------------------------------
    
    def enable_audio(self, audio_enabled: bool):
        # 1. Gracefully teardown any existing stream
        if self.audio_stream:
            try:
                self.audio_stream.abort()
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None
        # 2. Reset sound playback tracking indices
        self.audio_sample_index = 0
        # 3. Spin up the new stream if conditions are met
        if complex_throttle_enabled and audio_enabled:
            if self.axle_offsets is None:
                self.axle_joint_indices = []
                self.clack_sample = numpy.array([])
            else:
                self.axle_joint_indices = [-1] * len(self.axle_offsets) 
                # Synthesize a localized rail joint impact wave
                duration = 0.5 
                t_sample = numpy.linspace(0, duration, int(self.sample_rate * duration))
                weight = numpy.sin(2 * numpy.pi * 40 * t_sample) * numpy.exp(-25.0 * t_sample)
                brown_noise = numpy.cumsum(numpy.random.normal(0, 0.05, len(t_sample)))
                brown_noise -= numpy.mean(brown_noise) 
                rumble = brown_noise * numpy.exp(-35.0 * t_sample)
                impact = numpy.sin(2 * numpy.pi * 150 * t_sample) * numpy.exp(-120.0 * t_sample) * 0.2
                self.clack_sample = ((weight + rumble + impact) / numpy.max(numpy.abs(weight + rumble + impact))) * 0.7
            # Fire audio stream engine thread
            self.audio_stream = sounddevice.OutputStream(channels=2, callback=self.audio_callback,
                                                         samplerate=self.sample_rate, blocksize=8192)
            self.audio_stream.start()

    #----------------------------------------------------------------------------------------------------
    # This is the video processing loop
    #----------------------------------------------------------------------------------------------------

    def update_video_stream(self):
        if not self.video_running or self.video_capture is None:
            return
        if self.video_capture.grab():
            ret, frame = self.video_capture.retrieve()
            if ret and frame is not None:
                frame = cv2.resize(frame, (480, 270))
                cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(cv2image)
                imgtk = ImageTk.PhotoImage(image=img)
                self.video_screen.imgtk = imgtk
                self.video_screen.configure(image=imgtk)
        if self.video_running:
            self.next_video_loop_event = self.root_window.after(30, self.update_video_stream)

    #----------------------------------------------------------------------------------------------------
    # This is the main control loop handling the locomotive performance
    #----------------------------------------------------------------------------------------------------

    def update_physics(self):
        # Cache Tkinter values to primitive thread-safe states for background audio thread consumption
        self.cached_brake_demand = float(self.brake_demand.get())
        
        # 1. Evaluate Direction Selector Interlocks (Must be static, zero power, full brakes to reverse)
        if self.current_speed == 0 and float(self.throttle_demand.get()) == 0 and self.cached_brake_demand == 100:
            self.btn_fwd.configure(state="normal")
            self.btn_rev.configure(state="normal")
        else:
            self.btn_fwd.configure(state="disabled")
            self.btn_rev.configure(state="disabled")
            
        # 2. Evaluate Lever Slider Interlocks (Must select direction before levers activate)
        if self.dcc_direction in [True, False]:
            self.throttle.configure(state="normal")
            self.brake.configure(state="normal")
        else:
            self.throttle.configure(state="disabled")
            self.brake.configure(state="disabled")
            
        # 3. Simulate Throttle Notch Resolution (Maps slider % into discrete 8-notch steps)
        raw_val = float(self.throttle_demand.get())
        if raw_val < 5:
            self.target_throttle = 0
        else:
            notch = round((raw_val / 100) * 8)
            self.target_throttle = (notch / 8) * 100
        # Symmetrical engine spooling delay based on prototype responsiveness
        self.actual_power += (self.target_throttle - self.actual_power) * self.traction_responsiveness
        
        # 4. Simulate Brake Air Pipe Pressurization Delay
        target_pressure = 100.0 - self.cached_brake_demand
        self.actual_brake += (target_pressure - self.actual_brake) * self.brake_responsiveness
        
        # 5. Compute Available Tractive Effort (TE)
        # Interlock: Force TE to 0 if brakes are heavily applied (Power Cut-Out)
        if self.cached_brake_demand > 10.0 or self.actual_brake < 90.0:
            available_te = 0.0
        else:
            throttle_pct = (self.target_throttle / 100.0) 
            crossover_speed = 3.5  # MPH boundary where curves shift
            if self.current_speed < crossover_speed:
                # Low Speed: Adhesion limited
                available_te = throttle_pct * self.max_tractive_effort
            else:
                # High Speed: Horsepower limited cap
                hp_limited_te = (self.loco_horsepower * 375 * throttle_pct) / max(0.01, self.current_speed)
                available_te = min(hp_limited_te, throttle_pct * self.max_tractive_effort)
                
        # 6. Compute Davis Equation Rolling Resistance Forces
        if self.current_speed < 0.01:
            total_resistance = 0.0
        else:
            # Mechanical bearing resistance (res_a) is fully present the instant we move
            res_a = self.total_mass * 2.5  
            res_b = self.current_speed * (self.total_mass * 0.05)
            res_c = (self.current_speed**2) * 0.25
            total_resistance = res_a + res_b + res_c
            
        # 7. Compute Total Braking Retardation Force
        brake_perc = (100.0 - self.actual_brake) / 100.0
        braking_force_lbf = brake_perc * 35000
        # Net mechanical tractive calculation
        net_lbf = available_te - (total_resistance + braking_force_lbf)
        if self.current_speed < 0.01 and net_lbf < 0:
            net_lbf = 0.0 
            
        # 8. Calculate Acceleration (a = F/m) & Apply Time-Step Delta (dt = 0.1s)
        # 0.01097 converts lbs & tonnes to mph/s. 1.1 includes a 10% rotational inertia factor.
        accel_mph_per_sec = (net_lbf / (self.total_mass * 1.1)) * 0.01097  
        self.current_speed += accel_mph_per_sec * 0.1  # Exactly 100ms time step slice
        
        # 9. Wheel Joint Impact (Clack) Distance Tracker
        if self.axle_offsets is not None and self.current_speed > 0.01 and len(self.axle_joint_indices) > 0:
            fps = self.current_speed * 1.46667
            self.track_distance += fps * 0.1  # Calculate precise distance covered in this 100ms cycle
            for i, offset in enumerate(self.axle_offsets):
                axle_pos = self.track_distance - offset
                current_joint = int(axle_pos // self.joint_spacing)
                # Check if a wheel-set has passed over a new rail break
                if current_joint > self.axle_joint_indices[i]:
                    vol = min(1.3, self.current_speed / 40.0) # Sound volume correlates with physical speed
                    with self.clack_lock:
                        self.pending_clacks.append([0, vol])
                    self.axle_joint_indices[i] = current_joint      
                    
        # Apply strict clamp parameters
        if self.current_speed < 0.01: self.current_speed = 0
        if self.current_speed > self.loco_max_speed: self.current_speed = self.loco_max_speed
        
        self.speed_dial.update_dial(self.current_speed)
        self.power_dial.update_dial(self.actual_power)
        self.brake_dial.update_dial(self.actual_brake)
        
        # 10 Calculate DCC base speed step (0 to 127) relative to max locomotive physics limits
        # Apply layout motor dampening factor, then round cleanly to the nearest integer step
        # We also inhibit the emergency stop (speed=1)
        base_dcc_step = (self.current_speed / max(1, self.loco_max_speed)) * 127
        final_dcc_step = round(base_dcc_step * self.dcc_speed_scaling)
        self.dcc_speed_value = max(0, min(127, final_dcc_step))
        if self.dcc_speed_value == 1: self.dcc_speed_value = 0

        # Terminal Log Reporting (Outputs roughly once per second)
        self.iterations += 1
        if self.iterations % 10 == 0:
            log_line = (
                f"{self.loco_name:<9} | "
                f"Speed: {self.current_speed:>5.2f} mph | "
                f"Thrt Dem: {self.target_throttle:>3.0f}% ({self.actual_power:>3.0f}% Act) | "
                f"TE: {available_te:>5.0f} lbs | "
                f"Brake Dem: {self.cached_brake_demand:>3.0f}% (Pipe: {self.actual_brake:>5.1f}% -> {braking_force_lbf:>5.0f} lbs) | "
                f"Res: {total_resistance:>5.0f} lbs | "
                f"Net: {net_lbf:>6.0f} lbs | "
                f"DCC Step: {self.dcc_speed_value:>3d}")
            logging.debug(log_line)
        # Loop iteration schedule
        self.next_physics_loop_event = self.root_window.after(100, self.update_physics)

    #----------------------------------------------------------------------------------------------------
    # Functions to handle the throttle audio (engine, brake hiss and clackity-clack)
    #----------------------------------------------------------------------------------------------------

    def audio_callback(self, outdata, frames, time, status):
        outdata[:] = self.generate_engine_frame(frames)

    def generate_engine_frame(self, frames):
        sr = self.sample_rate
        pwr = self.actual_power / 100.0
        t = (numpy.arange(frames) + self.audio_sample_index) / sr
        self.audio_sample_index += frames
        # Layer 1: Core square wave motor drone modifying frequency and volume dynamically with power notch
        engine_audio = 0.3 * numpy.sign(numpy.sin(2 * numpy.pi * (15 + pwr * 35) * t) - 0.4) 
        engine_audio *= (0.7 + 0.3 * numpy.sin(2 * numpy.pi * (3 + pwr * 8) * t)) * (0.12 + (pwr * 0.25))
        
        # Layer 2: Compressed air venting hiss (triggers during brake line pressure drops)
        hiss_audio = self.stereo_buffer[:frames, 0] 
        hiss_audio[:] = 0.0
        # Safe thread lookup pointing to our internal numeric variable swap instead of the Tk object
        pressure_diff = self.actual_brake - (100.0 - self.cached_brake_demand)
        if pressure_diff > 0.5:
            start_idx = numpy.random.randint(0, self.hiss_buffer_len - frames)
            hiss_audio = self.pre_baked_hiss[start_idx : start_idx + frames]
            
        # Layer 3: Dynamic wheel joint click mixing loop
        clack_audio = self.stereo_buffer[:frames, 1] 
        clack_audio[:] = 0.0
        if self.pending_clacks:
            with self.clack_lock:
                self.active_clacks.extend(self.pending_clacks)
                self.pending_clacks.clear()
        ducking_factor = 1.0
        for clack in self.active_clacks:
            idx, vol = clack[0], clack[1]
            remaining_samples = len(self.clack_sample) - idx
            play_len = min(frames, remaining_samples)
            clack_audio[:play_len] += self.clack_sample[idx : idx + play_len] * vol
            clack[0] += play_len 
            # Temporarily duck (lower) engine volume on sudden joint impacts for enhanced clarity/punch
            if idx < (sr * 0.15): 
                ducking_factor = 0.35
        self.active_clacks = [c for c in self.active_clacks if c[0] < len(self.clack_sample)]
        
        # Render clean stereo out frame signals
        self.stereo_buffer[:frames, :] = 0.0
        d_eng = engine_audio * ducking_factor
        self.stereo_buffer[:frames, 0] = d_eng + clack_audio + (hiss_audio * 0.3)  # Left audio channel
        self.stereo_buffer[:frames, 1] = (d_eng * 0.4) + clack_audio + (hiss_audio * 1.0)  # Right audio channel
        return numpy.clip(self.stereo_buffer[:frames], -1.0, 1.0)

##############################################################################################################################
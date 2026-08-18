import tkinter as Tk
import logging
import threading
import math
import numpy
import time
import multiprocessing
import queue

import cv2  # Open Source Computer Vision Library (for cab-view video streams)
import sounddevice  # Cross-platform audio stream management
from PIL import Image, ImageTk  # Handles converting OpenCV frames into Tkinter images

from .widgets import integer_entry_box
from . import mqtt_interface

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
        self.create_oval(self.center-self.radius, self.center-self.radius, self.center+self.radius,
                         self.center+self.radius, fill="#1a1a1a", outline="#444", width=3)
        # Render graduations and the center text label
        self.draw_ticks()
        self.create_text(self.center, self.center + (self.radius * 0.4), text=self.label_text,
                         fill="White", font=("Arial", int(self.size/15), "bold"))
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
            angle = 135 + ((val - self.min_val) / total_range * 270) if total_range != 0 else 135
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
                self.create_text(x_text, y_text, text=str(int(val)), fill="white", font=("Arial", int(self.size/15)))

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
# Video stream tuning constants
#--------------------------------------------------------------------------------------------------------

VIDEO_FRAME_QUEUE_SIZE = 2
VIDEO_STATUS_QUEUE_SIZE = 8
VIDEO_WIDTH = 480
VIDEO_HEIGHT = 360
VIDEO_SWITCH_DEBOUNCE_S = 0.25
# Reader-side detection
VIDEO_OPEN_TIMEOUT_MSEC = 2000
VIDEO_READ_TIMEOUT_MSEC = 1000
VIDEO_BUFFERSIZE = 1
VIDEO_READ_RETRY_SLEEP_S = 0.02
VIDEO_READ_FAILS_BEFORE_INTERRUPT = 2
# Manager-side detection
VIDEO_DROP_DETECT_S = 0.5
VIDEO_UI_POLL_MS = 30
# Reconnect policy
VIDEO_INITIAL_CONNECT_WINDOW_S = 5.0
VIDEO_RECONNECT_ATTEMPT_INTERVAL_S = 0.25
VIDEO_RECONNECT_WINDOW_S = 5.0
# Process shutdown
VIDEO_PROCESS_JOIN_TIMEOUT_S = 0.2
VIDEO_PROCESS_TERMINATE_JOIN_TIMEOUT_S = 0.3
# User-facing messages
VIDEO_MSG_SELECT_DIRECTION = "Select cab direction (FWD/REV) to start video"
VIDEO_MSG_NO_URL_TEMPLATE = "No {direction} video stream URL configured"
VIDEO_MSG_CONNECTING = "Connecting to cab view..."
VIDEO_MSG_RECONNECTING = "Attempting video reconnect..."
VIDEO_MSG_LOST = "Video feed lost"
VIDEO_MSG_OPEN_FAILED = "Unable to open video stream"
VIDEO_MSG_RENDER_ERROR = "Video render error"
VIDEO_MSG_CONNECT_FAILED = "Failed to connect to video feed"

#--------------------------------------------------------------------------------------------------------
#    Isolated subprocess that handles blocking video I/O. Communicates only via queues.
#    Invariant: Frame queue has maxsize=2 (always discard oldest when full).
#    Invariant: Status messages are sent only on state changes / terminal reader events.
#--------------------------------------------------------------------------------------------------------
   
class VideoReaderProcess(multiprocessing.Process):
    def __init__(self, url, generation, frame_queue, status_queue, stop_event, width, height, brightness, contrast):
        super().__init__(daemon=True)
        self.url = url
        self.generation = generation
        self.frame_queue = frame_queue
        self.status_queue = status_queue
        self.stop_event = stop_event
        self.width = width
        self.height = height
        self.brightness = brightness
        self.contrast = contrast

    def push_status(self, kind, message):
        # Send a status update to the UI (non-blocking).
        try:
            self.status_queue.put_nowait((kind, self.generation, message))
        except queue.Full:
            pass

    def push_frame(self, frame_rgb):
        # Push frame, silently dropping oldest if queue is full (FIFO freshness)
        try:
            self.frame_queue.put_nowait(("frame", self.generation, frame_rgb))
        except queue.Full:
            try:
                self.frame_queue.get_nowait()
                self.frame_queue.put_nowait(("frame", self.generation, frame_rgb))
            except Exception:
                pass

    def run(self):
        cap = None
        fail_count = 0
        sent_connected = False
        try:
            logging.debug(f"VideoReaderProcess - gen={self.generation} - Initialising")
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            try: cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, VIDEO_OPEN_TIMEOUT_MSEC)
            except Exception: pass
            try: cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, VIDEO_READ_TIMEOUT_MSEC)
            except Exception: pass
            try: cap.set(cv2.CAP_PROP_BUFFERSIZE, VIDEO_BUFFERSIZE)
            except Exception: pass
            if cap is None or not cap.isOpened():
                logging.warning(f"VideoReaderProcess - gen={self.generation} - FAILED to open {self.url}")
                self.push_status("open_failed", VIDEO_MSG_OPEN_FAILED)
                return
            logging.debug(f"VideoReaderProcess - gen={self.generation} - Opened {self.url}, starting video stream")  
            while not self.stop_event.is_set():
                try:
                    ret, frame = cap.read()
                    if self.stop_event.is_set():
                        break
                    if not ret or frame is None:
                        fail_count += 1
                        if fail_count >= VIDEO_READ_FAILS_BEFORE_INTERRUPT:
                            logging.warning(f"VideoReaderProcess - gen={self.generation} - Stream interrupted")
                            self.push_status("interrupted", "Video stream interrupted")
                            break
                        time.sleep(VIDEO_READ_RETRY_SLEEP_S)
                        continue
                    if not sent_connected:
                        self.push_status("connected", "connected")
                        sent_connected = True
                    fail_count = 0
                    
                    frame = cv2.resize(frame, (self.width, self.height))
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frame_float = frame.astype(numpy.float32)
                    numpy.multiply(frame_float, 1.0 / 255.0, out=frame_float)
                    numpy.subtract(frame_float, 0.5, out=frame_float)
                    numpy.multiply(frame_float, self.contrast, out=frame_float)
                    numpy.add(frame_float, 0.5, out=frame_float)
                    numpy.add(frame_float, self.brightness / 100.0, out=frame_float)
                    numpy.clip(frame_float, 0.0, 1.0, out=frame_float)
                    frame = (frame_float * 255.0).astype(numpy.uint8)
                    self.push_frame(frame)
                except Exception as e:
                    if self.stop_event.is_set():
                        break
                    logging.warning(f"VideoReaderProcess - gen={self.generation} - Exception: {e}")
                    self.push_status("error", f"Video stream error: {e}")
                    break
        finally:
            if cap is not None:
                try: cap.release()
                except Exception: pass
            logging.debug(f"VideoReaderProcess - gen={self.generation} - Exiting")

#--------------------------------------------------------------------------------------------------------
# Simplified Video Management: Single Source of Truth
#    Encapsulates all video lifecycle logic. Separates concerns:
#    - State tracking (running, generation, direction, URLs)
#    - Process lifecycle (start, stop, monitoring, reconnect)
#    - UI updates (queues, painting, messages)
#    Invariants:
#    - Only one generation's reader process exists at a time
#    - process is None ⟺ no reader currently active
#    - Reconnect attempts continue only within VIDEO_RECONNECT_WINDOW_S
#    - After reconnect window expires, stream enters sticky lost state until user toggles feed
#--------------------------------------------------------------------------------------------------------

class VideoStreamManager:
    
    def __init__(self, root_window, show_message_callback):
        self.root_window = root_window
        self.show_message_callback = show_message_callback
        # State tracking (protected by state_lock)
        self.state_lock = threading.Lock()
        self.video_running = False
        self.video_direction = None
        self.video_connect_generation = 0
        self.fwd_stream_url = ""
        self.rev_stream_url = ""
        # Process and queue references (protected by state_lock)
        self.video_reader_process = None
        self.video_reader_stop_event = None
        self.video_frame_queue = None
        self.video_status_queue = None
        # Timing (protected by state_lock)
        self.video_last_frame_ts = 0.0
        self.video_reconnect_start_ts = 0.0
        self.video_last_reconnect_attempt_ts = 0.0
        # Switch debouncing (separate lock to avoid contention)
        self.switch_lock = threading.Lock()
        self.last_video_switch_ts = 0.0
        # Current state / status (protected by state_lock)
        self.video_has_ever_connected = False
        self.video_status = None
        self.video_reconnecting = False
        self.video_terminal_failure = False
        self.video_target_url = None
        # Stream adjustments
        self.stream_brightness = 0
        self.stream_contrast = 1.0

    def set_direction(self, direction: bool):
        # Toggle video direction; None means no direction selected.
        with self.state_lock:
            if self.video_direction == direction:
                self.video_direction = None
            else:
                self.video_direction = direction
        self.update_stream_source()

    def set_stream_urls(self, fwd_url: str, rev_url: str):
        # Update the forward and reverse stream URLs
        with self.state_lock:
            self.fwd_stream_url = (fwd_url or "").strip()
            self.rev_stream_url = (rev_url or "").strip()

    def set_stream_adjustments(self, brightness: int, contrast: float):
        # Update brightness/contrast; only affects new readers.
        with self.state_lock:
            self.stream_brightness = int(brightness)
            self.stream_contrast = float(contrast)

    def update_stream_source(self):
        # Called when direction changes or URLs update. Debounced at 250ms to avoid thrashing.
        # Orchestrates: cleanup old reader → check direction/URLs → start new reader.
        with self.switch_lock:
            now = time.monotonic()
            if now - self.last_video_switch_ts < VIDEO_SWITCH_DEBOUNCE_S:
                return
            self.last_video_switch_ts = now
        # Snapshot intent (direction + URL) under lock
        with self.state_lock:
            direction = self.video_direction
            target_url = None
            if direction is True:
                target_url = self.fwd_stream_url
            elif direction is False:
                target_url = self.rev_stream_url
            direction_name = "Forward" if direction is True else "Reverse" if direction is False else None
        # Stop any existing reader synchronously
        self._stop_reader_sync()
        # Clear transient state when switching source
        with self.state_lock:
            self.video_status = None
            self.video_reconnecting = False
            self.video_terminal_failure = False
            self.video_reconnect_start_ts = 0.0
            self.video_last_reconnect_attempt_ts = 0.0
            self.video_target_url = target_url
            self.video_has_ever_connected = False
        # Handle each case
        if direction is None:
            self.root_window.after(0, lambda: self.show_message_callback(
                VIDEO_MSG_SELECT_DIRECTION))
            return
        if not target_url:
            self.root_window.after(0, lambda dn=direction_name: self.show_message_callback(
                VIDEO_MSG_NO_URL_TEMPLATE.format(direction=dn.lower()), color="orange"))
            return
        # Valid direction + URL; start new reader
        self.root_window.after(0, lambda: self.show_message_callback(VIDEO_MSG_CONNECTING, color="orange"))
        self._start_reader(target_url)

    def _stop_reader_sync(self):
        # Synchronously stop the current reader process and drain queues.
        p = None
        ev = None
        with self.state_lock:
            p = self.video_reader_process
            ev = self.video_reader_stop_event
            self.video_reader_process = None
            self.video_reader_stop_event = None
        if p is None:
            return
        # Signal stop
        try:
            if ev is not None:
                ev.set()
        except Exception:
            pass
        # Join with timeout
        try:
            p.join(timeout=VIDEO_PROCESS_JOIN_TIMEOUT_S)
        except Exception:
            pass
        # Force-terminate if still alive
        if p.is_alive():
            try:
                p.terminate()
            except Exception:
                pass
            try:
                p.join(timeout=VIDEO_PROCESS_TERMINATE_JOIN_TIMEOUT_S)
            except Exception:
                pass
        # Drain queues off Tk thread to avoid blocking
        threading.Thread(target=self._drain_queues, daemon=True).start()

    def _drain_queues(self):
        # Non-blocking queue drain (safe to call from background thread)
        with self.state_lock:
            fq = self.video_frame_queue
            sq = self.video_status_queue
        try:
            if fq is not None:
                while True:
                    fq.get_nowait()
        except (queue.Empty, Exception):
            pass
        try:
            if sq is not None:
                while True:
                    sq.get_nowait()
        except (queue.Empty, Exception):
            pass

    def _start_reader(self, url: str, reset_connection_history=True):
        # Create and start a new reader process.
        # Increments generation and sets running=True before returning.
        with self.state_lock:
            self.video_connect_generation += 1
            gen = self.video_connect_generation
            self.video_running = True
            self.video_status = None
            self.video_target_url = url
            self.video_last_frame_ts = time.monotonic()
            self.video_frame_queue = multiprocessing.Queue(maxsize=VIDEO_FRAME_QUEUE_SIZE)
            self.video_status_queue = multiprocessing.Queue(maxsize=VIDEO_STATUS_QUEUE_SIZE)
            self.video_reader_stop_event = multiprocessing.Event()
            if reset_connection_history: self.video_has_ever_connected = False
            brightness = self.stream_brightness
            contrast = self.stream_contrast
        reader = VideoReaderProcess(
            url=url,
            generation=gen,
            frame_queue=self.video_frame_queue,
            status_queue=self.video_status_queue,
            stop_event=self.video_reader_stop_event,
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
            brightness=brightness,
            contrast=contrast)
        reader.start()
        with self.state_lock:
            self.video_reader_process = reader

    def _begin_reconnect_locked(self, now, reason=None):
        # Caller must hold state_lock.
        if self.video_terminal_failure:
            return
        if not self.video_reconnecting:
            self.video_reconnect_start_ts = now
        self.video_reconnecting = True
        self.video_last_reconnect_attempt_ts = 0.0
        self.video_status = reason or VIDEO_MSG_RECONNECTING

    def _begin_reconnect(self, reason=None):
        now = time.monotonic()
        self._stop_reader_sync()
        with self.state_lock:
            if not self.video_running:
                return
            self._begin_reconnect_locked(now, reason=reason)
        self.root_window.after(0, lambda: self.show_message_callback(VIDEO_MSG_RECONNECTING, color="orange"))

    def _enter_terminal_lost_state(self, message=None):
        self._stop_reader_sync()
        with self.state_lock:
            self.video_running = False
            self.video_reconnecting = False
            self.video_terminal_failure = True
            self.video_status = message or VIDEO_MSG_LOST
        self.root_window.after(0, lambda msg=self.video_status: self.show_message_callback(msg, color="red"))

    def _maybe_attempt_reconnect(self, now):
        with self.state_lock:
            if not self.video_running or not self.video_reconnecting or self.video_terminal_failure:
                return False
            target_url = self.video_target_url
            reconnect_started = self.video_reconnect_start_ts
            last_attempt = self.video_last_reconnect_attempt_ts
            if not target_url:
                self.video_running = False
                self.video_reconnecting = False
                self.video_terminal_failure = True
                self.video_status = VIDEO_MSG_LOST
                self.root_window.after(0, lambda: self.show_message_callback(VIDEO_MSG_LOST, color="red"))
                return True
            reconnect_expired = (now - reconnect_started) >= VIDEO_RECONNECT_WINDOW_S
            should_start = (last_attempt == 0.0 or
                            (now - last_attempt) >= VIDEO_RECONNECT_ATTEMPT_INTERVAL_S)
            if not reconnect_expired and should_start:
                self.video_last_reconnect_attempt_ts = now
        if reconnect_expired:
            self._enter_terminal_lost_state(VIDEO_MSG_LOST)
            return True
        if should_start:
            self._stop_reader_sync()
            self.root_window.after(0, lambda: self.show_message_callback(VIDEO_MSG_RECONNECTING, color="orange"))
            self._start_reader(target_url, reset_connection_history=False)
            return True
        return False

    def ui_update_loop(self):
        # Non-blocking UI paint loop. Called from complex_throttle.update_video_stream() method.
        # Returns immediately but re-schedules itself via the root_window.after() method
        #    1. Check if stream is still running; exit early if not
        #    2. If reconnecting, attempt reconnect when interval expires
        #    3. Drain status queue (exactly once; keep last status)
        #    4. Drain frame queue (keep newest frame only)
        #    5. Paint frame if available
        #    6. Monitor for stall and trigger reconnect if needed
        with self.state_lock:
            running = self.video_running
            generation = self.video_connect_generation
            sq = self.video_status_queue
            fq = self.video_frame_queue
            last_frame_ts = self.video_last_frame_ts
            status = self.video_status
            reconnecting = self.video_reconnecting
            terminal_failure = self.video_terminal_failure
        # If not running, show final status and exit
        if not running:
            if status:
                self.show_message_callback(status, color="red")
            return
        now = time.monotonic()
        # If reconnecting, attempt reconnect on schedule
        if reconnecting and not terminal_failure:
            self._maybe_attempt_reconnect(now)
            with self.state_lock:
                if not self.video_running:
                    return
                generation = self.video_connect_generation
                sq = self.video_status_queue
                fq = self.video_frame_queue
                last_frame_ts = self.video_last_frame_ts
        latest_status_kind = None
        latest_status_message = None
        # 1) Drain status queue—keep only the last status message
        if sq is not None:
            try:
                while True:
                    kind, msg_gen, message = sq.get_nowait()
                    if msg_gen == generation:
                        latest_status_kind = kind
                        latest_status_message = message
            except queue.Empty:
                pass
            except Exception:
                pass
        # Apply latest status
        if latest_status_kind == "connected":
            with self.state_lock:
                self.video_reconnecting = False
                self.video_terminal_failure = False
                self.video_status = None
                self.video_last_frame_ts = now
                self.video_has_ever_connected = True
        elif latest_status_kind in ("interrupted", "error", "open_failed"):
            with self.state_lock:
                still_running = self.video_running
                has_ever_connected = self.video_has_ever_connected
            if still_running:
                if has_ever_connected:
                    self._begin_reconnect(reason=latest_status_message)
                else:
                    self._enter_terminal_lost_state(VIDEO_MSG_CONNECT_FAILED)
            return
        # 2) Drain frame queue—keep only the newest frame
        newest_frame = None
        if fq is not None:
            try:
                while True:
                    kind, frm_gen, payload = fq.get_nowait()
                    if kind == "frame" and frm_gen == generation:
                        newest_frame = payload
            except queue.Empty:
                pass
            except Exception:
                pass
        # 3) Paint if we have a frame
        if newest_frame is not None:
            with self.state_lock:
                self.video_last_frame_ts = now
                self.video_reconnecting = False
                self.video_terminal_failure = False
                self.video_status = None
                self.video_has_ever_connected = True
            try:
                img = Image.fromarray(newest_frame)
                img_tk = ImageTk.PhotoImage(image=img)
                # Delegate painting to caller (complex_throttle)—just return the PhotoImage
                # Caller's update_video_stream() will handle the Canvas operations
                return img_tk
            except Exception as e:
                logging.debug(f"VideoStreamManager - gen={generation} - Failed to render video frame: {e}")
                self._enter_terminal_lost_state(VIDEO_MSG_RENDER_ERROR)
                return
        # 4) Stall watchdog: if no frame for >VIDEO_DROP_DETECT_S, begin reconnect
        with self.state_lock:
            reconnecting = self.video_reconnecting
            terminal_failure = self.video_terminal_failure
            last_frame_ts = self.video_last_frame_ts
        if not reconnecting and not terminal_failure:
            if now - last_frame_ts > VIDEO_DROP_DETECT_S:
                with self.state_lock:
                    has_ever_connected = self.video_has_ever_connected
                logging.debug(f"VideoStreamManager - gen={generation} - No frame for {now - last_frame_ts:.3f}s")
                if has_ever_connected:
                    logging.debug(f"VideoStreamManager - gen={generation} - Beginning reconnect")
                    self._begin_reconnect(reason="Frame timeout")
                else:
                    if now - last_frame_ts >= VIDEO_INITIAL_CONNECT_WINDOW_S:
                        logging.warning(f"VideoStreamManager - gen={generation} - Initial connect timed out")
                        self._enter_terminal_lost_state(VIDEO_MSG_CONNECT_FAILED)
                return
        # 5) No frame this cycle
        return None

    def cleanup(self):
        # Called on application shutdown. Safely stops all readers and clears state.
        with self.state_lock:
            self.video_running = False
            self.video_reconnecting = False
            self.video_terminal_failure = False
            self.video_connect_generation += 1
            self.video_status = None
        self._stop_reader_sync()

#--------------------------------------------------------------------------------------------------------
# Complex_throttle Class
#--------------------------------------------------------------------------------------------------------

class complex_throttle(Tk.LabelFrame):
    
    def __init__(self, root_window, parent_frame):
        super().__init__(parent_frame)
        self.pack(fill=Tk.BOTH, expand=False)
        self.root_window = root_window
        # ===== VIDEO FRAME SETUP =====
        self.video_frame = Tk.Frame(self, bg="black", width=VIDEO_WIDTH, height=VIDEO_HEIGHT)
        self.video_frame.pack(side=Tk.TOP, pady=5)
        self.video_frame.pack_propagate(False)
        self.video_screen = Tk.Canvas(self.video_frame, bg="black", width=VIDEO_WIDTH, height=VIDEO_HEIGHT-30, highlightthickness=0)
        self.video_screen.pack(side=Tk.TOP, fill=Tk.X)
        self.video_canvas_image_id = self.video_screen.create_image(0, 0, anchor=Tk.NW, image=None)
        self.video_button_frame = Tk.Frame(self.video_frame, bg="black", height=30)
        self.video_button_frame.pack(side=Tk.TOP, fill=Tk.X)
        self.video_button_frame.pack_propagate(False)
        self.video_btn_rev = Tk.Button(self.video_button_frame, text="REV", font=('Arial', 8, 'bold'),
                    fg="white", bg="#444444", width=8, height=1, command=lambda: self._on_video_direction(False))
        self.video_btn_rev.pack(side=Tk.LEFT, padx=5, pady=2)
        
        self.video_btn_fwd = Tk.Button(self.video_button_frame, text="FWD", font=('Arial', 8, 'bold'),
                    fg="white", bg="#444444", width=8, height=1, command=lambda: self._on_video_direction(True))
        self.video_btn_fwd.pack(side=Tk.RIGHT, padx=5, pady=2)
        # ===== CONTROL DESK (unchanged) =====
        self.control_desk = Tk.Frame(self)
        self.control_desk.pack(side=Tk.TOP, fill=Tk.X, padx=10, pady=5)
        # Left Column: Locomotive Power Throttle Slider (8-Notch Detents)
        left_lever_frame = Tk.Frame(self.control_desk, width=80, height=340)
        left_lever_frame.pack(side=Tk.LEFT, padx=10, fill=Tk.Y)
        left_lever_frame.pack_propagate(False) 
        Tk.Label(left_lever_frame, text="THROTTLE", font=('Arial', 10, 'bold')).pack(side=Tk.TOP)
        self.throttle_demand = Tk.DoubleVar(value=0)
        self.throttle = Tk.Scale(left_lever_frame, from_=100, to=0, orient="vertical", width=50, length=320,
                state="disabled", sliderlength=40, variable=self.throttle_demand, resolution=12.5, tickinterval=12.5, showvalue=0)
        self.throttle.pack(side=Tk.TOP, fill=Tk.Y)
        # Center Column: Rolling Stock Mass Config & Dashboard Dials
        center_dashboard = Tk.Frame(self.control_desk)
        center_dashboard.pack(side=Tk.LEFT, padx=5, fill=Tk.BOTH)
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
        self.brake = Tk.Scale(right_lever_frame, from_=100, to=0, orient="vertical", width=50, length=320,
                state="disabled", sliderlength=40, variable=self.brake_demand, resolution=5, tickinterval=20, showvalue=0)
        self.brake.pack(side=Tk.TOP, fill=Tk.Y)
        # Bottom Sub-Component: Reverser and Emergency Protection Console
        button_console = Tk.Frame(self)
        button_console.pack(side=Tk.TOP, fill=Tk.X, padx=5, pady=(5, 5), ipady=5)
        self.btn_rev = Tk.Button(button_console, text="REV", font=('Arial', 10, 'bold'), width=6, height=2,
                                 state="disabled", command=lambda: self.set_direction(False))
        self.btn_rev.pack(side=Tk.LEFT, expand=True, padx=5, pady=5)
        self.btn_estop = Tk.Button(button_console, text="EMERGENCY\nSTOP", font=('Arial', 10, 'bold'), bg="#900", fg="white",
                activebackground="#f00", activeforeground="white", width=14, height=2, state="disabled", command=self.trigger_emergency_stop)
        self.btn_estop.pack(side=Tk.LEFT, expand=True, padx=5, pady=5)
        self.btn_fwd = Tk.Button(button_console, text="FWD", font=('Arial', 10, 'bold'), width=6, height=2,
                                 state="disabled", command=lambda: self.set_direction(True))
        self.btn_fwd.pack(side=Tk.LEFT, expand=True, padx=5, pady=5)
        # ===== VIDEO MANAGER INSTANCE =====
        self.video_mgr = VideoStreamManager(root_window, self._show_video_message)
        self.next_video_loop_event = None
        self.current_video_image = None  # Hold PhotoImage to prevent GC
        # ===== LOCOMOTIVE STATE =====
        self.loco_name = ""
        self.loco_mass = 0
        self.loco_max_speed = 100
        self.loco_horsepower = 100
        self.max_tractive_effort = 0
        self.traction_responsiveness = 0.0
        self.brake_responsiveness = 0.0
        self.axle_offsets = None
        self.axle_joint_indices = []
        self.load_mass = 0
        self.total_mass = 0
        self.dcc_direction = None
        self.dcc_speed_value = 0
        self.session_id = 0
        self.dcc_speed_scaling = 1.0
        self.cached_brake_demand = 100.0
        # ===== AUDIO STATE =====
        self.audio_stream = None
        self.sample_rate = 22050
        self.stereo_buffer = numpy.zeros((8192, 2))
        self.hiss_buffer_len = self.sample_rate * 2
        self.pre_baked_hiss = numpy.random.normal(0, 0.12, self.hiss_buffer_len) * 0.2
        self.audio_sample_index = 0
        self.hiss_playback_index = 0
        self.joint_spacing = 120.0
        self.clack_lock = threading.Lock()
        self.pending_clacks = []
        self.active_clacks = []
        self.clack_sample = numpy.array([])
        # ===== PHYSICS STATE =====
        self.next_physics_loop_event = None
        self.brake_demand_lock = threading.Lock()
        self.power_state_lock = threading.Lock()
        # Initialize
        self.reset_to_defaults()
        self.set_controls_disabled_state(disabled=False)

    #----------------------------------------------------------------------------------------------------
    # VIDEO INTEGRATION METHODS
    #----------------------------------------------------------------------------------------------------

    def _on_video_direction(self, direction: bool):
        # FWD/REV button pressed; update direction and trigger stream source change.
        self.video_mgr.set_direction(direction)
        self._update_video_button_visuals()

    def _update_video_button_visuals(self):
        # Update video button states based on current direction.
        direction = self.video_mgr.video_direction
        if direction is True:  # FWD
            self.video_btn_fwd.configure(bg="#2a7ade", relief=Tk.SUNKEN)
            self.video_btn_rev.configure(bg="#444444", relief=Tk.RAISED)
        elif direction is False:  # REV
            self.video_btn_rev.configure(bg="#2a7ade", relief=Tk.SUNKEN)
            self.video_btn_fwd.configure(bg="#444444", relief=Tk.RAISED)
        else:
            self.video_btn_fwd.configure(bg="#444444", relief=Tk.RAISED)
            self.video_btn_rev.configure(bg="#444444", relief=Tk.RAISED)

    def _show_video_message(self, text: str, color: str = "white"):
        # Show a message overlay in the video frame (non-blocking).
        self.video_screen.itemconfig(self.video_canvas_image_id, image="")
        self.video_screen.delete("video_msg")
        self.video_screen.create_text(VIDEO_WIDTH/2, (VIDEO_HEIGHT-30)/2, text=text, fill=color, font=("Arial", 12), tags="video_msg")

    def update_video_stream(self):
        # UI paint loop for video (called every 30ms).
        # Non-blocking: drains queues, paints frame if available, reschedules itself.
        img_tk = self.video_mgr.ui_update_loop()
        # Paint the frame if one was returned
        if img_tk is not None:
            self.video_screen.delete("video_msg")
            self.video_screen.itemconfig(self.video_canvas_image_id, image=img_tk)
            self.current_video_image = img_tk  # Hold reference to prevent garbage collection
        # Reschedule for 30ms later
        self.next_video_loop_event = self.root_window.after(30, self.update_video_stream)

    #----------------------------------------------------------------------------------------------------
    # LOCOMOTIVE PARAMETER UPDATE API METHOD - Called when a new locomotive is selected.
    # Stops current video, resets state, and configures new loco parameters.
    #----------------------------------------------------------------------------------------------------

    def update_parameters(self, loco_name:str, dcc_address:int, loco_mass_tonnes:int, loco_max_speed_mph:int, max_tractive_effort_lbf:int, 
                        traction_responsiveness:float, brake_responsiveness:float, dcc_speed_scaling:float, axle_offsets_ft:list,
                        fwd_stream_url:str, rev_stream_url:str, loco_horsepower:int, stream_brightness:int, stream_contrast:float):
        # Stop video cleanly
        self.video_mgr.cleanup()
        # Cancel physics loop
        if self.next_physics_loop_event:
            try: self.root_window.after_cancel(self.next_physics_loop_event)
            except Exception: pass
            self.next_physics_loop_event = None
        # Reset UI to defaults
        self.reset_to_defaults()
        self.set_controls_disabled_state(disabled=False)
        # Bind loco parameters
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
        # Update video stream URLs and adjustments
        self.video_mgr.set_stream_urls(fwd_stream_url, rev_stream_url)
        self.video_mgr.set_stream_adjustments(stream_brightness, stream_contrast)
        self.next_video_loop_event = self.root_window.after(30, self.update_video_stream)
        # Load mass from entry
        try:
            entry_val = self.load_mass_entry.get()
            self.load_mass = int(entry_val) if entry_val is not None else 0
        except (ValueError, TypeError):
            self.load_mass = 0
        self.total_mass = self.loco_mass + self.load_mass
        self.mass_text_label.configure(text=f"{self.loco_name} ({self.total_mass} Tonnes)")
        # Recalibrate speed dial
        self.speed_dial.recalibrate(new_max_val=self.loco_max_speed)
        # Start physics loop
        self.next_physics_loop_event = self.root_window.after(100, self.update_physics)

    def on_close(self):
        # Graceful shutdown: stop all loops and clean resources.
        # Flag loops to stop
        if self.next_physics_loop_event:
            try: self.root_window.after_cancel(self.next_physics_loop_event)
            except Exception: pass
        if self.next_video_loop_event:
            try: self.root_window.after_cancel(self.next_video_loop_event)
            except Exception: pass
        # Clean video manager
        self.video_mgr.cleanup()
        # Clean audio
        if self.audio_stream:
            try:
                self.audio_stream.abort()
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None

    #----------------------------------------------------------------------------------------------------
    # OTHER METHODS
    #----------------------------------------------------------------------------------------------------

    def reset_to_defaults(self):
        # Reset all dials and state to defaults.
        self.target_throttle = 0.0
        self.target_brake = 0.0
        self.actual_power = 0.0
        self.actual_brake = 0.0
        self.current_speed = 0.0
        self.iterations = 0
        self.track_distance = 0.0
        if hasattr(self, 'pending_clacks'): self.pending_clacks.clear()
        if hasattr(self, 'active_clacks'): self.active_clacks.clear()
        self.throttle_demand.set(0)
        self.brake_demand.set(100)
        self.dcc_direction = None
        self._update_direction_button_visuals()
        self._show_video_message("Select cab direction (FWD/REV) to start video")
        self.speed_dial.update_dial(0)
        self.power_dial.update_dial(0)
        self.brake_dial.update_dial(0)

    def _update_direction_button_visuals(self):
        # Update main direction button states.
        if self.dcc_direction is True:
            self.btn_fwd.configure(bg="#2a7ade", fg="white")
            self.btn_rev.configure(bg="lightgray", fg="black")
        elif self.dcc_direction is False:
            self.btn_fwd.configure(bg="lightgray", fg="black")
            self.btn_rev.configure(bg="#2a7ade", fg="white")
        else:
            self.btn_fwd.configure(bg="lightgray", fg="black")
            self.btn_rev.configure(bg="lightgray", fg="black")

    def set_direction(self, direction):
        # Main locomotive direction control.
        if self.dcc_direction == direction:
            self.dcc_direction = None
        else:
            self.dcc_direction = direction
            mqtt_message = {"sessionid": self.session_id, "speed": self.dcc_speed_value, "direction": self.dcc_direction}
            mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=False,
                                log_message=f"Loco Control: Publishing loco control message to broker :{mqtt_message}")
        self._update_direction_button_visuals()

    def set_controls_disabled_state(self, disabled: bool):
        # Enable/disable all control widgets.
        state_val = "disabled" if disabled else "normal"
        self.throttle.configure(state=state_val)
        self.brake.configure(state=state_val)
        self.btn_fwd.configure(state=state_val)
        self.btn_rev.configure(state=state_val)
        self.btn_estop.configure(state=state_val)

    def mass_updated(self):
        # Callback: load mass changed.
        try:
            raw_val = self.load_mass_entry.get()
            self.load_mass = int(raw_val) if raw_val is not None else 0
        except (ValueError, TypeError):
            self.load_mass = 0
        self.total_mass = self.loco_mass + self.load_mass
        if self.loco_name:
            self.mass_text_label.configure(text=f"{self.loco_name} ({self.total_mass} Tonnes)")

    def trigger_emergency_stop(self):
        # Emergency stop button.
        mqtt_message = {"sessionid": self.session_id, "speed": 1, "direction": self.dcc_direction}
        mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=False,
                            log_message=f"Loco Control: Publishing loco control message to broker :{mqtt_message}")
        self.reset_to_defaults()

    #----------------------------------------------------------------------------------------------------
    # API FUNCTION to enable/disable audio
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
        self.hiss_playback_index = 0
        # 3. Spin up the new stream if conditions are met
        if audio_enabled:
            if self.axle_offsets is None or self.axle_offsets == []:
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
                mix = weight + rumble + impact
                denom = numpy.max(numpy.abs(mix))
                self.clack_sample = ((mix / denom) * 0.7) if denom > 0 else numpy.array([])
            # Fire audio stream engine thread
            try:
                self.audio_stream = sounddevice.OutputStream(channels=2, callback=self.audio_callback, samplerate=self.sample_rate, blocksize=8192)
                self.audio_stream.start()
            except Exception as e:
                logging.warning(f"Failed to start audio stream: {e}")
                self.audio_stream = None

    #----------------------------------------------------------------------------------------------------
    # API FUNCTION to "activate" a new session (or release an existing session if session_id=0)
    #----------------------------------------------------------------------------------------------------

    def activate_loco_session(self, session_id: int):
        self.session_id = session_id
        if self.session_id == 0:
            # If session_id = 0 - all dials/controls set to defaults and all controls disabled
            self.reset_to_defaults()
            self.set_controls_disabled_state(disabled=True)
        else:
            # If Session ID > 0 - Controls enabled (only FWD, REV buttons visible/active first)
            # We explicitly disable the levers here; update_physics will naturally manage the rest.
            self.set_controls_disabled_state(disabled=True)  # Clean base baseline
            self.btn_fwd.configure(state="normal")
            self.btn_rev.configure(state="normal")
            self.btn_estop.configure(state="normal")

    #----------------------------------------------------------------------------------------------------
    # This is the main control loop handling the locomotive performance
    #----------------------------------------------------------------------------------------------------

    def update_physics(self):
        # Interlock guard: If there's no active session, prevent physics from altering control states
        if self.session_id == 0:
            self.set_controls_disabled_state(disabled=True)
            self.next_physics_loop_event = self.root_window.after(100, self.update_physics)
            return
        # Safety guard: avoid divide-by-zero / invalid mass conditions.
        if self.total_mass <= 0:
            self.speed_dial.update_dial(0)
            self.power_dial.update_dial(0)
            self.brake_dial.update_dial(0)
            self.next_physics_loop_event = self.root_window.after(100, self.update_physics)
            return
        # Cache Tkinter values to primitive thread-safe states for background audio thread consumption
        with self.brake_demand_lock:
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
        with self.power_state_lock:
            # 4. Simulate engine spooling
            self.actual_power += (self.target_throttle - self.actual_power) * self.traction_responsiveness
            # 5. Simulate Brake Air Pipe Pressurisation
            target_pressure = 100.0 - self.cached_brake_demand
            self.actual_brake += (target_pressure - self.actual_brake) * self.brake_responsiveness
        # 6. Compute Available Tractive Effort (TE)
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
        # 7. Compute Davis Equation Rolling Resistance Forces
        if self.current_speed < 0.01:
            total_resistance = 0.0
        else:
            # Mechanical bearing resistance (res_a) is fully present the instant we move
            res_a = self.total_mass * 2.5
            res_b = self.current_speed * (self.total_mass * 0.05)
            res_c = (self.current_speed**2) * 0.25
            total_resistance = res_a + res_b + res_c
        # 8. Compute Total Braking Retardation Force
        brake_perc = (100.0 - self.actual_brake) / 100.0
        braking_force_lbf = brake_perc * 35000
        # Net mechanical tractive calculation
        net_lbf = available_te - (total_resistance + braking_force_lbf)
        if self.current_speed < 0.01 and net_lbf < 0:
            net_lbf = 0.0
        # 9. Calculate Acceleration (a = F/m) & Apply Time-Step Delta (dt = 0.1s)
        # 0.01097 converts lbs & tonnes to mph/s. 1.1 includes a 10% rotational inertia factor.
        accel_mph_per_sec = (net_lbf / (self.total_mass * 1.1)) * 0.01097
        self.current_speed += accel_mph_per_sec * 0.1  # Exactly 100ms time step slice
        # 10. Wheel Joint Impact (Clack) Distance Tracker
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
        # Update dials
        self.speed_dial.update_dial(self.current_speed)
        self.power_dial.update_dial(self.actual_power)
        self.brake_dial.update_dial(self.actual_brake)
        # 11. Calculate DCC base speed step (0 to 127) relative to max locomotive physics limits
        # Apply layout motor dampening factor, then round cleanly to the nearest integer step
        # We also inhibit the emergency stop (speed=1)
        base_dcc_step = (self.current_speed / max(1, self.loco_max_speed)) * 127
        final_dcc_step = round(base_dcc_step * self.dcc_speed_scaling)
        # Update the DCC Speed value
        old_dcc_speed_value = self.dcc_speed_value
        self.dcc_speed_value = max(0, min(127, final_dcc_step))
        # Inhibit the emergency stop (dcc_speed = 1)
        if self.dcc_speed_value == 1: self.dcc_speed_value = 0
        # Output the speed and direction (if changed) to the MQTT Broker
        if self.dcc_speed_value != old_dcc_speed_value:
            # Speed/Direction messages include the Session ID, Speed value and Direction Flag
            mqtt_message = {"sessionid": self.session_id, "speed": self.dcc_speed_value, "direction": self.dcc_direction}
            mqtt_interface.send_mqtt_message("dcc_locomotive_control_commands", 0, data=mqtt_message, retain=False,
                            log_message=f"Loco Control: Publishing loco control message to broker :{mqtt_message}")
        # Terminal Log Reporting (Outputs roughly once per second)
        self.iterations += 1
        if self.iterations % 10 == 0:
            log_line = (f"{self.loco_name:<9} | " f"Speed: {self.current_speed:>5.2f} mph | " f"Thrt Dem: {self.target_throttle:>3.0f}% ({self.actual_power:>3.0f}% Act) | " f"TE: {available_te:>5.0f} lbs | " f"Brake Dem: {self.cached_brake_demand:>3.0f}% (Pipe: {self.actual_brake:>5.1f}% -> {braking_force_lbf:>5.0f} lbs) | " f"Res: {total_resistance:>5.0f} lbs | " f"Net: {net_lbf:>6.0f} lbs | " f"DCC Step: {self.dcc_speed_value:>3d}")
            logging.info(log_line)
        # Loop iteration schedule
        self.next_physics_loop_event = self.root_window.after(100, self.update_physics)

    #----------------------------------------------------------------------------------------------------
    # Functions to handle the throttle audio (engine, brake hiss and clackity-clack)
    #----------------------------------------------------------------------------------------------------

    def audio_callback(self, outdata, frames, time, status):
        outdata[:] = self.generate_engine_frame(frames)

    def generate_engine_frame(self, frames):
        sr = self.sample_rate
        # Read power state safely from audio thread
        with self.power_state_lock:
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
        with self.brake_demand_lock:
            current_brake_demand = self.cached_brake_demand
        with self.power_state_lock:
            pressure_diff = self.actual_brake - (100.0 - current_brake_demand)
        if pressure_diff > 0.5:
            # Use modulo-based cycling instead of expensive RNG
            self.hiss_playback_index = (self.hiss_playback_index + frames * 7) % (self.hiss_buffer_len - frames - 1)
            hiss_audio = self.pre_baked_hiss[self.hiss_playback_index : self.hiss_playback_index + frames]
        # Layer 3: Dynamic wheel joint click mixing loop
        clack_audio = self.stereo_buffer[:frames, 1]
        clack_audio[:] = 0.0
        # Drain pending clacks atomically (check + move under same lock)
        with self.clack_lock:
            if self.pending_clacks:
                self.active_clacks.extend(self.pending_clacks)
                self.pending_clacks.clear()
        ducking_factor = 1.0        
        for clack in self.active_clacks:
            idx, vol = clack[0], clack[1]
            remaining_samples = len(self.clack_sample) - idx
            play_len = min(frames, remaining_samples)
            if play_len > 0:
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
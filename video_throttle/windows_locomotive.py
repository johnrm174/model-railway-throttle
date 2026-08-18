import tkinter as Tk
import threading
import logging
import time
import socket
import cv2
import queue
import io
import multiprocessing as mp
from PIL import Image, ImageTk
from zeroconf import Zeroconf, ServiceBrowser
from tkinter import ttk

from .widgets import integer_entry_box, float_entry_box, string_entry_box, axle_entry_box
from .widgets import ConfigControlBar

#----------------------------------------------------------------------------------------------------
# Spawn-safe preview worker
#----------------------------------------------------------------------------------------------------

def preview_worker_process(url, frame_queue, control_queue, brightness, contrast):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 1200)
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 400)
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if cap is None or not cap.isOpened():
            frame_queue.put(("status", "Unable to open stream", "red"))
            return
        frame_queue.put(("status", "Streaming Active", "green"))
        brightness = float(brightness)
        contrast = float(contrast)
        while True:
            while True:
                try:
                    cmd = control_queue.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    break
                if cmd == "stop":
                    return
                if isinstance(cmd, tuple) and len(cmd) == 3 and cmd[0] == "settings":
                    _, brightness, contrast = cmd
                    brightness = float(brightness)
                    contrast = float(contrast)
            ret, frame = cap.read()
            if not ret:
                frame_queue.put(("status", "Stream disconnected or unavailable", "red"))
                break
            frame = cv2.convertScaleAbs(frame, alpha=contrast, beta=brightness)
            frame = cv2.resize(frame, (320, 240))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                continue
            try:
                frame_queue.put(("frame", encoded.tobytes()), timeout=0.2)
            except Exception:
                break
    finally:
        try:
            cap.release()
        except Exception:
            pass

#----------------------------------------------------------------------------------------------------
# Loco Config Window
#----------------------------------------------------------------------------------------------------

class LocoConfigWindow(Tk.Toplevel):
    # Track singleton instance so only one non-modal config window can exist at a time.
    active_instance = None

    @classmethod
    def open_or_focus(cls, parent, current_config, save_callback):
        # If window already exists, just raise and focus it.
        existing = cls.active_instance
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
        cls.active_instance = window
        return window

    def __init__(self, parent, current_config, save_callback):
        super().__init__(parent)
        self.title("Locomotive Configuration")
        self.resizable(False, False)
        # Non-modal behaviour (main app remains responsive), but keep window linked to parent.
        self.transient(parent)
        self.save_callback = save_callback
        self.initial_config = current_config
        self.entries = {}
        # Tracking dictionaries for discovered cameras
        self.discovered_cameras = {"None": "", "Manual URL Entry": ""}
        # Add saved stream URLs to the discovered list
        fwd_url = current_config.get("fwd_stream_url", "").strip()
        rev_url = current_config.get("rev_stream_url", "").strip()
        if fwd_url and fwd_url not in self.discovered_cameras.values():
            self.discovered_cameras[f"[Saved] {fwd_url}"] = fwd_url
        if rev_url and rev_url not in self.discovered_cameras.values():
            self.discovered_cameras[f"[Saved] {rev_url}"] = rev_url
        self.scan_interval_ms = 5000
        self.scan_thread = None
        self.scan_in_progress = False
        self.user_just_selected = False
        self.preview_thread_running = False
        self.current_preview_url = ""
        self.last_preview_selection_label = "None"
        self.last_preview_selection_url = ""
        self.preview_thread = None
        self.preview_generation = 0
        self.preview_token = 0
        self.window_closing = False
        # Outer Layout Split Frame
        main_layout = Tk.Frame(self)
        main_layout.pack(fill=Tk.BOTH, expand=True)
        # Left Side Form Layout
        form_frame = Tk.Frame(main_layout, padx=15, pady=10)
        form_frame.pack(side=Tk.LEFT, fill=Tk.BOTH, expand=True)
        # Right Side Preview Panel
        preview_frame = Tk.LabelFrame(main_layout, text="Live Camera Preview", padx=10, pady=10)
        preview_frame.pack(side=Tk.RIGHT, fill=Tk.BOTH, expand=True, padx=(0, 15), pady=10)
        self.preview_selection_label = Tk.Label(preview_frame, text="Selected Feed: None", fg="gray")
        self.preview_selection_label.pack(pady=(0, 5))
        self.preview_canvas = Tk.Canvas(preview_frame, width=320, height=240, bg="black")
        self.preview_canvas.pack()
        self.preview_image_id = self.preview_canvas.create_image(0, 0, anchor=Tk.NW, image=None)
        self.status_label = Tk.Label(preview_frame, text="Select a camera to preview", fg="gray")
        self.status_label.pack(pady=(5, 0))
        # Field configurations (Using custom types for streams)
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
            ("Axle Offsets (ft):", axle_entry_box, "axle_offsets_ft",
             {"max_length": 100, "tooltip": "Axle positions from front of the locomotive (in feet) to synchronize track-clack clicks "+
                                            "(e.g. 0.0, 7.0, 14.0, 40.0, 47.0, 54.0 for a Class 47 Co-Co)"}),
            ("Forward Stream URL:", "fwd_combo", "fwd_stream_url",
             {"max_length": 255, "tooltip": "Forward facing cab camera IP address/port (e.g. http://192.168.1.149:8080)"}),
            ("Reverse Stream URL:", "rev_combo", "rev_stream_url",
             {"max_length": 255, "tooltip": "Rear facing cab camera local IP address/port (e.g. http://192.168.1.150:8080)"}),]
        # Render the input fields
        for row, (label_text, widget_class, key, extra_args) in enumerate(fields):
            Tk.Label(form_frame, text=label_text, anchor="w").grid(row=row, column=0, sticky="ew", pady=4, padx=(0, 10))
            val = current_config.get(key, "")
            if isinstance(widget_class, str):
                # Handle streaming dropdown elements
                widget = ttk.Combobox(form_frame, width=32, state="normal")
                widget.grid(row=row, column=1, sticky="ew", pady=4)
                widget.bind("<<ComboboxSelected>>", lambda e, k=key: self.on_camera_selected(k))
                widget.bind("<KeyRelease>", lambda e, k=key: self.on_camera_typed(k))
                widget.set(val)  # Set raw string URL initially as a fallback
            else:
                # Handle standard entry fields cleanly
                width = 45 if widget_class in (string_entry_box, axle_entry_box) else 12
                widget = widget_class(form_frame, width=width, **extra_args)
                widget.grid(row=row, column=1, sticky="w" if width == 12 else "ew", pady=4)
                widget.set(val)
            self.entries[key] = widget
        control_bar = ConfigControlBar(self,
            on_ok=lambda: self.validate_and_save(close_window=True),
            on_apply=lambda: self.validate_and_save(close_window=False),
            on_reset=self.reset_to_original,
            on_cancel=self.close_window)
        control_bar.pack(fill=Tk.X, pady=10, side=Tk.BOTTOM)
        # Stream adjustment sliders directly under the preview
        slider_container = Tk.Frame(preview_frame)
        slider_container.pack(fill=Tk.X)
        Tk.Label(slider_container, text="Brightness:", anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.stream_brightness_var = Tk.IntVar(value=int(current_config.get("stream_brightness", 0)))
        self.stream_brightness_scale = Tk.Scale(slider_container, from_=-100, to=100, orient=Tk.HORIZONTAL,
                    command=self.on_brightness_update, resolution=1, showvalue=0, variable=self.stream_brightness_var, length=220)
        self.stream_brightness_scale.grid(row=0, column=1, sticky="ew", pady=4)
        self.entries["stream_brightness"] = self.stream_brightness_scale
        Tk.Label(slider_container, text="Contrast:", anchor="w").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.stream_contrast_var = Tk.DoubleVar(value=float(current_config.get("stream_contrast", 1.0)))
        self.stream_contrast_scale = Tk.Scale(slider_container, from_=0.5, to=2.0, orient=Tk.HORIZONTAL,
                    command=self.on_contrast_update,resolution=0.05, showvalue=0, variable=self.stream_contrast_var, length=220)
        self.stream_contrast_scale.grid(row=1, column=1, sticky="ew", pady=4)
        self.entries["stream_contrast"] = self.stream_contrast_scale
        slider_container.columnconfigure(1, weight=1)
        self.brightness = float(self.stream_brightness_var.get())
        self.contrast = float(self.stream_contrast_var.get())
        # Ensure comboboxes always have baseline options even before/without discovery.
        self.update_camera_dropdown_values()
        # Run initial discovery scan immediately
        self.run_discovery_if_idle()
        # Start periodic discovery loop
        self.schedule_discovery_tick()
        # Handle close cleanup to stop streaming threads safely
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        
    # -------------------------------------------------------------------------
    # Safely shut down everything gracefully on window close
    # -------------------------------------------------------------------------

    def close_window(self):
        self.window_closing = True
        self.close_discovery_engine()
        self.stop_preview_stream()
        self.current_preview_url = ""
        # Stop the periodic network scan
        self.scan_in_progress = False
        # ... rest of method ...        # 1. Break the loop inside stream_worker instantly
        self.preview_thread_running = False
        self.preview_generation += 1
        # 2. Reset tracking variables
        self.current_preview_url = ""
        # 3. Clear canvas image references to free up memory buffers
        try:
            self.preview_canvas.itemconfig(self.preview_image_id, image="")
            self.preview_canvas.delete("preview_text")
            self.preview_canvas.image = None
        except Exception:
            pass # UI widgets might already be closing, pass safely
        # 4. Clear active-instance tracker
        if LocoConfigWindow.active_instance is self:
            LocoConfigWindow.active_instance = None
        # 5. Destroy the Toplevel window block completely
        self.destroy()

    # -------------------------------------------------------------------------
    # Network Scanning Logic
    # -------------------------------------------------------------------------

    def schedule_discovery_tick(self):
        # Tk-thread scheduler: run every scan_interval_ms
        if not self.winfo_exists() or self.window_closing:
            return
        self.run_discovery_if_idle()
        self.after(self.scan_interval_ms, self.schedule_discovery_tick)

    def run_discovery_if_idle(self):
        # Don't start another scan if previous scan thread still running
        if self.scan_in_progress:
            return
        self.scan_in_progress = True
        self.scan_thread = threading.Thread(target=self.scan_network, daemon=True)
        self.scan_thread.start()

    def _ensure_discovery_engine(self):
        """
        Create and retain a long-lived Zeroconf + ServiceBrowser pair.
        This avoids repeatedly creating background threads and sockets every scan tick.
        """
        if getattr(self, "_discovery_zeroconf", None) is not None:
            return

        class ESPHomeDiscovery:
            def __init__(self, outer):
                self.outer = outer

            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name)
                if not info:
                    return

                for address in info.addresses:
                    try:
                        ip = socket.inet_ntoa(address)
                    except Exception:
                        continue

                    clean_name = name.split('.')[0]
                    url = f"http://{ip}:8080"

                    # Cache discovery results in a persistent store
                    self.outer._discovered_camera_cache[clean_name] = url

                    # Update UI-facing list on the Tk thread
                    self.outer.after(
                        0,
                        lambda n=clean_name, u=url: self.outer.register_discovered_camera(n, u)
                    )

            def update_service(self, zc, type_, name):
                pass

            def remove_service(self, zc, type_, name):
                pass

        if not hasattr(self, "_discovered_camera_cache"):
            self._discovered_camera_cache = {}

        self._discovery_zeroconf = Zeroconf()
        self._discovery_listener = ESPHomeDiscovery(self)
        self._discovery_browser = ServiceBrowser(
            self._discovery_zeroconf,
            ["_esphomelib._tcp.local.", "_http._tcp.local."],
            self._discovery_listener)

    def scan_network(self):
        try:
            # Preserve baseline options AND saved URLs
            baseline = {"None": "", "Manual URL Entry": ""}
            saved_urls = {k: v for k, v in self.discovered_cameras.items() if k.startswith("[Saved]")}
            self.discovered_cameras = baseline.copy()
            self.discovered_cameras.update(saved_urls)

            for name, url in getattr(self, "_discovered_camera_cache", {}).items():
                display_label = f"DISCOVERED: {name} ({url})"
                self.discovered_cameras[display_label] = url

            self._ensure_discovery_engine()
            # Allow async callbacks to fire while keeping the discovery engine alive
            time.sleep(3.0)
        except Exception as e:
            logging.error(f"[Discovery] Error during scan: {e}")
        finally:
            self.scan_in_progress = False

    def register_discovered_camera(self, name, url):
        url = url.rstrip('/')
        display_label = f"DISCOVERED: {name} ({url})"
        self.discovered_cameras[display_label] = url
        # Only debounce if user just selected something
        if not self.user_just_selected:
            self.after(0, self.update_camera_dropdown_values)
            
    def close_discovery_engine(self):
        try:
            browser = getattr(self, "_discovery_browser", None)
            if browser is not None:
                try:
                    browser.cancel()
                except Exception:
                    pass
            zeroconf = getattr(self, "_discovery_zeroconf", None)
            if zeroconf is not None:
                try:
                    zeroconf.close()
                except Exception as e:
                    logging.error(f"[Discovery] Error closing Zeroconf: {e}")
        finally:
            self._discovery_browser = None
            self._discovery_listener = None
            self._discovery_zeroconf = None

    def update_camera_dropdown_values(self):
        if not hasattr(self, 'entries'):
            return
        options = list(self.discovered_cameras.keys())
        for key in ["fwd_stream_url", "rev_stream_url"]:
            if key not in self.entries:
                continue
            combo = self.entries[key]
            current_val = combo.get().strip()
            # Only update values if they've actually changed (prevents dropdown glitch)
            current_options = list(combo["values"])
            if set(current_options) != set(options):
                combo["values"] = options
            # Preserve the current value (raw URL) after dropdown update
            if current_val:
                if current_val.startswith(("http://", "https://", "rtsp://")):
                    combo.set(current_val)
                elif current_val in self.discovered_cameras:
                    combo.set(current_val)
                else:
                    combo.set(current_val)
            else:
                combo.set("None")

    # -------------------------------------------------------------------------
    # Preview Handler
    # -------------------------------------------------------------------------

    def set_last_preview_selection(self, label, url):
        self.last_preview_selection_label = label if label else "None"
        self.last_preview_selection_url = url.strip() if isinstance(url, str) else ""
        if hasattr(self, "preview_selection_label") and self.preview_selection_label.winfo_exists():
            self.preview_selection_label.config(text=f"{self.last_preview_selection_label}")
            
    def show_no_feed_preview(self, message="No feed selected"):
        self.stop_preview_stream()
        try:
            self.preview_canvas.itemconfig(self.preview_image_id, image="")
            self.preview_canvas.delete("preview_text")
            self.preview_canvas.create_text(160, 120, text=message, fill="white", font=("Arial", 12), tags="preview_text")
            self.preview_canvas.image = None
        except Exception:
            pass
        if hasattr(self, "status_label") and self.status_label.winfo_exists():
            self.status_label.config(text=message, fg="gray")

    def on_camera_selected(self, key):
        selected_label = self.entries[key].get().strip()
        # The label stays in the combobox display - but we extract the URL for preview
        target_url = self.discovered_cameras.get(selected_label, "").strip()
        # Block discovery updates
        self.user_just_selected = True
        self.after(500, lambda: setattr(self, 'user_just_selected', False))
        # Display in preview label (strip prefix for readability)
        display_label = selected_label.replace("DISCOVERED: ", "").replace("[Saved] ", "")
        self.set_last_preview_selection(display_label if display_label else "None", target_url)
        # Start preview if there's a URL
        if target_url:
            if target_url != self.current_preview_url:
                self.current_preview_url = target_url
                self.start_preview_stream(target_url)
        else:
            self.current_preview_url = ""
            self.show_no_feed_preview("No feed selected")

    def on_camera_typed(self, key):
        typed_text = self.entries[key].get().strip()
        # Block discovery updates
        self.user_just_selected = True
        self.after(500, lambda: setattr(self, 'user_just_selected', False))
        # If user typed a raw URL directly (not a label), use it
        if typed_text.startswith(("http://", "https://", "rtsp://")):
            self.set_last_preview_selection("Custom / Manual", typed_text)
            if typed_text != self.current_preview_url:
                self.current_preview_url = typed_text
                self.start_preview_stream(typed_text)
        elif typed_text == "":
            self.current_preview_url = ""
            self.show_no_feed_preview("No feed selected")
        else:
            # User typed something that's not a URL - maybe incomplete
            self.set_last_preview_selection("Custom / Manual (incomplete)", typed_text)
            
    def on_contrast_update(self, contrast):
        self.contrast = float(contrast)
        self.send_preview_settings_update()
 
    def on_brightness_update(self, brightness):
        self.brightness = float(brightness)
        self.send_preview_settings_update()

    def send_preview_settings_update(self):
        if not getattr(self, "preview_worker_alive", False):
            return
        control_queue = getattr(self, "preview_control_queue", None)
        if control_queue is None:
            return
        message = ("settings", float(self.brightness), float(self.contrast))
        try:
            control_queue.put_nowait(message)
            return
        except queue.Full:
            pass
        except Exception:
            return
        retained_messages = []
        try:
            while True:
                queued_message = control_queue.get_nowait()
                if queued_message != "stop":
                    continue
                retained_messages.append(queued_message)
        except queue.Empty:
            pass
        except Exception:
            return
        for queued_message in retained_messages:
            try:
                control_queue.put_nowait(queued_message)
            except Exception:
                return
        try:
            control_queue.put_nowait(message)
        except Exception:
            pass
             
    def start_preview_stream(self, url):
        self.stop_preview_stream(wait=True)
        self.status_label.config(text="Connecting to stream...", fg="orange")
        self.current_preview_url = url
        self.preview_generation += 1
        self.preview_token += 1
        self.preview_frame_queue = mp.Queue(maxsize=2)
        self.preview_control_queue = mp.Queue(maxsize=2)
        self.preview_worker_alive = True
        self.preview_last_frame_at = time.monotonic()
        self.preview_watchdog_ms = 5000
        self.preview_process = mp.Process(
            target=preview_worker_process,
            args=(url, self.preview_frame_queue, self.preview_control_queue,
                  float(self.brightness), float(self.contrast)),
            daemon=True)
        self.preview_process.start()
        self.after(50, self.poll_preview_queue)
        self.after(250, self.preview_watchdog)

    def poll_preview_queue(self):
        if not getattr(self, "preview_worker_alive", False):
            return
        try:
            while True:
                kind, *payload = self.preview_frame_queue.get_nowait()

                if kind == "status":
                    text, color = payload
                    self.safe_preview_status(text, color, self.preview_generation, self.preview_token)
                    if text in ("Unable to open stream", "Stream disconnected or unavailable"):
                        self.stop_preview_stream(wait=False)
                        return
                elif kind == "frame":
                    data = payload[0]
                    self.preview_last_frame_at = time.monotonic()
                    img = Image.open(io.BytesIO(data))
                    img_tk = ImageTk.PhotoImage(img)
                    self.draw_frame(img_tk, self.preview_generation, self.preview_token)
        except queue.Empty:
            pass
        except Exception:
            pass
        if self.preview_worker_alive:
            self.after(50, self.poll_preview_queue)

    def preview_watchdog(self):
        if not getattr(self, "preview_worker_alive", False):
            return
        if time.monotonic() - getattr(self, "preview_last_frame_at", 0) > 5.0:
            self.safe_preview_status("Stream stalled", "red", self.preview_generation, self.preview_token)
            self.stop_preview_stream(wait=False)
            return
        self.after(250, self.preview_watchdog)

    def stop_preview_stream(self, wait=False, timeout=1.5):
        self.preview_generation += 1
        self.preview_token += 1
        self.preview_worker_alive = False
        exited_cleanly = True
        proc = getattr(self, "preview_process", None)
        if proc is not None:
            try:
                if getattr(self, "preview_control_queue", None) is not None:
                    try:
                        self.preview_control_queue.put_nowait("stop")
                    except Exception:
                        pass
                if wait:
                    proc.join(timeout=timeout)
                if proc.is_alive():
                    exited_cleanly = False
                    proc.terminate()
                    proc.join(timeout=timeout)
                    if proc.is_alive():
                        exited_cleanly = False
                    else:
                        exited_cleanly = False
            except Exception:
                exited_cleanly = False
                try:
                    proc.terminate()
                except Exception:
                    pass
            finally:
                self.preview_process = None
        self.preview_control_queue = None
        self.preview_frame_queue = None
        self.preview_thread_running = False
        return exited_cleanly

    def validate_preview_ready(self, timeout=1.5):
        return self.stop_preview_stream(wait=True, timeout=timeout)

    def safe_preview_status(self, text, color, generation, token):
        if token != self.preview_token: return
        if generation != self.preview_generation: return
        if hasattr(self, "status_label") and self.status_label.winfo_exists():
            self.status_label.config(text=text, fg=color)
            
    def draw_frame(self, img_tk, generation, token):
        if token != self.preview_token:
            return
        if generation != self.preview_generation:
            return
        if self.preview_worker_alive:
            self.preview_canvas.delete("preview_text")
            self.preview_canvas.itemconfig(self.preview_image_id, image=img_tk)
            self.preview_canvas.image = img_tk

    # -------------------------------------------------------------------------
    # Data Validation and Pipeline Handling
    # -------------------------------------------------------------------------

    def validate_and_save(self, close_window=True):
        # Run validators for custom entries (new baseline widgets expose validate()).
        for key, field in self.entries.items():
            # Skip combobox stream fields (manual validation handled below)
            if key in ("fwd_stream_url", "rev_stream_url"):
                continue
            if hasattr(field, 'validate'):
                if not field.validate():
                    return
            elif hasattr(field, 'entry_box_updated'):
                # Backward compatibility fallback
                field.entry_box_updated()
                if field.cget('fg') == 'red':
                    return
        # Manual validation for stream URLs (allow blank; if set, must look like URL)
        fwd_label = self.entries["fwd_stream_url"].get().strip()
        rev_label = self.entries["rev_stream_url"].get().strip()
        # Convert labels to URLs
        fwd_url = self.discovered_cameras.get(fwd_label, "").strip()
        # If not found in discovered (user typed raw URL), use it directly
        if not fwd_url:
            fwd_url = fwd_label if fwd_label.startswith(("http://", "https://", "rtsp://")) else ""
        rev_url = self.discovered_cameras.get(rev_label, "").strip()
        if not rev_url:
            rev_url = rev_label if rev_label.startswith(("http://", "https://", "rtsp://")) else ""
        # Validate URLs
        if fwd_url and not fwd_url.startswith(("http://", "https://", "rtsp://")):
            self.status_label.config(text="Forward stream URL must start with http://, https://, or rtsp://", fg="red")
            return
        if rev_url and not rev_url.startswith(("http://", "https://", "rtsp://")):
            self.status_label.config(text="Reverse stream URL must start with http://, https://, or rtsp://", fg="red")
            return
        updated_config = {
            "loco_name": self.entries["loco_name"].get(),
            "dcc_address": self.entries["dcc_address"].get(),
            "dcc_speed_scaling": self.entries["dcc_speed_scaling"].get(),
            "loco_horsepower": self.entries["loco_horsepower"].get(),
            "loco_mass_tonnes": self.entries["loco_mass_tonnes"].get(),
            "loco_max_speed_mph": self.entries["loco_max_speed_mph"].get(),
            "max_tractive_effort_lbf": self.entries["max_tractive_effort_lbf"].get(),
            "traction_responsiveness": self.entries["traction_responsiveness"].get(),
            "brake_responsiveness": self.entries["brake_responsiveness"].get(),
            "axle_offsets_ft": self.entries["axle_offsets_ft"].get(),
            "stream_brightness": int(self.stream_brightness_var.get()),
            "stream_contrast": float(self.stream_contrast_var.get()),
            "fwd_stream_url": fwd_url,
            "rev_stream_url": rev_url}
        # Disconnect preview stream before saving, so main app can take the feed immediately.
        if not self.validate_preview_ready(timeout=1.5):
            logging.warning("[Preview] Previous preview worker did not stop cleanly; continuing save anyway.")
        self.current_preview_url = ""
        self.status_label.config(text="Stream Released", fg="gray")
        self.preview_canvas.itemconfig(self.preview_image_id, image="")
        self.preview_canvas.delete("preview_text")
        self.preview_canvas.create_text(160, 120, text="Preview paused", fill="white", font=("Arial", 12), tags="preview_text")
        self.preview_canvas.image = None
        # Save the updated config
        self.save_callback(updated_config)
        if close_window:
            self.close_window()

    def reset_to_original(self):
        for key, widget in self.entries.items():
            original_val = self.initial_config.get(key, "")
            if key == "stream_brightness":
                self.stream_brightness_var.set(int(original_val if original_val != "" else 0))
            elif key == "stream_contrast":
                self.stream_contrast_var.set(float(original_val if original_val != "" else 1.0))
            elif key in ("fwd_stream_url", "rev_stream_url"):
                # For stream URLs, restore the raw URL value
                combo = widget
                combo.set(original_val if original_val else "None")
            else:
                widget.set(original_val)
                if hasattr(widget, 'validate'):
                    widget.validate()
                elif hasattr(widget, 'entry_box_updated'):
                    widget.entry_box_updated()
                    
###############################################################################################
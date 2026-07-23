import tkinter as Tk
from tkinter import ttk

#---------------------------------------------------------------------------------------------------------
# Generic Class for creating tooltips
#---------------------------------------------------------------------------------------------------------

class CreateToolTip():
    def __init__(self, widget, text: str = 'widget info'):
        self.waittime = 500     # milliseconds
        self.wraplength = 180   # pixels
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)
        self.tool_tip_scheduled = None
        self.tool_tip_window = None
        self.screen_width = self.widget.winfo_screenwidth() - 25
        self.screen_height = self.widget.winfo_screenheight() - 25
        
    def enter(self, event=None):
        self.schedule()
        
    def leave(self, event=None):
        self.unschedule()
        self.hidetip()
        
    def schedule(self):
        self.unschedule()
        self.tool_tip_scheduled = self.widget.after(self.waittime, self.showtip)
        
    def unschedule(self):
        tool_tip_scheduled = self.tool_tip_scheduled
        self.tool_tip_scheduled = None
        if tool_tip_scheduled: 
            self.widget.after_cancel(tool_tip_scheduled)
        
    def showtip(self, event=None):
        tool_tip_x1 = self.widget.winfo_rootx()
        tool_tip_y1 = self.widget.winfo_rooty()
        self.tool_tip_window = Tk.Toplevel(self.widget)
        self.tool_tip_window.attributes('-topmost', True)
        self.tool_tip_window.wm_geometry("+%d+%d" % (tool_tip_x1 + 25, tool_tip_y1 + 25))
        self.tool_tip_window.wm_overrideredirect(True)
        tool_tip_label = Tk.Label(self.tool_tip_window, text=self.text, justify='left',
                                  background="#ffffff", relief='solid', borderwidth=1, wraplength=self.wraplength)
        tool_tip_label.pack(ipadx=1)
        self.widget.update_idletasks()
        tool_tip_window_width = self.tool_tip_window.winfo_width()
        tool_tip_window_height = self.tool_tip_window.winfo_height()
        tool_tip_x2 = tool_tip_x1 + tool_tip_window_width
        tool_tip_y2 = tool_tip_y1 + tool_tip_window_height
        
        if tool_tip_x2 > self.screen_width and tool_tip_y2 > self.screen_height:
            tool_tip_x1 = tool_tip_x1 - tool_tip_window_width
            tool_tip_y1 = tool_tip_y1 - tool_tip_window_height
            self.tool_tip_window.wm_geometry("+%d+%d" % (tool_tip_x1 + 25, tool_tip_y1))
        elif tool_tip_x2 > self.screen_width:
            tool_tip_x1 = tool_tip_x1 - tool_tip_window_width
            self.tool_tip_window.wm_geometry("+%d+%d" % (tool_tip_x1 + 25, tool_tip_y1 + 25))
        elif tool_tip_y2 > self.screen_height:
            tool_tip_y1 = tool_tip_y1 - tool_tip_window_height
            self.tool_tip_window.wm_geometry("+%d+%d" % (tool_tip_x1 + 25, tool_tip_y1))
        
    def hidetip(self):
        tool_tip_window = self.tool_tip_window
        self.tool_tip_window = None
        if tool_tip_window: 
            tool_tip_window.destroy()

#---------------------------------------------------------------------------------------------------------
# Generic Class for a dropdown box
#-------------------------------------------------------------------------------------------------------

def dropdown_box(parent, values, tooltip:str, **kwargs):
    # Create a Combobox themed widget
    combo = ttk.Combobox(parent, values=values, state="readonly", **kwargs)
    CreateToolTip(combo, tooltip)
    return combo

#---------------------------------------------------------------------------------------------------------
# Generic Class for a check box
#---------------------------------------------------------------------------------------------------------

class check_box(Tk.Checkbutton):
    def __init__(self, parent_frame, width: int, label: str, tooltip: str = "", callback=None):
        self.parent_frame = parent_frame
        self.callback = callback
        self.base_tooltip = tooltip
        self.is_valid = True
        self.validation_error = None
        # Internal boolean tracking engine matching your standard pattern
        self.selection = Tk.BooleanVar(self.parent_frame, False)
        super().__init__(self.parent_frame, text=label, anchor="w", width=width, variable=self.selection, command=self.entry_box_updated)
        self.tooltip_manager = CreateToolTip(self, self.base_tooltip)

    def validate(self):
        # Checkboxes are intrinsically valid; this method exists for unified caller pipelines.
        self.is_valid = True
        self.validation_error = None
        self.configure(fg='black')
        self.tooltip_manager.text = self.base_tooltip
        return True

    def get_validation_error(self):
        return self.validation_error

    def entry_box_updated(self, event=None):
        # Note the Unified method name for validation loop passes
        self.parent_frame.focus()
        # Checkboxes don't have visual validation exceptions (like text blocks turning red),
        # but we need to maintain this method to ensure the programmatic validation loop in
        # The your parent window class (field.entry_box_updated()) doesn't break.
        self.validate()
        if self.callback is not None: 
            self.callback()

    def get(self):
        return self.selection.get()

    def set(self, new_value: bool):
        self.selection.set(new_value)
        self.validate()

#---------------------------------------------------------------------------------------------------------
# Generic Class for an integer entry box
#---------------------------------------------------------------------------------------------------------

class integer_entry_box(Tk.Entry):
    def __init__(self, parent_frame, width: int, min_val=None, max_val=None, tooltip: str = "", callback=None):
        self.value = 0
        self.min_val = min_val
        self.max_val = max_val
        self.base_tooltip = tooltip if tooltip else "Enter an integer value."
        self.entry = Tk.StringVar(parent_frame, str(self.value))
        self.parent_frame = parent_frame
        self.callback = callback
        self.is_valid = True
        self.validation_error = None
        super().__init__(self.parent_frame, width=width, textvariable=self.entry, justify='center')
        self.tooltip_manager = CreateToolTip(self, self.base_tooltip)
        # Live validation on entry + explicit commit validation hooks.
        self.bind('<KeyRelease>', self.entry_box_live_validate)
        self.bind('<Return>', self.entry_box_updated)
        self.bind('<Escape>', self.entry_box_cancel)
        self.bind('<FocusOut>', self.entry_box_updated)
        
    def validate(self):
        entered_value = self.entry.get()        
        if entered_value == "":
            self.entry.set("0")
            self.value = 0
            self.is_valid = True
            self.validation_error = None
            self.configure(fg='black')
            self.tooltip_manager.text = self.base_tooltip
            return True
        elif not entered_value.lstrip('-+').isdigit():
            self.is_valid = False
            self.validation_error = "Input must be a valid integer."
            self.configure(fg='red')
            self.tooltip_manager.text = f"Error: {self.validation_error}"
            return False
        else:
            parsed_val = int(entered_value)
            # Range validation checks
            if self.min_val is not None and parsed_val < self.min_val:
                self.is_valid = False
                self.validation_error = f"Value must be ≥ {self.min_val}."
                self.configure(fg='red')
                self.tooltip_manager.text = f"Out of range! {self.validation_error}"
                return False
            if self.max_val is not None and parsed_val > self.max_val:
                self.is_valid = False
                self.validation_error = f"Value must be ≤ {self.max_val}."
                self.configure(fg='red')
                self.tooltip_manager.text = f"Out of range! {self.validation_error}"
                return False
            self.configure(fg='black')
            self.value = parsed_val
            self.is_valid = True
            self.validation_error = None
            self.tooltip_manager.text = self.base_tooltip
            return True

    def get_validation_error(self):
        return self.validation_error

    def entry_box_live_validate(self, event=None):
        # Validate continuously while typing so errors are shown immediately.
        self.validate()
        if self.callback is not None:
            self.callback()

    def entry_box_updated(self, event=None):
        self.validate()
        if event and getattr(event, "keysym", None) == 'Return': 
            self.parent_frame.focus()
        if self.callback is not None: 
            self.callback()
        
    def entry_box_cancel(self, event):
        self.entry.set(str(self.value))
        self.configure(fg='black')
        self.is_valid = True
        self.validation_error = None
        self.tooltip_manager.text = self.base_tooltip
        self.parent_frame.focus()
        
    def get(self):
        return self.value

    def set(self, new_value):
        self.value = int(new_value)
        self.entry.set(str(self.value))
        self.configure(fg='black')
        self.is_valid = True
        self.validation_error = None
        self.tooltip_manager.text = self.base_tooltip

#---------------------------------------------------------------------------------------------------------
# Generic Class for an float entry box
#---------------------------------------------------------------------------------------------------------

class float_entry_box(Tk.Entry):
    def __init__(self, parent_frame, width: int, min_val=None, max_val=None, tooltip: str = "", callback=None):
        self.value = 0.0
        self.min_val = min_val
        self.max_val = max_val
        self.base_tooltip = tooltip if tooltip else "Enter a decimal value."
        self.entry = Tk.StringVar(parent_frame, str(self.value))
        self.parent_frame = parent_frame
        self.callback = callback
        self.is_valid = True
        self.validation_error = None
        super().__init__(self.parent_frame, width=width, textvariable=self.entry, justify='center')
        self.tooltip_manager = CreateToolTip(self, self.base_tooltip)
        # Live validation on entry + explicit commit validation hooks.
        self.bind('<KeyRelease>', self.entry_box_live_validate)
        self.bind('<Return>', self.entry_box_updated)
        self.bind('<Escape>', self.entry_box_cancel)
        self.bind('<FocusOut>', self.entry_box_updated)
        
    def validate(self):
        entered_value = self.entry.get()        
        try:
            if entered_value == "":
                parsed_val = 0.0
                self.entry.set("0.0")
            else:
                parsed_val = float(entered_value)
            # Range validation checks
            if self.min_val is not None and parsed_val < self.min_val:
                self.is_valid = False
                self.validation_error = f"Value must be ≥ {self.min_val}."
                self.configure(fg='red')
                self.tooltip_manager.text = f"Out of range! {self.validation_error}"
                return False
            if self.max_val is not None and parsed_val > self.max_val:
                self.is_valid = False
                self.validation_error = f"Value must be ≤ {self.max_val}."
                self.configure(fg='red')
                self.tooltip_manager.text = f"Out of range! {self.validation_error}"
                return False
            self.value = parsed_val
            self.configure(fg='black')
            self.is_valid = True
            self.validation_error = None
            self.tooltip_manager.text = self.base_tooltip
            return True
        except ValueError:
            self.is_valid = False
            self.validation_error = "Input must be a valid float decimal."
            self.configure(fg='red')
            self.tooltip_manager.text = f"Error: {self.validation_error}"
            return False

    def get_validation_error(self):
        return self.validation_error

    def entry_box_live_validate(self, event=None):
        # Validate continuously while typing so errors are shown immediately.
        self.validate()
        if self.callback is not None:
            self.callback()

    def entry_box_updated(self, event=None):
        self.validate()
        if event and getattr(event, "keysym", None) == 'Return': 
            self.parent_frame.focus()
        if self.callback is not None: 
            self.callback()
        
    def entry_box_cancel(self, event):
        self.entry.set(str(self.value))
        self.configure(fg='black')
        self.is_valid = True
        self.validation_error = None
        self.tooltip_manager.text = self.base_tooltip
        self.parent_frame.focus()
        
    def get(self):
        return self.value

    def set(self, new_value):
        self.value = float(new_value)
        self.entry.set(str(self.value))
        self.configure(fg='black')
        self.is_valid = True
        self.validation_error = None
        self.tooltip_manager.text = self.base_tooltip

#---------------------------------------------------------------------------------------------------------
# Generic Class for an string entry box
#---------------------------------------------------------------------------------------------------------

class string_entry_box(Tk.Entry):
    def __init__(self, parent_frame, width: int, max_length=None, tooltip: str = "", callback=None):
        self.value = ""
        self.max_length = max_length
        self.base_tooltip = tooltip if tooltip else "Enter text."
        self.entry = Tk.StringVar(parent_frame, self.value)
        self.parent_frame = parent_frame
        self.callback = callback
        self.is_valid = True
        self.validation_error = None
        super().__init__(self.parent_frame, width=width, textvariable=self.entry, justify='left')
        self.tooltip_manager = CreateToolTip(self, self.base_tooltip)
        # Live validation on entry + explicit commit validation hooks.
        self.bind('<KeyRelease>', self.entry_box_live_validate)
        self.bind('<Return>', self.entry_box_updated)
        self.bind('<Escape>', self.entry_box_cancel)
        self.bind('<FocusOut>', self.entry_box_updated)
        
    def validate(self):
        entered_value = self.entry.get()
        if self.max_length is not None and len(entered_value) > self.max_length:
            self.is_valid = False
            self.validation_error = f"Maximum length allowed is {self.max_length} characters."
            self.configure(fg='red')
            self.tooltip_manager.text = f"Too long! {self.validation_error}"
            return False
        self.value = entered_value
        self.configure(fg='black')
        self.is_valid = True
        self.validation_error = None
        self.tooltip_manager.text = self.base_tooltip
        return True

    def get_validation_error(self):
        return self.validation_error

    def entry_box_live_validate(self, event=None):
        # Validate continuously while typing so errors are shown immediately.
        self.validate()
        if self.callback is not None:
            self.callback()

    def entry_box_updated(self, event=None):
        self.validate()
        if event and getattr(event, "keysym", None) == 'Return': 
            self.parent_frame.focus()
        if self.callback is not None: 
            self.callback()
        
    def entry_box_cancel(self, event):
        self.entry.set(self.value)
        self.configure(fg='black')
        self.is_valid = True
        self.validation_error = None
        self.tooltip_manager.text = self.base_tooltip
        self.parent_frame.focus()
        
    def get(self):
        return self.value

    def set(self, new_value):
        self.value = str(new_value)
        self.entry.set(self.value)
        self.configure(fg='black')
        self.is_valid = True
        self.validation_error = None
        self.tooltip_manager.text = self.base_tooltip
        
#---------------------------------------------------------------------------------------------------------
# Generic Class for an axle entry box
#---------------------------------------------------------------------------------------------------------

class axle_entry_box(Tk.Entry):
    def __init__(self, parent_frame, width: int, max_length=None, tooltip: str = "", callback=None):
        # Internal state stores the clean Python list of floats
        self.value = []
        self.max_length = max_length
        self.base_tooltip = tooltip if tooltip else "Enter comma-separated numbers for axle offsets."
        self.entry = Tk.StringVar(parent_frame, "")
        self.parent_frame = parent_frame
        self.callback = callback
        self.is_valid = True
        self.validation_error = None
        super().__init__(self.parent_frame, width=width, textvariable=self.entry, justify='left')
        self.tooltip_manager = CreateToolTip(self, self.base_tooltip)
        # Live validation on entry + explicit commit validation hooks.
        self.bind('<KeyRelease>', self.entry_box_live_validate)
        self.bind('<Return>', self.entry_box_updated)
        self.bind('<Escape>', self.entry_box_cancel)
        self.bind('<FocusOut>', self.entry_box_updated)
        
    def validate(self):
        entered_value = self.entry.get().strip()
        # 1. Enforce max character length safety first
        if self.max_length is not None and len(entered_value) > self.max_length:
            self.is_valid = False
            self.validation_error = f"Maximum length allowed is {self.max_length} characters."
            self.configure(fg='red')
            self.tooltip_manager.text = f"Too long! {self.validation_error}"
            return False
        # 2. Check for empty string (Perfectly valid -> translates to an empty list)
        if not entered_value:
            self.value = []
            self.configure(fg='black')
            self.is_valid = True
            self.validation_error = None
            self.tooltip_manager.text = self.base_tooltip
            return True
        else:
            # 3. Parse and validate comma-separated digits
            try:
                parsed_list = [float(x.strip()) for x in entered_value.split(",") if x.strip() != ""]
                self.value = parsed_list
                self.configure(fg='black')
                self.is_valid = True
                self.validation_error = None
                self.tooltip_manager.text = self.base_tooltip
                return True
            except ValueError:
                self.is_valid = False
                self.validation_error = "Input must be numbers separated by commas only (e.g. 0.0, 7.5)."
                self.configure(fg='red')
                self.tooltip_manager.text = f"Error: {self.validation_error}"
                return False

    def get_validation_error(self):
        return self.validation_error

    def entry_box_live_validate(self, event=None):
        # Validate continuously while typing so errors are shown immediately.
        self.validate()
        if self.callback is not None:
            self.callback()

    def entry_box_updated(self, event=None):
        self.validate()
        if event and getattr(event, "keysym", None) == 'Return': 
            self.parent_frame.focus()
        if self.callback is not None: 
            self.callback()
        
    def entry_box_cancel(self, event):
        # Revert back to the last successfully committed state, stripped of brackets
        self.entry.set(", ".join(map(str, self.value)))
        self.configure(fg='black')
        self.is_valid = True
        self.validation_error = None
        self.tooltip_manager.text = self.base_tooltip
        self.parent_frame.focus()
        
    def get(self):
        # Seamlessly returns a native python list directly to validate_and_save()
        return self.value

    def set(self, new_value):
        # Automatically unpacks an incoming list into a raw comma-separated string for the UI view
        if isinstance(new_value, list):
            self.value = new_value
            self.entry.set(", ".join(map(str, new_value)))
        else:
            # Fallback handling for blank configurations
            self.value = []
            self.entry.set("")
        self.configure(fg='black')
        self.is_valid = True
        self.validation_error = None
        self.tooltip_manager.text = self.base_tooltip

#---------------------------------------------------------------------------------------------------------
# Generic Class for one or more radio buttons
#---------------------------------------------------------------------------------------------------------

class RadioGroupWrapper:
    def __init__(self, parent_frame, options, callback=None, default_value=20):
        self.parent_frame = parent_frame
        self.callback = callback
        self.var = Tk.IntVar(value=default_value)  # Defaulting to INFO (20) unless explicitly overridden
        self.buttons = []
        self.is_valid = True
        self.validation_error = None
        # Grid or pack the options neatly inside this container frame
        for text, value in options:
            rb = Tk.Radiobutton(parent_frame, text=text, variable=self.var, value=value, command=self.entry_box_updated)
            rb.pack(side=Tk.LEFT, padx=10)
            self.buttons.append(rb)

    def validate(self):
        try:
            int(self.var.get())
            self.is_valid = True
            self.validation_error = None
            return True
        except Exception:
            self.is_valid = False
            self.validation_error = "No valid selection."
            return False

    def get_validation_error(self):
        return self.validation_error

    def entry_box_updated(self, event=None):
        self.parent_frame.focus()
        self.validate()
        if self.callback is not None:
            self.callback()

    def get(self) -> int:
        return self.var.get()

    def set(self, value):
        self.var.set(int(value))
        self.validate()

#----------------------------------------------------------------------------------------------------
# Common config window control buttons
#----------------------------------------------------------------------------------------------------

class ConfigControlBar(Tk.Frame):
    def __init__(self, parent, on_ok, on_apply, on_reset, on_cancel, **kwargs):
        super().__init__(parent, **kwargs)
        # Internal container frame used exclusively to center the button group
        button_container = Tk.Frame(self)
        button_container.pack(expand=True)  # Expands to absorb extra space, centering contents
        # Order: OK -> Apply -> Reset -> Cancel
        Tk.Button(button_container, text="OK", width=8, command=on_ok).pack(side=Tk.LEFT, padx=5)
        Tk.Button(button_container, text="Apply", width=8, command=on_apply).pack(side=Tk.LEFT, padx=5)
        Tk.Button(button_container, text="Reset", width=8, command=on_reset).pack(side=Tk.LEFT, padx=5)
        Tk.Button(button_container, text="Cancel", width=8, command=on_cancel).pack(side=Tk.LEFT, padx=5)

######################################################################################################################
import tkinter as Tk

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


class integer_entry_box(Tk.Entry):
    def __init__(self, parent_frame, width: int, min_val=None, max_val=None, tooltip: str = "", callback=None):
        self.value = 0
        self.min_val = min_val
        self.max_val = max_val
        self.base_tooltip = tooltip if tooltip else f"Enter an integer value."
        
        self.entry = Tk.StringVar(parent_frame, str(self.value))
        self.parent_frame = parent_frame
        self.callback = callback
        super().__init__(self.parent_frame, width=width, textvariable=self.entry, justify='center')
        
        self.tooltip_manager = CreateToolTip(self, self.base_tooltip)
        
        self.bind('<Return>', self.entry_box_updated)
        self.bind('<Escape>', self.entry_box_cancel)
        self.bind('<FocusOut>', self.entry_box_updated)
        
    def entry_box_updated(self, event=None):
        entered_value = self.entry.get()        
        if entered_value == "":
            self.entry.set("0")
            self.value = 0
            self.configure(fg='black')
            self.tooltip_manager.text = self.base_tooltip
        elif not entered_value.lstrip('-+').isdigit():
            self.configure(fg='red')
            self.tooltip_manager.text = "Error: Input must be a valid integer."
            return 
        else:
            parsed_val = int(entered_value)
            # Range validation checks
            if self.min_val is not None and parsed_val < self.min_val:
                self.configure(fg='red')
                self.tooltip_manager.text = f"Out of range! Value must be ≥ {self.min_val}."
                return
            if self.max_val is not None and parsed_val > self.max_val:
                self.configure(fg='red')
                self.tooltip_manager.text = f"Out of range! Value must be ≤ {self.max_val}."
                return
                
            self.configure(fg='black')
            self.value = parsed_val
            self.tooltip_manager.text = self.base_tooltip
            
        if event and event.keysym == 'Return': 
            self.parent_frame.focus()
        if self.callback is not None: 
            self.callback()
        
    def entry_box_cancel(self, event):
        self.entry.set(str(self.value))
        self.configure(fg='black')
        self.tooltip_manager.text = self.base_tooltip
        self.parent_frame.focus()
        
    def get(self):
        return self.value

    def set(self, new_value):
        self.value = int(new_value)
        self.entry.set(str(self.value))
        self.configure(fg='black')
        self.tooltip_manager.text = self.base_tooltip


class float_entry_box(Tk.Entry):
    def __init__(self, parent_frame, width: int, min_val=None, max_val=None, tooltip: str = "", callback=None):
        self.value = 0.0
        self.min_val = min_val
        self.max_val = max_val
        self.base_tooltip = tooltip if tooltip else "Enter a decimal value."
        
        self.entry = Tk.StringVar(parent_frame, str(self.value))
        self.parent_frame = parent_frame
        self.callback = callback
        super().__init__(self.parent_frame, width=width, textvariable=self.entry, justify='center')
        
        self.tooltip_manager = CreateToolTip(self, self.base_tooltip)
        
        self.bind('<Return>', self.entry_box_updated)
        self.bind('<Escape>', self.entry_box_cancel)
        self.bind('<FocusOut>', self.entry_box_updated)
        
    def entry_box_updated(self, event=None):
        entered_value = self.entry.get()        
        try:
            if entered_value == "":
                parsed_val = 0.0
                self.entry.set("0.0")
            else:
                parsed_val = float(entered_value)
                
            # Range validation checks
            if self.min_val is not None and parsed_val < self.min_val:
                self.configure(fg='red')
                self.tooltip_manager.text = f"Out of range! Value must be ≥ {self.min_val}."
                return
            if self.max_val is not None and parsed_val > self.max_val:
                self.configure(fg='red')
                self.tooltip_manager.text = f"Out of range! Value must be ≤ {self.max_val}."
                return
                
            self.value = parsed_val
            self.configure(fg='black')
            self.tooltip_manager.text = self.base_tooltip
        except ValueError:
            self.configure(fg='red')
            self.tooltip_manager.text = "Error: Input must be a valid float decimal."
            return
            
        if event and event.keysym == 'Return': 
            self.parent_frame.focus()
        if self.callback is not None: 
            self.callback()
        
    def entry_box_cancel(self, event):
        self.entry.set(str(self.value))
        self.configure(fg='black')
        self.tooltip_manager.text = self.base_tooltip
        self.parent_frame.focus()
        
    def get(self):
        return self.value

    def set(self, new_value):
        self.value = float(new_value)
        self.entry.set(str(self.value))
        self.configure(fg='black')
        self.tooltip_manager.text = self.base_tooltip


class string_entry_box(Tk.Entry):
    def __init__(self, parent_frame, width: int, max_length=None, tooltip: str = "", callback=None):
        self.value = ""
        self.max_length = max_length
        self.base_tooltip = tooltip if tooltip else "Enter text."
        
        self.entry = Tk.StringVar(parent_frame, self.value)
        self.parent_frame = parent_frame
        self.callback = callback
        super().__init__(self.parent_frame, width=width, textvariable=self.entry, justify='left')
        
        self.tooltip_manager = CreateToolTip(self, self.base_tooltip)
        
        self.bind('<Return>', self.entry_box_updated)
        self.bind('<Escape>', self.entry_box_cancel)
        self.bind('<FocusOut>', self.entry_box_updated)
        
    def entry_box_updated(self, event=None):
        entered_value = self.entry.get()
        
        if self.max_length is not None and len(entered_value) > self.max_length:
            self.configure(fg='red')
            self.tooltip_manager.text = f"Too long! Maximum length allowed is {self.max_length} characters."
            return
            
        self.value = entered_value
        self.configure(fg='black')
        self.tooltip_manager.text = self.base_tooltip
        
        if event and event.keysym == 'Return': 
            self.parent_frame.focus()
        if self.callback is not None: 
            self.callback()
        
    def entry_box_cancel(self, event):
        self.entry.set(self.value)
        self.configure(fg='black')
        self.tooltip_manager.text = self.base_tooltip
        self.parent_frame.focus()
        
    def get(self):
        return self.value

    def set(self, new_value):
        self.value = str(new_value)
        self.entry.set(self.value)
        self.tooltip_manager.text = self.base_tooltip
        
######################################################################################################################
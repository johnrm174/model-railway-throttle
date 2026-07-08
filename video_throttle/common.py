import queue
import logging

root_window = None
event_queue = queue.Queue()

def set_root_window(root):
    global root_window
    root_window = root
    # Start the polling loop (for handling events passed in by other threads)
    root_window.after(100, process_external_events)
    return()

def process_external_events():
    while not event_queue.empty():
        try:
            callback = event_queue.get_nowait()
            callback()
        except Exception as exception:
            logging.error(f"Exception processing event in Tkinter Thread: {exception}")
    root_window.after(50, process_external_events)
    return()

def execute_function_in_tkinter_thread(callback_function):
    event_queue.put(callback_function)
    return()

def mqtt_transmit_all():
    pass

##################################################################################################


from pythreader import LogFile, LogStream
import sys
from datetime import datetime

_enabled = False
_debug_out = None

def init(path):
    global _debug_out, _enabled
    print("debug file:", path)
    if path == "-":
        _debug_out = LogStream(sys.stdout)
    else:
        _debug_out = LogFile(path, flush_interval=3.0, keep=2)
        _debug_out.start()
    _enabled = True
    
def debug(msg, t=None, add_timestamp=True):
    if _enabled:
        if add_timestamp or t is not None:
            msg = "%s: %s" % (make_timestamp(t), msg)
        _debug_out.log(msg)

def make_timestamp(t=None):
    if t is None:   
        t = datetime.datetime.now()
    elif isinstance(t, (int, float)):
        t = datetime.datetime.fromtimestamp(t)
    return t.strftime("%m/%d/%Y %H:%M:%S") + ".%03d" % (t.microsecond//1000)


class Debugged(object):
    
    def __init__(self, my_name=None, send_to=None, save_in_memory=False, add_timestamps=False, enabled=True):
        self.MyName = my_name if my_name is not None else str(self)
        self.SendTo = send_to
        self.Enabled = enabled
        self.AddTimestamps = add_timestamps
        
    def debug(self, msg, t=None, add_timestamp = None):
        if self.Enabled:
            msg = "%s: %s" % (self.MyName, msg)
            if add_timestamp is None:   add_timestamp = self.AddTimestamps
            if self.SendTo is None:
                debug(msg, t=t, add_timestamp=add_timestamp)
            else:
                self.SendTo.log(msg, t=t, add_timestamp=add_timestamp)

        

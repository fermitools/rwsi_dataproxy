from pythreader import LogFile, LogStream
from request_logger import RequestLogger
import sys

logfile = None
errfile = None
debugfile = None
request_log = None

def openLogFile(path):
    global logfile
    if path == "-":
        logfile = LogStream(sys.stdout)
    else:
        logfile = LogFile(path, flush_interval=1.0)
        logfile.start()
    
def openErrorFile(path):
    global errfile
    if path == "-":
        errfile = LogStream(sys.stdout)
    else:
        errfile = LogFile(path, flush_interval=1.0)
        errfile.start()

def openDebugFile(path):
    global debugfile
    debugfile = LogStream(sys.stdout) if path == "-" else LogFile(path, interval="1h", flush_interval=1.0)
    debugfile.log("-------- Started --------")
    
def openRequestLog(path, data_logger):
    global request_log
    if path:
        logfile = LogFile(path)
        logfile.start()
        request_log = RequestLogger(logfile, data_logger)
        
class Logged(object):
    def __init__(self, log_to=None, name=None, **args):
        self.LogName = name
        self.log_to(log_to or logfile)
        
    def log_to(self, log_to):
        self.LogTo = LogFile(log_to) if isinstance(log_to, str) else log_to
        
    def log(self, msg):
        if self.LogTo is not None:
            name = self.LogName or str(self)
            prefix = name + ": " if name else ""
            self.LogTo.log("%s%s" % (prefix, msg))
        
    def errorLog(self, msg):
        global errfile
        if errfile is not None:
            name = self.LogName or str(self)
            prefix = name + ": " if name else ""
            errfile.log("%s%s" % (prefix, msg))
            
    def log_request(self, request):
        global request_log
        if request_log is not None:
            request_log.log(request)
            
            
            
        
        
            
        
        
    

    
    


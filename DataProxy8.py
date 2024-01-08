import threading
#from Selector import Selector
import yaml, socket, time, fnmatch, signal, select, sys, traceback
from datetime import datetime, timedelta
from LogFile import LogFile
from threading import RLock
from WebInterface2 import DataProxyWebInterface
from pythreader import TaskQueue, Task, PyThread, synchronized, Primitive, Scheduler
from HTTPProxy2 import HTTPProxy
from DataLogger2 import DataLogger
from record import TimeWindow
#from DataLogger import DataLogger
from logs import Logged
from debug import Debugged
import debug
from timelib import timestamp
from VServer1 import VirtualServer
from service import Service
from py3 import to_bytes, PY3
from iptable import IPTable
from redirector import Redirector
from zlib import adler32
from uid import uid


if PY3:
    from urllib.request import urlopen
else:
    from urllib2 import urlopen


def seconds(t1, t2):
    if t1 == None or t2 == None:    return None
    delta = t2 - t1
    return delta.days * 3600 * 24 + delta.seconds + delta.microseconds/1000000.0


class DataProxy(Debugged, Logged, PyThread):

    GlobalFields = ["tick"]

    TickInterval = 10.0


    def __init__(self, config_file, scanner_detector, data_logger, logfile, logdir):
        Logged.__init__(self, logfile)
        PyThread.__init__(self)
        self.DataLogger = data_logger
        self.ConfigFile = config_file
        self.Config = yaml.load(open(config_file, 'r'), Loader=yaml.SafeLoader)
        debug_enabled = self.Config.get("Debug",{}).get("enabled", False)
        Debugged.__init__(self)
        self.Services = {}      # {name: Service}
        self.Servers = {}       # {port:server}
        for svc in self.Config["Services"]:
            name = svc["name"]
            if name in self.Services:
                print(("Service %s appears twice in the configuration" % (name,)))
            self.Services[name] = service = Service.create(self, data_logger, svc)
            self.DataLogger.addService(name, service.LoggerFields)
        for srv in self.Config["Servers"]:
            port = srv["Port"]
            if port in self.Servers:
                print(("Server with port=%d appears twice in the configuration" % (port,)))
            self.Servers[port] = server = VirtualServer(self.Services, scanner_detector, self.DataLogger, srv, logdir)
            self.DataLogger.addServer(port, server.LoggerFields)
        self.DataLogger.addGlobals(self.GlobalFields)

    def __str__(self):
        return "[DataProxy]"

    def service(self, name):
        return self.Services[name]

    def tick(self):
        self.DataLogger.add("global", event="tick")
        for s in self.Services.values():
            s.tick()
        for s in self.Servers.values():
            s.tick()
        
    def run(self):
        for s in self.Servers.values():
            s.start()
        scheduler = Scheduler()
        scheduler.add(self.tick, self.TickInterval)
        scheduler.add(self.DataLogger.sendStatsToGraphite, 60.0, self)
        scheduler.start()
        scheduler.join()
        
    def reconfigure(self):
    
        new_config = yaml.load(open(self.ConfigFile, 'r'), Loader=yaml.SafeLoader)
        
        if new_config.get("Log"):
            self.LogFile = LogFile(new_config["Log"])
            self.log("reconfiguring...")
        else:
            self.LogFile = None
        
        new_servers = {}
        to_remove = list(self.Servers.keys())
        #print self.Servers
        for c in new_config["Servers"]:
            p = c["Port"]
            if p in self.Servers:
                s = self.Servers[p]
                s.reconfigure(c)
                to_remove.remove(p)
            else:
                s = VirtualServer(self, c)
                s.start()
            new_servers[p] = s
        for p in to_remove:
            s = self.Servers[p]
            s.shutdown()
        self.Servers = new_servers
        self.Config = new_config
        self.log("reconfigured")
        
    # for backward compatibility
    @property
    @synchronized
    def _____Services(self):
        dct = {}
        for p, srv in self.Servers.items():
            for name, svc in srv.Services.items():
                #print p, name
                svc.Port = p
                dct[name] = svc
        return dct
        
    def services(self):
        return self.Services
        
    def service(self, name):
        return self.Services[name]    
        
    def virtualServersForService(self, svc_name):
        lst = [vs for vs in self.Servers.values() if svc_name in vs.Services]
        return sorted(lst, key=lambda vs: vs.Port)

class   SignalHandler:

    def __init__(self, signum, receiver):
        self.Receiver = receiver
        signal.signal(signum, self)
        
    def __call__(self, signo, frame):
        try:    self.Receiver.reconfigure()
        except: 
            exctype, excvalue = sys.exc_info()[:2]
            print("Signal handler error:", exctype, excvalue)
            
def getMemory():
    # returns memory utilization in MB
    try:    f = open("/proc/%s/status" % (os.getpid(),), "r")
    except:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return None, rss/1024.0/1024.0
    vmsize = None
    vmrss = None
    for l in f.readlines():
        l = l.strip()
        if l.startswith("VmSize:"):
            vmsize = int(l.split()[1])
        elif l.startswith("VmRSS:"):
            vmrss = int(l.split()[1])
    return float(vmsize)/1024.0, float(vmrss)/1024.0

class Monitor(PyThread, Logged):

    def __init__(self, proxy, logfile):
        Logged.__init__(self, logfile, name="thread monitor")
        PyThread.__init__(self)
        self.Proxy = proxy
        
    def run(self):
        while True: 
            vm, rss = getMemory()
            self.log(f"memory usage: VM:{vm} RSS:{rss}")
            
            try:
                fd = os.open("/dev/null", os.O_RDWR)
                os.close(fd)
            except:
                self.log("Error opening/closing /dev/null: %s" % (traceback.format_exc(),))
                fd = -1
            counts = {}
            for x in threading.enumerate():
                n = x.__class__.__name__
                if isinstance(x, Primitive):
                        try:    n = x.kind
                        except: pass
                counts[n] = counts.get(n, 0)+1
            self.log("thread counts:")
            for n, c in sorted(counts.items()):
                self.log("  %-50s%d" % (n+":", c))
            
            if False:
                ocount = "object counts:"
                for cname, n in sorted(Counted.counts()):
                    ocount = ocount + f" {cname}: {n}"
                self.log(ocount)
            time.sleep(30)
            
            
if __name__ == "__main__":
    import traceback, sys, os, threading, getopt
    try:
        import logs
        from webpie import HTTPServer, HTTPSServer

        open("DataProxy.pid", "w").write("%d" % (os.getpid(),))
        
        config_file = None
        
        opts, args = getopt.getopt(sys.argv[1:], "c:d")
        opts = dict(opts)
        config_file = opts.get("-c", os.environ.get("OCTOPUS_CONFIG"))
        if not config_file:
            print("Config file must be specified either with -c or using OCTOPUS_CONFIG environment variable")
            sys.exit(1)

        config = yaml.load(open(config_file, 'r'), Loader=yaml.SafeLoader)
        debug_file = "-" if "-d" in opts else None
        if "-d" in opts or ("Debug" in config and config["Debug"]["enabled"]):
            cfg = config.get("Debug", {})
            debug_file = debug_file or cfg.get("file", "DataProxy.debug")
            debug.init(debug_file)

        print("creating DataLogger...")
        data_logger = DataLogger(config)
        monitor_file = None   
        logdir = None

        requests_logger = None
        if "Log" in config:
            cfg = config["Log"]
            if cfg.get("enabled", True):
                logdir = cfg.get("logdir", ".")
                os.makedirs(logdir, exist_ok = True)
                logs.openLogFile(logdir + "/DataProxy.log")
                logs.openErrorFile(logdir + "/DataProxy.errors")
                monitor_file = logdir + "/monitor.log"
                logs.openRequestLog(logdir + "/requests.log", data_logger)
                
        #sel = Selector()              


        scanner_detector = None
        if "ScannerDetector" in config:
            from scanner_detector import ScannerDetector
            cfg = config["ScannerDetector"]
            scanner_detector = ScannerDetector(cfg)
            print("Scanner detector created")

        print("creating DataProxy...")
        tm = DataProxy(config_file, scanner_detector, data_logger, logs.logfile, logdir)
        data_logger.start()


        gui_server = None
        gui_redirector = None
        gui_url = None

        if "WebGUI" in config:
            cfg = config["WebGUI"]
            static_location = cfg.get("static_location", "./product/static")
            log_file = cfg.get("logfile")
            if log_file:
                log_file = LogFile(log_file)
                log_file.start()
            title = cfg.get("title", "Octopus Proxy %s" % (socket.getfqdn(),))
            correlations_file = cfg.get("correlations_file")
            print("creating DataProxyWebInterface...")
            gui = DataProxyWebInterface(tm, title, data_logger, scanner_detector, static_location, correlations_file)
            port = cfg["port"]
            tls = "tls" in cfg
            logging = log_file is not None
            debug = None        # for now
            if tls:
                keyfile = cfg["tls"]["key_file"]
                certfile = cfg["tls"]["cert_file"]
                ca_file = cfg["tls"].get("ca_file")
                gui_server = HTTPSServer(port, gui, 
                    certfile, keyfile, ca_file=ca_file,
                    url_pattern = "*", max_connections = 20, max_queued = 10,
                    logging = logging, log_file=log_file, debug=debug)
                gui_url = "https://%s:%s/index" % (socket.getfqdn(), port)
            else:
                gui_server = HTTPServer(port, gui, 
                            url_pattern = "*", max_connections = 20, max_queued = 10,
                            logging = logging, log_file=log_file, debug=debug)
                gui_url = "http://%s:%s/index" % (socket.getfqdn(), port)
            print("starting HTTPServer...")
            gui_server.start()
            gui_server.kind = "GUIServer"
            
            if "redirector" in cfg:
                rport = cfg["redirector"]["port"]
                url = cfg["redirector"].get("url", gui_url)
                gui_redirector = HTTPServer(rport, Redirector(url), 
                        url_pattern = "*", 
                        max_connections = 20, max_queued = 10, logging = logging, log_file=log_file, debug=None)
                gui_redirector.kind = "GUIRedirector"
                print("starting Redirector...")
                gui_redirector.start()
                

        S = SignalHandler(signal.SIGHUP, tm)

        tm.start()

        monitor_log = LogFile("monitor.log", append=False)
        monitor_log.start()
        monitor = Monitor(tm, monitor_log)
        monitor.start()

        print("--- started ---")
        tm.join()
    except:
        print("Exception in main:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        sys.stdout.flush()
        

            
                        
                        

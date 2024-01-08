from datetime import datetime
from Version import Version
import jinja2, json, pprint
import os
import numpy as np
from webpie import WPApp, WPHandler, WPStaticHandler
from DataLogger2 import DataLogger
from dns import DNS
#from object_counter import Counted

import time

def pretty_time(t):
    if t == None:   return ""
    sign = ''
    if t < 0:   
        sign = '-'
        t = -t
    seconds = t
    if seconds < 60:
        out = '%.1fs' % (seconds,)
    elif seconds < 3600:
        seconds = int(seconds)
        minutes = seconds // 60
        seconds = seconds % 60
        out = '%sm%ss' % (minutes, seconds)
    else:
        seconds = int(seconds)
        minutes = seconds // 60
        hours = minutes // 60
        minutes = minutes % 60
        out = '%sh%sm' % (hours, minutes)
    return sign + out
   
def pretty_frequency(f):
    unit = ""
    if f > 0.0:
        unit = "/s"
        if f < 1.0:
            f = f*60.0
            unit = "/m"
            if f < 1.0:
                f = f*60.0
                unit = "/h"
        return "%.1f%s" % (f, unit)
    else:
        return ""

def host_port(addr):
    if not addr:    return ""
    ip, port = addr
    host = DNS[ip]
    return f"{ip}:{port}" if host == ip else f"{host}({ip}):{port}"
    
def time_delta(t1, t2=None):
    if not t1 or t1 == None:    return ""
    if t2 == None:  
        t1, t2 = time.time(), t1
    dt = t1 - t2
    return pretty_time(dt)
    
def dt_fmt(t):
    if not t:   return ""
    tup = time.localtime(t)
    return time.strftime("%m/%d/%y %H:%M:%S", tup)
    
def none2null(x):
    return "null" if (x is None or x == np.nan) else x

_robots_response = """User-agent: *
Disallow: /
"""

    
class Handler(WPHandler):
    
    def __init__(self, request, app):
        WPHandler.__init__(self, request, app)
        self.static = WPStaticHandler(request, app, root=app.StaticLocation, cache_ttl=60)
        self.addHandler("robots.txt", (_robots_response, "text/plain"))
        
    def service(self, req, relpath, **args):
        service = relpath
        service = self.App.Proxy.Services[service]
        queue, active = service.requests()
        history = service.connectionHistory()
        
        free_servers, busy_servers, bad_servers = service.Servers.getLists()

        return self.render_to_response("service.html", service=service,
                active_requests = active,
                queue = queue,
                history = history,
                free_servers = free_servers, busy_servers = busy_servers, 
                bad_servers = bad_servers)
        
    def request(self, req, relpath, **args):
        words = relpath.split("/",1)
        service_name, rid = words
        if service_name not in self.App.Proxy.Services:
            # redirect
            #print "service %s not found" % (service,)
            self.redirect("/index")

        #print "service %s found" % (service,)
        service = self.App.Proxy.Services[service_name]

        request = service.findRequest(rid)
        if request is None:
            self.redirect(f"/service/{service_name}")
                
        return self.render_to_response("request.html", service = service, request=request)

       
    def services(self, req, relpath, **args):
        #print "WebInterface:index()"
        lst = list(self.App.Proxy.Services.items())
        lst.sort()
        svc_to_servers = {}     # {svc_name:[vserver, vserver...]}
        for name, s in lst:
            #print "WebInterface:index:requestFrequencies()"
            frequencies = s.requestFrequencies()
            s.f1 = frequencies[0][1]
            s.f2 = frequencies[1][1]
            s.f3 = frequencies[2][1]
            s.request_count_class = ""
            if s.activeRequestCount() > s.MaxConnections/2:
                s.request_count_class = "yellow"
            if s.activeRequestCount() >= s.MaxConnections:
                s.request_count_class = "red"
            svc_to_servers[name] = self.App.Proxy.virtualServersForService(name)            
            
        #print "WebInterface:index:done"
        return self.render_to_response("services.html", services=[(s, svc_to_servers.get(n, [])) for n, s in lst])
        
    def servers(self, req, relpath, **args):
        lst = [s for p, s in sorted(self.App.Proxy.Servers.items())]
        return self.render_to_response("servers.html", servers = lst)
        
    def correlations(self, req, relpath, **args):
        """
        #
        # Data file structure:
        #
        {
            "windows": [
                    10,
                    60,
                    7200,
                    604800
                ],
            "stats": [
                {
                    "key": [
                        "/NOvACon/v2_2b/app/get",
                        "table=fardet.chan_rate_state",
                        "type=mcdata",
                        "columns=state"
                    ],
                    "stats": [
                        {
                            "hit_ratio": 0.0,
                            "hits": 0,
                            "requests": 1,
                            "window": 10
                        },
                        {
                            "hit_ratio": 0.0,
                            "hits": 0,
                            "requests": 1,
                            "window": 60
                        },
                        ...
        }
        will be converted to:
        {...
            "stats":    [
                {
                    "key": ...,
                    "stats":    {
                        10: {
                        },
                        60: {
                        },...
                    }
                }
            ]
        
        }
        """
        data_file = self.App.CorrelationsFile
        stats = windows = data = None
        if data_file:
            data = json.load(open(data_file, "r"))
            stats = sorted(data["stats"], key=lambda x:tuple(x["key"]))
            windows = sorted(data["windows"])
            for item in stats:
                s = item["stats"]
                as_dict = {d["window"]:d for d in s}
                item["stats"] = as_dict
        return self.render_to_response("correlations.html", stats=stats, windows=windows)
        
    def time_frame(self, window, t0=None, t1=None):
        now = time.time()
        w = 3600
        if window == "day": w = 3600*24
        if window == "week": w = 3600*24*7
        if t0 != None:
            t0 = int(t0)
        else:
            t0 = now - w
        if t1 != None:
            t1 = int(t1)
        else:
            t1 = now
        t0dt = datetime.fromtimestamp(t0)
        t1dt = datetime.fromtimestamp(t1)
        return now, t0, t1, t0dt, t1dt
    
    def getStats(self, prefix, window, t0, t1, columns):
        
        now, t0, t1, t0dt, t1dt = self.time_frame(window, t0, t1)
        #print("getStats: window:", window,"   now", now, "   t0:", t0, t0dt,"   t1:", t1, t1dt)
        
        wildcard_names = set()
        for cn in columns:
            name, agg = cn.split("/",1)
            if name.endswith("[*]"):
                name = name[:-3]
                wildcard_names.add(name)
        
        t, data = self.App.DataLogger.getColumns(prefix, window, t0, t1, columns)
        
        #print(data)
        
        
        #print("data[0]")
        #data = list(data)
        #for x in data[0]:
        #    print (type(x), x)
        
        out_dict = {
            "minT": t0,
            "maxT": t1
        }
        
        labels_for_names = {n:set() for n in wildcard_names}
        
        column_tags = []
        column_values = []
        for (name, label, agg), values in data.items():
            if name in labels_for_names:
                labels_for_names[name].add(label)
            column_tags.append("%s[%s]/%s" % (name, label, agg))
            column_values.append(values)

        out_dict["labels_for_names"] = {n:list(s) for n, s in labels_for_names.items()}

        out_dict["data"] = data_list = []
        # convert list of column values to list or rows as dictionaries
        data_list = []
        for i, row in enumerate(zip(*column_values)):
            row_dict = dict(zip(column_tags, row))
            row_dict['t'] = t[i]
            data_list.append(row_dict)

        out_dict["data"] = data_list
        return out_dict
        
    def server_stats(self, req, relpath, window="day", t0=None, t1=None, columns="", **args):

        port = relpath
        if not port:
            return "Port must be specified", 400
            
        port = int(port)

        if port not in self.App.Proxy.Servers:
            # redirect
            return "Not found", 404
        
        if not columns:
            return "Some columns must be specified", 400
            
        columns = columns.split(",")
        prefix = "server:%d." % (port,)
        
        out = self.getStats(prefix, window, t0, t1, columns)
        #for row in out["data"]:
        #    print(int(row["t"]), row["status.server.denied[]/count"])
        return json.dumps(out), "text/json"
        
    def server_charts(self, request, relpath, window="day", **args):
        
        port = int(relpath)
        server = self.App.Proxy.Servers[port]
        services = sorted(list(server.Services.keys()))
        bin = DataLogger.WindowToBin[window]
        return self.render_to_response("server_charts1.html", server=server, services=services, window=window, bin=bin)
        
        
    def service_stats(self, req, relpath, window="day", t0=None, t1=None, columns="", **args):

        service=relpath
        if not service:
            return "Service must be specified", 400
            
        if service not in self.App.Proxy.Services:
            # redirect
            return "Not found", 404
        
        if not columns:
            return "Some columns must be specified", 400
            
        columns = columns.split(",")
        prefix = "service:%s." % (service,)
        
        out = self.getStats(prefix, window, t0, t1, columns)
        return json.dumps(out), "text/json"
        
    def service_charts(self, req, relpath, window="day", **args):
        #print args
        service = relpath
        service = self.App.Proxy.Services[service]
        return self.render_to_response("service_charts2.html", service=service, window=window)
        
    def dashboard(self, req, relpath, window="day", **args):
        return self.render_to_response("dashboard.html", window=window)
        
    def paths(self, req, relpath, window="day", columns="", **args):
        if not columns:
            return "Some columns must be specified", 400
            
        now, t0, t1, t0dt, t1dt = self.time_frame(window)

        columns = columns.split(",")
        prefix = "global:"

        times, data = self.App.DataLogger.getColumns(prefix, window, t0, t1, columns)
        totals = {}
        for (name, label, agg), values in data.items():
            key = f"{name}[{label}]/{agg}"
            #print(name, label, agg)
            totals[key] = sum(values)
        #print("totals:", pprint.pprint(totals))
        return json.dumps({"data":totals}), "text/json"
        
    index = dashboard
    
    def scans(self, req, relpath, port=None, all="no", **args):
        all = all == "yes"
        detector = self.App.ScannerDetector
        data = []
        if port is not None:
            port = int(port)
            servers = [self.App.Proxy.Servers[port]]
        else:
            servers = [s for p, s in sorted(self.App.Proxy.Servers.items())]
        if detector is not None:
            for s in servers:
                scans = detector.scans(s.Port)[::-1]
                if not all:
                    scans = [s for s in scans if s.N > 10]
                if not scans:    scans = [None]
                data.append((s, scans))
        return self.render_to_response("scans.html", data = data, dns=DNS, detector=detector)
        
    def scan(self, req, relpath, port=None, start=None, **args):
        port = int(port)
        start = float(start)
        detector = self.App.ScannerDetector
        if detector is not None:
            for scan in detector.scans(port):
                if scan.TStart == start:
                    break
            else:
                scan = None
        if not scan:
            self.redirect(f"./scans?port={port}")
        return self.render_to_response("scan.html", scan=scan, dns=DNS)
        
    
class DataProxyWebInterface(WPApp):

    def __init__(self, proxy, title, data_logger, scanner_detector, static_location, correlations_file):
        WPApp.__init__(self, Handler)
        self.StaticLocation = static_location
        self.Proxy = proxy
        self.DataLogger = data_logger
        self.ScannerDetector = scanner_detector
        self.CorrelationsFile = correlations_file
        here = os.path.dirname(__file__)
        self.initJinjaEnvironment(
                tempdirs = [here+"/templates"],
                filters = dict([
                        ("pretty_time", pretty_time),
                        ("pretty_frequency", pretty_frequency),
                        ("host_port", host_port),
                        ("time_delta", time_delta),
                        ("dt_fmt", dt_fmt),
                        ("none2null", none2null)
                ]),
                globals = {"Version":Version, "Title":title}
        )



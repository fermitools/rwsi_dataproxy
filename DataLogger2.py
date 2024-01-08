import time, sys
from pythreader import PyThread, synchronized
from datetime import datetime
import socket
from GraphiteInterface import GraphiteInterface
from timelib import timestamp
from record import RecordDatabase
import numpy as np
from logs import Logged


class DataLogger(PyThread, Logged):

    Bins = [
        #(1.0,        60.0),
        (20.0,       3600.0),
        (300.0,      24*3600.0),
        (1800.0,     7*24*3600.0)
    ]

    WindowToBin = {
            "week": 1800.0,
            "day":  300.0,
            "hour": 20.0,
            #"minute": 1.0
        }


    def __init__(self, config):
        PyThread.__init__(self)
        Logged.__init__(self, name="DataLogger")
        self.DBFile = config.get("DataLoggerFile", None)
        self.Interval = config.get("DataLoggerInterval", 10)
        self.GraphiteInterface = None
        if config.get("Graphite"):
            self.GraphiteInterface = GraphiteInterface(config.get("Graphite"))
            self.debug("created GraphiteInterface")
        self.LastReqHistoryT = None
        self.LastGraphiteT = None
        self.DB = RecordDatabase(self.DBFile)
        self.DB.init()
        #print("DataLogger.__init__")
        self.addGlobals(["path.requests", "path.bytes.cs", "path.bytes.sc", "path.bytes"])
        
    def addService(self, name, fields):
        for bin, length in self.Bins:
            for f in fields:
                #print("addService: adding timeline:", "service:%s.%s" % (name, f), bin, length)
                self.DB.add_timeline("service:%s.%s" % (name, f), bin, length)        

    def addServer(self, port, fields):
        for bin, length in self.Bins:
            for f in fields:
                self.DB.add_timeline("server:%d.%s" % (port, f), bin, length)    
                
    def addGlobals(self, fields):
        for bin, length in self.Bins:
            for f in fields:
                self.DB.add_timeline("global:%s" % (f,), bin, length)
        
                
    def add(self, category, source=None, event=None, t=None, data=None, label="", **kv):
        #
        # category: "server" or "service" or "global"
        # source: identity of the source, e.g. port number
        #
        if event is not None:
            data_dict = {event:1.0}
        elif data is not None:
            data_dict = data
        else:
            data_dict = kv
            
        if category == "global":
            data_dict = {
                "global:%s" % (f,): v for f, v in data_dict.items()
            }
        else:
            data_dict = {
                "%s:%s.%s" % (category, source, f): v for f, v in data_dict.items()
            }
        self.DB.add(t=t, data_dict=data_dict, label=label)
        
    def logRequest(self, request):
        
        #
        # Server
        #
        t_ssl_created = t_received = 0.0
        t_start = request.RequestReaderStartTime - request.CreatedTime
        if request.RequestReaderSSLCreated:
            t_ssl_created = request.RequestReaderSSLCreated - request.RequestReaderStartTime
            if request.RequestReaderEndTime:
                t_received = request.RequestReaderEndTime - request.RequestReaderSSLCreated
        error = request.RequestReaderStatus != "ok"

        port = request.VServerPort
        data = {
                        "request.time.wait":t_start,
                        "request.time.ssl":t_ssl_created,
                        "request.time.read":t_received,
                        "request.status.all":1.0,
                        "request.status.readerror":1.0 if error else 0.0                        
        }

        self.add("server", port, data=data)
        
        if request.Received:
            nomatch = request.DispatcherStatus == "nomatch"
            ok = request.DispatcherStatus == "dispatched"
            rejected = request.VServerStatus == "rejected"
            denied = request.VServerStatus == "denied"
            data = {
                            "request.status.nomatch":1.0 if nomatch else 0.0,
                            "request.status.accepted":1.0 if ok else 0.0,
                
                            "status.server.connected": 1.0,
                            "status.server.denied": 1.0 if request.VServerStatus == "denied" else 0.0,
                            "status.server.rejected": 1.0 if request.VServerStatus == "rejected" else 0.0,
                            "status.server.nomatch": 1.0 if nomatch else 0.0,
                            "status.server.dispatched": 1.0 if ok else 0.0
            }
        
            self.add("server", port, data=data)

            if request.Dispatched:
                service_name = request.ServiceName
                self.add("server", port, label=service_name, data={"status.service":1.0})
        
                data = {
                    "request.incoming": 1.0,
                    "request.%s" % (request.ServiceAcceptStatus,): 1.0
                }
        
                if request.Started:
                    wait_t = request.TransferStartTime - request.CreatedTime
                    proc_t = request.TransferEndTime - request.TransferStartTime
                    data.update(dict(
                        wait_time=wait_t, process_time=proc_t, 
                        bytes_client_to_server=request.BytesClientToServer, bytes_server_to_client=request.BytesServerToClient,
                        data_size=request.ByteCount)
                    )

                self.add("service", service_name, t=request.TransferEndTime, data = data)
                if request.HTTPStatus is not None:
                    self.add("service", service_name, t=request.TransferEndTime, event="request.status", label="%d" % ((request.HTTPStatus//100)*100,))

        #
        # global
        #
        server_error = service_error = ""
        service = request.ServiceName or ""
        if not request.Dispatched:
            server_error = request.RequestReaderStatus if request.RequestReaderStatus != "ok" else request.DispatcherStatus
        if request.ServiceAcceptStatus != "queued":
            service_error = request.ServiceAcceptStatus 

        worker = ""
        if request.ServerAddress:
            wname, wport = request.ServerAddress
            worker = "%s:%s" % (wname or "", wport or "") 

        path = "%d/%s/%s/%s/%s/%s" % (request.VServerPort, server_error, service, service_error, worker, request.HTTPStatus or "")
            
        self.add("global", label = path, data = {
            "path.requests":      1.0,
            "path.bytes.cs":      float(request.BytesClientToServer),
            "path.bytes.sc":      float(request.BytesServerToClient),
            "path.bytes":         float(request.ByteCount)
        })
        
    def getColumns(self, prefix, window, t0, t1, columns):
        #print("DataLogger.getColumns: columns:", columns)
        #
        # columns: list containing column specifications:
        #    name/agg - same as name[+]/agg - default label
        #    name[label]/agg - aggregated values for specified label
        #    name[*]/agg - aggregated columns for all label values, by label
        #
        # returns:
        #   time column, data_dict
        #       data_dict:  { (name, label, agg): values } - name does not contain the prefix
        #
        
        bin = self.WindowToBin[window]
        
        prefixed_specs = []
        
        for c in columns:
            label = ""
            name, agg = c.split("/", 1)
            if '[' in name:
                name, label = name.split('[',1)
                assert label[-1] == ']'
                label = label[:-1]
            prefixed_specs.append((prefix+name, label, agg))
        
        t, data = self.DB.aggregates(prefixed_specs, bin, t0, t1)
        out_dict = { 
                (name[len(prefix):] if name.startswith(prefix) else name, label, agg): 
                values 
                for (name, label, agg), values in data.items()
        }
        return t, out_dict
        
        
    def getDataForService(self, service, window, t0, t1, columns):
        prefix = "service:%s." % (service,)
        return self.getColumns(prefix, window, t0, t1, columns)

    def getDataForServer(self, port, window, t0, t1, columns):
        prefix = "server:%d." % (port,)
        return self.getColumns(prefix, window, t0, t1, columns)
        

    @synchronized
    def getCurrentData(self, svc):
        frequencies = svc.requestFrequencies()
        f1 = frequencies[0][1]
        f2 = frequencies[1][1]
        f3 = frequencies[2][1]
        return (f1, f2, f3,
                svc.AvgWaitT, svc.MaxWaitT,
                svc.AvgProcT, svc.MaxProcT,
                svc.activeRequestCount(), svc.queueCount())

    def sendStatsToGraphite(self, proxy):
        if self.GraphiteInterface:
            lst = []
            now = time.time()
            now_round = int(now/60)*60
            data = {}
            for name, svc in proxy.Services.items():
                if not svc.SendToGraphite:  continue
                #print("sendStatsToGraphite:", name)
                f1, f2, f3, awt, mwt, apt, mpt, acount, qcount = self.getCurrentData(svc)
                d = dict(
                        ActiveCount = acount,
                        QueueCount = qcount
                    )
                for k, v in d.items():
                    data["%s.%s" % (svc.GraphiteSuffix, k)] = v
                #print "Last T =", self.LastReqHistoryT
                request_history = svc.getRequestHistory(self.LastReqHistoryT, now_round)
                #print len(request_history)
                counts = self.aggregateRequestHistory(request_history, 60)
                for t, avg_wt, max_wt, avg_pt, max_pt, requests, bytes_sent, bytes_received, data_size in counts:
                    self.GraphiteInterface.feedData(t, "%s.RequestCount" % (svc.GraphiteSuffix,), float(requests)/60.0) 
                    self.GraphiteInterface.feedData(t, "%s.BytesSent" % (svc.GraphiteSuffix,), float(bytes_sent)/60.0) 
                    self.GraphiteInterface.feedData(t, "%s.BytesReceived" % (svc.GraphiteSuffix,), float(bytes_received)/60.0) 
                    self.GraphiteInterface.feedData(t, "%s.AverageProcessTime" % (svc.GraphiteSuffix,), avg_pt) 
                    self.GraphiteInterface.feedData(t, "%s.MaxProcessTime" % (svc.GraphiteSuffix,), max_pt) 
                    self.GraphiteInterface.feedData(t, "%s.AverageWaitTime" % (svc.GraphiteSuffix,), avg_wt) 
                    self.GraphiteInterface.feedData(t, "%s.MaxWaitTime" % (svc.GraphiteSuffix,), max_wt) 
            self.GraphiteInterface.send_dict(data)
            #print "Sent data to Graphite:", data
            self.GraphiteInterface.flushData()
            self.LastReqHistoryT = now_round
            

    def aggregateRequestHistory(self, data, agg_interval = 60):
        # data: [(t, wait_time, process_time, http_status,  received_count, sent_count, data_size), ...]
        # return: [(t1, avg_wait_time, max_wait_time, avg_process_time, max_process_time, request_count, bytes_sent, bytes_received, data_size), ...]
        # include (t1, None, None, ...) when data is missing
        # assumes data is ordered by t

        if not data:  return []
        summary = []        # ([(t, request count, bytes sent, bytes received), ...]
        requests = 0
        bytes_sent = 0
        bytes_received = 0
        data_size = 0
        sum_wt = 0.0
        sum_pt = 0.0
        max_pt = 0.0
        max_wt = 0.0
        t0 = data[0][0]
        t0 = int(t0/agg_interval)*agg_interval
        interval_begin = t0
        interval_end = t0 + agg_interval
        for t, wt, pt, http_s, rcnt, scnt, bcnt in data:
            if t < interval_begin:  continue
            while t >= interval_end:
                # close this interval
                if requests > 0:
                    avg_wt = sum_wt/requests
                    avg_pt = sum_pt/requests
                else:
                    avg_wt = None
                    avg_wt = None
                    max_pt = None
                    avg_pt = None
                summary.append((interval_end, avg_wt, max_wt, avg_pt, max_pt, requests, bytes_sent, bytes_received, data_size))
                requests = 0
                bytes_sent = 0
                bytes_received = 0
                data_size = 0
                sum_wt = 0.0
                sum_pt = 0.0
                max_pt = 0.0
                max_wt = 0.0
                interval_begin = interval_end
                interval_end = interval_begin + agg_interval
            requests += 1
            sum_wt += wt
            sum_pt += pt
            bytes_sent += scnt
            bytes_received += rcnt
            data_size += bcnt
            max_wt = max(max_wt, wt)
            max_pt = max(max_pt, pt)

        if requests > 0:
            avg_wt = sum_wt/requests
            avg_pt = sum_pt/requests
            summary.append((interval_end, avg_wt, max_wt, avg_pt, max_pt, requests, bytes_sent, bytes_received, data_size))
            
            
        return summary

    def run(self):
        self.DB.start()
        while 1:
            time.sleep(self.Interval)
            
                    
        

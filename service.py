from pythreader import synchronized, TaskQueue, Task, Primitive
from debug import Debugged
from logs import Logged
from iptable import IPTable
from server_list import HashedServerList, ServerList
from record import TimeWindow
import time, threading, traceback, socket, sys, fnmatch
from HTTPProxy2 import HTTPProxy
from py3 import to_bytes, PY3


if PY3:
    from urllib.request import urlopen
else:
    from urllib2 import urlopen


class Transfer(Task, Debugged, Logged):
    
    def __init__(self, request, service):
        Task.__init__(self)
        self.Request = request
        rid = request.Id
        Debugged.__init__(self, f"[{rid} transfer]")
        Logged.__init__(self, name=f"[{rid} transfer]")
        self.Service = service
    
    def chooseServer(self, request, server_list):
        probe = self.Service.Probe
        servers = server_list.snapshot(request.HTTPRequest.URI)

        for i, server in enumerate(servers):
            address = server.address()
            host, port = address
            if probe:
                    url = "http://%s:%s%s" % (host, port, probe)
                    #self.debug("Trying probe: %s, probe_timeout=%s" % (url,self.Service.ProbeTimeout))
                    try:    urlopen(url, None, self.Service.ProbeTimeout)
                    except:
                        exctype, excvalue = sys.exc_info()[:2]
                        #self.debug("probe failed: %s, probe_timeout: %s, error:%s %s" % (
                        #        url, self.Service.ProbeTimeout, exctype, excvalue))    
                        server_list.mark_bad(server)
                        continue

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                    #self.debug("Connecting to %s:%s ..." % address)
                    s.settimeout(self.Service.TransferTimeout)  
                    s.connect(address)
                    s.settimeout(None)
            except:
                    exctype, excvalue = sys.exc_info()[:2]
                    self.debug("connection failed: %s %s" % (exctype, excvalue))
                    s.close()
                    continue
            #self.debug("connected to %s:%s" % address)
            server_list.allocate(server)
            return s, server
        else:
            #self.debug("can not find available server")
            return None, None

    def run(self):
        request = self.Request
        rid = request.Id
        
        csock = request.CSock
        
        request.Started = True
        request.TransferStartTime = time.time()
    
        #self.debug("Started in thread: %s" % (threading.current_thread().name,))
    
        # get request 
        
        server_list = self.Service.Servers
        ssock, server = self.chooseServer(request, server_list)
        request.ConnectedToWorkerTime = time.time()
        
        #mb = ['8'*1024*1024 for _ in range(10)]
        
        error = None
        if not ssock:
            self.debug("No server available")
            error = "Can not find available server"
            csock.sendall(to_bytes("HTTP/1.1 503 No server available\n\n"))
            request.close(False)
        else:
            saddr = server.address()
            self.debug("connected to: %s:%s" % saddr)
            
            request.ServerAddress = saddr

            proxy = HTTPProxy(request, ssock, transfer_timeout = self.Service.TransferTimeout)
            #self.Proxy = proxy
            ok, error, cs_bytes, sc_bytes = proxy.run()
            
            request.BytesServerToClient = sc_bytes
            request.BytesClientToServer = cs_bytes
            #self.debug("HTTP proxy ok: %s, error message: %s" % (ok, error or ""))
            if ok:
                if proxy.Method.upper() in ("PUT", "POST"):
                    request.ByteCount = cs_bytes
                else:
                    request.ByteCount = sc_bytes
            else:
                request.ByteCount = max(cs_bytes, sc_bytes)
            request.TransferFailed, request.Error = not ok, error
            request.HTTPStatus = proxy.HTTPStatus
            server_ok = request.HTTPStatus and request.HTTPStatus/100 != 5
            server_list.release(server, server_ok)
            request.close(True)
        return request

class Service(Primitive, Debugged, Logged):
    
    #
    # Note on URI rewriting
    # ---------------------
    # URL rewriting will not work with keep-alive sockets with digest authentication because
    # First request will contain a URI to be rewritten and then subsequent request
    # with proper authentication headers will have same URI, but it will have to be
    # rewritten again. So to implement URI rewriting, we would need to really get into
    # all the details of HTTP protocol
    #


    LoggerFields = ["request.incoming", "request.rejected", "request.queued", "request.denied", "request.status",
                    "wait_time", "process_time", 
                    "active_connections", "queued_connections",
                    "bytes_client_to_server", "bytes_server_to_client", "data_size"                    
                ]
                
    def __init__(self, mgr, data_logger, name,
                max_connections, max_frequency, backlog, servers, 
                probe, probe_timeout, match, transfer_timeout,
                server_discipline, access, remove_prefix, add_prefix,
                graphite_suffix = None):
        Logged.__init__(self, mgr.LogTo)
        self.ServiceName = name
        Primitive.__init__(self, name=f"[Service {name}")
        Debugged.__init__(self)
        self.Match = match
        self.RewriteURI = None  # see note about URL rewriting  # rewrite_uri   # tuple: ("old_head", "new_head") or None
        self.Manager = mgr
        self.MaxConnections = max_connections
        self.MaxFrequency = max_frequency
        self.Backlog = backlog

        stagger = 1.0/max_frequency if max_frequency else None

        self.TransferQueue = TaskQueue(self.MaxConnections, capacity=self.Backlog, name=f"[Service Queue {name}]", delegate=self,
            stagger = stagger)

        self.ServerDiscipline = server_discipline
        self.Servers = (HashedServerList(servers) if server_discipline == "hash" 
                                            else ServerList(servers))
        self.Probe = probe
        self.ProbeTimeout = probe_timeout
        self.TransferTimeout = transfer_timeout
        if self.TransferTimeout != None:  self.TransferTimeout = float(self.TransferTimeout)
        #self.debug("Service created: %s, %s, %s, pt=%s, tt=%s, %s" % 
        #        (name, max_connections, probe, probe_timeout, self.TransferTimeout, servers))
        self.Access = access
        self.RemovePrefix = remove_prefix
        self.AddPrefix = add_prefix
                
        self.TimeWindows = (TimeWindow(10.0),TimeWindow(180.0),TimeWindow(3600.0))

        self.TransferHistory = []
        self.DataLogger = data_logger
        
        self.Enabled = True
        self.GraphiteSuffix = graphite_suffix
        self.SendToGraphite = graphite_suffix != None
        
        self.AvgWaitT = None
        self.MaxWaitT = None
        self.AvgProcT = None
        self.MaxProcT = None
        
        self.RequestHistory = []
        
    def listServers(self):
        return self.Servers.snapshot("", rotate = False)

    @staticmethod
    def create(mgr, data_logger, cfg):
        #print "Service.create: cfg=", cfg
        servers = []
        for url in cfg['servers']:
                host, port = tuple(url.split(':'))
                servers.append((host, int(port)))

        access_table = IPTable(config = cfg.get("access", {}))
        s = Service(mgr, data_logger, cfg['name'], 
                cfg.get('max_connections', 10), 
                cfg.get('max_frequency'), 
                cfg.get('queue', 10),
                servers, cfg.get('probe', None),
                cfg.get('probe_timeout', 10), 
                cfg.get('match', '*'),
                cfg.get('transfer_timeout', 30),
                cfg.get('server_selection', "round-robin"),    # or "hash"
                access_table, cfg.get("remove_prefix"), cfg.get("add_prefix"),
                cfg.get('graphite_suffix', None)
        )
        return s
        
    def requests(self):
        queue, active = self.TransferQueue.tasks()
        return [t.Request for t in queue], [t.Request for t in active]
        
    def connectionHistory(self):
        return self.TransferHistory
        
    def reconfigure(self, cfg):
        self.Match = cfg.get('match','*')
        self.MaxConnections = cfg.get('max_connections', 10)
        self.Backlog = cfg.get('queue', 10)
        new_servers = []
        for url in cfg['servers']:
            host, port = tuple(url.split(':'))
            new_servers.append((host, int(port)))
        self.Servers = ServerList(new_servers)
        self.Probe = cfg.get('probe', None)
        self.ProbeTimeout = cfg.get('probe_timeout',10)
        self.TransferTimeout = cfg.get('transfer_timeout',30)
        self.GraphiteSuffix = cfg.get('graphite_suffix', None)
        self.SendToGraphite = not not self.GraphiteSuffix

    def __str__(self):
        return "[Service %s]" % (self.ServiceName,)

    #def log(self, msg):
    #    self.Manager.log("%s: %s" % (self, msg))

    def acceptRequest(self, request):
        rid = request.Id
        http_request = request.HTTPRequest
        
        match_with_slash = self.Match if self.Match.endswith('/') else self.Match + "/"
        match = \
            http_request.Path == self.Match \
            or http_request.Path.startswith(match_with_slash) \
            or fnmatch.fnmatch(http_request.Path, self.Match)
        
        if not match:  return False
        
        request.ServiceName = self.ServiceName

        port = request.VServerPort
        sock = request.CSock
        addr = request.ClientAddress
        body = request.Body
        
        method = http_request.Method
        uri = http_request.URI
        
        #self.debug("request %s path %s matched pattern %s" % (request.Id, http_request.Path, self.Match))
        
        accepted = False
        
        if self.Access.deny(addr[0]):
            self.log("[%s] %s:%s - denied" % (http_request.headline(), addr[0], addr[1]))
            sock.sendall(to_bytes("HTTP/1.1 403 Access denied\n\n"))
            request.ServiceAcceptStatus = "denied"
            request.Error = "access denied"
        else:
            if self.RemovePrefix is not None and uri.startswith(self.RemovePrefix):
                saved = uri
                uri = uri[len(self.RemovePrefix):]
                if self.AddPrefix is not None:
                    uri = self.AddPrefix + uri
                http_request.replaceURI(uri)
                self.debug("URI rewritten from: [%s] to: [%s]" % (saved, uri))
            now = time.time()
            for tw in self.TimeWindows: tw.add(now)
            self.DataLogger.add("service", self.ServiceName, event="request.incoming")
            try:
                self.TransferQueue.addTask(Transfer(request, self), timeout = 0)
                accepted = True
                request.ServiceAcceptStatus = "queued"
            except RuntimeError:
                sock.sendall(to_bytes("HTTP/1.1 503 Server unavailable. Retry later\n\n"))
                request.ServiceAcceptStatus = "rejected"
                self.log("[%s] %s:%s - rejected: queue is full" % (http_request.headline(), addr[0], addr[1]))
                self.RequestHistory.append((now, 0.0, 0.0, 503, 0, 0, 0))
                request.Error = "service is busy"
                
        self.debug(f"{rid}: accept status: {request.ServiceAcceptStatus}")
        #nqueued, nrunning = self.TransferQueue.counts()
        #self.debug(f"{rid}: queue counts: {nqueued}, {nrunning}")
            
        return True     # tell the dispatcher that the request was handled
        
    def logRequest(self, request):

        self.log_request(request)
        
        http_request = request.HTTPRequest
        addr = request.ClientAddress
        headline = (http_request.headline() or '').strip()
        if request.ServiceAcceptStatus != "queued":
            self.DataLogger.add("service", self.ServiceName, event="request.%s" % (request.ServiceAcceptStatus,))

        wait_t = request.TransferStartTime - request.CreatedTime
        proc_t = request.TransferEndTime - request.TransferStartTime
        t_created, t_started, t_complete = request.CreatedTime, request.TransferStartTime, request.TransferEndTime
        self.DataLogger.add("service", self.ServiceName, t=t_complete, 
            wait_time=wait_t, process_time=proc_t, 
            bytes_client_to_server=request.BytesClientToServer, bytes_server_to_client=request.BytesServerToClient,
            data_size=request.ByteCount)
    
        if request.HTTPStatus is not None:
            self.DataLogger.add("service", self.ServiceName, event="request.status", label="%d" % ((request.HTTPStatus//100)*100,))
            
        self.DataLogger.recordRequest(request)        
        
            
    def currentQueueWaitTime(self):
        queue = self.TransferQueue.waitingTasks()
        if not queue:
            return 0.0
        return time.time() - queue[0].Created
        
    def currentProcessTime(self):
        maxt = None
        active = [c for c in self.TransferQueue.activeTasks() if c.Started is not None]
        if active:
            now = time.time()
            maxt = max([now - c.Started for c in active])
        return maxt  


    def activeRequestCount(self):
        return self.TransferQueue.nrunning()
        
    def queueCount(self):
        return self.TransferQueue.nwaiting()

    def requestFrequencies(self):
        ret = []
        for tw in self.TimeWindows:
            ret.append((tw.Length, tw.frequency()))
        return ret
        
    def tick(self):
        queued_connections, active_connections = self.TransferQueue.counts()
        self.DataLogger.add("service", self.ServiceName,
            active_connections = active_connections,
            queued_connections = queued_connections)

    def findRequest(self, rid):
        tasks1, tasks2 = self.TransferQueue.tasks()
        for t in tasks1 + tasks2:
            r = t.Request
            if r.Id == rid:
                return r
        for r in self.TransferHistory:
            if r.Id == rid:
                return r
        #print "%s not found" % (cid,)
        return None


    @synchronized    
    def getRequestHistory(self, t0, t1):
        out = [x for x in self.RequestHistory[:]
            if (t0 is None or x[0] >= t0) 
                and (t1 is None or x[0] < t1)
        ]
        #print("%s.getRequestHistory(): len=%d" % (ServiceName, len(out)))
        return out
        
    @synchronized
    def purgeRequestHistory(self, delta):
        # delete stats older than t0
        now = time.time()
        t0 = now - delta*2
        t1 = now - delta
        t_oldest = self.RequestHistory[0][0]      # timestamp of the oldest record
        if t_oldest < t0:
            self.RequestHistory = list(filter( lambda tup, t0=t0: tup[0] >= t1, 
                                    self.RequestHistory ))
                
    @synchronized
    def shutdown(self):
        self.Shutdown = True
        

    #
    # Task Queue delegate methods
    #
    
    CONNECTION_HISTORY_SIZE = 200
    def requestEnded(self, request):
        self.TransferHistory.insert(0, request)
        self.TransferHistory = self.TransferHistory[:self.CONNECTION_HISTORY_SIZE]
        self.log_request(request)
        
    def taskEnded(self, queue, task, request):
        request.TransferStartTime = task.Started
        request.TransferEndTime = task.Ended
        self.requestEnded(request)
        rid = request.Id
        #self.debug(f"{rid} transfer ended")
            
    def taskFailed(self, queue, task, exc_type, exc_value, tb):
        request = task.Request
        request.TransferStartTime = task.Started
        request.TransferEndTime = task.Ended
        self.requestEnded(request)
        rid = request.Id
        info = f"Request {rid} failed:\n" + ("".join(traceback.format_exception(exc_type, exc_value, tb)))
        self.errorLog(info)
        self.debug(info)


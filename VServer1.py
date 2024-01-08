import yaml, socket, time, fnmatch, signal, select, sys, traceback
from datetime import datetime, timedelta
from pythreader import TaskQueue, Task, PyThread, synchronized, Primitive            #, printWaiting
from History import HistoryWindow
from py3 import to_bytes, to_str, PY3
from logs import Logged, format_server_log
from HTTPHeader import HTTPHeader
from iptable import IPTable
from record import TimeWindow
from uid import uid
from request import Request
from dns import DNS

class RequestDispatcher(Logged):
    
    def __init__(self, services):
        Logged.__init__(self, name = "[RequestDispatcher]")
        self.Services = services
        
    def dispatch(self, request):
        # loop over services to find first match
        # once the match is found, add the request
        # if failed, return error

        # status:
        #   ok
        #   nomatch     - service not found
        for service in self.Services:
            if service.acceptRequest(request):
                request.Dispatched = True
                request.DispatcherStatus = "dispatched"
                request.ServiceName = service.ServiceName
                return service
        else:
            request.Dispatched = False
            request.DispatcherStatus = "nomatch"
            return None

class RequestReaderTask(Task, Logged):
    
    def __init__(self, request, vserver, dispatcher):
        Task.__init__(self)
        self.Request = request
        self.Id = request.Id
        self.VServer = vserver
        Logged.__init__(self, name = f"[%s request reader]" % (self.Id,), logger=self.VServer)
        self.Dispatcher = dispatcher
    
    def run(self):
        request = self.Request
        rid = request.Id
        #self.debug("started processing request")
        request.RequestReaderStartTime = time.time()
        error = None
        sock = request.CSock
        if self.VServer.TLS:
            request.CSock = sock = self.VServer.wrap_socket(sock)
            if sock is None:
                request.close(False)
                return request # TLS wrapper failed
            request.RequestReaderSSLCreated = time.time()

        #self.debug("wrapped socket: %s, timeout:%s, dir:%s" % (sock, sock.timeout, dir(sock)))
        http_status = None
        received = False
        http_request = HTTPHeader()
        body = b''
        sock_saved_timeout = sock.timeout
        sock.settimeout(10.0)
        error = None
        reader_status = "ok"
        try:
            while not received and not error:
                #self.debug(f"{rid}: loop...")
                data = b""
                try:    
                    data = sock.recv(1000)
                    #self.debug(f"data:{data}")
                except socket.timeout:
                    error = "Time-out while reading the request headline"
                    reader_status = "timeout"
                    http_status = 400
                    break
                except:
                    error = "Error reading header: %s %s" % sys.exc_info()[:2]
                    reader_status = "exception"
                    http_status = 400
                    break
                
                if not data:    
                    error = 'Socket closed while reading the request headline' 
                    reader_status = "disconnected"
                    http_status = 400
                    break
                
                try:    
                    received, body = http_request.consume(data)
                except:
                        error = "Error parsing HTTP request"
                        reader_status = "error"
                        http_status = 400
                        break
        finally:
            sock.settimeout(sock_saved_timeout)
            
        request.RequestReaderStatus = reader_status
        
        if received:
            request.Received = True
            headline = http_request.headline()
            self.debug(f"Request received: {headline}")
            body_length = len(body)
            dispatched = False
            request.Body = body
            request.RequestReaderStatus = "ok"
            request.HTTPRequest = http_request
            
            if self.VServer.check_scanner(request) and False:           # pass request to the detector, but do never block it
                error = "Scanner detected"
                http_status = 403
            else:    
                service = self.Dispatcher.dispatch(request)        
                if not service:
                    self.log("not found:", http_request.URI)
                    error = "Service not found"
                    http_status = 404

        if not request.Dispatched:
            request.Error = error
            request.HTTPStatus = http_status
            self.debug(f"senfing HTTP error: {http_status} {error}")
            try:    sock.sendall(to_bytes("HTTP/1.1 %s %s\n\n" % (http_status, error)))
            except: pass
            request.Failed = True
            request.close(False)
            #self.VServer.recordRequest(request)
            
        return request
        
class VirtualServer(PyThread, Logged):
    
    LoggerFields = [
        "status.server.connected", "status.server.rejected", "status.server.denied",
        "status.server.nomatch", "status.server.dispatched",
        "status.service",
        "request.time.wait", "request.time.ssl","request.time.read",
        "request.status.readerror", "request.status.all", "request.status.nomatch", "request.status.accepted",
        "queue.waiting", "queue.active"
    ]
    
    def __init__(self, services, scanner_detector, data_logger, config):
        self.Port = int(config["Port"])
        PyThread.__init__(self, name="VServer %d" % (self.Port,))
        Logged.__init__(self, name="[VServer %s]" % (self.Port,), 
            log_channel=f"server({self.Port}).log",
            error_channel=f"server({self.Port}).errors",
            )
        self.Config = config
        self.Services = {}          # {name:Service}
        self.ServicesList = []      # [Service] - for ordered URL match lookup
        self.TLS = self.Config.get("TLS",{}).get("enabled", False)
        self.Timeout = self.Config.get("timeout", 5)
        self.DataLogger = data_logger
        self.ScannerDetector = scanner_detector
        
        self.TimeWindows = (TimeWindow(10.0),TimeWindow(180.0),TimeWindow(3600.0))
        
        if self.TLS:
            import ssl
            self.log("tls enabled")
            tlsconfig = self.Config["TLS"]
            self.CertFile = tlsconfig["cert"]
            self.KeyFile = tlsconfig["key"]
            self.CABundle = tlsconfig.get("ca_bundle")
            self.TLSMode = {
                "none":         ssl.CERT_NONE,
                "optional":     ssl.CERT_OPTIONAL,
                "required":     ssl.CERT_REQUIRED
            }[tlsconfig.get("verification", "optional")]
            self.SSLContext = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
            self.SSLContext.load_cert_chain(self.CertFile, self.KeyFile)
            self.SSLContext.load_verify_locations(cafile = self.CABundle)
            self.SSLContext.verify_mode = self.TLSMode
            self.SSLContext.load_default_certs()

        self.ConnectionHistory = HistoryWindow(600)         # (service, error, error_type)     
        self.HistorySnapshotT = None  

        self.Backlog = self.Config.get("backlog", 5)

        self.TimeWindowsByService = {}
        for sname in config['Services']:
            s = services[sname]
            self.Services[sname] = s
            self.ServicesList.append(s)
            self.TimeWindowsByService[sname] = (TimeWindow(10.0),TimeWindow(180.0),TimeWindow(3600.0))

        self.Dispatcher = RequestDispatcher(self.ServicesList)
        
        max_readers = config.get("max_readers", 10)
        queue_capacity = config.get("queue", 10)
        put_timeout = config.get("timeout", 300)
        stagger = None
        max_frequency = config.get("max_frequency")
        if max_frequency is not None:
            max_frequency = float(max_frequency)
            if max_frequency > 0.0:
                stagger = 1.0/max_frequency
        self.ReaderQueue = TaskQueue(max_readers, capacity=queue_capacity, delegate=self, stagger=stagger,
            name=f"RequestReaderQueue {self.Port}")

        self.Access = IPTable(config = self.Config.get("access", {}))
        self.Shutdown = False

        self.kind = "[server %s]" % (self.Port,)
        self.debug("created")
        
    def wrap_socket(self, sock):
        if not self.TLS:
            return sock
        try:    
            sock.settimeout(self.Timeout)
            tls_sock = self.SSLContext.wrap_socket(sock, server_side=True)
        except Exception as e:
            #self.error("TLS error in wrap_socket: %s: %s" % (addr, e))
            self.debug("TLS error in wrap_socket: %s" % (e,))
            self.ConnectionHistory.add(data=(None, True, "ssl"))
            try:
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
            except:
                pass
            return None
        else:
            #print "Client cert: %s" % (tls_sock.getpeercert(),)
            self.debug("TLS socket created")
            return tls_sock

    def run(self):
        self.log("----- started -----")
        self.Sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.Sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:    self.Sock.bind(('', self.Port))
        except Exception as exc:
            print("Can not bind to port %d: %s" % (self.Port, exc))
            raise
        self.Sock.listen(self.Backlog)
        while not self.Shutdown:
            try:
                sock, addr = self.Sock.accept()
                self.DataLogger.add("server", self.Port, event="status.server.connected")
                now = time.time()
                for w in self.TimeWindows:
                    w.add(now)
                
                request = Request(sock, addr, self.Port)
                submitted = False
                rid = request.Id
                
                host = DNS[addr[0]]
                
                self.debug("%s: connection accepted from: %s(%s):%s" % (rid, host, addr[0], addr[1]))
                if self.Access.deny(addr[0]):
                    request.Failed = True
                    request.VServerStatus = "denied"
                    self.debug("%s: denied access for %s" % (rid, addr[0]))
                else:
                    try:
                        self.ReaderQueue.addTask(RequestReaderTask(request, self, self.Dispatcher))
                        #self.debug(f"request {request.Id} sent to the request reader")
                        request.RequestReaderQueuedTime = time.time()
                        submitted = True
                    except RuntimeError:
                        request.VServerStatus = "rejected"       # a.k.a. full
                        try:
                            self.debug("%s: header reader queue full" % (rid,))
                            sock.sendall(to_bytes("HTTP/1.1 503 Service unavailable -- Virtual server request queue is full\n\n"))
                        except:
                            pass
                        self.ConnectionHistory.add(data=(None, True, "header queue full"))
                if not submitted:
                    if request.Received:
                        self.DataLogger.logRequest(request)
                    request.close(False)
            except:
                sys.stderr.write("%s: Uncaught exception in VServer(port=%d) main loop: %s\n" % (rid, self.Port, traceback.format_exc()))

        self.Sock.close()
        self.RequestReader.close()
        self.RequestReader.join()
        self.DataLogger = None
        
    def check_scanner(self, request):
        if self.ScannerDetector is not None:
            self.ScannerDetector.check_for_scanner_request(self.Port, request.ClientAddress[0], request.HTTPRequest.OriginalURI)
        return False
        
    def log_request(self, request):
        log_line = format_server_log(request)
        self.log(log_line)

    #
    # Task queue delegate interface
    #
    def taskEnded(self, queue, task, request):
        request.RequestReaderQueuedTime = task.Queued
        request.RequestReaderStartTime = task.Started
        request.RequestReaderEndTime = task.Ended
        request.VServerError = request.Error
        self.log_request(request)

    def taskFailed(self, queue, task, exc_type, exc_value, tb):
        request = task.Request
        rid = request.Id
        request.RequestReaderQueuedTime = task.Queued
        request.RequestReaderStartTime = task.Started
        request.RequestReaderEndTime = task.Ended
        request.VServerError = request.Error
        self.log_request(request)
        info = f"Request {rid} failed:\n" + ("".join(traceback.format_exception(exc_type, exc_value, tb)))
        self.error(info)

    def tick(self):
        nwaiting, nactive = self.ReaderQueue.counts()
        self.DataLogger.add("server", self.Port,
            data = {
                "queue.waiting": nwaiting,
                "queue.active": nactive
            }
        )
        
    @synchronized
    def requestFrequencies(self, sname=None):
        windows = self.TimeWindows if sname is None else self.TimeWindowsByService[sname]
        return [(w.Length, w.frequency()) for w in windows]

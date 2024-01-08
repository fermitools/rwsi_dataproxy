from pythreader import PyThread, synchronized, Primitive
from logs import Logged
import sys, select, os, socket, traceback
from py3 import to_bytes, to_str, PY3
from HTTPHeader import HTTPHeader
import errno

class HTTPReader(Logged):
    
    def __init__(self, sock, my_name, header_received=False, nbytes=0):
        self.Header = None
        self.HeaderReceived = header_received
        self.Sock = sock
        self.ByteCount = nbytes
        self.EOF = False
        Logged.__init__(self, name=my_name)

    MAXREAD = 1000000
        
    def read(self):
        try:    data = self.Sock.recv(self.MAXREAD)
        except socket.timeout:
            #self.debug("timeout")
            data = b''
        except Exception as e: 
            self.debug("reader error: %s" % (e,))
            data = b''
        #self.debug("data received: %s" % (repr(data),))
        if not data:
            self.EOF = True
            #self.debug("EOF, self.EOF: %s" % (self.EOF,))
            yield b''  
        elif self.HeaderReceived:
            self.ByteCount += len(data)
            #self.debug("body")
            yield data             # body
        else:
            if self.Header is None: self.Header = HTTPHeader()
            complete, rest = self.Header.consume(data)
            #self.debug("header.consume -> %s, %s" % (complete, rest))
            if complete:
                self.HeaderReceived = final = self.Header.is_final()
                yield self.Header
                self.Header = None
                if rest:    
                    self.ByteCount += len(rest)
                    yield rest
            else:
                assert not rest

class HTTPPeer(PyThread, Logged):

    MAXMSG = 1000
    
    S_OK = "OK"
    S_EOF = "EOF"
    S_ERROR = "ERROR"
    S_TIMEOUT = "TIMEOUT"
    S_SHUTDOWN = "SHUTDOWN"

    def __init__(self, proxy, my_name, fsock, tsock, timeout=None, request_received=False):
        PyThread.__init__(self, daemon=True)
        self.MyName = my_name
        Logged.__init__(self, name = self.MyName)
        self.FSock = fsock
        self.TSock = tsock
        self.Proxy = proxy
        self.DataByteCount = 0
        self.ContentsLength = None
        self.Timeout = timeout

        self.RequestReceived = request_received
        self.FinalHeaderReceived = False

        self.ErrorMessage = ""
        self.ExitStatus = self.S_OK

        self.EOF = False
        self.Shutdown = False
        self.Error = False
        self.kind = "HTTPPeer"
        
    def shutdown(self):
        self.Shutdown = True

    def _____sendall(self, data):
        #self.debug("sendall(%d bytes: %s)" % (len(data), repr(data[-10:])))
        while data:
            #self.debug("sendall: sending %d bytes..." % (len(data),))
            n = self.TSock.send(data)
            #self.debug("sent %d bytes" % (n,))
            data = data[n:]

    def run(self):

        saved_timeout = self.FSock.gettimeout()
        if self.Timeout is not None:
            self.FSock.settimeout(self.Timeout)
            
        exit_status = self.S_OK
        error_message = None

        try:
            reader = HTTPReader(self.FSock, self.MyName + "/reader", header_received = self.RequestReceived)
            while not reader.EOF and not self.Shutdown:
                #self.debug("calling reader.read()...")
                for item in reader.read():
                    forward = item
                    ndata = 0
                    if isinstance(item, HTTPHeader):
                        self.Proxy.headerReceived(item)
                        forward = item.as_bytes() + b"\r\n"
                    else:
                        ndata = len(item)
                        #self.debug("received %d bytes of data" % (ndata,))
                        #self.debug("sending %d bytes of body. total bytes: %d" % (ndata, self.DataByteCount))
                    if forward:
                        try:    
                            #self.debug(">> [%s]" % (to_str(forward),))
                            self.TSock.sendall(forward)
                        except Exception as exc:
                            self.debug("Error sending %d bytes to peer: %s" % (len(forward), exc))
                            raise
                    self.DataByteCount += ndata
                    if reader.EOF:  
                        self.debug("EOF")
                        exit_status = self.S_EOF
            #self.debug("exit from while loop. EOF=%s, Shutdown=%s" % (reader.EOF, self.Shutdown))         
            if not reader.EOF:
                exit_status = self.S_SHUTDOWN
            #self.debug("sent %d bytes of data. exit status: %s" % (self.DataByteCount, exit_status))   

        except Exception as e:
            self.debug("Error: %s" % (traceback.format_exc(),))
            exit_status = self.S_ERROR
            error_message = str(e)
        finally:
            self.FSock.settimeout(saved_timeout)
            self.Proxy.peerClosed(self, exit_status, error_message)
            self.debug("peer closed. exit_status: %s, data bytes: %s, error: %s" % (exit_status, self.DataByteCount, error_message or ""))
            self.Proxy = None
        self.ExitStatus = exit_status
        self.ErrorMessage = error_message
            
                
class HTTPProxy(Primitive, Logged):

    def __init__(self, request, ssock, transfer_timeout = 30):
        Primitive.__init__(self)
        transfer_id = request.Id
        self.MyName = "[%s proxy]" % (transfer_id,) if transfer_id is not None else "proxy"
        Logged.__init__(self, name=self.MyName)
        self.Request = request
        self.HTTPRequest = request.HTTPRequest
        self.Body = request.Body or b''
        self.SSock = ssock
        self.CSock = request.CSock
        self.Failed = False
        self.ErrorMessage = None
        #self.SCBytes = 0
        #self.CSBytes = 0
        self.TransferTimeout = transfer_timeout
        self.HTTPResponse = None
        self.ServerProtocol = self.ClientProtocol = None
        self.HTTPStatus = None
        self.HTTPStatusMessage = None
        self.Method = None
        #if request is not None:
        #    self.clientHeaderReceived(request)
        self.TransferName = transfer_id
        self.ServerPeer = self.ClientPeer = None
        self.ClientShut = self.ServerShut = False
        self.kind = "HTTPProxy"
        #self.debug("--- Created: request: %s, body:[%s]" % (client_request, body))
        
    def __str__(self):
        return self.MyName

    @synchronized
    def headerReceived(self, header):
        #self.debug("headerReceived: [%s]" % (header.as_text(),))
        header.forceConnectionClose()
        #self.debug("Added 'Connection: close' header")
        if header.is_server():
            self.HTTPStatus = header.StatusCode
            self.HTTPStatusMessage = header.StatusMessage
            self.ServerProtocol = header.Protocol
            self.ServerHeaders = header.Headers
            self.ServerHeaderReceived = header.is_final()
            self.Request.HTTPResponse = header
            #print("serverHeaderReceived:", header.as_text())
            self.Request.ResponseParts.append(header)
        else:
            assert header.is_client()
            #header.removeKeepAlive()
            #self.debug("keep alive removed")
            self.Method = header.Method
            self.URI = header.URI
            self.ClientProtocol = header.Protocol
            self.ClientHeaders = header.Headers
            self.ClientHeaderReceived = True
            self.HTTPRequest = header
            self.Request.RequestParts.append(header)
 
    def run(self):
        try:
            cs_bytes = sc_bytes = 0
            if self.HTTPRequest:
                #self.debug("started with client request:%s\n    and %d bytes of buffered body" % (self.Request, len(self.Body,)))
                assert self.HTTPRequest.is_client()
                self.headerReceived(self.HTTPRequest)
                try:
                    data = self.HTTPRequest.as_bytes() + b"\r\n" 
                    #self.debug("->s: [%s]" % to_str(data))
                    #self.debug("sending buffered request to server: [%s]" % data)
                    self.SSock.sendall(data)
                    if self.Body:
                        #self.debug("->s: [%s]" % (to_str(self.Body),))
                        self.SSock.sendall(self.Body)
                except Exception as e:
                    self.Failed = True
                    self.ErrorMessage = "Error sending buffered request to the server: %s" % (e,)

            if not self.Failed:

                    self.ClientPeer = client_peer = HTTPPeer(self, "[%s c->s peer]" % (self.TransferName,), 
                        self.CSock, self.SSock, self.TransferTimeout, self.HTTPRequest is not None,
                    )
                    self.ServerPeer = server_peer = HTTPPeer(self, "[%s s->c peer]" % (self.TransferName,), 
                        self.SSock, self.CSock, self.TransferTimeout
                    )
                
                    client_peer.start()
                    server_peer.start()
                    server_peer.join()
                    client_peer.join()
                    cs_bytes = client_peer.DataByteCount
                    sc_bytes = server_peer.DataByteCount

                    self.Failed = client_peer.ExitStatus == client_peer.S_ERROR or server_peer.ExitStatus == server_peer.S_ERROR
                    if self.Failed:
                        self.ErrorMessage = "client: [%s], server: [%s]" % (client_peer.ErrorMessage, server_peer.ErrorMessage)
        finally:
            self.ServerPeer = self.ClientPeer = None
            try:    self.SSock.close()
            except: pass
            try:    self.CSock.close()
            except: pass
            self.debug("sockets closed")
        return not self.Failed, self.ErrorMessage, cs_bytes, sc_bytes
            
    @synchronized
    def peerClosed(self, peer, exit_status, error_message=None):
        sock = None
        if peer is self.ClientPeer:
            if not self.ServerShut:
                self.ServerShut = True
                #self.debug("shutting down writing to server")
                sock = self.SSock
        elif peer is self.ServerPeer:
            if not self.ClientShut:
                self.ClientShut = True
                #self.debug("shutting down writing to client")
                sock = self.CSock
        if sock is not None:
                try:
                    pass    
                    sock.shutdown(socket.SHUT_WR)
                except OSError as exc:
                    if exc.errno == errno.ENOTCONN:
                        #self.debug("not connected exception -- ignored")
                        pass
                    else:
                        #self.debug("Error shutting down write side: %s" % (traceback.format_exc(),))
                        pass
 

if __name__ == "__main__":
    
    import sys, socket, pprint
    import logs
    
    logs.openDebugFile("-")
    
    pport, server, sport = sys.argv[1:4]
    sport = int(sport)
    pport = int(pport)

    psock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    psock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    psock.bind(("", pport))
    psock.listen(1)
    
    while True:
        csock, addr = psock.accept()
        print ("Connection from ", addr)
        ssock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ssock.connect((server, sport))

        p = HTTPProxy(None, csock, ssock, None, b"", transfer_timeout=5)
        ok, error = p.run()
        print ("Status:",ok, "   error:", error or "(no error)")
        
        print ("Request:")
        print ("  %s" % (p.Request.Headline))
        for k, v in p.Request.Headers.items():
            print("  %s: %s" % (k, v))
        print ("  [%d bytes body]" % (p.CSBytes,))
        
        print ("Response:")
        print ("  %s" % (p.Response.Headline))
        for k, v in p.Response.Headers.items():
            print("  %s: %s" % (k, v))
        print ("  [%d bytes body]" % (p.SCBytes,))
        
        
    
    
    
    

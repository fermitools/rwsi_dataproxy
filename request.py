from uid import uid
import time
from dns import DNS

class Request(object):
    
    def __init__(self, csock, caddr, server_port):
        self.Id = uid()
        self.CSock = csock
        self.HTTPRequest = None
        self.HTTPResponse = None
        self.Body = b''             # extra bytes received while reading the HTTPRequest
        self.VServerPort = server_port
        self.ClientAddress = caddr
        
        self.ResponseParts = []
        self.RequestParts = []
        
        self.Received = self.Dispatched = self.Started = self.Done = self.Failed = False
        self.Error = None
        
        self.CreatedTime = time.time()
        self.RequestReaderQueuedTime = None
        self.RequestReaderStartTime = None
        self.RequestReaderSSLCreated = None
        self.RequestReaderEndTime = None
        
        self.TransferStartTime = None
        self.ConnectedToWorkerTime = None
        self.TransferEndTime = None

        self.SentToServiceTime = None
        
        self.VServerStatus = None
        self.RequestReaderStatus = None
        self.DispatcherStatus = None
        self.ServiceAcceptStatus = None
        self.TransferStatus = None
        
        self.HTTPStatus = None
        
        self.VServerError = None
        self.ServiceName = None
        self.ServiceError = None
        
        self.ServerAddress = None

        self.ResponseHeadersReceivedTime = None
        self.BytesClientToServer = 0
        self.BytesServerToClient = 0
        self.ByteCount = 0              # either BytesClientToServer or BytesServerToClient, depending on the request

        self.TransferFailed = False
        
        self.__setattr__ = self.__my_setattr
        
    @property
    def clientHost(self):
        if self.ClientAddress is None:  return None
        return DNS[self.ClientAddress[0]]
        
    @property
    def URI(self):
        return self.HTTPRequest.URI
        
    def __my_setattr(self, name, value):
        if not hasattr(self, name):
            raise ValueError(f"Attempt to add unknown attribute '{name}' to request record")
        else:
            self.__dict__[name] = value
            
    def close(self, done):
        self.Done = done
        self.Failed = not done
        if self.CSock is not None:
            self.CSock.close()
            self.CSock = None
        

        

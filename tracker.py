import time, socket
from uid import uid

class Tracker(object):

    IPAddrCache = {}        # {ip:hostname}
    
    def __init__(self, id):
        self.Id = id
        self.CreatedTime = time.time()
        self.VServerPort = None
        self.ClientAddress = None
        self.RequestReaderStartedTime = None
        self.SocketWrappedTime = None
        
        self.RequestReaderQueuedTime = None
        self.RequestReaderStartTime = None
        self.RequestReaderSSLCreated = None
        self.RequestReaderEndTime = None
        self.RequestReaderStatus = None
        self.URI = None
        self.HTTPStatus = None
        
        self.SentToServiceTime = None
        self.ServerError = None
        self.ServiceError = None
        self.ServiceName = None

        self.TransferStartTime = None
        self.WorkerAddress = None
        self.ConnectedToWorkerTime = None
        self.TransferEndTime = None
        
        self.ResponseHeadersReceivedTime = None
        self.BytesClientToServer = 0
        self.BytesServerToClient = 0
        self.ByteCount = 0
        self.Error = None
        
        self.__setattr__ = self.__my_setattr
        
    def __my_setattr(self, name, value):
        if not hasattr(self, name):
            raise ValueError(f"Attempt to add unknown attribute '{name}' to tracker")
            
    @property
    def workerName(self):
        if self.WorkerAddress is None:  return None
        wip, wport = self.WorkerAddress
        hostname = self.IPAddrCache.get(wip)
        if not hostname:
            try:
                hostname, _, _ = socket.hethostbyaddr(wip)
                self.IPAddrCache[wip] = hostname
            except:
                hostname = wip
        return hostname

    @property
    def workerPort(self):
        if self.WorkerAddress is None:  return None
        wip, wport = self.WorkerAddress
        return wport 
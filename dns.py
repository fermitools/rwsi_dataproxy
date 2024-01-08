import socket, time
from pythreader import Primitive, synchronized


class _DNS(Primitive):
    
    TTL = 24*3600

    def __init__(self):
        Primitive.__init__(self)
        self.Map = {}               # ip -> (exp_time, hostname)
    
    @synchronized
    def hostname(self, ip):
        
        host = None
        
        if ip in self.Map:
            exp, host = self.Map[ip]
            if time.time() > exp:
                host = None
        
        if host is None:
            try:    
                ttl = self.TTL
                host, _, _ = socket.gethostbyaddr(ip)
            except: 
                ttl = 3600
                host = ip
            self.Map[ip] = (time.time() + ttl, host)
        
        return host
            
    __getitem__ = hostname

DNS = _DNS()
        


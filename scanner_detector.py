import numpy as np
from python_model import Model
from logs import Logged
import random, time
from pythreader import Primitive, synchronized
from logs import Logged

class Scan(object):
    
    TIMEOUT = 3600      # one hour
    MAXURI = 100

    def __init__(self, server_port, ip_address, fraction):
        self.TEnd = self.TStart = time.time()
        self.IPAddress = ip_address
        self.N = 0
        self.ServerPort = server_port
        self.URISamples = []        # [(uri, signal), ...]
        self.Fraction = fraction
        
    def add_hit(self, uri, signal):
        self.N += 1
        self.TEnd = time.time()
        if self.TStart is None:
            self.TStart = self.TEnd
        self.URISamples.append((uri, signal))
        while len(self.URISamples) > self.MAXURI:
            self.URISamples.pop(random.randint(0, len(self.URISamples)-1))
    
    def is_closed(self):
        return time.time() > self.TEnd + self.TIMEOUT
        
    @property
    def frequency(self):
        if self.N < 10: return 0.0
        if self.TStart == self.TEnd:    return 1.0
        return self.N/(self.TEnd - self.TStart)/self.Fraction
        
    @property
    def estimated_requests(self):
        return self.N/self.Fraction
    
class ScannerDetector(Primitive, Logged):
    
    DefaultThreshold = 0.9 # everything with signal > threshold will be considered scanner
    DefaultSamplingFraction = 0.1     # run only a fraction of requests through the NN to save CPU time

    def __init__(self, config):
        Primitive.__init__(self, name="ScannerDetector")
        Logged.__init__(self, "scanner_detector.log")
        load_from = config.get("model_file_prefix", "scanner_detector")
        self.Threshold = config.get("threshold", self.DefaultThreshold)
        self.SamplingFraction = config.get("fraction", self.DefaultSamplingFraction)
        try:
            self.NN = Model.from_saved(load_from)
        except Exception as e:
            self.NN = None
            
        self.Scans = []        # [ScanerRun, ...]
        self.CurrentScans = {}      # (server_port, client_ip) -> latest scan
        
        
    def scans(self, port=None):
        if port is None:
            return self.Scans
        else:
            return [r for r in self.Scans if r.ServerPort == port]
            
    def vectorize(self, uri):
        text = text.strip()
        n = len(text)
        vectors = np.zeros((100, 256))
        for ic, c in enumerate(text[:100]):
            c = min(ord(c), 255)
            vectors[ic,c] = 1.0
        return vectors

    RUN_TIME_TO_KEEP = 30*24*3600        # 1 month
        
    @synchronized
    def purge_scans(self):
        if self.Scans and self.Scans[0].TEnd is not None and self.Scans[0].TEnd < time.time() - self.RUN_TIME_TO_KEEP:
            self.Scans = [r for r in self.Scans if r.TEnd > time.time() - self.RUN_TIME_TO_KEEP]
        

    @synchronized
    def add_scanner_hit(self, server_port, ip_address, uri, signal):
        t = time.time()
        scan = self.CurrentScans.get((server_port, ip_address))
        if scan is None or scan.is_closed():
            scan = Scan(server_port, ip_address, self.SamplingFraction)
            self.CurrentScans[(server_port, ip_address)] = scan
            self.Scans.append(scan)
            self.purge_scans()
            self.log("new scan detected: server port: %s scanner address: %s" % (server_port, ip_address))
        scan.add_hit(uri, signal)
    
    
    def check_for_scanner_request(self, server_port, ip_address, uri):
        if self.NN is None: return False
        if random.random() > self.SamplingFraction: return False

        # vectorize URI
        text = uri
        n = len(text)
        vectors = np.zeros((100, 256))
        for ic, c in enumerate(text[:100]):
            c = min(ord(c), 255)
            vectors[ic,c] = 1.0

        signal = self.NN.compute(vectors[None,:,:])[0,0]
        is_scanner = signal > self.Threshold
        if is_scanner:
            self.add_scanner_hit(server_port, ip_address, uri, signal)
            self.debug("scanner detected: server port: %s, ip: %s, confidence: %.3f, uri:%s" % (server_port, ip_address, signal, uri))
        return is_scanner
    

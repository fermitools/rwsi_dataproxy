from datetime import datetime, timedelta
import sys, os, stat, re, time
from timelib import ShiftTZ, timestamp
from GraphiteInterface import GraphiteInterface

class CacheLogParser:

    def __init__(self, files, last_file_inode, last_file_position, last_t):
        self.Files = files[:]
        self.TMax = None
        self.TStart = last_t
        self.LastFileInode = last_file_inode
        self.LastFilePosition = last_file_position
        
    def parseLine(self, l):
        out = {}
        while l:
            l = l.strip()
            if not l:   break
            words = l.split("=", 1)
            if len(words) != 2:
                break
            n, rest = tuple(words)
            if rest[0] == '[':
                words = rest[1:].split("]",1)
            else:
                words = rest.split(None, 1)
            val = words[0]
            rest = words[1] if len(words) > 1 else ""
            if n == 'time':
                words = val.split()
                dt = datetime.strptime(words[0], "%d/%b/%Y:%H:%M:%S")
                zone = None
                if len(words) > 1:
                    zone = words[1]
                    minus = 1.0
                    if zone[0] == '-':
                        minus = -1.0
                        zone = zone[1:]
                    elif zone[0] == '+':
                        zone = zone[1:]
                    zone = zone[:4]
                    h = float(zone[:2])
                    m = float(zone[2:])/60.0
                    shift = (h+m)*minus
                    zone = ShiftTZ(shift)
                    dt = dt.replace(tzinfo=zone)
                out["clock"] = timestamp(dt)
                #print val, " -> ", dt, out["clock"]
            elif n == 'request':
                req, url, proto = val.split(None, 2)
                out["req"] = req
                out["url"] = url
                out["proto"] = proto
            out[n] = val
            l = rest
        #print "out=", out
        return out
        
    def validateData(self, data):
        for k in ['req','url','clock','cached','bytes_sent']:
            if k not in data: return False
        return True
                
    def parse(self):
        out = []        # [(t, data),...]
        t_max = last_t
        
        files = []
        for f in self.Files:
            try:    s = os.stat(f)
            except:
                print(sys.exc_info())
            mtime = s.st_mtime
            if last_t == None or mtime >= self.TStart:
                files.append((mtime, f))
            else:
                print("File %s was not updated since last scan time(%s). File updated at %s" % (
                    f, time.ctime(mtime), time.ctime(last_t)))
                
        files.sort()
        
        t_begin = None
        
        for mt, fn in files:
            try:
                f = open(fn, 'r')
            except:
                continue
                
            s = os.fstat(f.fileno())
            size = s.st_size
            inode = s.st_ino
            
            if inode == self.LastFileInode:
                f.seek(self.LastFilePosition)
            
            self.LastFileInode = inode
            self.LastFilePosition = size
            
            for l in f.readlines():
                try:
                    data = self.parseLine(l)
                except:
                    continue
                if self.validateData(data):
                    t = data["clock"]
                    if last_t == None or t > last_t:
                        yield (t, data)
                        if t_max == None:    
                            t_begin = t
                            t_max = t
                        t_max = max(t_max, t)
                else:
                    #print "data validation failed:", l
                    pass
        self.TMax = t_max
        
class ServiceData:
    def __init__(self, suffix, interval):
        self.Suffix = suffix
        self.Interval = interval
        self.RequestsMiss = 0
        self.RequestsHit = 0
        self.BytesMiss = 0
        self.BytesHit = 0
        
    def frequencies(self):
        return (
            float(self.RequestsHit)/self.Interval, 
            float(self.RequestsMiss)/self.Interval, 
            float(self.BytesHit)/self.Interval, 
            float(self.BytesMiss)/self.Interval   
        )
        
    def __str__(self):
        return "[Service %s: requests: %d/%d  bytes: %d/%d]" % (self.Suffix, 
                self.RequestsHit, self.RequestsMiss, self.BytesHit, self.BytesMiss)
        
class CacheLogSummarizer:

    def __init__(self, parser, map):
        self.Files = files
        self.URLMap = map            # (graphite_suffix, url_head)
        self.Parser = parser
        
    def interval(self, dt, interval):
        dt = int(dt)
        t0 = (dt//interval)*interval
        t1 = t0 + interval
        return t0, t1
        
    def summarize(self, interval):
        # interval - seconds
        lst = self.Parser.parse()
        t0, t1 = None, None
        int_data = {}
        for t, data in lst:
            if t0 == None or t >= t1:
                if int_data:    yield (t0, t1, int_data)
                t0, t1 = self.interval(t, interval)
                int_data = {}   # {service_name -> ServiceData}
            # find service
            svc = None
            suffix = None
            for url_head, sfx in self.URLMap:
                if data["url"].startswith(url_head):
                    suffix = sfx
                    break
            else:
                continue
                
            svc_data = int_data.get(sfx)
            if svc_data == None:
                svc_data = ServiceData(sfx, interval)
                int_data[sfx] = svc_data
            cache_sts = data["cached"]
            try:
                n = int(data["bytes_sent"])
            except:
                n = 0
                
            if cache_sts == 'HIT':
                svc_data.RequestsHit += 1
                svc_data.BytesHit += n
            else:
                svc_data.RequestsMiss += 1
                svc_data.BytesMiss += n
                
        if int_data:
            yield (t0, t1, int_data)

if __name__ == '__main__':

    import yaml, getopt, sys, glob
    
    config_file = None
    
    opts, args = getopt.getopt(sys.argv[1:], "c:")

    for opt, val in opts:
        if opt == '-c': config_file = val

    config = yaml.load(open(config_file, 'r').read())
    map = config.get("mapping")
    
    map_lst = []
    for d in map:
        map_lst.append((d["url"],d["suffix"]))
    #print map_lst
    
    
    state_file = config.get("state_file")
    interval = config.get("aggregation_interval", 60)
    files = config.get("files")
    
    GI = GraphiteInterface(config.get("Graphite"))
    
    last_t = None
    
    try:
        sf = open(state_file, 'r')
        words = sf.read().split()
        last_file_inode = int(words[0])
        last_file_position = int(words[1])
        last_t = int(words[2])
    except:
        last_file_inode = None
        last_file_position = None
        last_t = None
    
    parser = CacheLogParser(glob.glob(files), last_file_inode, last_file_position, last_t)
    s = CacheLogSummarizer(parser, map_lst)
    
    lst = s.summarize(interval)
    for t0, t1, data in lst:
        for svc, svc_data in sorted(data.items()):
            rh, rm, bh, bm = svc_data.frequencies()
            GI.feedData(t1, svc_data.Suffix+".requests.hit", rh)
            GI.feedData(t1, svc_data.Suffix+".requests.miss", rm)
            GI.feedData(t1, svc_data.Suffix+".bytes.hit", bh)
            GI.feedData(t1, svc_data.Suffix+".bytes.miss", bm)
            #print t0, t1, svc, svc_data.frequencies()
        last_t = t0
    GI.flushData()
            
    if last_t:
        open(state_file, 'w').write("%s %s %d" % (parser.LastFileInode, parser.LastFilePosition, last_t))
            
        
        
        
        
        
        

import time
import os
import datetime

from threading import RLock, Thread, Event

def synchronized(method):
    def smethod(self, *params, **args):
        self._Lock.acquire()
        try:    
            return method(self, *params, **args)
        finally:
            self._Lock.release()
    return smethod

def make_timestamp(t=None):
    if t is None:   
        t = datetime.datetime.now()
    elif isinstance(t, (int, float)):
        t = datetime.datetime.fromtimestamp(t)
    return t.strftime("%m/%d/%Y %H:%M:%S") + ".%03d" % (t.microsecond//1000)
                
class LogStream:

    def __init__(self, stream, add_timestamp=True):
        self._Lock = RLock()
        self.Stream = stream            # sys.stdout, sys.stderr
        self.AddTimestamps = add_timestamp

    @synchronized
    def log(self, msg, add_timestamp=True):
        if add_timestamp:
            msg = "%s: %s" % (make_timestamp(), msg)
        self.Stream.write(msg + '\n');
        self.Stream.flush()
        
class LogFile(Thread):

        def __init__(self, path, interval = '1d', keep = 10, add_timestamp=True, append=True, flush_interval=5.0):
                # interval = 'midnight' means roll over at midnight
                Thread.__init__(self)
                assert isinstance(path, str)
                self._Lock = RLock()
                self.Path = path
                self.File = None
                self.CurLogBegin = 0
                if type(interval) == type(''):
                        mult = 1
                        if interval[-1] == 'd' or interval[-1] == 'D':
                                interval = interval[:-1]
                                mult = 24 * 3600
                                interval = int(interval) * mult
                        elif interval[-1] == 'h' or interval[-1] == 'H':
                                interval = interval[:-1]
                                mult = 3600
                                interval = int(interval) * mult
                        elif interval[-1] == 'm' or interval[-1] == 'M':
                                interval = interval[:-1]
                                mult = 60
                                interval = int(interval) * mult
                self.Interval = interval
                self.Keep = keep
                self.AddTimestamps = add_timestamp
                self.LineBuf = ''
                self.LastLog = None
                self.LastFlush = time.time()
                self.FlushInterval = flush_interval
                if append:
                    self.File = open(self.Path, 'a')
                    self.File.write("%s: [appending to old log]\n" % (make_timestamp(),))
                    self.CurLogBegin = time.time()
                #print("LogFile: created with file:", self.File)
                    
        def run(self):
            while True:
                time.sleep(self.FlushInterval)
                self.flush()
                    
        def newLog(self):
            if self.File != None:
                    self.File.close()
            try:    os.remove('%s.%d' % (self.Path, self.Keep))
            except: pass
            for i in range(self.Keep - 1):
                    inx = self.Keep - i
                    old = '%s.%d' % (self.Path, inx - 1)
                    new = '%s.%d' % (self.Path, inx)
                    try:    os.rename(old, new)
                    except: pass
            try:    os.rename(self.Path, self.Path + '.1')
            except: pass
            self.File = open(self.Path, 'w')
            self.CurLogBegin = time.time()

        @synchronized
        def log(self, msg, raw=False, add_timestamp=True):
            t = time.time()
            if self.Interval == 'midnight':
                if datetime.date.today() != self.LastLog:
                        self.newLog()
            elif isinstance(self.Interval, (int, float)):
                if t > self.CurLogBegin + self.Interval:
                        self.newLog()
            if add_timestamp and not raw:
                msg = "%s: %s" % (make_timestamp(t), msg)
            self._write(msg if raw else msg + "\n")

        @synchronized
        def write(self, msg):
            self.log(msg, raw=True)
            
        @synchronized
        def _write(self, msg):
            if msg:
                #print("LogFile.write: writing to:", self.File)
                self.File.write(msg)
            self.flush()
            self.LastLog = datetime.date.today()
            
        @synchronized
        def flush(self):
            if time.time() > self.LastFlush + self.FlushInterval:
                self.File.flush()
                self.LastFlush = time.time()
        
        def __del__(self):
            #self.flush()
            if self.File is not None:
                self.File.close()
                self.File = None

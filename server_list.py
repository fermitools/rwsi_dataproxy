from pythreader import synchronized, Primitive
import time
from zlib import adler32
from py3 import to_bytes, PY3

if PY3:
    from urllib.request import urlopen
else:
    from urllib2 import urlopen



class ServerAddress:

    def __init__(self, listid, address):
        self.Address = address
        self.BadUntil = 0.0
        self.ListID = listid
        
    def address(self):
        return self.Address
    
    @property
    def is_good(self):
        return not self.BadUntil 
        
    def __str__(self):
        return "%s:%s" % self.Address
        
    def __repr__(self):
        return self.__str__()

class ServerList(Primitive):     # Round-robin list

    def __init__(self, lst):
        Primitive.__init__(self)
        self.FreeList = [ServerAddress(id(self), address) for address in lst]
        self.BusyList = []
        self.BadList = []
        
    def belongsToMe(self, x):
        return x.ListID == id(self)

    @synchronized
    def getLists(self):
        return self.FreeList[:], self.BusyList[:], self.BadList[:]

    @synchronized        
    def allocate(self, x):
        if self.belongsToMe(x):
            if x in self.FreeList:
                self.FreeList.remove(x)
                self.BusyList.append(x)
            elif x in self.BusyList:
                self.BusyList.remove(x)
                self.BusyList.append(x)
            elif x in self.BadList:
                self.BadList.remove(x)
                self.BadList.append(x)

    @synchronized        
    def mark_bad(self, x):
        if self.belongsToMe(x):
            if x in self.FreeList:
                self.FreeList.remove(x)
            elif x in self.BusyList:
                self.BusyList.remove(x)
            elif x in self.BadList:
                self.BadList.remove(x)

            x.BadUntil = time.time() + 60.0
            self.BadList.append(x)

    @synchronized        
    def release(self, x, ok):
        if self.belongsToMe(x):
            #print "release(%s, %s)" % (x.address(), ok)
            if x in self.FreeList:
                self.FreeList.remove(x)
            elif x in self.BusyList:
                self.BusyList.remove(x)
            elif x in self.BadList:
                self.BadList.remove(x)

            if ok:
                self.FreeList.append(x)
            else:
                x.BadUntil = time.time() + 60.0
                self.BadList.append(x)

            # review bad status

            for x in self.BadList[:]:
                if x.BadUntil < time.time():
                    x.BadUntil = 0.0
                    self.BadList.remove(x)
                    self.FreeList.append(x)

            #print self.FreeList

    @synchronized        
    def snapshot(self, url, rotate = True):
        ret = self.FreeList + self.BusyList + self.BadList
        if rotate:  self.rotate()
        #print "snapshot: %s" % (ret,)
        return ret
        
    @synchronized        
    def rotate(self):
        self.FreeList = self.FreeList[1:] + self.FreeList[:1]
        #self.BusyList = self.BusyList[1:] + self.BusyList[:1]

class HashedServerList(Primitive):     

    def __init__(self, lst):
        Primitive.__init__(self)
        self.AddressList = [ServerAddress(id(self), address) for address in lst]
        self.Offset = 0
        
    def belongsToMe(self, x):
        return x.ListID == id(self)

    @synchronized
    def getLists(self):
        return [x for x in self.AddressList if x.BadUntil == 0.0], [], [x for x in self.AddressList if x.BadUntil]

    @synchronized        
    def allocate(self, x):
        pass

    @synchronized        
    def mark_bad(self, x):
        if self.belongsToMe(x):
            x.BadUntil = time.time() + 60.0
        
    @synchronized        
    def release(self, x, ok):
        if self.belongsToMe(x):
            #print "release(%s, %s)" % (x.address(), ok)

            if not ok:
                x.BadUntil = time.time() + 60.0

            for x in self.AddressList:
                if not x.is_good and x.BadUntil < time.time():
                    x.BadUntil = 0.0

    @synchronized        
    def snapshot(self, url, rotate = True):
        # rotate is applied only to bad list
        all = self.AddressList[:]
        h = adler32(to_bytes(url))
        shift = h%len(all)
        all = all[shift:] + all[:shift]
        good = [a for a in all if a.is_good]
        bad = [a for a in all if not a.is_good]
        if bad:
            bad_shift = self.Offset % len(bad)
            bad = bad[bad_shift:] + bad[:bad_shift]
            if rotate:
                self.rotate()
        return good + bad

    @synchronized        
    def rotate(self):
        self.Offset = (self.Offset + 1) % len(self.AddressList)
        #self.BusyList = self.BusyList[1:] + self.BusyList[:1]

#from TCPClientConnection import TCPClientConnection


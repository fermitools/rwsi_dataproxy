from pythreader import Primitive, synchronized
import time

class HistoryWindow(Primitive):
    
    def __init__(self, time_window=None, capacity=None):
        Primitive.__init__(self)
        assert capacity is not None or time_window is not None
        self.Capacity = capacity
        self.TimeWindow = time_window
        self.Points = []        # [(t, data),...]
        
    @synchronized   
    def add(self, t=None, data=None):
        now = time.time()
        if t is None:   t = now
        if self.TimeWindow is not None and t < now - self.TimeWindow:
            return
        need_sort = self.Points and self.Points[0][0] > t
        self.Points.insert(0, (t, data))
        if need_sort:
            self.Points = sorted(self.Points)
        self.purge()
        
    @synchronized   
    def purge(self):
        now = time.time()
        if self.Capacity is not None and len(self.Points) > self.Capacity:
            self.Points = self.Points[:self.Capacity]
        if self.Points and self.TimeWindow is not None and self.Points[-1][0] < now - self.TimeWindow:
            self.Points = [(t,x) for t, x in self.Points if t >= now - self.TimeWindow]

    @synchronized   
    def frequency(self):
        self.purge()
        return len(self.Points)/float(self.TimeWindow)

    @synchronized   
    def count(self):
        self.purge()
        return len(self.Points)

    @synchronized
    def select(self, filter=None, tmin=None, tmax=None):
        self.purge()
        out = []
        for t, x in self.Points:
            if ( (tmin is None or t > tmin) 
                        and (tmax is None or t <= tmax) 
                        and (filter is None or filter(t, x))
            ):
                out.append((t, x))
        return out
        
    @synchronized
    def counts(self, bin=1, filter=None, tmin=None, tmax=None):
        assert isinstance(bin, int)
        now = int(time.time())
        t0 = self.Points[-1][0]
        t0 = (int(t0)/bin)*bin
        t1 = ((now+bin-1)/bin)*bin+1
        nbins = (t1-t0)/bin
        counts = [0]*nbins
        edges = list(range(t0, t1, bin))
        for t, _ in self.select(filter=filter, tmin=tmin, tmax=tmax):
            i = (int(t)-t0)/bin
            counts[i] += 1
        return edges, counts

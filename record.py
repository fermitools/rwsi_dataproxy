from pythreader import Primitive, PyThread, synchronized, Scheduler
import numpy as np
import time, fnmatch
import sqlite3
from debug import Debugged

IMin, ISum, ILast, IMax = 0,1,2,3

class RecordSet(object):
    
    def __init__(self, t, data_dict, bin, zeros):
        self.T = t
        self.DataDict = data_dict       # { label: (v, c) }
        #print("RecordSet.__init__: data_dict:", data_dict)
        self.Bin = bin
        self.Zeros = zeros
        
    def labels(self):
        return self.DataDict.keys()
        
    def __getitem__(self, label):
        return self.T, self.DataDict[label]
        
    def data(self, label=None):
        if label is None:
            return self.T, self.DataDict
        else:
            return self.T, self.DataDict[label]
            
    __call__ = data
    
    def aggregate_label(self, agg, label):
        v, c = self.DataDict.get(label, self.Zeros)
        return self.extract(v, c, agg)
        
    def extract(self, v, c, agg):
        if agg == "min":        
            return v[:,IMin]
        elif agg == "max":      
            return v[:,IMax]
        elif agg == "last":     
            return v[:,ILast]
        elif agg == "sum":     
            return v[:,ISum]
        elif agg == "count":    
            return np.asarray(c, dtype=np.float)
        elif agg in ("average", "mean"):  
            v = v[:,ISum].copy()
            invalid = c==0
            valid = c>0
            v[valid] = v[valid]/c[valid]
            v[invalid] = np.nan
            return v
        elif agg == "frequency":      
            return np.asarray(c, dtype=np.float)/self.Bin
        elif agg == "flow":
            return v[:,ISum]/self.Bin

    def combine_labels(self, agg, labels=None):
        assert not agg in ("last",), "Invalid aggreate for comining labels"
        if labels is None:  labels = list(self.labels())
        if not labels:
            return self.Zeros[0][:,ISum]
        vout, cout = self.DataDict.get(labels[0], self.Zeros)
        for l in labels[1:]:
            v, c = self.DataDict.get(l, self.Zeros)
            cout += c
            vout[:,IMin] = np.minimum(vout[:,IMin], v[:,IMin])
            vout[:,IMax] = np.minimum(vout[:,IMax], v[:,IMax])
            vout[:,ISum] += v[:,ISum]
        return self.extract(vout, cout, agg)
            
    def convert_nans(self, v):
        return [None if np.isnan(x) else float(x) for x in v]
        
    def aggregate(self, agg, label="+"):
        #print("RecordSet.aggregate: label:", label, "   labels:", self.labels())
        out = {}
        if label == '+':
            v = self.combine_labels(agg)
            #print("aggregate: combine_labels->", v)
            out["+"] = self.convert_nans(self.combine_labels(agg))
        else:
            labels = self.labels() if label == '*' else [label]
            for l in labels:
                out[l] = self.convert_nans(self.aggregate_label(agg, l))
        return self.T, out
        
class TimeLine(Primitive):

    def __init__(self, bin, length):
        Primitive.__init__(self)
        assert length % bin == 0
        self.Length = length
        self.Bin = bin
        self.N = int(length/bin)
        self.Changed = np.zeros((self.N,), dtype = np.bool)
        self.T = self.round_t()
        self.CVDict = {}        # type -> (counts, values)

    def round_t(self, t=None):
        if t is None:    t = time.time()
        return int(t/self.Bin)*self.Bin + self.Bin
        
    @property
    def tmin(self):
        return self.T - self.Length

    def ibin(self, t):
        assert t >= self.tmin
        if t >= self.T: 
            i = -1
        else:
            i = int((t-self.tmin)/self.Bin)
        #print("record.ibin: T:", self.T, "  t:", t, "  delta:", t-self.T, "  bin:", self.Bin, "  ibin->", i)
        return i

    def bin_t(self, i):
        return self.tmin + i*self.Bin
        
    @synchronized
    def clear_changed(self):
        self.Changed[:] = False
        
    @synchronized
    def set_data(self, data_dict):
        #
        # Used when loaded from the DB
        # data_dict is a dict:
        #   { type: list of tuples:
        #       [ (t, vmin, vsum, vlast, vmax, count), ]
        #   }
        #
        
        for typ, data in data_dict.items():
            counts, values = self.cvForLabel(typ)
            for t, vmin, vsum, vlast, vmax, count in data:
                i = self.ibin(t)
                if i < self.N and i >= 0:
                    values[i,:] = [vmin, vsum, vlast, vmax]
                    counts[i] = count
        
    @synchronized
    def roll(self, t=None):
        new_T = self.round_t(t)
        if new_T > self.T:
            n = int((new_T - self.T)/self.Bin)
            if n > 0:
                #print("record.roll: values:", type(self.Values), self.Values,"   n:", n)
                for label, (counts, values) in list(self.CVDict.items()):
                    counts = np.roll(counts, -n)
                    counts[-n:] = 0
                    if np.all(counts==0):
                        del self.CVDict[label]
                    else:
                        values = np.roll(values, -n, axis=0)
                        values[-n:,:] = 0.0
                        self.CVDict[label] = (counts, values)
                self.Changed = np.roll(self.Changed, -n)
                self.Changed[-n:] = False
            self.T = new_T

    def zeros(self):
        values = np.zeros((self.N,4), dtype = np.float)        # min, sum, last, max
        counts = np.zeros((self.N,), dtype = np.int)
        return values, counts
                
    def cvForLabel(self, label):
        cv = self.CVDict.get(label)
        if not cv:
            values, counts = self.zeros()
            self.CVDict[label] = cv = (counts, values)
        return cv
            
    @synchronized
    def add(self, x, t=None, label=""):
        #print("TimeLine.add(%s, t=%s, label=%s)" % (x, t, label))
        if label == "*":
            raise ValueError("Invalid label value '*' - should be used for reading only")
        if x is None:   return
        now = time.time()
        if t is None:   t = now
        self.roll(t)
        if t < self.tmin:
            return
        i = self.ibin(t)
        
        counts, values = self.cvForLabel(label)
        c = counts[i]
        if c == 0:
            values[i,:] = x
            counts[i] = 1
        else:
            values[i,IMin] = min(x, values[i,IMin])
            values[i,ISum] += x
            values[i,ILast] = x
            values[i,IMax] = max(x, values[i,IMax])
            counts[i] += 1
        
        self.Changed[i] = True

    @synchronized
    def changed(self):
        out = []
        for label, (counts, values) in self.CVDict.items():
            out += [(label, self.bin_t(i), v, c) 
                    for i, (v, c, d) in enumerate(zip(values, counts, self.Changed))
                        if d
            ]
        return out
    
    def select(self, t0, t1):
        self.roll(time.time())
        if t1 is None:  t1 = self.T
        if t0 is None:  t0 = self.tmin 
        t0 = max(t0, self.tmin)
        t1 = min(t1, self.T)

        i0 = self.ibin(t0)
        i1 = self.ibin(t1)+1
        
        #print("select: i0, i1:", i0, i1)
        
        t = self.tmin + np.arange(self.N)*self.Bin
        t = t[i0:i1].copy()
        
        out = {}
        for l in self.CVDict.keys():
            counts, values = self.cvForLabel(l)
            out[l] = (values[i0:i1].copy(), counts[i0:i1].copy())
            #print("select: label:", l, "    out:", out)
        #print("select: selected:", out)
        return RecordSet(t, out, self.Bin, self.zeros())
        
    def __getitem__(self, inx):
        # to be used to get a time interval:  timeline[t0:t1]
        assert isinstance(inx, slice)
        assert inx.step is None
        return self.select(inx.start, inx.stop)
                
class Record(object):
    
    def __init__(self, bins_lengths = []):
        self.TimeLines = {bin: TimeLine(bin, length) for bin, length in bins_lengths}
        
    def add_timeline(self, bin, length):
        self.TimeLines[bin] = TimeLine(bin, length)
        
    def load_data(self, bin, data_dict):
        tl = self.TimeLines.get(bin)
        if tl is not None:
            tl.set_data(data_dict)
        
    def add(self, x, t=None, label=""):
        if t is None:   t = time.time()     # to have consistent timestamps
        for tl in self.TimeLines.values():
            tl.add(x, t, label)

    def changed(self, clear=False):
        out = {}
        for bin, tl in sorted(self.TimeLines.items()):
            out[bin] = tl.changed()
            if clear:   tl.clear_changed()
        return out
        
    def clear_changed(self):
        for tl in self.TimeLines.values():
            tl.clear_changed()        
        
    def __getitem__(self, bin):
        return self.TimeLines[bin]

    def bins(self):
        return list(self.TimeLines.keys())

    keys = bins

    def aggregate(self, agg, bin, t0=None, t1=None, label="+"):
        return self[bin][t0:t1].aggregate(agg, label)

class RecordDatabase(PyThread, Debugged):

    def __init__(self, dbpath, timelines=[], save_interval=30, load_all=False, retain="7d"):
        PyThread.__init__(self)
        Debugged.__init__(self, "[record db]")
        self.DBPath = dbpath
        self.Records = {}       # name -> Record
        self.SaveInterval = save_interval
        if timelines:
            self.init(timelines, load_all)
        self.ShutDown = False
        if isinstance(retain, str):
            if retain[-1] in "mhds":
                n = int(retain[:-1])
                mult = {
                    'm':    60,
                    'h':    3600,
                    'd':    24*3600
                }[retain[-1]]
                retain = n * mult
        assert isinstance(retain, int)
        self.Retain = retain
        self.VacuumInterval = 24*3600
        self.NextVacuum = time.time() + self.VacuumInterval
        
            
    @synchronized
    def init(self):
        db = sqlite3.connect(self.DBPath)
        c = db.cursor()
        #print("RecordDatabase.run(): creating tables in", self.DBPath)
        c.execute("""
            create table if not exists records
            (   name    text,
                label   text,
                t       bigint,
                bin     bigint,
                vmin    double precision,
                vsum    double precision,
                vlast   double precision,
                vmax    double precision,
                n       bigint,
                primary key(name, bin, label, t)
            )
        """)
        c.execute("""
            CREATE INDEX if not exists records_name_bin_t on records(name, bin, t)
        """)
        c.execute("""
            CREATE INDEX if not exists records_bin_t on records(bin, t)
        """)

    @synchronized
    def __getitem__(self, inx):
        if isinstance(inx, tuple):
            assert len(inx) <= 2       # name, bin
            name, bin = inx
            return self.Records[name][bin]
        else:
            assert isinstance(inx, str)
            return self.Records[inx]

    @synchronized
    def names(self, pattern="*"):
        return [k for k in self.Records.keys() if fnmatch.fnmatch(k, pattern)]

    keys = names
    
    @synchronized
    def add_timeline(self, name, bin, length, load=True):
        r = self.Records.setdefault(name, Record())
        assert not bin in r.bins(), "Timeline %s/%s already exists" % (name, bin)
        r.add_timeline(bin, length)
        if load:
            self.load_timeline(name, bin)
            
    def load_timeline(self, name, bin):
        r = self.Records[name]
        tl = r[bin]
        db = sqlite3.connect(self.DBPath)
        c = db.cursor()
        c.execute("""
            select label, t, vmin, vsum, vlast, vmax, n
                from records
                where name = ? and bin = ? and t >= ?
                order by label, t""", (name, bin, tl.tmin))
        out = {}
        for label, t, vmin, vsum, vlast, vmax, n in c.fetchall():
            lst = out.setdefault(label, [])
            lst.append((t, vmin, vsum, vlast, vmax, n))
        r.load_data(bin, out)

    @synchronized
    def load_data(self):
        db = sqlite3.connect(self.DBPath)
        c = db.cursor()
        c.execute("""select distinct name, bin from records order by name, bin""")
        names_bins = c.fetchall()
        
        for name, bin in names_bins:
            if name in self.Records:
                self.load_timeline(name, bin)
        db.close()
        
    @synchronized
    def add(self, data_dict=None, t=None, label="", **args):
        if t is None:   t = time.time()
        if data_dict is None:   data_dict = args
        for name, value in data_dict.items():
            self.Records[name].add(value, t, label=label)
            #self.debug(f"add:t={t} name={name} label={label} value={value}")

    @synchronized
    def _flush(self):
        db = sqlite3.connect(self.DBPath)
        c = db.cursor()
        for name, record in self.Records.items():
            changed = record.changed()
            for bin, lst in changed.items():
                c.executemany("""
                    insert or replace into records(name, label, bin, t, n, vmin, vsum, vlast, vmax)
                        values(?,?,?,?,?,?,?,?,?)
                    """, [(name, label,  bin, t, int(count), 
                                float(vmin), float(vsum), float(vlast), float(vmax)) 
                            for label, t, (vmin, vsum, vlast, vmax), count in lst
                    ]
                )
            record.clear_changed()
        db.commit()
        db.close()
        #self.debug("flushed")
        self.wakeup()
        
    @synchronized
    def _cleanup(self):
        self.debug("cleanup...")
        db = sqlite3.connect(self.DBPath)
        c = db.cursor()
        
        bins_limits = {}     # {bin -> longest timeline length}
        max_limit = 0
        
        for r in self.Records.values():
            for tl in r.TimeLines.values():
                bin, l  = tl.Bin, tl.Length
                bins_limits[bin] = max(l, bins_limits.get(bin, 0))
                max_limit = max(l, max_limit)
        
        for bin, l in bins_limits.items():
            c.execute(
                """delete from records where bin = ? and t < ?""", 
                (bin, time.time() - l,)
            )
            self.debug("... bin: %s, limit: %s: %d records deleted" % (bin, l, c.rowcount))
            db.commit()
        c.execute("delete from records where t < ?", (time.time() - max_limit,))
        db.commit()
        self.debug("cleanup done")
        db.close()
        
    @synchronized
    def _vacuum(self):
        self.debug("vacuum...")
        db = sqlite3.connect(self.DBPath)
        db.cursor().execute("vacuum")
        self.debug("vacuum done")
        db.close()
        
    def run(self):
        scheduler = Scheduler()
        scheduler.add(self._flush,  self.SaveInterval)
        scheduler.add(self._cleanup, 24*3600)
        scheduler.add(self._vacuum, 24*3600)                  # once per day
        scheduler.start()
        scheduler.join()
      
    @synchronized
    def close(self):
        self.save()
        self.ShutDown = True
        self.wakeup()

    @synchronized
    def save(self):
        db = sqlite3.connect(self.DBPath)
        self._flush(db)
        
    @synchronized
    def rollup(self, names, bin):
        tmax = max(self[name, bin].T for name in names) - bin
        for name in names:
            self[name, bin].roll(tmax)
        
    @synchronized
    def values(self, names, bin, t0, t1):
        # synchronized version, makes sure time values are consistent between all the names
        self.rollup(names, bin)
        
        data = {}
        for name in names:
            t, v, c = self[name, bin].values(t0, t1)
            data[name] = (v, c)
            
        return t, data        
        
    def aggregate(self, agg, name, bin, t0=None, t1=None, label="+"):
        tl = self[name, bin]
        return tl[t0:t1].aggregate(agg, label=label)
        
        
    @synchronized
    def aggregates(self, names_labels_aggs, bin, t0=None, t1=None):
        # synchronized version, makes sure time values are consistent between all the names
        
        # returns tuple:
        #   t array, { (name, label, agg): values }
        
        names = list(set(name for name, _, _ in names_labels_aggs))
        self.rollup(names, bin)
        
        out = {}
        for name, label, agg in names_labels_aggs:
            t, data_dict = self.aggregate(agg, name, bin, t0, t1, label)
            for l, data in data_dict.items():
                out[(name, l, agg)] = data
            
        return t, out
        
class TimeWindow(object):

    def __init__(self, length):
        self.Length = length
        self.T = TimeLine(length/10.0, length)

    def add(self, t=None):
        self.T.add(1.0, t)
            
    def frequency(self):
        return self.count()/float(self.Length)

    def count(self):
        now = time.time()
        data = self.T.select(now-self.Length, now)
        data = data.aggregate("count")[1]["+"]
        return sum(data)




if __name__ == "__main__":
    import random, sys
    
    def test():
        tl = TimeLine(10.0, 100.0)
        now = time.time()
        tl.add(1.0, now)
        tl.add(1.1, now+0.1, label="one")
        tl.add(1.2, now+0.3, label="three")
        print("now:", now, "   tl.T:", tl.T)
        print(tl.CVDict)
        
        rs = tl[:]
        print("rs=", rs, "   rs.labels:", rs.labels())
        print("rs.agg('max', '*')", rs.agg("max", "*"))
        print("rs.agg('mean')", rs.agg("mean"))
        
    def test_record():
        r = Record([
            (1, 60),
            (10, 600)
        ])
        now = time.time()
        r.add(1.0, now)
        r.add(1.1, now+0.1, label="one")
        r.add(1.2, now+0.3, label="three")
        print(r.aggregate("last"))
        
    def test_db():
        timelines = [
            ("x", 1, 60),
            ("x", 10, 600),
            #("x", 100, 6000),
            ("y", 1, 60),
            #("y", 10, 6000),
            #("y", 100, 6000)
        ]
        db = RecordDatabase("records.db")
        db.init()
        for name, bin, length in timelines:
            db.add_timeline(name, bin, length, load=False)
        
        db.start()

        t1 = time.time()
        t0 = t1 - 10
        t = t0
        while t < t1:
            db.add(t=t, x=t-t0, y=t1-t)
            db.add(t=t, x=t-t0+random.random(), y=t1-t+0.5)
            db.add(t=t, x=t-t0, y=t1-t, label="hello")
            db.add(t=t, x=t-t0+random.random(), y=t1-t+0.5, label="hello")
            t += 1
            
        db.save()
        print("DB saved")
        
        db = RecordDatabase("records.db")
        for name, bin, length in timelines:
            db.add_timeline(name, bin, length, load=True)
        print ("DB restored")
        
        aggs = db.aggregates([
                ("x", "mean"), ("x", "max")
            ],
            10,
            label=None
        )
        print ("aggs by label:", aggs)
        
        aggs = db.aggregates([
                ("x", "mean"), ("x", "max")
            ],
            10,
            label="hello"
        )
        print ("aggs for hello:", aggs)
        
        
        
    
    test_db()
    sys.exit(1)
    
    
    
   
    db = RecordDatabase("records.db")
    db.init()
    for name, bin, length in timelines:
        db.add_timeline(name, bin, length, load=False)
    
    db.start()

    t1 = time.time()
    t0 = t1 - 10
    t = t0
    while t < t1:
        db.add(t=t, x=t-t0, y=t1-t)
        db.add(t=t, x=t-t0+random.random(), y=t1-t+0.5)
        t += 1


    print("bin:",1)
    t, v, c = db["x"][1].values(t0=t0, t1=t1)
    print("t:",time.time() - t)
    print("v:", v)
    print("c:", c)


    print("Aggs")
    aggs = [("x","mean"), ("x","last"), ("x","max")]
    t, agg_vals = db.aggregates(aggs, 1, t0, t1)
    print("t:", t)
    for name, agg in aggs:
        print(name, agg, agg_vals[(name, agg)])
    



    print ("DB saved")
    
    sys.exit(1)

    db1 = RecordDatabase("records.db", timelines=timelines)
    print ("DB restored")
    t, v, c = db["x"][1].values(t0=t0, t1=t1)
    print("t:",time.time() - t)
    print("v:", v)
    print("c:", c)

    
    

    
    
        

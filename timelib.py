from datetime import datetime, tzinfo, timedelta, time
import time

class UTC(tzinfo):

    ZERO = timedelta(0)

    def utcoffset(self, dt):
        return self.ZERO
        
    def tzname(self):
        return "UTC"
        
    def dst(self, dt):
        return self.ZERO

class ShiftTZ(tzinfo):
    
    def __init__(self, shift):
        self.Shift = shift
        
    def utcoffset(self, dt):
        return timedelta(hours=self.Shift)
        
    def tzname(self):
        return '%+02d:00' % (self.Shift,)
        
    def dst(self, dt):
        return timedelta(0)
        
class LocalTZ(ShiftTZ):

    def __init__(self):
        now = datetime.now()
        utcnow = datetime.utcnow()
        sign = 1
        if now < utcnow:
            sign = -1
            delta = utcnow - now
        else:
            sign = 1
            delta = now - utcnow
        delta = delta.days*3600*24 + delta.seconds + delta.microseconds/1000.0
        delta = int(delta/3600 + 0.5) * sign
        ShiftTZ.__init__(self, delta)

_LocalTZ = LocalTZ()

def relativeTime(t):
    if type(t) == type(""):
        return not t or t == "now" or t[0]=="-"
    if type(t) == type(1.0) or type(t) == type(1):
        return t < 0
    return False
    

def text2datetime(t):
    #
    # Implied timezone is Central/Chicago
    #
    # Accepted formats:
    #   now
    #   mm/dd/yyyy hh:mm:ss
    #   yyyy-mm-ddThh:mm:ss[.ssss][+hh[[:]mm]]
    #   yyyy-mm-ddThh:mm:ss[.ssss][-hh[[:]mm]]
    #   seconds-since-epoch
    #   -nnnn[.ffff][dhms]
    #
    now = datetime.now().replace(tzinfo = LocalTZ())

    if t == None or t == "" or t == 'now':
        return now

    if type(t) == type(1.0) or type(t) == type(1):
        if t < 0:
            t = now - timedelta(seconds=-t)
        else:
            t = datetime.fromtimestamp(t, UTC())
        return t

    if t.find('T') >= 0:
        dt, tm = tuple(t.split('T',1))
        z = None
        zsign = 0
        if tm.find('-') >= 0:
            zsign = -1
            tm, z = tuple(tm.split('-',1))
        elif tm.find('+') >= 0:
            zsign = +1
            tm, z = tuple(tm.split('+',1))
        elif tm.find(' ') >= 0:
            zsign = +1
            tm, z = tuple(tm.split(' ',1))
        #print tm, '--', z
        if z:
            if z.find(':') >= 0:
                hh,mm = tuple(z.split(':',1))
            else:
                hh = z[:2]
                mm = z[2:]
            hh = hh or '00'
            mm = mm or '00'
            hh = int(hh)
            mm = int(mm)
        t = '%sT%s' % (dt, tm)
        try:
            t = datetime.strptime(t, '%Y-%m-%dT%H:%M:%S.%f')
        except:
            t = datetime.strptime(t, '%Y-%m-%dT%H:%M:%S')
        if z:
            # convert to UTC and add/subtract the offset
            t = t.replace(tzinfo=UTC())
            shift = timedelta(hours = hh, minutes = mm)
            if zsign < 0:
                t = t + shift
            else:
                t = t - shift
        else:
            t = t.replace(tzinfo=LocalTZ())
        #print t
        return t

    try:    
        t = datetime.strptime(t, '%m/%d/%Y %H:%M:%S.%f')
        t = t.replace(tzinfo=LocalTZ())
        return t
    except: pass

    try:    
        t = datetime.strptime(t, '%m/%d/%Y %H:%M:%S')
        t = t.replace(tzinfo=LocalTZ())
        return t    
    except: pass

    try:    
        t = datetime.strptime(t, '%Y-%m-%d %H:%M:%S')
        t = t.replace(tzinfo=LocalTZ())
        return t    
    except: pass

    try:    
        t = datetime.strptime(t, '%H:%M:%S').time()
        today = datetime.now().date()
        t = datetime.combine(today, t).replace(tzinfo=LocalTZ())
        return t    
    except: pass

    unit = 's'
    if t[-1].lower() in 'dhms':
        unit = t[-1].lower()
        t = t[:-1]
    t = float(t)
    if t < 0:
        mult = {
            'd':    24*3600,
            'h':    3600,
            'm':    60,
            's':    1
            }[unit]
        t = t * mult
    if type(t) == type(1.0) or type(t) == type(1):
        if t < 0:
            t = now - timedelta(seconds=-t)
        else:
            t = datetime.fromtimestamp(t, UTC())
    #print "t=", type(t), t
    return t

def tzinfo(tz):
    # tz: 
    #   UTC
    #   +hh
    #   -hh
    if not tz:  return LocalTZ()
    if tz.lower() == 'utc':
        return UTC()
    return ShiftTZ(int(tz))

def parseTimeWindow(w):
    if not w:   return timedelta(seconds = 0)
    units = w[-1]
    seconds = int(w[:-1])
    if units == 'd':
        seconds *= 24 * 3600
    elif units == 'h':
        seconds *= 3600
    elif units == 'm':
        seconds *= 60
    return timedelta(seconds = seconds)
    
def seconds(delta):
    return delta.days * 3600 * 24 + delta.seconds + int(delta.microseconds/1000000.0+0.5)
    
def timestamp(t):
    if t.tzinfo == None:
        t = t.replace(tzinfo = _LocalTZ)
    t0 = datetime(1970,1,1,0,0,0, tzinfo=UTC())
    delta = t - t0
    return seconds(delta)


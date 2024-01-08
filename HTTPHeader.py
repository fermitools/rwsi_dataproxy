from py3 import to_bytes, to_str, PY3
import re
from uid import uid
#from object_counter import Counted

class HTTPHeader(object):

    def __init__(self):
        self.Headline = None
        self.StatusCode = None
        self.StatusMessage = ""
        self.Method = None
        self.URI = None
        self.Path = None
        self.OriginalURI = None
        self.Headers = {}
        self.Raw = b""
        self.Buffer = b""
        self.Complete = False
        
    def __str__(self):
        return "HTTPHeader(headline='%s', status=%s)" % (self.Headline, self.StatusCode)
        
    __repr__ = __str__
        
    def replaceURI(self, uri):
        self.URI = uri

    def is_server(self):
        return self.StatusCode is not None

    def is_client(self):
        return self.Method is not None

    def is_final(self):
        return self.is_server() and self.StatusCode//100 != 1 or self.is_client()

    EOH_RE = re.compile(b"\r?\n\r?\n")

    def consume(self, inp):
        #print(self, ".consume(): inp:", inp)
        header_buffer = self.Buffer + inp
        match = self.EOH_RE.search(header_buffer)
        if not match:   
            self.Buffer = header_buffer
            return False, b''
        i1, i2 = match.span()            
        self.Complete = True
        self.Raw = header = header_buffer[:i1]
        rest = header_buffer[i2:]
        headers = {}
        header = to_str(header)
        lines = [l.strip() for l in header.split("\n")]
        if lines:
            self.Headline = headline = lines[0]
            
            words = headline.split(" ", 2)
            #print ("HTTPHeader: headline:", headline, "    words:", words)
            if words[0].lower().startswith("http/"):
                self.StatusCode = int(words[1])
                self.StatusMessage = words[2]
                self.Protocol = words[0].upper()
            else:
                self.Method = words[0].upper()
                self.Path = self.URI = self.OriginalURI = uri = words[1]
                if '?' in uri:
                    # detach query part
                    self.Path = uri.split("?", 1)[0]
                self.Protocol = words[2].upper()
                    
            for l in lines[1:]:
                if not l:   continue
                try:   
                    #print ("HTTPHeader: header line:", type(l), l)
                    h, b = tuple(l.split(':', 1))
                    #print (h, b)
                    headers[h] = b.strip()
                    #if h.lower() in ("www-authenticate", "authorization"):
                    #    headers[h] = "#### hidden ####"
                    #elif h.lower == "connection":
                    #    headers[h] = "close"			# always override keep-alive
                except: pass
            self.Headers = headers
            #print("HTTPHeader: headers:", headers)
        self.Buffer = b""
        #print("exit from consume: status/message/proto:", self.StatusCode, self.StatusMessage, self.Protocol)
        #print("HTTPHeader: returning True,",rest)
        return True, rest

    def removeKeepAlive(self):
        if "Connection" in self.Headers:
            self.Headers["Connection"] = "close"

    def forceConnectionClose(self):
        self.Headers["Connection"] = "close"

    def headersAsText(self):
        headers = []
        for k, v in self.Headers.items():
            if isinstance(v, list):
                for vv in v:
                    headers.append("%s: %s" % (k, vv))
            else:
                headers.append("%s: %s" % (k, v))
        return "\r\n".join(headers) + "\r\n"

    def headline(self, original=False):
        if self.is_client():
            return "%s %s %s" % (self.Method, self.OriginalURI if original else self.URI, self.Protocol)
        else:
            return "%s %s %s" % (self.Protocol, self.StatusCode, self.StatusMessage)

    def as_text(self, original=False):
        return "%s\r\n%s" % (self.headline(original), self.headersAsText())

    def as_bytes(self, original=False):
        return to_bytes(self.as_text(original))

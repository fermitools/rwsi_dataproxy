from LogFile import LogFile
from request import Request
from pythreader import Primitive
from dns import DNS

class RequestLogger(Primitive):
    
    def __init__(self, logfile, data_logger):
        if isinstance(logfile, str):
            logfile = LogFile(logfile)
            
        self.LogFile = logfile
        self.DataLogger = data_logger
        
    def log(self, request):
        assert isinstance(request, Request)
        created = request.CreatedTime
        caddr = request.ClientAddress
        http_request = request.HTTPRequest
        headline = (http_request.headline() if http_request is not None else '') or ''
        headline = headline.strip()
        port = request.VServerPort
        sname = request.ServiceName or '-'
        saddr = request.ServerAddress or (None, None)
        saddr = (saddr[0] or '-', saddr[1] or '-')
        http_status = request.HTTPStatus or "-"
        nbytes = request.BytesClientToServer + request.BytesServerToClient
        chost = DNS[caddr[0]]
        if request.Failed or not request.Started:
            line = '%s :%d %s(%s):%s [%s] -> "%s" %s:%s %s %s e:[%s]' % (request.Id, port, 
                    chost, caddr[0], caddr[1], headline or '?', sname, saddr[0], saddr[1],
                    http_status, nbytes, 
                    request.Error or '')
        else:
            started = request.TransferStartTime
            done = request.TransferEndTime

            dtstart = started - created
            dtdone = done - started
            
            line = '%s :%d %s(%s):%s [%s] -> "%s" %s:%s %s %s w:%.3f t:%.3f' % \
                (request.Id, port, 
                chost, caddr[0], caddr[1], headline,
                sname, saddr[0], saddr[1],
                http_status, nbytes,
                dtstart, dtdone)
            if request.Error:   line += f" e:[{request.Error}]"
        self.LogFile.log(line)
        
        self.DataLogger.logRequest(request)
        

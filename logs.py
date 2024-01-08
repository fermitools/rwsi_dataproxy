from webpie.logs import Logged, Logger, LogFile, init
from dns import DNS

def format_service_log(request):
    created = request.CreatedTime
    started = request.TransferStartTime
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
        dtstart = dtdone = "-"
    else:
        dtstart = "%.3f" % (started - created,)
        dtdone = "%.3f" % (request.TransferEndTime - started,)
    line = '%s %s(%s):%s -> :%d [%s] -> "%s" %s:%s %s %s w:%s t:%s' % \
        (request.Id, 
        chost, caddr[0], caddr[1], 
        port, headline,
        sname, saddr[0], saddr[1],
        http_status, nbytes,
        dtstart, dtdone)
    if request.Error:   line += f" e:[{request.Error}]"
    return line

def format_server_log(request):
    created = request.CreatedTime
    caddr = request.ClientAddress
    cip, cport = caddr
    chost = DNS[cip]
    http_request = request.HTTPRequest
    headline = (http_request.headline() if http_request is not None else '') or ''
    headline = headline.strip()
    port = request.VServerPort

    dtstart = dtssl = dtend = "-"
    if request.RequestReaderStartTime:         dtstart = "%.3f" % (request.RequestReaderStartTime - created,)
    if request.RequestReaderSSLCreated:        dtssl = "%.3f" % (request.RequestReaderSSLCreated - created,)
    if request.RequestReaderEndTime:           dtend = "%.3f" % (request.RequestReaderEndTime - created,)

    line = '%s %s(%s):%s -> :%d %s [%s] -> "%s" wait:%s ssl:%s done:%s' % \
        (request.Id, 
        chost, caddr[0], caddr[1], 
        port,
        request.RequestReaderStatus, headline, request.ServiceName or "-", 
        dtstart, dtssl, dtend)
    if request.Error:   line += f" e:[{request.Error}]"
    return line

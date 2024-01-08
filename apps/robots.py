import sys, getopt
from webpie import WPApp, Response

opts, args = getopt.getopt(sys.argv[1:], "p:")
opts = dict(opts)
port = int(opts.get("-p", 8080))

response = Response(body="Disallow: /\n", content_type="text/plain") 

print("Starting on port", port)
WPApp(response).run_server(port)

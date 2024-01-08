from webpie import WPApp, WPHandler

class Handler(WPHandler):

        def __call__(self, request, relpath, **args):
                return self.redirect(self.App.Target)

class RedirectorApp(WPApp):

        def __init__(self, handler, url):
                WPApp.__init__(self, handler)
                self.Target = url

def Redirector(url):
        return RedirectorApp(Handler, url)

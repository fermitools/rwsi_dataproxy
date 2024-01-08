import threading
class Counted(object):

    _InstanceCounts = {}
    _Lock = threading.RLock()

    @classmethod
    def __new__(cls, *params, **args):
        cname = cls.__name__
        with Counted._Lock:
            Counted._InstanceCounts[cname] = Counted._InstanceCounts.get(cname, 0) + 1
        return object.__new__(cls)

    def __del__(self):
        cname = self.__class__.__name__
        with Counted._Lock:
            Counted._InstanceCounts[cname] -= 1

    @staticmethod
    def counts():
        with Counted._Lock:
            return list(Counted._InstanceCounts.items())

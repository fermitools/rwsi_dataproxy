from pythreader import Primitive, synchronized
import string, random


class _UIDGen(Primitive):
    
    def __init__(self):
        Primitive.__init__(self)
        self.Range = 1000000
        self.Next = 1

    _alphabet=string.ascii_uppercase #+ string.ascii_lowercase #+ string.ascii_uppercase

    @synchronized
    def get(self, as_int=False):
        #print("uid.get()")
        u = self.Next
        self.Next = (self.Next + 1) % self.Range
        if as_int:
            return u
        else:
            a1 = random.choice(self._alphabet)
            a2 = random.choice(self._alphabet)
            a3 = random.choice(self._alphabet)
            return "%s%s%s-%03d" % (a1, a2, a3, u%1000)
        

_uid = _UIDGen()

def uid(u=None, as_int=False, tag=""):
    global _uid
    if u is not None:   return u
    u = _uid.get(as_int)
    return u
    
    
if __name__ == "__main__":
    
    for x in range(100000):
        u = uid(as_int=False)
        if x % 763 == 0:
            print(u)
import time, struct, socket, sys
import logs
from py3 import PY3, to_bytes
from debug import Debugged

if PY3:
        import pickle
else:
        import cPickle as pickle
 
def sanitize_key(key):
    if key is None:
        return key
    replacements = {
            ".": "_",
            " ": "_",
    }
    for old,new in replacements.items():
        key = key.replace(old, new)
    return key

class GraphiteInterface(Debugged):
    def __init__(self, config):
        Debugged.__init__(self, my_name="GraphiteInterface")
        # pickle only for now
        self.host = config.get("host")
        self.pickle_port = config.get("port")
        self.namespace = config.get("namespace")
        assert not not (self.host and self.pickle_port and self.namespace)
        self.AccumulatedData = []
        self.BatchSize = 1000
        
    def send_dict(self, data, batch_size=1000):
        """send data contained in dictionary as {k: v} to graphite dataset
        $namespace.k with current timestamp"""
        timestamp=time.time()
        post_data=[]
        # turning data dict into [('$path.$key',($timestamp,$value)),...]]
        for k,v in data.items():
            t = (self.namespace+"."+k, (timestamp, v))
            post_data.append(t)
            #logger.debug(str(t))
        return self.post_formatted_data(post_data, batch_size)
            
    def flatten_dict(self, dct, key_base):
        dct_out = {}
        for k, v in list(dct.items()):
            key = key_base + "." + k
            if type(v) == type({}):
                dct_out.update(self.flatten_dict(v,key))
            else:
                dct_out[key] = v
        return dct_out
                
    def send_timed_array(self, lst, batch_size=1000):
        # lst is a list of tuples:
        # [(timestamp, dct),...]
        # dct can be nested dictionary with data. each key branch will be represented as dot-separated string
        data_list = []
        for t, dct in lst:
            t = float(t)
            dct = self.flatten_dict(dct, self.namespace)
            data_list += [(k, (t, v)) for k, v in dct.items()]
        #for k, (t, v) in data_list:
        #    #print(t, k, v)
        return self.post_formatted_data(data_list, batch_size)
        
    def feedData(self, t, path, value):
        self.AccumulatedData.append((self.namespace + "." + path, (float(t), value)))
        if len(self.AccumulatedData) > self.BatchSize:
            self.flushData()
            
    def flushData(self):
        self.post_formatted_data(self.AccumulatedData)
        #print "sent data: ", len(self.AccumulatedData)
        #print self.AccumulatedData[:5]
        self.AccumulatedData = []
        
        
    def post_formatted_data(self, post_data, batch_size=1000):
        #
        # post_data: [(key, (t, val)),...]
        for i in range(len(post_data)//batch_size + 1):
            # pickle data
            batch = post_data[i*batch_size:(i+1)*batch_size]
            payload = pickle.dumps(batch, protocol=2)
            header = struct.pack("!L", len(payload))
            message = header + payload
            # throw data at graphite
            s=socket.socket()
            try:
                s.connect( (self.host, self.pickle_port) )
                s.sendall(message)
                #self.debug("successfully sent all data to Graphite")
            except socket.error as e:
                self.errorLog("unable to send data to graphite at %s:%d: %s" % (self.host, self.pickle_port, e))
                #print("unable to send data to graphite at %s:%d: %s\n" % (self.host, self.pickle_port, e))
            finally:
                s.close()

                    
        
        
        

import time
from pythreader import Primitive, synchronized

class IPTable(Primitive):
    
    def __init__(self, rules=[], default=True, config=None):
        Primitive.__init__(self)
        #
        # rules:
        #   [("ip.address/mask", result), ... ]
        # result can be: "accept" or "reject"
        #
        self.Default = default
        self.Rules = []
        self.RulesText = []
        
        if config is not None:
            self.Default = config.get("default", "allow") == "allow"
            rules = config.get("rules", [])
            rules = [r.split() for r in rules]
            self.RulesText = rules
        
        for ip_mask, result in rules:
            ip, mask = ip_mask.split("/",1)
            ip = self.binip(ip)
            mask = int(mask)
            self.Rules.append((ip, (-1) << (32-mask), result=="allow" or result == True, None)) # rule without expiration
    
    @synchronized
    def ban_ip_address(self, ip_address, duration=30.0):
        ip = self.binip(ip_address)
        self.Rules.insert(0, (ip, -1, False, time.time() + duration))
        
    def rules_as_text(self):
        return self.RulesText
            
    def binip(self, ip):
        bin_ip = 0
        for w in ip.split("."):
            bin_ip = (bin_ip<<8) + int(w)
        return bin_ip        
        
    @synchronized
    def allow(self, ip_address):
        addr = self.binip(ip_address)
        # remove expired rules
        self.Rules = [r for r in self.Rules if r[-1] is None or r[-1] > time.time()]
        for ip, mask, result, expiration in self.Rules:
            if ip & mask == addr & mask:
                break
        else:
            result = self.Default
        return result
        
    def deny(self, ip_address):
        return not self.allow(ip_address)
        
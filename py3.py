import sys

PY3 = sys.version_info[0] == 3

if PY3:
    def to_bytes(s):
        if isinstance(s, bytes):  return s
        return s.encode("utf-8")
    def to_str(b):
        if isinstance(b, str):  return b
        return b.decode("utf-8", "ignore")
else:
    def to_bytes(s):
        return bytes(s)
    def to_str(b):
        return str(b)


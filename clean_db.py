from DataLogger2 import DataLogger
import debug
import yaml, getopt, sys

debug.init("-")

opts, args = getopt.getopt(sys.argv[1:], "c:v")
opts = dict(opts)


config = yaml.load(open(opts["-c"], 'r'), Loader=yaml.SafeLoader)
dl = DataLogger(config)

print("cleanup...")
dl.DB._cleanup()
if "-v" in opts:
    print("vacuum...")
    dl.DB._vacuum()


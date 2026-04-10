"""Send incrementing UDP packets for WinDivert testing.

Start a receiver with ncat: ``ncat -u -l -C localhost 9111``
"""
# http://nmap.org/dist/ncat-portable-5.59BETA1.zip
import subprocess
import argparse
from time import sleep
from sys import argv, exit

__all__ = ["NCAT_EXE"]

NCAT_EXE = r'C:\Bin\nmap-7.91\ncat'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ncat num sender')
    parser.add_argument('host', type=str)
    parser.add_argument('port', type=str)
    parser.add_argument('-s', '--sleep', default=100, type=int, help='sleep time', required=False)
    parser.add_argument('--nosleep', help='nosleep', action='store_true')
    parser.add_argument('--tcp', help='use tcp instead of udp', action='store_true')
    args = parser.parse_args()

    cmd = [NCAT_EXE, '-u', '-C', args.host, args.port]
    if args.tcp:
        cmd.remove('-u')
    ncat = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    cnt = 1
    while True: # send till die
        ncat.stdin.write( ('%s\r\n' % ('-' * (1 + (cnt % 8)))).encode() )
        ncat.stdin.flush()
        cnt += 1
        print(cnt)
        if not args.nosleep:
            sleep(args.sleep/1000.0)


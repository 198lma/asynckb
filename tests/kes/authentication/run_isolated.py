"""Run disposable authentication services without changing host port policy."""

import os
import subprocess
import sys


def main():
    if not sys.platform.startswith('linux') or os.getuid() == 0:
        raise SystemExit('Run as a non-root Linux user with unshare and iproute2')
    uid, gid = os.getuid(), os.getgid()
    command = (
        'set -eu\n'
        'ip link set lo up\n'
        'printf 0 > /proc/sys/net/ipv4/ip_unprivileged_port_start\n'
        f'exec unshare -U --map-user={uid} --map-group={gid} "$@"'
    )
    return subprocess.run([
        'unshare', '-Urn', 'sh', '-c', command, 'kes-auth-isolated',
        sys.executable, '-m', 'pytest', '-q', '--assert=rewrite', '--tb=short',
        'tests/kes/authentication/test_external_authentication.py',
        'tests/kes/authentication/test_mac.py', '--kes-auth-isolated',
        'tests/kes/authentication/test_mac_whitelist.py',
        *sys.argv[1:],
    ]).returncode


if __name__ == '__main__':
    raise SystemExit(main())

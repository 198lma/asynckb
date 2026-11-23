"""Resolve the real interface rather than an arbitrary host MAC."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

from asynckb import kes
import pytest










@pytest.mark.case_id("KB-AUTH-022")
@pytest.mark.unit
@pytest.mark.skipif(sys.platform != 'linux', reason='Linux interface discovery')
def test_routed_interface_matches_operating_system():
    """测试点：实际出站接口的 MAC 与内核 sysfs 一致，不误取回环地址。"""
    if not shutil.which('ip'):
        pytest.skip('iproute2 is required for independent route verification')
    route = json.loads(subprocess.check_output(
        ['ip', '-j', 'route', 'get', '192.0.2.1'], text=True,
    ))[0]
    expected = (Path('/sys/class/net') / route['dev'] / 'address').read_text().strip()
    assert kes.client_mac_address((route['prefsrc'], 54321)) == expected

#!/usr/bin/env python3
"""Patches applied to upstream Flowseal files. Every patch asserts its anchor: if upstream changes the
file so an anchor is gone, the build FAILS instead of publishing a half-patched service.bat."""
import re

UPSTREAM_REPO = 'Flowseal/zapret-discord-youtube'

INSTALL_BLOCK = r''':: Creating the service. The command line is built by utils\install_service.ps1 straight from the
:: selected general2*.bat: zapret2 options (--lua-desync=fake:blob=x:repeats=6 ...) must not be split.
call :tcp_enable

net stop zapret >nul 2>&1
sc delete zapret >nul 2>&1

set "ZP_STRATEGY=%~dp0!selectedFile!"
set "ZP_BIN=%~dp0bin\"
set "ZP_LUA=%~dp0lua\"
set "ZP_LISTS=%~dp0lists\"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0utils\install_service.ps1"
if errorlevel 1 (
    echo.
    echo Service installation failed, see the messages above.
    pause
    goto menu
)
'''

class PatchError(RuntimeError):
    pass

def _need(cond, msg):
    if not cond:
        raise PatchError(msg)

def patch_service_bat(raw: bytes, repo: str, branch: str, version: str) -> bytes:
    s = raw.decode('utf-8').replace('\r\n', '\n')

    # 1. engine name
    _need('winws.exe' in s, 'service.bat: no "winws.exe" found (upstream layout changed?)')
    s = s.replace('winws.exe', 'winws2.exe')

    # 2. service installation: replace the argument parser + sc create with the PowerShell installer
    a_marker = ':: Args that should be followed by value'
    b_marker = 'for %%F in ("!file%choice%!") do ('
    _need(s.count(a_marker) == 1, 'service.bat: start marker of the install block not found exactly once')
    a = s.index(a_marker)
    _need(s.count(b_marker) == 1, 'service.bat: end marker of the install block not found exactly once')
    b = s.index(b_marker)
    _need(a < b, 'service.bat: install block markers are in the wrong order')
    s = s[:a] + INSTALL_BLOCK + s[b:]
    _need('sc create' not in s, 'service.bat: a leftover "sc create" remains after patching')

    # 3. version + update sources -> this repository
    s, n = re.subn(r'^set "LOCAL_VERSION=[^"]*"', 'set "LOCAL_VERSION=%s"' % version, s, count=1, flags=re.M)
    _need(n == 1, 'service.bat: LOCAL_VERSION line not found')
    # only the update sources move to this repo; links to upstream issues/discussions must stay as they are
    pat = re.compile(re.escape(UPSTREAM_REPO) + r'(?=/(?:main/\.service|refs/heads/main/\.service|releases)\b)')
    s, n = pat.subn(repo, s)
    _need(n >= 5, 'service.bat: expected >=5 update URLs pointing to %s, found %d' % (UPSTREAM_REPO, n))
    s = s.replace('refs/heads/main/.service', 'refs/heads/%s/.service' % branch)
    s = s.replace('%s/main/.service' % repo, '%s/%s/.service' % (repo, branch))
    _need(not pat.search(s), 'service.bat: an upstream update URL is left over')

    # 4. UX: a running service keeps the game-filter ports it was installed with (optional, no assert)
    s = s.replace('"Restart the zapret to apply the changes"',
                  '"Reinstall the service (menu 1) or restart the .bat to apply the changes"')

    _need(re.search(r'winws(?!2)\.exe', s) is None, 'service.bat: "winws.exe" left over')
    return s.replace('\n', '\r\n').encode('utf-8')

def patch_test_ps1(raw: bytes) -> bytes:
    s = raw.decode('utf-8')
    s, n1 = re.subn(r'-Name "winws"', '-Name "winws2"', s)
    s, n2 = re.subn(r"Name='winws\.exe'", "Name='winws2.exe'", s)
    _need(n1 >= 1 and n2 >= 1, 'utils/test zapret.ps1: process-name anchors not found (%d/%d)' % (n1, n2))
    _need('-Name "winws"' not in s and "'winws.exe'" not in s, 'test zapret.ps1: winws reference left over')
    return s.encode('utf-8')

#!/usr/bin/env python3
"""Gate before publishing: every strategy of a build must be accepted by the real nfqws2 of the same zapret2 version.

  validate.py DIST NFQWS2 PWSH [--sudo]

For each general2*.bat the service command line is produced by utils/install_service.ps1 -DryRun (exactly what
the Windows service would get), then handed unchanged to nfqws2, which initialises Lua, loads blobs, lists and
resolves every --lua-desync function. If this machine cannot bind an NFQUEUE (some CI kernels), a weaker static
mode is used (option/file check + every desync function name must exist) and that is reported loudly.
"""
import glob, os, re, shlex, shutil, subprocess, sys, tempfile
from pathlib import Path

BAD = re.compile(r'error|fail|not found|invalid|unknown|does not exist|cannot|unrecogni|required', re.I)

def run_nfqws(nfqws, args, sudo, dry=False):
    cmd = (['sudo', '-E'] if sudo else []) + (['timeout', '-s', 'INT', '3'] if not dry else []) + [nfqws, '--qnum=200'] + (['--uid=0:0'] if (sudo or os.geteuid() == 0) else []) + (['--dry-run'] if dry else []) + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout + r.stderr

def lua_functions(dist):
    names = set()
    for f in glob.glob(str(Path(dist) / 'lua' / '*.lua')):
        names |= set(re.findall(r'^function\s+([A-Za-z_][\w]*)\s*\(', Path(f).read_text(encoding='utf-8'), re.M))
    return names

def main():
    dist, nfqws, pwsh = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
    sudo = '--sudo' in sys.argv
    tmp = Path(tempfile.mkdtemp()); tmp.chmod(0o755)   # nfqws2 drops privileges after init; --uid=0:0 below keeps root, this is belt and braces
    lists = tmp / 'lists'; shutil.copytree(dist / 'lists', lists)
    for n in ('list-general-user.txt', 'list-exclude-user.txt', 'ipset-exclude-user.txt'):
        (lists / n).write_text('example.abc\n')
    lua = [str(dist / 'lua' / f) for f in ('zapret-lib.lua', 'zapret-antidpi.lua', 'zapret-flowseal.lua')]

    control = run_nfqws(nfqws, ['--lua-init=@' + lua[0], '--lua-init=@' + lua[1], '--payload=tls_client_hello',
                                '--lua-desync=fake:blob=fake_default_tls'], sudo)
    strict = 'unbinding from queue' in control and not BAD.search(control)
    print('mode: %s' % ('STRICT (real nfqws2 initialisation)' if strict else
                        'STATIC (cannot bind NFQUEUE here: option/file check + function names only)'))
    if not strict: print('control output tail:', control.strip().splitlines()[-2:])
    known = lua_functions(dist)
    env = dict(os.environ, ZP_BIN=str(dist / 'bin') + '/', ZP_LUA=str(dist / 'lua') + '/', ZP_LISTS=str(lists) + '/',
               GameFilterTCP='1024-65535', GameFilterUDP='1024-65535', DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1')
    files = sorted(glob.glob(str(dist / 'general2*.bat')))
    if not files: sys.exit('no general2*.bat in %s' % dist)
    failed = 0
    for f in files:
        name = os.path.basename(f)
        r = subprocess.run([pwsh, '-NoProfile', '-File', str(dist / 'utils' / 'install_service.ps1'), '-DryRun'],
                           capture_output=True, text=True, env=dict(env, ZP_STRATEGY=f))
        cl = r.stdout.strip()
        problems = []
        if r.returncode != 0 or not cl:
            problems.append('install_service.ps1 -DryRun failed: ' + (r.stderr or r.stdout).strip()[:200])
        else:
            toks = shlex.split(cl)
            args = [t for t in toks[1:] if not t.startswith('--wf-')]
            if '%' in cl: problems.append('unresolved %VAR% in command line')
            if any(t.startswith('--dpi-desync') for t in args): problems.append('zapret1 option left in command line')
            if re.search(r'--lua-desync(=|$)', ' '.join(a for a in args if a == '--lua-desync')): problems.append('garbled --lua-desync')
            for fn in sorted({m.group(1) for m in (re.match(r'--lua-desync=([A-Za-z_]\w*)', t) for t in args) if m} - known):
                problems.append('desync function %s is not defined in lua/' % fn)
            out = run_nfqws(nfqws, args, sudo, dry=not strict)
            ok_marker = 'unbinding from queue' if strict else 'command line parameters verified'
            if ok_marker not in out or BAD.search(out):
                bad = [l for l in out.splitlines() if BAD.search(l)] or out.strip().splitlines()[-1:]
                problems.append('nfqws2: ' + (bad[0] if bad else 'did not start')[:200])
        print(('OK    ' if not problems else 'FAIL  ') + name + ('' if not problems else '\n        ' + '\n        '.join(problems)))
        failed += bool(problems)
    # lua syntax
    luajit = shutil.which('luajit')
    for f in lua:
        if luajit and subprocess.run([luajit, '-bl', f], capture_output=True).returncode != 0:
            print('FAIL  lua syntax:', f); failed += 1
    print('%d strategies checked, %d failed, mode=%s' % (len(files), failed, 'strict' if strict else 'static'))
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(1 if failed else 0)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Keeps this repository in step with its two upstreams.

  Flowseal/zapret-discord-youtube  -> strategies, lists, fakes, service.bat   (converted to zapret2)
  bol-van/zapret2                  -> winws2.exe, WinDivert, lua scripts

Sub-commands (used by .github/workflows/sync-upstream.yml, all runnable locally):
  check       compare latest upstream releases with .service/upstream.json, decide whether to rebuild
  build       build a complete distribution into a directory
  apply       copy a build over the managed files of the repository
  zip         pack a build into the release archive
  lists-sync  refresh .service/hosts and .service/ipset-service.txt from Flowseal's main branch
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.error, urllib.request, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import convert, make_lua, patches          # noqa: E402

FLOWSEAL = 'Flowseal/zapret-discord-youtube'
ZAPRET2 = 'bol-van/zapret2'
WIN_BINS = ['winws2.exe', 'WinDivert.dll', 'WinDivert64.sys', 'cygwin1.dll']
LUA_FILES = ['zapret-lib.lua', 'zapret-antidpi.lua']
STATE = '.service/upstream.json'
# files Flowseal refreshes on main BETWEEN releases (no version bump): repo path -> minimum plausible line count
SERVICE_LISTS = {'.service/hosts': 20, '.service/ipset-service.txt': 1000, 'lists/ipset-all.txt.backup': 1000}


# ----------------------------------------------------------------------------- helpers
def log(*a): print(*a, flush=True)

def http_get(url, accept=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'zapret2-sync'})
    tok = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if tok and 'api.github.com' in url:
        req.add_header('Authorization', 'Bearer ' + tok)
    if accept:
        req.add_header('Accept', accept)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

def api(path):
    return json.loads(http_get('https://api.github.com/' + path, 'application/vnd.github+json'))

def latest_tag(repo):
    return api('repos/%s/releases/latest' % repo)['tag_name']

def release_exists(repo, tag):
    try:
        api('repos/%s/releases/tags/%s' % (repo, tag)); return True
    except urllib.error.HTTPError as e:
        if e.code == 404: return False
        raise

def make_version(flowseal, zapret2, rev=0):
    v = '%s_zapret2-%s' % (flowseal, zapret2.lstrip('v')) + ('-r%d' % rev if rev else '')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', v):          # goes into a cmd "set" and into URLs
        raise SystemExit('version string %r contains characters that are unsafe in cmd.exe' % v)
    return v

def read_state(root):
    p = Path(root) / STATE
    return json.loads(p.read_text()) if p.exists() else {}

def set_output(**kv):
    f = os.environ.get('GITHUB_OUTPUT')
    for k, v in kv.items():
        log('::output %s=%s' % (k, v))
        if f:
            with open(f, 'a') as fh: fh.write('%s=%s\n' % (k, v))

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------- check
def cmd_check(a):
    state = read_state(a.root)
    fl, z2 = a.flowseal_tag or latest_tag(FLOWSEAL), a.zapret2_tag or latest_tag(ZAPRET2)
    rev = int(state.get('rev', 0))
    version = make_version(fl, z2, rev)
    why = []
    if a.force: why.append('forced')
    if state.get('flowseal') != fl: why.append('Flowseal %s -> %s' % (state.get('flowseal'), fl))
    if state.get('zapret2') != z2: why.append('zapret2 %s -> %s' % (state.get('zapret2'), z2))
    if state.get('built_for') != a.repo: why.append('built for %s, running in %s' % (state.get('built_for'), a.repo))
    if not why and not a.skip_release_check and not release_exists(a.repo, version):
        why.append('release %s does not exist yet' % version)
    log('upstream: Flowseal=%s zapret2=%s -> version %s' % (fl, z2, version))
    log('rebuild needed: ' + ('; '.join(why) if why else 'no, up to date'))
    set_output(build=str(bool(why)).lower(), flowseal=fl, zapret2=z2, version=version, rev=rev, reason=('; '.join(why) or 'none'))


# ----------------------------------------------------------------------------- build
def fetch_flowseal(tag, dest):
    log('cloning %s @ %s' % (FLOWSEAL, tag))
    subprocess.run(['git', 'clone', '--quiet', '--depth', '1', '--branch', tag,
                    'https://github.com/%s.git' % FLOWSEAL, str(dest)], check=True)

def fetch_zapret2(tag, dest_zip):
    rel = api('repos/%s/releases/tags/%s' % (ZAPRET2, tag))
    assets = {x['name']: x['browser_download_url'] for x in rel['assets']}
    zname = next((n for n in assets if re.fullmatch(r'zapret2-v[\d.]+\.zip', n)), None)
    if not zname or 'sha256sum.txt' not in assets:
        raise SystemExit('zapret2 %s: expected assets zapret2-v*.zip and sha256sum.txt, got %s' % (tag, sorted(assets)))
    log('downloading', zname)
    Path(dest_zip).write_bytes(http_get(assets[zname]))
    Path(str(dest_zip) + '.sums').write_bytes(http_get(assets['sha256sum.txt']))

def verify_against_sums(files, sums_text):
    """files: {relative path inside the zip: Path on disk}. Every shipped binary must be listed and match."""
    table = {}
    for line in sums_text.splitlines():
        m = re.match(r'([0-9a-fA-F]{64})\s+\*?(.+)$', line.strip())
        if m: table[m.group(2).split('/', 1)[-1]] = m.group(1).lower()
    for rel, p in files.items():
        want = table.get(rel)
        if not want: raise SystemExit('no checksum listed for %s in sha256sum.txt - refusing to ship it' % rel)
        if sha256(p) != want: raise SystemExit('CHECKSUM MISMATCH for %s' % rel)
    log('sha256 verified for %d zapret2 files' % len(files))

def cmd_build(a):
    out = Path(a.out)
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix='z2sync-'))

    fl_dir = Path(a.flowseal_dir) if a.flowseal_dir else tmp / 'flowseal'
    if not a.flowseal_dir: fetch_flowseal(a.flowseal_tag, fl_dir)
    z2_zip = Path(a.zapret2_zip) if a.zapret2_zip else tmp / 'zapret2.zip'
    if not a.zapret2_zip: fetch_zapret2(a.zapret2_tag, z2_zip)
    sums = Path(str(z2_zip) + '.sums')
    z2_dir = tmp / 'zapret2'
    with zipfile.ZipFile(z2_zip) as z: z.extractall(z2_dir)
    z2_root = next(p for p in z2_dir.iterdir() if p.is_dir())

    version = make_version(a.flowseal_tag, a.zapret2_tag, a.rev)
    if a.save_zapret2_src:
        shutil.copytree(z2_root, a.save_zapret2_src, dirs_exist_ok=True)

    # --- zapret2 engine
    (out / 'bin').mkdir()
    (out / 'lua').mkdir()
    win = z2_root / 'binaries' / 'windows-x86_64'
    shipped = {}
    for n in WIN_BINS:
        shutil.copy2(win / n, out / 'bin' / n); shipped['binaries/windows-x86_64/' + n] = win / n
    for n in LUA_FILES:                       # sha256sum.txt covers binaries/ only; lua comes from the same release archive
        shutil.copy2(z2_root / 'lua' / n, out / 'lua' / n)
    if sums.exists():
        verify_against_sums(shipped, sums.read_text())
    else:
        log('WARNING: no sha256sum.txt supplied, engine files are NOT verified')
    make_lua.generate(z2_root / 'lua' / 'zapret-antidpi.lua', out / 'lua' / 'zapret-flowseal.lua')

    # --- Flowseal content
    for f in sorted((fl_dir / 'bin').glob('*.bin')): shutil.copy2(f, out / 'bin' / f.name)
    shutil.copytree(fl_dir / 'lists', out / 'lists')
    shutil.copytree(fl_dir / 'utils', out / 'utils', ignore=shutil.ignore_patterns('check_updates.enabled', 'game_filter.enabled', 'test results'))
    (out / '.service').mkdir()
    for n in ('hosts', 'ipset-service.txt'): shutil.copy2(fl_dir / '.service' / n, out / '.service' / n)

    # --- strategies + patches
    report = convert.convert_dir(str(fl_dir), str(out))
    (out / 'service.bat').write_bytes(patches.patch_service_bat((fl_dir / 'service.bat').read_bytes(), a.repo, a.branch, version))
    ps = out / 'utils' / 'test zapret.ps1'
    ps.write_bytes(patches.patch_test_ps1(ps.read_bytes()))

    # --- licences
    (out / 'licenses').mkdir()
    shutil.copy2(fl_dir / 'LICENSE.txt', out / 'licenses' / 'LICENSE-flowseal.txt')
    shutil.copy2(z2_root / 'docs' / 'LICENSE.txt', out / 'licenses' / 'LICENSE-zapret2.txt')
    (out / 'licenses' / 'THIRD-PARTY.txt').write_text(
        'bin\\winws2.exe, WinDivert.dll, WinDivert64.sys, cygwin1.dll are redistributed unmodified from the\n'
        'zapret2 release %s (https://github.com/%s). WinDivert and Cygwin are separate projects with their own\n'
        'licences; see their upstream distributions.\n'
        'Strategies are converted from %s release %s.\n' % (a.zapret2_tag, ZAPRET2, FLOWSEAL, a.flowseal_tag))

    # --- our own files on top
    shutil.copytree(HERE / 'overlay', out, dirs_exist_ok=True)

    # --- state
    (out / '.service' / 'version.txt').write_text(version + '\n')
    (out / STATE).write_text(json.dumps({'flowseal': a.flowseal_tag, 'zapret2': a.zapret2_tag, 'rev': a.rev,
                                         'built_for': a.repo, 'version': version}, indent=2) + '\n')
    notes = [(n, x) for n, x in report if x]
    log('built %s: %d strategies, %d with notes' % (version, len(report), len(notes)))
    for n, x in notes: log('  note', n, x)
    shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- apply / zip
MANAGED_DIRS = ['bin', 'lua', 'lists', 'utils', 'licenses']
MANAGED_FILES = ['service.bat', '.service/version.txt', '.service/upstream.json', '.service/hosts', '.service/ipset-service.txt']

def cmd_apply(a):
    build, root = Path(a.build), Path(a.root)
    for p in root.glob('general2*.bat'): p.unlink()
    for d in MANAGED_DIRS:
        if (root / d).exists(): shutil.rmtree(root / d)
        shutil.copytree(build / d, root / d)
    for p in build.glob('general2*.bat'): shutil.copy2(p, root / p.name)
    (root / '.service').mkdir(exist_ok=True)
    for f in MANAGED_FILES: shutil.copy2(build / f, root / f)
    log('applied build to', root)

def cmd_zip(a):
    build, out = Path(a.build), Path(a.out)
    top = 'zapret2-discord-youtube-' + a.version
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for d in MANAGED_DIRS:
            for p in sorted((build / d).rglob('*')):
                if p.is_file(): z.write(p, '%s/%s' % (top, p.relative_to(build).as_posix()))
        for p in sorted(list(build.glob('*.bat'))):
            z.write(p, '%s/%s' % (top, p.name))
    log('wrote', out, '(%d bytes)' % out.stat().st_size)


# ----------------------------------------------------------------------------- lists-sync
def cmd_lists_sync(a):
    base = 'https://raw.githubusercontent.com/%s/refs/heads/main/' % FLOWSEAL
    changed = []
    for rel, min_lines in SERVICE_LISTS.items():
        data = (Path(a.override_dir) / rel).read_bytes() if a.override_dir else http_get(base + rel)
        n = data.count(b'\n')
        if n < min_lines:
            raise SystemExit('%s from upstream has only %d lines (< %d): refusing to overwrite' % (rel, n, min_lines))
        dst = Path(a.root) / rel
        if not dst.exists() or dst.read_bytes() != data:
            dst.parent.mkdir(parents=True, exist_ok=True); dst.write_bytes(data); changed.append(rel)
    log('service lists changed:', changed or 'none')
    set_output(lists_changed=str(bool(changed)).lower())


# ----------------------------------------------------------------------------- cli
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check'); c.set_defaults(f=cmd_check)
    c.add_argument('--repo', required=True); c.add_argument('--root', default=str(ROOT))
    c.add_argument('--force', action='store_true'); c.add_argument('--skip-release-check', action='store_true')
    c.add_argument('--flowseal-tag'); c.add_argument('--zapret2-tag')
    b = sub.add_parser('build'); b.set_defaults(f=cmd_build)
    b.add_argument('--repo', required=True); b.add_argument('--branch', default='main')
    b.add_argument('--flowseal-tag', required=True); b.add_argument('--zapret2-tag', required=True)
    b.add_argument('--rev', type=int, default=0); b.add_argument('--out', required=True)
    b.add_argument('--flowseal-dir'); b.add_argument('--zapret2-zip')
    b.add_argument('--save-zapret2-src', help='copy the extracted zapret2 release here (to compile nfqws2 for validation)')
    ap = sub.add_parser('apply'); ap.set_defaults(f=cmd_apply)
    ap.add_argument('--build', required=True); ap.add_argument('--root', default=str(ROOT))
    z = sub.add_parser('zip'); z.set_defaults(f=cmd_zip)
    z.add_argument('--build', required=True); z.add_argument('--version', required=True); z.add_argument('--out', required=True)
    l = sub.add_parser('lists-sync'); l.set_defaults(f=cmd_lists_sync)
    l.add_argument('--root', default=str(ROOT)); l.add_argument('--override-dir')
    a = p.parse_args()
    a.f(a)

if __name__ == '__main__':
    main()

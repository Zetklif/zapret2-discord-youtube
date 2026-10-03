#!/usr/bin/env python3
"""Convert Flowseal winws.exe (zapret1) strategy .bat files to winws2.exe (zapret2)."""
import re, sys, os, glob, shlex


PASS = {'--filter-tcp','--filter-udp','--filter-l3','--hostlist','--hostlist-exclude','--hostlist-domains',
        '--hostlist-exclude-domains','--ipset','--ipset-exclude'}
L7MAP = {'discord':'discord','stun':'stun','quic':'quic','unknown':'unknown','tls':'tls','http':'http'}

def tokenize(s):
    # split on whitespace, keep "..." groups intact (they hold %VARS% and may contain spaces)
    return re.findall(r'(?:[^\s"]+|"[^"]*")+', s)

def blobname(path):
    path = path.replace('%BIN%','')
    m = re.search(r'([^\\/"]+?)\.bin"?$', path)
    return re.sub(r'[^A-Za-z0-9_]', '_', m.group(1)) if m else None

def parse_profile(toks):
    p = {'pass': [], 'fake': {}, 'mods': [], 'fooling': [], 'desync': []}
    for t in toks:
        if t.startswith('--') and '=' in t: k, v = t.split('=', 1)
        else: k, v = t, None
        if k in PASS: p['pass'].append((k, v))
        elif k == '--filter-l7': p['pass'].append((k, ','.join(L7MAP.get(x, x) for x in v.split(','))))
        elif k == '--dpi-desync': p['desync'] = v.split(',')
        elif k == '--dpi-desync-fooling': p['fooling'] = v.split(',')
        elif k.startswith('--dpi-desync-fake-') and k != '--dpi-desync-fake-tls-mod':
            if k == '--dpi-desync-fake-tcp-mod': continue
            p['fake'].setdefault(k[len('--dpi-desync-fake-'):], []).append(v)
        elif k == '--dpi-desync-fake-tls-mod': p['mods'].append(v)
        elif k.startswith('--dpi-desync-'): p[k[len('--dpi-desync-'):]] = v
        elif k == '--ip-id': p['ip-id'] = v
        else: p.setdefault('unknown', []).append(t)
    return p

NEED_ALT=[False]
blobs = {}   # name -> original quoted path
def blob_ref(v):
    """fake value -> (blob arg, is_tls_file)"""
    if v is None or v == '^!' or v == '!': return 'fake_default_tls'
    if v.startswith('0x'): return v
    n = blobname(v); blobs[n] = v
    return n

def fooling_args(p, fns):
    a = []
    f = p['fooling']
    if 'md5sig' in f: a.append('tcp_md5')
    if 'badseq' in f:
        a.append('tcp_seq=%s' % p.get('badseq-increment', '-10000'))
        a.append('tcp_ack=%s' % p.get('badack-increment', '-66000'))
        a.append('tcp_ts_up')
    if 'ts' in f: a.append('tcp_ts=%s' % p.get('ts-increment', '-600000'))
    if 'datanoack' in f: a.append('tcp_flags_unset=ack')
    if 'badsum' in f: a.append('badsum')
    return a

def tls_mod_arg(p):
    if p['mods']:
        m = p['mods'][-1]
        return None if m == 'none' else m
    return None

def render(p, cls, notes):
    """Build desync chain text for payload class cls."""
    out = []
    ipid = ['ip_id=%s' % p['ip-id']] if p.get('ip-id') else []
    foo = fooling_args(p, None)
    rep = ['repeats=%s' % p['repeats']] if p.get('repeats') else []
    has_fake_sender = any(x in ('fake','fakedsplit','hostfakesplit','fakeddisorder') for x in p['desync'])
    anyp = p.get('any-protocol') == '1'
    pl = ['payload=known,unknown'] if anyp else []
    pos = p.get('split-pos'); seqovl = p.get('split-seqovl'); pat = p.get('split-seqovl-pattern')
    for fn in p['desync']:
        if fn == 'fake':
            lst = p['fake'].get({'tls':'tls','http':'http','quic':'quic','unk':'unknown',
                                 'unkudp':'unknown-udp'}.get(cls, cls))
            mod = tls_mod_arg(p)
            fakes = []
            if cls == 'tls':
                vals = lst if lst else [None]
                for v in vals:
                    b = blob_ref(v)
                    is_tls = b == 'fake_default_tls' or (v and 'tls_clienthello' in v)
                    m = mod if is_tls else None
                    if not lst and not p['mods']: m = 'rnd,rndsni,dupsid'   # nfqws1 default mods
                    fakes.append((b, m))
            elif cls == 'http':
                for v in (lst or [None]): fakes.append(('fake_default_http' if v is None else blob_ref(v), None))
            elif cls == 'quic':
                for v in (lst or [None]): fakes.append(('fake_default_quic' if v is None else blob_ref(v), None))
            elif cls in ('discord','stun'):
                for v in (lst or [None]): fakes.append(('0x' + '00'*64 if v is None else blob_ref(v), None))
            elif cls == 'unknown_udp':
                lst = p['fake'].get('unknown-udp')
                for v in (lst or [None]): fakes.append(('0x' + '00'*64 if v is None else blob_ref(v), None))
            elif cls == 'unknown_tcp':
                lst = p['fake'].get('unknown')
                for v in (lst or [None]): fakes.append(('0x' + '00'*256 if v is None else blob_ref(v), None))
            for b, m in fakes:
                args = ['blob=' + b] + rep + foo + ipid + (['tls_mod=' + m] if m else []) + pl
                out.append('--lua-desync=fake:' + ':'.join(args))
        elif fn in ('multisplit','multidisorder'):
            args = []
            if pos: args.append('pos=' + pos)
            if seqovl: args.append('seqovl=' + seqovl)
            if pat:
                args.append('seqovl_pattern=' + (blob_ref(pat) if not pat.startswith('0x') else pat))
            args += ipid + pl
            if not has_fake_sender or True:
                pass
            if not [x for x in p['desync'] if x == 'fake'] and rep: args += rep
            out.append('--lua-desync=%s%s' % (fn, (':' + ':'.join(args)) if args else ''))
        elif fn == 'fakedsplit':
            args = []
            if pos: args.append('pos=' + pos)
            pt = p.get('fakedsplit-pattern')
            if pt and pt != '0x00': args.append('pattern=' + blob_ref(pt))
            mod = p.get('fakedsplit-mod', '')
            m = re.search(r'altorder=(\d+)', mod)
            if m: notes.append('fakedsplit altorder=%s not ported (check zapret2 docs)' % m.group(1))
            args += rep + foo + ipid + pl
            out.append('--lua-desync=fakedsplit:' + ':'.join(a for a in args if a))
        elif fn == 'hostfakesplit':
            args = []
            mod = p.get('hostfakesplit-mod', '')
            alt = 'altorder=1' in mod.split(',')
            for part in mod.split(','):
                if part.startswith('host='): args.append(part)
            if p.get('hostfakesplit-midhost'): args.append('midhost=' + p['hostfakesplit-midhost'])
            if not alt: args.append('nofake2')      # nfqws1 sends a single fake host; zapret2 stock sends two
            args += rep + foo + ipid + pl
            if alt: NEED_ALT[0] = True
            out.append('--lua-desync=%s:%s' % ('hostfakesplit_alt' if alt else 'hostfakesplit', ':'.join(args)))
        elif fn == 'syndata':
            out.append('--lua-desync=syndata' + (':' + ':'.join(foo) if foo else ''))
        else:
            notes.append('UNPORTED desync: ' + fn)
    return out

def convert_profile(p, notes):
    pr = list(p['pass'])
    ports_tcp = any(k == '--filter-tcp' for k, _ in pr)
    ports_udp = any(k == '--filter-udp' for k, _ in pr)
    l7 = next((v for k, v in pr if k == '--filter-l7'), None)
    anyp = p.get('any-protocol') == '1'
    cut = p.get('cutoff')
    parts = []
    if not p['desync']:
        return [' '.join(f'{k}={v}' if v is not None else k for k, v in pr)]
    # classes
    classes = []   # (payload list, class key)
    if ports_tcp:
        if anyp:
            classes = [('tls_client_hello','tls'), ('http_req','http'), ('unknown','unknown_tcp')]
        else:
            classes = [('tls_client_hello','tls'), ('http_req','http')]
    else:
        if anyp:
            classes = [('unknown','unknown_udp')]
            if p['fake'].get('stun'): classes.append(('stun','stun'))
            if p['fake'].get('discord'): classes.append(('discord_ip_discovery','discord'))
            if p['fake'].get('quic'): classes.append(('quic_initial','quic'))
            if not p['fake'].get('unknown-udp') and not p['fake'].get('unknown'):
                notes.append('any-protocol UDP without custom fake: using 64 zero bytes')
        else:
            l7s = (l7 or '').split(',') if l7 else ['quic']
            for x in l7s:
                if x == 'quic': classes.append(('quic_initial','quic'))
                if x == 'stun': classes.append(('stun','stun'))
                if x == 'discord': classes.append(('discord_ip_discovery','discord'))
            if not classes: classes = [('quic_initial','quic')]
            if not l7: classes = [('quic_initial','quic')]
    # syndata handled as separate empty-payload group, keeping instance order
    head = ' '.join(f'{k}={v}' if v is not None else k for k, v in pr)
    rng = []
    if ports_tcp and not anyp and not cut: rng = ['--out-range=-d10']
    if cut:
        m = re.match(r'n(\d+)', cut)
        rng = ['--out-range=-n%d' % (int(m.group(1)) - 1)] if m else []   # nfqws1 cutoff=nN is exclusive, -nM is inclusive
    chains = []
    for payloads, cls in classes:
        chains.append((payloads, render(p, cls, notes)))
    # merge classes whose chain is identical (e.g. split-only strategies)
    merged = []
    for payloads, ch in chains:
        for m in merged:
            if m[1] == ch: m[0].append(payloads); break
        else: merged.append([[payloads], ch])
    # syndata needs payload=empty group
    seg = []
    for plist, ch in merged:
        syn = [c for c in ch if c.startswith('--lua-desync=syndata')]
        rest = [c for c in ch if not c.startswith('--lua-desync=syndata')]
        if syn and ports_tcp and not seg:
            seg.append('--payload=empty ' + ' '.join(syn))
        if rest: seg.append('--payload=' + ','.join(plist) + ' ' + ' '.join(rest))
    return [head + ' ' + ' '.join(rng)] + ['  ' + s for s in seg]

def convert_file(path):
    raw = open(path, encoding='utf-8').read().replace('\r', '')
    m = re.search(r'^(start .*?winws\.exe"?\s*)(.*)$', raw, re.S | re.M)
    pre = raw[:m.start()]
    body = raw[m.start():]
    first, rest = body.split('winws.exe"', 1)
    argtext = rest.replace('^\n', ' ').replace('\n', ' ')
    toks = tokenize(argtext)
    wf = [t for t in toks if t.startswith('--wf-')]
    toks = [t for t in toks if not t.startswith('--wf-')]
    profiles, cur = [], []
    for t in toks:
        if t == '--new': profiles.append(cur); cur = []
        else: cur.append(t)
    profiles.append(cur)
    global blobs; blobs = {}; NEED_ALT[0] = False
    notes = []
    lines = []
    for pr in profiles:
        pp = parse_profile(pr)
        if pp.get('unknown'): notes.append('unrecognised: %s' % pp['unknown'])
        lines.append(convert_profile(pp, notes))
    wf2 = []
    for t in wf:
        wf2.append(t.replace('--wf-tcp=', '--wf-tcp-out=').replace('--wf-udp=', '--wf-udp-out='))
    blobl = ['--blob=%s:@%s' % (n, v) for n, v in sorted(blobs.items())]
    pre = pre.replace('set "LISTS=', 'set "LUA=%~dp0lua\\"\nset "LISTS=')
    s = pre + 'start "zapret2: %~n0" /min "%BIN%winws2.exe" ' + ' '.join(wf2) + ' ^\n'
    s += '--lua-init=@"%LUA%zapret-lib.lua" --lua-init=@"%LUA%zapret-antidpi.lua"' + (' --lua-init=@"%LUA%zapret-flowseal.lua"' if NEED_ALT[0] else '') + ' ^\n'
    for b in blobl: s += b + ' ^\n'
    for i, ln in enumerate(lines):
        last = i == len(lines) - 1
        for j, l in enumerate(ln):
            tail = '' if (last and j == len(ln) - 1) else (' --new ^' if j == len(ln) - 1 else ' ^')
            s += l + tail + '\n'
    return s.replace('\n', '\r\n'), notes

FATAL = ('UNPORTED', 'unrecognised')

def convert_dir(src, dst):
    """Convert every general*.bat in src into general2*.bat in dst.
    Returns [(name, [notes])]. Raises RuntimeError on anything that cannot be ported faithfully."""
    os.makedirs(dst, exist_ok=True)
    files = sorted(glob.glob(os.path.join(src, 'general*.bat')))
    if not files:
        raise RuntimeError('no general*.bat found in %s' % src)
    report, fatal = [], []
    for f in files:
        out, notes = convert_file(f)
        if 'set "LUA=' not in out:
            raise RuntimeError('%s: header has no set "LISTS=..." line to hang LUA on; upstream layout changed' % f)
        name = os.path.basename(f).replace('general', 'general2', 1)
        open(os.path.join(dst, name), 'w', encoding='utf-8', newline='').write(out)
        report.append((name, notes))
        fatal += ['%s: %s' % (name, n) for n in notes if n.startswith(FATAL)]
    if fatal:
        raise RuntimeError('unportable constructs:\n  ' + '\n  '.join(fatal))
    return report

if __name__ == '__main__':
    for n, nt in convert_dir(sys.argv[1], sys.argv[2]):
        print(n, '|', '; '.join(nt) if nt else 'ok')

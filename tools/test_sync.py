#!/usr/bin/env python3
"""Offline tests for the update logic. Run: python3 -m unittest discover -s tools -p 'test_*.py'"""
import hashlib, json, os, sys, tempfile, unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync, patches   # noqa: E402

def write_state(root, **kw):
    st = {'flowseal': '1.10.3', 'zapret2': 'v1.0.5.2', 'rev': 0, 'built_for': 'me/repo'}
    st.update(kw)
    p = Path(root) / sync.STATE; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(st))

def run_check(root, **kw):
    args = dict(repo='me/repo', root=str(root), force=False, skip_release_check=False,
                flowseal_tag='1.10.3', zapret2_tag='v1.0.5.2'); args.update(kw)
    out = {}
    with mock.patch.object(sync, 'set_output', lambda **k: out.update(k)), mock.patch.object(sync, 'log', lambda *a: None):
        sync.cmd_check(Namespace(**args))
    return out

class CheckLogic(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); write_state(self.d)
    def test_up_to_date_does_nothing(self):
        with mock.patch.object(sync, 'release_exists', return_value=True):
            self.assertEqual(run_check(self.d)['build'], 'false')
    def test_new_flowseal_release_triggers_build(self):
        o = run_check(self.d, flowseal_tag='1.10.4', skip_release_check=True)
        self.assertEqual(o['build'], 'true'); self.assertEqual(o['version'], '1.10.4_zapret2-1.0.5.2')
    def test_new_zapret2_release_triggers_build(self):
        o = run_check(self.d, zapret2_tag='v1.0.6', skip_release_check=True)
        self.assertEqual(o['build'], 'true'); self.assertEqual(o['version'], '1.10.3_zapret2-1.0.6')
    def test_both_new(self):
        o = run_check(self.d, flowseal_tag='1.11.0', zapret2_tag='v1.1.0', skip_release_check=True)
        self.assertEqual((o['build'], o['version']), ('true', '1.11.0_zapret2-1.1.0'))
    def test_first_run_in_a_new_repository_rebuilds(self):
        write_state(self.d, built_for='OWNER/REPO')
        self.assertIn('built for', run_check(self.d, skip_release_check=True)['reason'])
    def test_missing_release_is_created(self):
        with mock.patch.object(sync, 'release_exists', return_value=False):
            o = run_check(self.d)
        self.assertEqual(o['build'], 'true'); self.assertIn('does not exist', o['reason'])
    def test_force(self):
        self.assertEqual(run_check(self.d, force=True, skip_release_check=True)['build'], 'true')
    def test_rev_suffix(self):
        write_state(self.d, rev=2)
        self.assertEqual(run_check(self.d, force=True, skip_release_check=True)['version'], '1.10.3_zapret2-1.0.5.2-r2')
    def test_no_state_file_builds(self):
        self.assertEqual(run_check(tempfile.mkdtemp(), skip_release_check=True)['build'], 'true')

class Version(unittest.TestCase):
    def test_unsafe_version_rejected(self):
        with self.assertRaises(SystemExit): sync.make_version('1.0 & calc', 'v1')
        with self.assertRaises(SystemExit): sync.make_version('1.0', 'v1%PATH%')

class Checksums(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); self.f = self.d / 'winws2.exe'; self.f.write_bytes(b'binary')
        self.h = hashlib.sha256(b'binary').hexdigest()
    def test_match(self):
        sync.verify_against_sums({'binaries/windows-x86_64/winws2.exe': self.f},
                                 '%s  zapret2-v1/binaries/windows-x86_64/winws2.exe\n' % self.h)
    def test_mismatch_refused(self):
        with self.assertRaises(SystemExit):
            sync.verify_against_sums({'binaries/windows-x86_64/winws2.exe': self.f},
                                     '%s  zapret2-v1/binaries/windows-x86_64/winws2.exe\n' % ('0' * 64))
    def test_unlisted_refused(self):
        with self.assertRaises(SystemExit): sync.verify_against_sums({'binaries/windows-x86_64/winws2.exe': self.f}, '')

class ListsSync(unittest.TestCase):
    def mk(self, lines):
        d = Path(tempfile.mkdtemp())
        for rel, n in lines.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True); (d / rel).write_bytes(b'x\n' * n)
        return d
    def run_sync(self, root, up):
        out = {}
        with mock.patch.object(sync, 'set_output', lambda **k: out.update(k)), mock.patch.object(sync, 'log', lambda *a: None):
            sync.cmd_lists_sync(Namespace(root=str(root), override_dir=str(up)))
        return out
    GOOD = {'.service/hosts': 82, '.service/ipset-service.txt': 33000, 'lists/ipset-all.txt.backup': 33000}
    def test_updates_and_idempotent(self):
        root, up = self.mk({k: 5000 for k in self.GOOD}), self.mk(self.GOOD)
        self.assertEqual(self.run_sync(root, up)['lists_changed'], 'true')
        self.assertEqual(self.run_sync(root, up)['lists_changed'], 'false')
        self.assertEqual((root / 'lists/ipset-all.txt.backup').stat().st_size, 66000)
    def test_truncated_upstream_does_not_wipe_ours(self):
        root = self.mk(self.GOOD); bad = dict(self.GOOD); bad['.service/ipset-service.txt'] = 3
        with self.assertRaises(SystemExit): self.run_sync(root, self.mk(bad))
        self.assertEqual((root / '.service/ipset-service.txt').stat().st_size, 66000)

class Patches(unittest.TestCase):
    SRC = ('set "LOCAL_VERSION=1.0"\r\nset "u=https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/main/.service/version.txt"\r\n'
           'set "r=https://github.com/Flowseal/zapret-discord-youtube/releases/latest"\r\n'
           'set "a=https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/refs/heads/main/.service/hosts"\r\n'
           'set "b=https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/refs/heads/main/.service/ipset-service.txt"\r\n'
           'set "c=https://github.com/Flowseal/zapret-discord-youtube/releases/tag/"\r\n'
           'echo see https://github.com/Flowseal/zapret-discord-youtube/issues/7490\r\n'
           'winws.exe\r\n:: Args that should be followed by value\r\nsc create zapret\r\n'
           'for %%F in ("!file%choice%!") do (\r\n')
    def test_ok_and_issue_links_untouched(self):
        out = patches.patch_service_bat(self.SRC.encode(), 'me/repo', 'main', 'V1').decode()
        self.assertIn('me/repo/main/.service/version.txt', out); self.assertIn('LOCAL_VERSION=V1', out)
        self.assertIn('Flowseal/zapret-discord-youtube/issues/7490', out)
        self.assertNotIn('sc create', out); self.assertIn('install_service.ps1', out)
    def test_missing_anchor_fails(self):
        with self.assertRaises(patches.PatchError):
            patches.patch_service_bat(self.SRC.replace('Args that should', 'Changed').encode(), 'me/repo', 'main', 'V1')

if __name__ == '__main__':
    unittest.main(verbosity=2)

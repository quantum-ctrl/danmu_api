"""Offline regression tests: python3 .github/scripts/test-sync-upstream.py."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('sync-upstream.sh').resolve()


class SyncTests(unittest.TestCase):
    def git(self, *args, cwd=None):
        return subprocess.check_output(['git', *args], cwd=cwd or self.local,
                                       stderr=subprocess.DEVNULL, text=True).strip()

    def write(self, repo, path, content):
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)

    def commit(self, repo, message):
        self.git('add', '-A', cwd=repo)
        self.git('commit', '-m', message, cwd=repo)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.upstream, self.local, self.origin = [root / p for p in ('upstream', 'local', 'origin')]
        self.git('init', '-b', 'main', str(self.upstream), cwd=root)
        self.git('config', 'user.name', 'Test', cwd=self.upstream)
        self.git('config', 'user.email', 'test@example.com', cwd=self.upstream)
        self.write(self.upstream, '.github/workflows/sync.yml', 'original\n')
        self.write(self.upstream, '.github/workflows/delete.yml', 'delete me\n')
        self.write(self.upstream, 'app.txt', 'original\n')
        self.commit(self.upstream, 'base')
        self.git('clone', '--bare', str(self.upstream), str(self.origin), cwd=root)
        self.git('clone', str(self.origin), str(self.local), cwd=root)
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.com')

    def sync(self, success=True):
        env = dict(os.environ, UPSTREAM_REPOSITORY=str(self.upstream),
                   GITHUB_STEP_SUMMARY=str(self.local.parent / 'summary'))
        result = subprocess.run(['bash', str(SCRIPT)], cwd=self.local, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result.stdout

    def test_workflow_add_modify_delete_and_repeat(self):
        self.write(self.upstream, 'app.txt', 'updated\n')
        self.write(self.upstream, '.github/workflows/sync.yml', 'updated\n')
        self.write(self.upstream, '.github/workflows/new.yml', 'new\n')
        (self.upstream / '.github/workflows/delete.yml').unlink()
        self.commit(self.upstream, 'upstream update')
        before = self.git('rev-parse', 'HEAD')
        self.sync()
        self.assertEqual((self.local / 'app.txt').read_text(), 'updated\n')
        self.assertEqual(self.git('diff', before, 'HEAD', '--', '.github/workflows'), '')
        self.git('merge-base', '--is-ancestor', self.git('rev-parse', 'HEAD', cwd=self.upstream), 'HEAD')
        after = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.git('rev-parse', 'main', cwd=self.origin), after)
        self.assertIn('Already up to date', self.sync())
        self.assertEqual(self.git('rev-parse', 'HEAD'), after)
        self.write(self.upstream, 'next.txt', 'next update\n')
        self.commit(self.upstream, 'next update')
        self.sync()
        self.assertTrue((self.local / 'next.txt').exists())
        self.assertEqual(self.git('diff', before, 'HEAD', '--', '.github/workflows'), '')

    def test_workflow_conflict_is_preserved(self):
        self.write(self.local, '.github/workflows/sync.yml', 'local\n')
        self.commit(self.local, 'local workflow')
        self.write(self.upstream, '.github/workflows/sync.yml', 'upstream\n')
        self.commit(self.upstream, 'upstream workflow')
        self.sync()
        self.assertEqual((self.local / '.github/workflows/sync.yml').read_text(), 'local\n')
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_application_conflict_aborts_without_push(self):
        self.write(self.local, 'app.txt', 'local\n')
        self.commit(self.local, 'local app')
        before, remote = self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'main', cwd=self.origin)
        self.write(self.upstream, 'app.txt', 'upstream\n')
        self.commit(self.upstream, 'upstream app')
        self.sync(success=False)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.git('rev-parse', 'main', cwd=self.origin), remote)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_no_changes(self):
        before = self.git('rev-parse', 'HEAD')
        self.assertIn('Already up to date', self.sync())
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)

    def test_concurrent_remote_changes_are_not_overwritten(self):
        other = self.local.parent / 'other'
        self.git('clone', str(self.origin), str(other))
        self.git('config', 'user.name', 'Test', cwd=other)
        self.git('config', 'user.email', 'test@example.com', cwd=other)
        self.write(other, 'remote.txt', 'remote\n')
        self.commit(other, 'concurrent change')
        self.git('push', 'origin', 'main', cwd=other)
        remote = self.git('rev-parse', 'main', cwd=self.origin)
        self.write(self.upstream, 'next.txt', 'next\n')
        self.commit(self.upstream, 'next update')
        self.sync(success=False)
        self.assertEqual(self.git('rev-parse', 'main', cwd=self.origin), remote)


if __name__ == '__main__':
    unittest.main()

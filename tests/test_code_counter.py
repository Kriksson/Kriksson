import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/update_code_counter.py'
spec = importlib.util.spec_from_file_location('counter', SCRIPT)
counter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(counter)


class CounterTests(unittest.TestCase):
    def test_public_contribution_heading_not_calendar_noise(self):
        html = '<span>999</span><h2 id="js-contribution-activity-description"> 1,234\n contributions in the last year </h2><span>888</span>'
        self.assertEqual(counter.parse_contributions(html), 1234)
        self.assertEqual(counter.parse_contributions('<h2 id="js-contribution-activity-description">0 contributions in the last year</h2>'), 0)
        with self.assertRaises(RuntimeError):
            counter.parse_contributions('<h2>12 contributions in the last year</h2>')

    def test_public_repo_count_includes_profile_and_forks_but_never_private(self):
        repos = [{'private':False, 'name':name, 'owner':{'login':'Kriksson'}} for name in ['demo','Kriksson','fork']]
        repos += [{'private':True,'owner':{'login':'Kriksson'}}, {'private':False,'owner':{'login':'Elsewhere'}}]
        self.assertEqual(counter.public_repository_count(repos, 'Kriksson'), 3)

    def test_hero_contains_embedded_image_and_green_counter_and_activity(self):
        import xml.etree.ElementTree as ET
        data = {'added_lines':37021, 'public_repositories':9, 'contributions_last_year':263, 'repositories':[]}
        for mobile in [False, True]:
            svg = counter.render_card(data, mobile, artwork=b'fixture')
            tree = ET.fromstring(svg)
            texts = tree.findall('{http://www.w3.org/2000/svg}text')
            self.assertEqual(texts[0].text, '+37 021')
            self.assertEqual(texts[0].get('fill'), '#69f59b')
            self.assertEqual(tree.find('{http://www.w3.org/2000/svg}image').get('href'), 'data:image/png;base64,Zml4dHVyZQ==')
            self.assertIn('9 репозиториев', svg)
            self.assertIn('263 вклада за год', svg)

    def test_only_source_files_and_not_generated_tests_or_dependencies(self):
        for path in ['src/App.java', 'frontend/src/main.tsx', 'db/migrations/V1.sql', 'java/solution.java']:
            self.assertIsNotNone(counter.source_language(path), path)
        for path in ['README.md', 'package-lock.json', 'config.yml', 'pom.xml', 'image.svg',
                     'src/test/java/BankTest.java', 'tests/a.py', 'src/A.spec.ts', 'test_a.py',
                     'node_modules/a.js', 'target/generated/A.java', 'vendor/a.py',
                     'bot/moonloader/lib/a.lua', 'bundle.min.js', 'app.d.ts', 'gradlew', 'gradlew.bat']:
            self.assertIsNone(counter.source_language(path), path)

    def test_old_unlinked_git_names_count_but_other_github_accounts_do_not(self):
        commits = [
            {'sha':'linked', 'author':{'login':'Kriksson'}, 'commit':{'author':{'name':'Kirill'}}},
            {'sha':'old', 'author':None, 'commit':{'author':{'name':'kriksson'}}},
            {'sha':'other', 'author':{'login':'AnotherUser'}, 'commit':{'author':{'name':'Kriksson'}}},
            {'sha':'unknown', 'author':None, 'commit':{'author':{'name':'Another Name'}}},
        ]
        self.assertEqual(counter.authored_commit_shas(commits, 'Kriksson'), {'linked','old'})

    def test_patch_header_like_source_and_whitespace_are_handled_correctly(self):
        patch = counter.COMMIT_MARKER+'mine\n'+'''diff --git a/src/Space name.java b/src/Space name.java
--- a/src/Space name.java
+++ b/src/Space name.java
@@ -0,0 +1,5 @@
+class A {
+
+   
+++ b/not-a-file.java
+}
'''
        result = counter.parse_history(patch, {'mine'})
        self.assertEqual(result['added_lines'], 3)
        self.assertEqual(result['source_commits'], 1)

    def test_public_owner_only_excludes_private_forks_profile_and_empty_repos(self):
        common = dict(private=False, fork=False, size=1, owner={'login':'Kriksson'})
        repos = [{**common, 'name':'valid', 'full_name':'Kriksson/valid'},
                 {**common, 'name':'private', 'private':True},
                 {**common, 'name':'fork', 'fork':True},
                 {**common, 'name':'Kriksson'},
                 {**common, 'name':'empty', 'size':0},
                 {**common, 'name':'other', 'owner':{'login':'Elsewhere'}}]
        self.assertEqual([r['name'] for r in counter.eligible_repositories(repos, 'Kriksson')], ['valid'])

    def test_unchanged_data_does_not_refresh_timestamp_or_generate_empty_commits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            results = [{'repository':'Kriksson/demo', 'head':'abc', 'branch':'main',
                        'added_lines':123, 'languages':{'Java':123}, 'source_commits':2}]
            self.assertTrue(counter.write_results(root, results, 'Kriksson', '2026-10-25T12:00:00Z'))
            before = {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertFalse(counter.write_results(root, results, 'Kriksson', '2026-10-25T13:00:00Z'))
            self.assertEqual(before, {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})


class GitHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git('init', '--quiet', '--initial-branch=main')
        self.git('config', 'user.name', 'Kriksson')
        self.git('config', 'user.email', 'author@example.invalid')

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(self.repo),
                                        *args], text=True, stderr=subprocess.DEVNULL).strip()

    def write(self, path, content):
        p = self.repo/path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '--quiet', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def test_real_history_excludes_other_authors_blank_lines_tests_and_pure_renames(self):
        self.write('src/App.java', 'class App {\n\n  int n;\n}\n')
        self.write('src/test/AppTest.java', 'not counted\n')
        first = self.commit('first')
        self.write('src/App.java', 'class App {\n\n  int n;\n  int other;\n}\n')
        other = self.commit('other author')
        self.git('mv', 'src/App.java', 'src/Renamed.java')
        moved = self.commit('move')
        head = self.git('rev-parse','HEAD')
        result = counter.read_history(self.repo/'.git', head, {first,moved})
        self.assertEqual(result['added_lines'], 3)
        self.assertEqual(result['source_commits'], 1)
        self.assertNotIn(other, {first,moved})

    def test_merged_feature_changes_count_once(self):
        self.write('src/App.java', 'class App {}\n')
        first = self.commit('initial')
        self.git('checkout', '--quiet', '-b', 'feature')
        self.write('src/App.java', 'class App {}\n// feature\n')
        feature = self.commit('feature')
        self.git('checkout', '--quiet', 'main')
        self.write('README.md', 'documentation\n')
        docs = self.commit('docs')
        self.git('merge', '--quiet', '--no-ff', 'feature', '-m', 'merge')
        merge = self.git('rev-parse', 'HEAD')
        result = counter.read_history(self.repo/'.git', merge, {first,feature,docs,merge})
        self.assertEqual(result['added_lines'], 2)
        self.assertEqual(result['source_commits'], 2)


if __name__ == '__main__':
    unittest.main()

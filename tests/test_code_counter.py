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
    def test_repository_count_includes_private_profile_and_owned_forks(self):
        repos = [{'private':False, 'name':'Kriksson', 'owner':{'login':'Kriksson'}},
                 {'private':True, 'name':'private-fixture', 'owner':{'login':'Kriksson'}},
                 {'private':False, 'fork':True, 'owner':{'login':'Kriksson'}},
                 {'private':False, 'owner':{'login':'Elsewhere'}}]
        self.assertEqual(counter.account_repository_count(repos, 'Kriksson'), 3)

    def test_incomplete_private_permissions_fail_before_statistics_are_written(self):
        class Api:
            token = 'fixture'
            oauth_scopes = {'repo'}
            def get(self, path): return {'login':'Kriksson'}
        with self.assertRaisesRegex(RuntimeError, 'read:user'):
            counter.verify_account_access(Api(), 'Kriksson')
        Api.oauth_scopes = {'repo','read:user'}
        self.assertEqual(counter.verify_account_access(Api(), 'Kriksson')['login'], 'Kriksson')
        with self.assertRaisesRegex(RuntimeError, 'profile owner'):
            counter.verify_account_access(Api(), 'SomeoneElse')

    def test_authenticated_contribution_query_and_failure(self):
        class Api:
            response = {'data':{'user':{'contributionsCollection':{'contributionCalendar':{'totalContributions':321}}}}}
            def get(self, path, *, payload):
                self.path, self.payload = path, payload
                return self.response
        api=Api()
        self.assertEqual(counter.account_contributions(api, 'Kriksson'), 321)
        self.assertEqual(api.path, 'graphql')
        self.assertEqual(api.payload['variables'], {'login':'Kriksson'})
        api.response = {'errors':[{'message':'fixture'}]}
        with self.assertRaises(RuntimeError):counter.account_contributions(api, 'Kriksson')

    def test_private_repository_metadata_cannot_enter_public_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            result={'repository':'owner/private-fixture','branch':'private-branch-fixture',
                    'head':'private-sha-fixture','added_lines':12,'source_commits':2,'languages':{'Java':12}}
            counter.write_results(root,[result],'Kriksson',total_repositories=12,contributions_last_year=321)
            for p in root.rglob('*'):
                if p.is_file():
                    text=p.read_text()
                    for secret in ['private-fixture','private-branch-fixture','private-sha-fixture']:
                        self.assertNotIn(secret,text)
            data=json.loads((root/'metrics/code-stats.json').read_text())
            self.assertNotIn('repositories',data)
            self.assertNotIn('languages',data)
            self.assertEqual(data['total_repositories'],12)
            self.assertEqual(data['added_lines'],12)

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

    def test_tests_and_examples_count_but_generated_code_and_dependencies_do_not(self):
        for path in ['src/App.java', 'frontend/src/main.tsx', 'db/migrations/V1.sql', 'java/solution.java',
                     'src/test/java/BankTest.java', 'tests/a.py', 'src/A.spec.ts', 'test_a.py', 'examples/Demo.java']:
            self.assertIsNotNone(counter.source_language(path), path)
        for path in ['README.md', 'package-lock.json', 'config.yml', 'pom.xml', 'image.svg',
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

    def test_owned_private_source_counts_and_forks_profile_empty_repos_do_not(self):
        common = dict(private=False, fork=False, size=1, owner={'login':'Kriksson'})
        repos = [{**common, 'name':'valid', 'full_name':'Kriksson/valid'},
                 {**common, 'name':'private', 'full_name':'Kriksson/private-fixture', 'private':True},
                 {**common, 'name':'fork', 'fork':True},
                 {**common, 'name':'Kriksson'},
                 {**common, 'name':'empty', 'size':0},
                 {**common, 'name':'other', 'owner':{'login':'Elsewhere'}}]
        self.assertEqual([r['name'] for r in counter.eligible_repositories(repos, 'Kriksson')], ['private','valid'])

    def test_unchanged_data_does_not_refresh_timestamp_or_generate_empty_commits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            results = [{'repository':'Kriksson/demo', 'head':'abc', 'branch':'main',
                        'added_lines':123, 'languages':{'Java':123}, 'source_commits':2}]
            self.assertTrue(counter.write_results(root, results, 'Kriksson', '2026-10-25T12:00:00Z',total_repositories=12,contributions_last_year=321))
            before = {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertFalse(counter.write_results(root, results, 'Kriksson', '2026-10-25T13:00:00Z',total_repositories=12,contributions_last_year=321))
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

    def test_real_history_includes_authored_tests_but_excludes_other_authors_blank_lines_and_renames(self):
        self.write('src/App.java', 'class App {\n\n  int n;\n}\n')
        self.write('src/test/AppTest.java', 'not counted\n')
        first = self.commit('first')
        self.write('src/App.java', 'class App {\n\n  int n;\n  int other;\n}\n')
        other = self.commit('other author')
        self.git('mv', 'src/App.java', 'src/Renamed.java')
        moved = self.commit('move')
        head = self.git('rev-parse','HEAD')
        result = counter.read_history(self.repo/'.git', head, {first,moved})
        self.assertEqual(result['added_lines'], 4)
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

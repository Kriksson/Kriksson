#!/usr/bin/env python3
"""Count source additions and activity across owned public and private repositories.

Repositories are read as Git data only. No downloaded project code is executed.
Only aggregate numbers are written to public files; private identifiers are never published.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


EXTENSIONS = {
    '.java': 'Java', '.py': 'Python', '.lua': 'Lua', '.luau': 'Lua',
    '.js': 'JavaScript', '.jsx': 'JavaScript', '.mjs': 'JavaScript', '.cjs': 'JavaScript',
    '.ts': 'TypeScript', '.tsx': 'TypeScript', '.html': 'HTML', '.css': 'CSS',
    '.scss': 'CSS', '.sass': 'CSS', '.less': 'CSS', '.sql': 'SQL',
    '.kt': 'Kotlin', '.kts': 'Kotlin', '.c': 'C/C++', '.h': 'C/C++',
    '.cpp': 'C/C++', '.hpp': 'C/C++', '.cs': 'C#', '.go': 'Go', '.rs': 'Rust',
    '.sh': 'Shell', '.bash': 'Shell', '.ps1': 'Shell', '.bat': 'Shell',
    '.vue': 'Vue', '.svelte': 'Svelte', '.rb': 'Ruby', '.php': 'PHP', '.swift': 'Swift',
}
EXCLUDED_PARTS = {
    '.git', '.github', '.idea', '.mvn', '.venv', 'venv', 'env', 'node_modules',
    'vendor', 'third_party', 'third-party', 'thirdparty', 'external', 'lib', 'libs',
    'target', 'dist', 'build', 'out', 'release', 'releases', 'coverage',
    'generated', '__generated__', 'gradle', 'site-packages',
}
COMMIT_MARKER = '\x1eCODE_COUNTER:'


def source_language(path: str) -> str | None:
    """Explicit source allowlist; dependency/config/docs/binary files never count."""
    p = PurePosixPath(path)
    parts = [part.casefold() for part in p.parts]
    name = p.name.casefold()
    if any(part in EXCLUDED_PARTS for part in parts):
        return None
    if name in {'mvnw', 'mvnw.cmd', 'gradlew', 'gradlew.bat'} or name.endswith(('.min.js', '.min.css', '.d.ts', '.generated.ts')):
        return None
    return EXTENSIONS.get(p.suffix.casefold())


def parse_history(patch: str, authored_commits: set[str]) -> dict:
    """Parse real unified Git patches, not numstat (which also counts blank lines)."""
    counts: Counter[str] = Counter()
    contributing: set[str] = set()
    sha = ''
    language = None
    in_hunk = False
    for line in patch.split('\n'):
        if line.startswith(COMMIT_MARKER):
            sha = line[len(COMMIT_MARKER):].strip()
            language, in_hunk = None, False
        elif line.startswith('diff --git '):
            language, in_hunk = None, False
        elif not in_hunk and line.startswith('+++ '):
            path = line[4:]
            language = source_language(path[2:]) if path.startswith('b/') else None
        elif line.startswith('@@ '):
            in_hunk = True
        elif in_hunk and line.startswith('+') and line[1:].strip():
            if sha in authored_commits and language:
                counts[language] += 1
                contributing.add(sha)
    return {'added_lines': sum(counts.values()), 'languages': dict(sorted(counts.items())),
            'source_commits': len(contributing)}


def run_git(*args: str, timeout: int = 180) -> str:
    env = os.environ.copy()
    env.update({'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1'})
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        index = int(env.get('GIT_CONFIG_COUNT', '0'))
        env['GIT_CONFIG_COUNT'] = str(index + 2)
        env[f'GIT_CONFIG_KEY_{index}'] = 'http.https://github.com/.extraheader'
        env[f'GIT_CONFIG_VALUE_{index}'] = ''
        index += 1
        env[f'GIT_CONFIG_KEY_{index}'] = 'http.https://github.com/.extraheader'
        auth = base64.b64encode(('x-access-token:'+token).encode()).decode()
        env[f'GIT_CONFIG_VALUE_{index}'] = 'AUTHORIZATION: basic '+auth
    r = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.quotePath=false',
                        *args], capture_output=True, text=True, errors='replace',
                       timeout=timeout, env=env)
    if r.returncode:
        raise RuntimeError('Git read failed; repository details withheld')
    return r.stdout


def read_history(git_dir: Path, head: str, authored_commits: set[str]) -> dict:
    # -p uses one-parent diffs; --no-merges prevents merged PR changes being counted twice.
    # Git's rename detection prevents an unchanged move from adding its lines again.
    patch = run_git('--git-dir='+str(git_dir), 'log', head, '--no-merges', '--format='+COMMIT_MARKER+'%H',
                    '--patch', '--find-renames', '--unified=0', '--no-color', '--no-ext-diff',
                    '--no-textconv')
    return parse_history(patch, authored_commits)


class GitHub:
    def __init__(self, token: str | None):
        self.token = token
        self.oauth_scopes = None

    def get(self, path: str, params: dict | None = None, *, payload: dict | None = None):
        url = 'https://api.github.com/' + path.lstrip('/')
        if params:
            url += '?' + urlencode(params)
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Kriksson-code-counter'}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        for attempt in range(4):
            try:
                with urlopen(Request(url, headers=headers, data=json.dumps(payload).encode() if payload is not None else None), timeout=40) as r:
                    scopes = r.headers.get('X-OAuth-Scopes')
                    if scopes is not None:
                        self.oauth_scopes = {x.strip() for x in scopes.split(',') if x.strip()}
                    return json.load(r)
            except HTTPError as error:
                # Never return a partial total when GitHub or a repository is unavailable.
                if attempt == 3 or error.code not in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f'GitHub HTTP {error.code}; request details withheld') from error
                time.sleep(min(8, 2 ** attempt))
            except URLError as error:
                if attempt == 3:
                    raise RuntimeError('GitHub unavailable; request details withheld') from error
                time.sleep(2 ** attempt)
        raise AssertionError('unreachable')

    def pages(self, path: str, params: dict | None = None) -> list:
        result = []
        for page in range(1, 1001):
            chunk = self.get(path, {**(params or {}), 'per_page': 100, 'page': page})
            if not isinstance(chunk, list):
                raise RuntimeError('Expected a paginated GitHub list')
            result.extend(chunk)
            if len(chunk) < 100:
                return result
        raise RuntimeError('Pagination limit reached; refusing an incomplete count')


def eligible_repositories(repos: list, username: str) -> list:
    result = []
    for repo in repos:
        if type(repo.get('private')) is not bool or repo.get('fork'):
            continue
        if repo.get('owner', {}).get('login', '').casefold() != username.casefold():
            continue
        if repo['name'].casefold() == username.casefold():
            continue  # The profile, its SVGs and generated counters must not count themselves.
        if repo.get('size', 0) == 0:
            continue
        result.append(repo)
    return sorted(result, key=lambda r: r['full_name'].casefold())


def authored_commit_shas(commits: list, username: str) -> set[str]:
    target = username.casefold()
    result = set()
    for commit in commits:
        account = commit.get('author')
        if account:
            matches = account.get('login', '').casefold() == target
        else:
            # An old unlinked Git identity is accepted only by exact owner-name match.
            matches = commit.get('commit', {}).get('author', {}).get('name', '').casefold() == target
        if matches:
            result.add(commit['sha'])
    return result


def collect_repository(api: GitHub, repo: dict, username: str, cache: Path) -> dict:
    full_name, branch = repo['full_name'], repo['default_branch']
    # Resolve the branch once; freeze both commit attribution and Git history to that SHA.
    head = api.get('repos/'+full_name+'/commits/'+quote(branch, safe=''))['sha']
    commits = api.pages('repos/'+full_name+'/commits', {'sha': head})
    authored = authored_commit_shas(commits, username)
    git_dir = cache / (hashlib.sha256(full_name.casefold().encode()).hexdigest()+'.git')
    if not git_dir.exists():
        run_git('clone', '--quiet', '--bare', '--single-branch', '--branch', branch,
                'https://github.com/'+full_name+'.git', str(git_dir))
    else:
        run_git('--git-dir='+str(git_dir), 'fetch', '--quiet', '--no-tags', 'origin', branch)
    # Public branch might have advanced after the API snapshot; Git objects still include head.
    run_git('--git-dir='+str(git_dir), 'cat-file', '-e', head+'^{commit}')
    result = read_history(git_dir, head, authored)
    return result  # Do not return repository names, branch names, or commit SHAs.


def number(value: int) -> str:
    return f'{value:,}'.replace(',', ' ')


def account_repository_count(repos: list, username: str) -> int:
    return sum(type(r.get('private')) is bool and
               r.get('owner', {}).get('login', '').casefold() == username.casefold() for r in repos)


def verify_account_access(api: GitHub, username: str) -> dict:
    if not api.token:
        raise RuntimeError('PROFILE_METRICS_TOKEN is required for public and private statistics')
    user = api.get('user')
    if user.get('login', '').casefold() != username.casefold():
        raise RuntimeError('Metrics token must belong to the profile owner')
    # Classic PAT/OAuth tokens disclose their scopes. Never silently omit private activity.
    scopes = api.oauth_scopes
    if scopes is None or 'repo' not in scopes or not ({'read:user', 'user'} & scopes):
        raise RuntimeError('Use a classic metrics token with repo and read:user scopes for complete private statistics')
    return user


def account_contributions(api: GitHub, username: str) -> int:
    query = ('query($login:String!){user(login:$login){contributionsCollection{'
             'contributionCalendar{totalContributions}}}}')
    response = api.get('graphql', payload={'query':query, 'variables':{'login':username}})
    if response.get('errors'):
        raise RuntimeError('Contribution access failed; previous statistics preserved')
    try:
        value = response['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions']
    except (KeyError, TypeError) as error:
        raise RuntimeError('Incomplete GitHub contribution result') from error
    if type(value) is not int or value < 0:
        raise RuntimeError('Invalid contribution total')
    return value


def plural(value: int, one: str, few: str, many: str) -> str:
    if 11 <= value % 100 <= 14:
        return many
    return one if value % 10 == 1 else few if 2 <= value % 10 <= 4 else many


def render_card(data: dict, mobile: bool = False, artwork: bytes | None = None) -> str:
    # Raster illustration remains intact; changing numbers are native SVG text.
    if artwork is None:
        artwork = (Path(__file__).resolve().parents[1]/'assets/profile/about/interests.png').read_bytes()
    embedded = base64.b64encode(artwork).decode('ascii')
    total = '+'+number(data['added_lines'])
    repository_count = data.get('total_repositories', data.get('public_repositories', len(data.get('repositories', []))+1))
    repos = number(repository_count)
    contributions = number(data.get('contributions_last_year', 0))
    width, height = (1120, 514) if mobile else (2048, 823)
    art_width, art_height, art_y = (1120, 374, 140) if mobile else (2048, 683, 140)
    x, y, size = (225, 105, 78) if mobile else (430, 103, 84)
    title = f'{total} строк кода; {repos} репозиториев (публичных и приватных); {contributions} contributions за последний год.'
    body = f'<rect width="{width}" height="{height}" rx="24" fill="#0d1117"/>'
    body += f'<image x="0" y="{art_y}" width="{art_width}" height="{art_height}" href="data:image/png;base64,{embedded}"/>'
    body += f'<text x="{x}" y="{y}" text-anchor="middle" font-family="DejaVu Sans Mono,monospace" font-size="{size}" font-weight="700" fill="#69f59b" stroke="#0d1117" stroke-width="5" paint-order="stroke">{total}</text>'
    # Group all three metrics above the scene, with a compact two-line layout on phones.
    positions = ((440, 52), (440, 108)) if mobile else ((760, 98), (1280, 98))
    label_size = 40
    icons = ('M3 2h22v27H3z M8 2v27 M12 8h8 M12 14h8',
             'M2 27V3 M2 27h29 M7 20l7-8 7 4 10-13')
    repo_label = plural(repository_count, 'репозиторий', 'репозитория', 'репозиториев')
    activity_label = plural(data.get('contributions_last_year', 0), 'вклад', 'вклада', 'вкладов')
    labels = (f'{repos} {repo_label}', f'{contributions} {activity_label} за год')
    for (left, row_y), icon, label in zip(positions, icons, labels):
        body += f'<g transform="translate({left},{row_y-27})" fill="none" stroke="#f6b179" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="{icon}"/></g>'
        body += f'<text x="{left+48}" y="{row_y}" fill="#bec9d5" font-family="Noto Sans,Arial,sans-serif" font-size="{label_size}">{escape(label)}</text>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title, quote=True)}"><title>{escape(title)}</title>{body}</svg>\n'


def write_results(root: Path, results: list, username: str, now: str | None = None, *,
                  total_repositories: int, contributions_last_year: int) -> bool:
    path = root/'metrics/code-stats.json'
    stable = {'schema': 2, 'username': username, 'metric': 'nonempty-source-line-additions',
              'attribution': 'github-login-or-unlinked-matching-git-name',
              'scope': 'owned-public-private-nonfork-default-branches',
              'includes_tests_and_examples': True,
              'added_lines': sum(r['added_lines'] for r in results),
              'source_commits': sum(r['source_commits'] for r in results),
              'total_repositories': total_repositories,
              'contributions_last_year': contributions_last_year,
              'contributions_scope': 'authenticated-public-private-last-year'}
    # Explicit aggregate allowlist: never serialize private names, IDs, paths or Git SHAs.
    old = json.loads(path.read_text()) if path.exists() else None
    unchanged = old and {k:v for k,v in old.items() if k != 'updated_at'} == stable
    data = old if unchanged else {**stable, 'updated_at': now or datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}
    # All repository reads finished before any output is touched.
    target = root/'assets/profile/stats'
    outputs = {path: json.dumps(data, ensure_ascii=False, indent=2)+'\n',
               target/'code-counter.svg': render_card(data),
               target/'code-counter-mobile.svg': render_card(data, mobile=True)}
    changed = False
    for output, content in outputs.items():
        if not output.exists() or output.read_text() != content:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content)
            changed = True
    if not changed:
        print('No changes; counter files remain identical.', flush=True)
        return False
    print('Total:', number(data['added_lines']), 'non-empty source additions', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='Kriksson')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--cache-dir', type=Path, default=Path('.code-counter-cache'))
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9-]+', args.username):
        parser.error('Invalid GitHub username')
    api = GitHub(os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN'))
    verify_account_access(api, args.username)
    account_repos = api.pages('user/repos', {'affiliation':'owner', 'visibility':'all'})
    owned = [r for r in account_repos if r.get('owner', {}).get('login', '').casefold() == args.username.casefold()]
    if not owned or any(type(r.get('private')) is not bool for r in owned):
        raise RuntimeError('Incomplete owned-repository response')
    repos = eligible_repositories(owned, args.username)
    contributions = account_contributions(api, args.username)
    if not repos:
        raise RuntimeError('No eligible repositories; refusing to replace the total with zero')
    args.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.cache_dir.chmod(0o700)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda r: collect_repository(api, r, args.username, args.cache_dir), repos))
    write_results(args.root, results, args.username,
                  total_repositories=account_repository_count(owned, args.username),
                  contributions_last_year=contributions)



if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Counter update failed:', error, file=sys.stderr)
        sys.exit(1)

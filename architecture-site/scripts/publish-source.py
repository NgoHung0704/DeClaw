"""Push a prepared static site using an ephemeral, non-echoed Sites credential.

Run in a terminal; the token is read from the console without echo and lives only
in memory and the child process environment. Never put it in a Git remote/config.
"""
import os
import subprocess
import sys
from pathlib import Path
import msvcrt

root = Path(__file__).resolve().parents[1] / '.publish'
remote = sys.argv[1]
branch = sys.argv[2]
if not remote.startswith('https://git.chatgpt-team.site/'):
    raise SystemExit('Unexpected source repository host')
print('Ready for ephemeral source credential (input will not be echoed).', flush=True)
chars = []
while True:
    char = msvcrt.getwch()
    if char in ('\r', '\n'):
        break
    chars.append(char)
token = ''.join(chars)
if not token:
    raise SystemExit('Missing credential')
env = os.environ.copy()
env.update({
    'GIT_CONFIG_COUNT': '3',
    'GIT_CONFIG_KEY_0': 'safe.directory',
    'GIT_CONFIG_VALUE_0': root.as_posix(),
    'GIT_CONFIG_KEY_1': 'http.extraHeader',
    'GIT_CONFIG_VALUE_1': f'Authorization: Bearer {token}',
    'GIT_CONFIG_KEY_2': 'credential.helper',
    'GIT_CONFIG_VALUE_2': '',
    'GIT_TERMINAL_PROMPT': '0',
})
result = subprocess.run(['git','push',remote,f'HEAD:{branch}'], cwd=root,env=env,capture_output=True,text=True)
print((result.stdout + result.stderr).replace(token,'[REDACTED]'),flush=True)
raise SystemExit(result.returncode)

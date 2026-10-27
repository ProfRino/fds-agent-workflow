"""Portable local FDS commands; Python standard library only."""
import argparse
import functools
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def input_file(value):
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    if not candidate.is_file():
        candidate = ROOT / 'simulations' / value / (value + '.fds')
    candidate = candidate.resolve()
    if not candidate.is_file() or candidate.suffix.lower() != '.fds':
        raise ValueError('Provide a simulation name or an existing .fds path.')
    if not candidate.is_relative_to(ROOT / 'simulations'):
        raise ValueError('Inputs must be inside this workspace simulations folder.')
    return candidate

def case_id(path):
    text = re.sub(r'!.*', '', path.read_text(encoding='utf-8-sig'))
    match = re.search(r'&HEAD\b[^/]*?\bCHID\s*=\s*[\"\x27]([A-Za-z0-9_-]+)[\"\x27]', text, re.I | re.S)
    if not match:
        raise ValueError('HEAD must specify a CHID containing only letters, numbers, underscores or hyphens.')
    return match.group(1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run','smokeview','serve','status','check'])
    parser.add_argument('input', nargs='?')
    parser.add_argument('--mpi', type=int)
    parser.add_argument('--preview-confirmed', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if args.action == 'serve':
        if not (ROOT / 'visualization/index.html').exists():
            raise ValueError('Viewer missing: rerun setup without -SkipViewer.')
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        print(f'Viewer: http://127.0.0.1:{args.port}/visualization/index.html', flush=True)
        with http.server.ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
            server.serve_forever()
        return 0
    config = json.loads((ROOT / 'scripts/config.local.json').read_text(encoding='utf-8-sig'))
    bin_dir = Path(config['fds_install']) / 'bin'
    env = dict(os.environ)
    env['PATH'] = str(bin_dir) + os.pathsep + str(bin_dir / 'mpi') + os.pathsep + env.get('PATH','')
    if args.action == 'check':
        return subprocess.run([str(bin_dir / 'fds.exe'), '-v'], env=env).returncode
    if not args.input:
        parser.error('This command requires a simulation name or input path.')
    path = input_file(args.input)
    chid = case_id(path)
    log = path.parent / (chid + '.out')
    if args.action == 'status':
        if not log.exists():
            print('No run log exists for this case.')
            return 1
        from collections import deque
        with log.open(errors='replace') as stream:
            print(''.join(deque(stream, maxlen=30)))
        return 0
    if args.action == 'smokeview':
        scene = path.parent / (chid + '.smv')
        if not scene.exists():
            raise ValueError('No Smokeview scene exists for this case.')
        return subprocess.run([config['smokeview_exe'], scene.name], cwd=path.parent, env=env).returncode
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_fds.py'), str(path)])
    if result.returncode:
        return result.returncode
    if not args.preview_confirmed:
        raise ValueError('Preview geometry in FDS Viewer first, then pass --preview-confirmed.')
    # Never silently overwrite a completed run, restart, or partially written output.
    if any(p.name == chid+'.out' or p.name == chid+'.smv' or p.name.startswith(chid+'_') for p in path.parent.iterdir()):
        raise ValueError('Existing case outputs found. Use a new case folder and CHID; no files were deleted.')
    ranks = args.mpi if args.mpi is not None else config['mpi_processes']
    if not 1 <= ranks <= 256:
        raise ValueError('MPI process count must be between 1 and 256 and no greater than the mesh count.')
    command = [str(bin_dir / 'fds.exe'), path.name]
    if ranks > 1:
        command = [str(bin_dir / 'mpi/mpiexec.exe'), '-localonly', '-n', str(ranks)] + command
    result = subprocess.run(command, cwd=path.parent, env=env)
    if result.returncode:
        return result.returncode
    if not log.exists() or 'FDS completed successfully' not in log.read_text(errors='replace'):
        print('Solver did not report successful completion. Inspect its log.', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)

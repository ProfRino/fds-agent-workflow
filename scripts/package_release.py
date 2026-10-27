"""Package only reviewed, allowlisted public source files (never Git history)."""
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'Windows personal directory': r'[A-Za-z]:[\\/]Users[\\/][^\s<>]+',
    'Unix personal directory': r'/(?:home|Users)/[A-Za-z0-9_.-]+',
    'private key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'provider token': r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})\b',
    'AWS key': r'\bAKIA[A-Z0-9]{16}\b',
    'credential assignment': r'(?im)^\s*(?:api_key|password|secret|access_token)\s*[=:]\s*[\"\x27]?[^\s\"\x27]{8,}',
}

def public_files(root=ROOT):
    names = (root / 'distribution-files.txt').read_text().splitlines()
    result = []
    for name in names:
        if not name or name.startswith('#'):
            continue
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f'Unsafe manifest entry: {name}')
        if not path.is_file() or path.suffix.lower() in {'.pdf','.exe','.dll','.zip'}:
            raise ValueError(f'Missing or non-source manifest entry: {name}')
        result.append(path)
    return result

def scan(paths):
    findings = []
    for path in paths:
        # Images are explicitly allowlisted and visually reviewed. Scan their raw
        # bytes for readable metadata too; never interpret binary images as UTF-8.
        if path.suffix.lower() in {'.png', '.gif'}:
            data = path.read_bytes().decode('latin-1')
        else:
            data = path.read_text(encoding='utf-8-sig')
        for label, pattern in PATTERNS.items():
            if re.search(pattern, data):
                findings.append(f'{path.name}: {label}')
    return findings

def main():
    paths = public_files()
    findings = scan(paths)
    if findings:
        raise SystemExit('Release blocked:\n'+'\n'.join(findings))
    destination = ROOT / 'archive/fds-agent-workflow.zip'
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, 'fds-agent-workflow/'+path.relative_to(ROOT).as_posix())
    print(f'Packaged {len(paths)} reviewed source files: {destination}')

if __name__ == '__main__':
    main()

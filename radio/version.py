"""A repeatable build label, including installations without Git."""
import hashlib
from pathlib import Path


def application_version():
    root = Path(__file__).resolve().parent
    files = list(root.glob('*.py'))
    files += list((root / 'templates').rglob('*.html'))
    files += list((root / 'static').rglob('*.js'))
    files += list((root / 'static').rglob('*.css'))

    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b'\0')
        # Git can change line endings when deploying from Windows to Linux.
        digest.update(path.read_bytes().replace(b'\r\n', b'\n'))
        digest.update(b'\0')

    return digest.hexdigest()[:10]

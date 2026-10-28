"""Syntax-check every inline app script without invoking network scans."""
import re
import subprocess
import tempfile
from pathlib import Path
for page in Path('.').rglob('*.html'):
    for i, script in enumerate(re.findall(r'<script\b[^>]*>(.*?)</script>', page.read_text(), re.S|re.I)):
        if script.strip():
            with tempfile.NamedTemporaryFile(suffix='.js',mode='w') as f:
                f.write(script); f.flush()
                subprocess.run(['node','--check',f.name],check=True)
    print(f'{page}: inline JavaScript syntax passed')

#!/usr/bin/env python3
"""Heuristic release check; catches obvious sensitive paths/credentials, not exhaustive."""
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PATTERNS = {
    'personal macOS home path':re.compile(r'/Users/[A-Za-z0-9._-]+/'),
    'user-specific AI history path':re.compile(r'\.gemini/antigravity-cli/brain/'),
    'probable private key':re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'),
    'probable GitHub token':re.compile(r'(?:ghp_|gho_|github_pat_)[A-Za-z0-9_]{20,}'),
    'probable OpenAI token':re.compile(r'sk-[A-Za-z0-9_-]{24,}'),
}
EXCLUDE={'.git','__pycache__','node_modules','.venv'}
problems=[]
for path in ROOT.rglob('*'):
    if path == Path(__file__).resolve() or not path.is_file() or any(part in EXCLUDE for part in path.relative_to(ROOT).parts):
        continue
    if path.suffix in ('.vsix','.zip','.png','.jpg','.jpeg','.dylib'):
        continue
    content=path.read_text(encoding='utf-8',errors='replace')
    for name,pattern in PATTERNS.items():
        if pattern.search(content):problems.append((path.relative_to(ROOT),name))
for path,name in problems:
    print('CHECK',path,'-',name)
print('Release heuristic:',len(problems),'flag(s); this is not a secret scan guarantee')
raise SystemExit(1 if problems else 0)

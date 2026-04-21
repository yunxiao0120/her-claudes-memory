"""Apply patches to imprint_memory/server.py.

This adds features that may not yet be in imprint-memory main:

1. `tags` parameter on `memory_remember` — PR pending upstream
2. `source` filter on `memory_list` — PR pending upstream
3. Admin MCP tools for managing the enum config
   (`memory_admin_list_enums`, `memory_admin_add_name`, etc.)

Idempotent: running twice is safe.

Usage:
    python scripts/patch_imprint_memory.py
"""
import ast
import re
import sys
from pathlib import Path

# Find the installed imprint_memory package
try:
    import imprint_memory
    pkg_path = Path(imprint_memory.__file__).parent
    server_path = pkg_path / 'server.py'
except ImportError:
    print('Error: imprint-memory is not installed. Run: pip install imprint-memory')
    sys.exit(1)

if not server_path.exists():
    print(f'Error: {server_path} not found')
    sys.exit(1)

src = server_path.read_text(encoding='utf-8')


# ---------- Patch 1: tags in memory_remember ----------
old_remember = '''def memory_remember(content: str, category: str = "general", source: str = "cc", importance: int = 5) -> str:
    """Store a memory. Call this when you encounter important information worth recalling in future conversations.
    category: facts/events/tasks/experience/general
    source: free-form label for where the info came from (e.g. cc, chat, api)
    DO NOT store: code patterns/file paths derivable from the codebase, git history, or info already in CLAUDE.md."""
    return remember(content=content, category=category, source=source, importance=importance)'''

new_remember = '''def memory_remember(content: str, category: str = "general", source: str = "cc", importance: int = 5, tags: list = None) -> str:
    """Store a memory. Call this when you encounter important information worth recalling in future conversations.
    category: facts/events/tasks/experience/general
    source: free-form label for where the info came from (e.g. cc, chat, api)
    importance: 1-10 (default 5)
    tags: optional list of strings for filtering/categorization (e.g. ["anchor", "important"])
    DO NOT store: code patterns/file paths derivable from the codebase, git history, or info already in CLAUDE.md."""
    return remember(content=content, category=category, source=source, importance=importance, tags=tags)'''

if old_remember in src:
    src = src.replace(old_remember, new_remember, 1)
    print('[1/3] memory_remember: tags parameter added')
elif 'tags: list = None' in src:
    print('[1/3] memory_remember: already has tags parameter (skipped)')
else:
    print('[1/3] memory_remember: signature changed upstream — skipped, review manually')


# ---------- Patch 2: source filter in memory_list ----------
old_list = '''@mcp.tool()
def memory_list(category: Optional[str] = None, limit: int = 20) -> str:
    """List memories (newest first)."""
    items = get_all(category=category, limit=limit)
    if not items:
        return "No memories yet"
    lines = []
    for m_item in items:
        lines.append(f"[{m_item['id']}] [{m_item['category']}|{m_item['source']}] {m_item['content']}  ({m_item['created_at']})")
    return "\\n".join(lines)'''

new_list = '''@mcp.tool()
def memory_list(category: Optional[str] = None, source: Optional[str] = None, limit: int = 20) -> str:
    """List memories (newest first).
    category: filter by category (optional)
    source: filter by source (optional) — pass your own name to see only your memories
    limit: max count (default 20)"""
    fetch_limit = limit * 5 if source else limit
    items = get_all(category=category, limit=fetch_limit)
    if source:
        items = [i for i in items if i.get("source") == source]
        items = items[:limit]
    if not items:
        return "No memories yet"
    lines = []
    for m_item in items:
        lines.append(f"[{m_item['id']}] [{m_item['category']}|{m_item['source']}] {m_item['content']}  ({m_item['created_at']})")
    return "\\n".join(lines)'''

if old_list in src:
    src = src.replace(old_list, new_list, 1)
    print('[2/3] memory_list: source filter added')
elif 'source: Optional[str]' in src and 'def memory_list' in src:
    print('[2/3] memory_list: already has source filter (skipped)')
else:
    print('[2/3] memory_list: signature changed upstream — skipped, review manually')


# ---------- Patch 3: admin tools ----------
if 'memory_admin_list_enums' in src:
    print('[3/3] admin tools: already installed (skipped)')
else:
    # Ensure json and os are imported
    if not re.search(r'^import json$', src, re.MULTILINE):
        src = re.sub(r'(\nimport [^\n]+\n)', r'\1import json\n', src, count=1)
    if not re.search(r'^import os$', src, re.MULTILINE):
        src = re.sub(r'(\nimport [^\n]+\n)', r'\1import os\n', src, count=1)

    admin_tools = '''


# ---------- admin: enum management ----------
_ENUMS_PATH = os.environ.get('HER_MEMORY_ENUMS_PATH', './config/enums.json')


def _read_enums():
    try:
        with open(_ENUMS_PATH) as f:
            d = json.load(f)
        return {
            'names': list(d.get('names', [])),
            'categories': list(d.get('categories', [])),
        }
    except Exception as e:
        return {'names': [], 'categories': [], 'error': str(e)}


def _write_enums(enums):
    tmp = _ENUMS_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(enums, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _ENUMS_PATH)


@mcp.tool()
def memory_admin_list_enums() -> str:
    """List currently allowed values for 'source' and 'category' enum."""
    e = _read_enums()
    if 'error' in e:
        return f"Error reading enums: {e['error']}"
    return (
        "Allowed names: " + ", ".join(e['names']) + "\\n"
        "Allowed categories: " + ", ".join(e['categories'])
    )


@mcp.tool()
def memory_admin_add_name(name: str) -> str:
    """Add a new allowed name (source) to the enum."""
    name = name.strip()
    if not name:
        return "Error: empty name"
    e = _read_enums()
    if name in e['names']:
        return f"Already exists: {name}"
    e['names'].append(name)
    _write_enums(e)
    return f"Added name: {name}"


@mcp.tool()
def memory_admin_remove_name(name: str) -> str:
    """Remove a name from the allowed enum.
    Won't delete existing memories with that source."""
    name = name.strip()
    e = _read_enums()
    if name not in e['names']:
        return f"Not in list: {name}"
    e['names'].remove(name)
    _write_enums(e)
    return f"Removed name: {name}"


@mcp.tool()
def memory_admin_add_category(category: str) -> str:
    """Add a new allowed category to the enum."""
    category = category.strip()
    if not category:
        return "Error: empty category"
    e = _read_enums()
    if category in e['categories']:
        return f"Already exists: {category}"
    e['categories'].append(category)
    _write_enums(e)
    return f"Added category: {category}"


@mcp.tool()
def memory_admin_remove_category(category: str) -> str:
    """Remove a category from the allowed enum."""
    category = category.strip()
    e = _read_enums()
    if category not in e['categories']:
        return f"Not in list: {category}"
    e['categories'].remove(category)
    _write_enums(e)
    return f"Removed category: {category}"
'''

    src = src.rstrip() + admin_tools + '\n'
    print('[3/3] admin tools: appended')

# Verify and write
try:
    ast.parse(src)
except SyntaxError as e:
    print(f'Syntax error after patching: {e}')
    print('Aborting. File not modified.')
    sys.exit(1)

server_path.write_text(src, encoding='utf-8')
print(f'\nPatched: {server_path}')
print('Restart the imprint-memory MCP server to pick up changes.')

"""
her-memory REST API
===================
Lightweight Starlette app wrapping imprint_memory functions so the
frontend (static/*.html) can read/write memories and messages
without going through MCP.

Run:
    python app.py

Environment variables:
    HER_MEMORY_PORT         default 8001
    HER_MEMORY_HOST         default 127.0.0.1
    HER_MEMORY_ENUMS_PATH   default ./config/enums.json
"""
import json
import os
import sys
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request

from imprint_memory import memory_manager as mm
from imprint_memory import bus


# ---------- config ----------
PORT = int(os.environ.get('HER_MEMORY_PORT', '8001'))
HOST = os.environ.get('HER_MEMORY_HOST', '127.0.0.1')
ENUMS_PATH = os.environ.get(
    'HER_MEMORY_ENUMS_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'enums.json'),
)


# ---------- enums (loaded dynamically from JSON) ----------

def _load_enums():
    """Load allowed names and categories from ENUMS_PATH.
    Falls back to permissive defaults if file missing or corrupt."""
    try:
        with open(ENUMS_PATH) as f:
            data = json.load(f)
        return set(data.get('names', [])), set(data.get('categories', []))
    except Exception:
        return (
            set(),  # empty names → allow any (or configure via /api/admin)
            {'fact', 'event', 'feeling', 'story', 'letter', 'other'},
        )


# ---------- memories ----------

async def list_memories(request: Request):
    """GET /api/memories?category=xxx&limit=50"""
    category = request.query_params.get('category')
    limit = int(request.query_params.get('limit', 50))
    rows = mm.get_all(category=category, limit=limit)
    return JSONResponse({'memories': rows, 'total': len(rows)})


async def search_memories(request: Request):
    """GET /api/search?q=xxx&limit=10&category=xxx"""
    q = request.query_params.get('q', '').strip()
    if not q:
        return JSONResponse({'error': 'query required'}, status_code=400)
    limit = int(request.query_params.get('limit', 10))
    category = request.query_params.get('category')
    rows = mm.search(q, limit=limit, category=category)
    return JSONResponse({'query': q, 'results': rows, 'total': len(rows)})


async def get_memory(request: Request):
    """GET /api/memories/:id"""
    mid = int(request.path_params['mid'])
    db = mm._get_db()
    row = db.execute("""
        SELECT id, content, category, source, importance, tags,
               created_at, updated_at, recalled_count
        FROM memories WHERE id = ? AND superseded_by IS NULL
    """, (mid,)).fetchone()
    db.close()
    if not row:
        return JSONResponse({'error': 'not found'}, status_code=404)
    return JSONResponse(dict(row))


async def create_memory(request: Request):
    """POST /api/memories  body: {content, category?, name?/source?, importance?, tags?}
    If the configured names enum is non-empty, name must be in it.
    category always validated against categories enum."""
    data = await request.json()
    content = data.get('content', '').strip()
    if not content:
        return JSONResponse({'error': 'content required'}, status_code=400)
    name = (data.get('name') or data.get('source') or 'assistant').strip()
    allowed_names, allowed_categories = _load_enums()
    if allowed_names and name not in allowed_names:
        return JSONResponse(
            {'error': f'name must be one of: {", ".join(sorted(allowed_names))}'},
            status_code=400,
        )
    category = data.get('category', 'other').strip()
    if category not in allowed_categories:
        return JSONResponse(
            {'error': f'category must be one of: {", ".join(sorted(allowed_categories))}'},
            status_code=400,
        )
    result = mm.remember(
        content=content,
        category=category,
        source=name,
        importance=int(data.get('importance', 5)),
        tags=data.get('tags'),
    )
    return JSONResponse({'ok': True, 'result': result})


async def update_memory(request: Request):
    """PUT /api/memories/:id  body: {content?, category?, importance?}"""
    mid = int(request.path_params['mid'])
    data = await request.json()
    _, allowed_categories = _load_enums()
    if data.get('category') and data['category'] not in allowed_categories:
        return JSONResponse(
            {'error': f'category must be one of: {", ".join(sorted(allowed_categories))}'},
            status_code=400,
        )
    result = mm.update_memory(
        memory_id=mid,
        content=data.get('content', ''),
        category=data.get('category', ''),
        importance=int(data.get('importance', 0)),
    )
    return JSONResponse(result)


async def delete_memory(request: Request):
    """DELETE /api/memories/:id"""
    mid = int(request.path_params['mid'])
    result = mm.delete_memory(mid)
    return JSONResponse(result)


# ---------- message bus (optional, short transactional messages) ----------

async def list_messages(request: Request):
    """GET /api/messages?limit=50"""
    limit = int(request.query_params.get('limit', 50))
    msgs = bus.bus_read(limit=limit)
    return JSONResponse({'messages': msgs, 'total': len(msgs)})


async def post_message(request: Request):
    """POST /api/messages  body: {source, direction, content}"""
    data = await request.json()
    source = data.get('source', '').strip()
    direction = data.get('direction', '').strip()
    content = data.get('content', '').strip()
    if not (source and direction and content):
        return JSONResponse(
            {'error': 'source, direction, content all required'},
            status_code=400,
        )
    bus.bus_post(source=source, direction=direction, content=content)
    return JSONResponse({'ok': True})


# ---------- enums ----------

async def get_enums(request: Request):
    names, categories = _load_enums()
    return JSONResponse({
        'names': sorted(names),
        'categories': sorted(categories),
    })


# ---------- health ----------

async def health(request: Request):
    return JSONResponse({'ok': True, 'service': 'her-memory-api'})


routes = [
    Route('/api/health', health, methods=['GET']),
    Route('/api/enums', get_enums, methods=['GET']),
    Route('/api/memories', list_memories, methods=['GET']),
    Route('/api/memories', create_memory, methods=['POST']),
    Route('/api/memories/{mid:int}', get_memory, methods=['GET']),
    Route('/api/memories/{mid:int}', update_memory, methods=['PUT']),
    Route('/api/memories/{mid:int}', delete_memory, methods=['DELETE']),
    Route('/api/search', search_memories, methods=['GET']),
    Route('/api/messages', list_messages, methods=['GET']),
    Route('/api/messages', post_message, methods=['POST']),
]


app = Starlette(routes=routes)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)

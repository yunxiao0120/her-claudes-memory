"""
memory-frontend REST API
========================
Lightweight Starlette app wrapping imprint_memory functions so the
frontend (memory.xinlibond.com/ui) can read/write memories and messages
without going through MCP.

Deploy location: /home/admin/memory-api/app.py on aliyun server
Run: python3.11 app.py (serves on port 8001)
Reverse-proxied under memory.xinlibond.com/api/ by nginx
"""
import json
import sys
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request

sys.path.insert(0, '/home/admin/.local/lib/python3.11/site-packages')
from imprint_memory import memory_manager as mm
from imprint_memory import bus


# ---------- enums (动态从 /home/admin/memory-api/enums.json 读) ----------
ENUMS_PATH = '/home/admin/memory-api/enums.json'


def _load_enums():
    try:
        with open(ENUMS_PATH) as f:
            data = json.load(f)
        names = set(data.get('names', []))
        categories = set(data.get('categories', []))
        return names, categories
    except Exception:
        # Fallback 如果文件坏了
        return (
            {'cc', 'atou', 'ashen', 'adu', 'feifei', 'catherine', 'other'},
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
    """POST /api/memories  body: {content, category?, name?/source?, importance?, tags?}"""
    data = await request.json()
    content = data.get('content', '').strip()
    if not content:
        return JSONResponse({'error': 'content required'}, status_code=400)
    # name is alias for source
    name = (data.get('name') or data.get('source') or 'cc').strip()
    allowed_names, allowed_categories = _load_enums()
    if name not in allowed_names:
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


# ---------- message bus (board) ----------

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


# ---------- bulletin board ----------

async def get_bulletin(request: Request):
    """GET /api/board/bulletin — return raw markdown content of config/board.md"""
    path = '/home/admin/memory-api/config/board.md'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return JSONResponse({'markdown': f.read()})
    except FileNotFoundError:
        return JSONResponse({'markdown': ''})

async def put_bulletin(request: Request):
    """PUT /api/board/bulletin — replace whole markdown content of config/board.md
       body: {"markdown": "..."}"""
    data = await request.json()
    md = data.get('markdown', '')
    path = '/home/admin/memory-api/config/board.md'
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(md)
        return JSONResponse({'ok': True})
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)




# ---------- enums exposure ----------

async def get_enums(request: Request):
    """GET /api/enums — return allowed source names and categories"""
    names, categories = _load_enums()
    return JSONResponse({
        'names': sorted(names),
        'categories': sorted(categories),
    })


# ---------- health ----------

async def health(request: Request):
    return JSONResponse({'ok': True, 'service': 'memory-api'})


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
    Route('/api/board/bulletin', get_bulletin, methods=['GET']),
    Route('/api/board/bulletin', put_bulletin, methods=['PUT']),
]


app = Starlette(routes=routes)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8001)

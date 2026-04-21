# Deployment

Reference setup for running `her-memory` behind nginx on a Linux server.

## Goal

- `https://memory.your-domain.com/` → serves the static frontend
- `https://memory.your-domain.com/api/*` → proxies to the local REST API on port 8001
- `https://memory.your-domain.com/maYOUR_SECRET_TOKEN` → proxies to imprint-memory's MCP endpoint (from imprint-memory itself, for Claude Code / MCP clients)
- All frontend paths behind HTTP Basic Auth (only you can log in)
- Icon and manifest files accessible without auth (so iOS can fetch them when adding to home screen)

## 1. Install and configure imprint-memory on server

```bash
pip install imprint-memory jieba
```

Set up its config (HTTP mode with OAuth, or stdio — see imprint-memory docs). For our setup we run it as an HTTP service on port 8000.

Apply our patches:

```bash
python scripts/patch_imprint_memory.py
```

Start the MCP server (example with setsid):

```bash
PATH=$HOME/.local/bin:$PATH setsid nohup imprint-memory --http > ~/imprint-memory.log 2>&1 < /dev/null &
```

## 2. Deploy this app

Upload the repo to `/home/your_user/memory-api/`:

```
/home/your_user/memory-api/
├── app.py
├── config/
│   └── enums.json
└── static/
    ├── index.html
    ├── memory.html
    ├── board.html
    ├── manifest.json
    ├── apple-touch-icon.png
    ├── icon-192.png
    └── icon-512.png
```

Start the REST API:

```bash
cd /home/your_user/memory-api
nohup python3 app.py > api.log 2>&1 < /dev/null &
```

## 3. Create basic auth credentials

```bash
# Replace YOUR_USERNAME and YOUR_PASSWORD
openssl passwd -apr1 'YOUR_PASSWORD' | xargs -I {} echo 'YOUR_USERNAME:{}' | sudo tee /etc/nginx/.htpasswd
sudo chmod 644 /etc/nginx/.htpasswd
```

## 4. Nginx config

Example `/etc/nginx/conf.d/her-memory.conf`:

```nginx
server {
    server_name memory.your-domain.com;

    # MCP endpoint (no auth — for Claude Code / other MCP clients)
    # Replace the path with whatever secret token imprint-memory uses
    location /maYOUR_SECRET_TOKEN {
        proxy_pass http://127.0.0.1:8000/mcp;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }

    # Icons and manifest — no auth
    # (iOS fetches these when adding to home screen without credentials)
    location ~ ^/(icon-.*\.png|apple-touch-icon.*\.png|manifest\.json|favicon\.ico)$ {
        root /home/your_user/memory-api/static;
        access_log off;
    }

    # REST API — basic auth
    location /api/ {
        auth_basic "Her Claudes' Memory";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Static frontend — basic auth
    location / {
        auth_basic "Her Claudes' Memory";
        auth_basic_user_file /etc/nginx/.htpasswd;
        root /home/your_user/memory-api/static;
        index index.html;
        try_files $uri $uri/ =404;
    }

    listen 443 ssl;
    # SSL certs — use certbot or your provider
    ssl_certificate /etc/letsencrypt/live/memory.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/memory.your-domain.com/privkey.pem;
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name memory.your-domain.com;
    return 301 https://$host$request_uri;
}
```

## 5. SSL certificate

```bash
sudo certbot --nginx -d memory.your-domain.com
```

## 6. Reload nginx

```bash
sudo nginx -t && sudo nginx -s reload
```

## 7. Test

```bash
# Should be 401 (unauthorized without credentials)
curl -o /dev/null -w '%{http_code}\n' https://memory.your-domain.com/

# Should be 200 with credentials
curl -u 'YOUR_USERNAME:YOUR_PASSWORD' https://memory.your-domain.com/api/health

# Should be 200 without auth (iOS needs this)
curl -o /dev/null -w '%{http_code}\n' https://memory.your-domain.com/apple-touch-icon.png
```

## 8. Add to iOS home screen

In Safari on iPhone:
1. Open `https://memory.your-domain.com/`
2. Enter your credentials, check "remember"
3. Tap *Share* → *Add to Home Screen*

Opens full-screen like a native app.

## Memory rebuild (if you migrate or reset FTS5)

If you ever need to rebuild the jieba-tokenized full-text search index:

```bash
python3 -c "
import sqlite3
from imprint_memory.db import segment_cjk
db = sqlite3.connect('~/.imprint/memory.db')
db.create_function('segment_cjk', 1, segment_cjk)
cur = db.cursor()
cur.execute('DELETE FROM memories_fts')
cur.execute('INSERT INTO memories_fts(rowid, content, category, tags) SELECT id, segment_cjk(content), category, tags FROM memories')
db.commit()
print(f\"Rebuilt FTS: {cur.execute('SELECT COUNT(*) FROM memories_fts').fetchone()[0]} entries\")
"
```

---

## Running in development (without nginx)

For local testing without a full nginx setup, just run `app.py` and open a browser to `http://127.0.0.1:8001/static/index.html` — no auth, no SSL. Obviously don't expose this to the internet.

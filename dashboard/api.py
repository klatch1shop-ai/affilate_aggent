import os, sys, json, re
from datetime import datetime
from decimal import Decimal
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import httpx
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
ENV_PATH = os.path.join(os.path.dirname(__file__), "../.env")
load_dotenv(dotenv_path=ENV_PATH)

from shared.utils.db import get_connection
from shared.utils.redis_queue import get_queue_length, push_task

app = FastAPI(title="Agent System Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = os.path.dirname(__file__)
AGENT_NAMES = ["orchestrator", "scraper", "marketing", "developer", "finance", "efficiency"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def fix_types(rows: list) -> list:
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, datetime):
                r[k] = v.isoformat()
            elif isinstance(v, Decimal):
                r[k] = float(v)
    return rows


def update_env(key: str, value: str):
    with open(ENV_PATH, "r") as f:
        content = f.read()
    pattern = rf"^{re.escape(key)}=.*$"
    new_line = f"{key}={value}"
    if re.search(pattern, content, re.MULTILINE):
        content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{key}={value}\n"
    with open(ENV_PATH, "w") as f:
        f.write(content)
    os.environ[key] = value


def mask_token(val: str) -> str:
    if not val or val == "your_api_key_here":
        return ""
    return "•" * max(0, len(val) - 4) + val[-4:] if len(val) > 4 else "••••"


def get_stats():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, type, status, updated_at FROM agents ORDER BY name")
        agents = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT level, source, title, message, created_at, is_read "
            "FROM alerts ORDER BY created_at DESC LIMIT 20"
        )
        alerts = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT el.level, el.message, el.created_at, a.name as agent "
            "FROM event_logs el LEFT JOIN agents a ON el.agent_id=a.id "
            "ORDER BY el.created_at DESC LIMIT 50"
        )
        logs = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT marketplace, COUNT(*) as cnt, AVG(price) as avg_price "
            "FROM products GROUP BY marketplace"
        )
        products = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) as cnt FROM alerts WHERE is_read=false")
        unread = cur.fetchone()
        cur.close(); conn.close()

        queues = {a: get_queue_length(f"queue:{a}") for a in AGENT_NAMES}
        return {
            "agents":        fix_types(agents),
            "alerts":        fix_types(alerts),
            "logs":          fix_types(logs),
            "products":      fix_types(products),
            "queues":        queues,
            "unread_alerts": unread["cnt"] if unread else 0,
            "updated_at":    datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Dashboard endpoints ───────────────────────────────────────────────────────

@app.get("/api/stats")
def stats():
    return get_stats()


@app.post("/api/command")
async def send_command(body: dict):
    push_task("queue:orchestrator", {
        "type":        "admin_command",
        "description": body.get("command", ""),
        "priority":    8,
        "source":      "dashboard",
        "timestamp":   datetime.now().isoformat(),
    })
    return {"status": "ok", "command": body.get("command", "")}


@app.post("/api/alerts/read")
def mark_read():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE alerts SET is_read=true WHERE is_read=false")
    conn.commit(); cur.close(); conn.close()
    return {"status": "ok"}


# ── Products ──────────────────────────────────────────────────────────────────

@app.get("/api/products")
def get_products(
    marketplace: str = None,
    price_min: float = None,
    price_max: float = None,
    search: str = None,
    in_stock: str = None,
    page: int = 1,
    limit: int = 50,
):
    try:
        conn = get_connection()
        cur = conn.cursor()

        conditions, params = [], []
        if marketplace:
            conditions.append("marketplace = %s"); params.append(marketplace)
        if price_min is not None:
            conditions.append("price >= %s"); params.append(price_min)
        if price_max is not None:
            conditions.append("price <= %s"); params.append(price_max)
        if search:
            conditions.append("title ILIKE %s"); params.append(f"%{search}%")
        if in_stock not in (None, ""):
            conditions.append("in_stock = %s"); params.append(in_stock.lower() == "true")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        cur.execute(f"SELECT COUNT(*) as total FROM products {where}", params)
        total = cur.fetchone()["total"]

        offset = (page - 1) * limit
        cur.execute(
            f"""SELECT id, external_id, marketplace, title, price, old_price,
                       url, category, seller, in_stock, data, scraped_at
                FROM products {where}
                ORDER BY scraped_at DESC NULLS LAST
                LIMIT %s OFFSET %s""",
            params + [limit, offset],
        )
        products = fix_types([dict(r) for r in cur.fetchall()])

        cur.execute("SELECT DISTINCT marketplace FROM products ORDER BY marketplace")
        marketplaces = [r["marketplace"] for r in cur.fetchall()]

        cur.close(); conn.close()
        return {"products": products, "total": total, "page": page,
                "limit": limit, "marketplaces": marketplaces}
    except Exception as e:
        return {"error": str(e), "products": [], "total": 0,
                "page": 1, "limit": limit, "marketplaces": []}


@app.post("/api/products/{product_id}/upload-prom")
def upload_to_prom(product_id: int):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, price, url, category, marketplace FROM products WHERE id = %s",
            (product_id,),
        )
        product = cur.fetchone()
        cur.close(); conn.close()

        if not product:
            return {"status": "error", "message": "Товар не знайдено"}

        push_task("queue:scraper", {
            "type":        "upload_to_prom",
            "description": f"Upload product '{product['title']}' to Prom.ua",
            "priority":    7,
            "context":     fix_types([dict(product)])[0],
            "source":      "dashboard",
        })
        return {"status": "ok", "message": "Задачу відправлено агенту scraper"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    return {
        "prom": {
            "token":    mask_token(os.getenv("PROM_API_TOKEN", "")),
            "has_data": bool(os.getenv("PROM_API_TOKEN", "")),
        },
        "rozetka": {
            "login":    os.getenv("ROZETKA_LOGIN", ""),
            "has_data": bool(os.getenv("ROZETKA_LOGIN", "")),
        },
        "epicentr": {
            "login":    os.getenv("EPICENTR_LOGIN", ""),
            "has_data": bool(os.getenv("EPICENTR_LOGIN", "")),
        },
        "anthropic": {
            "token":    mask_token(anthropic_key),
            "has_data": bool(anthropic_key and anthropic_key != "your_api_key_here"),
        },
    }


@app.post("/api/settings")
def save_settings(body: dict):
    mapping = {
        "prom_token":        "PROM_API_TOKEN",
        "rozetka_login":     "ROZETKA_LOGIN",
        "rozetka_password":  "ROZETKA_PASSWORD",
        "epicentr_login":    "EPICENTR_LOGIN",
        "epicentr_password": "EPICENTR_PASSWORD",
        "anthropic_key":     "ANTHROPIC_API_KEY",
    }
    saved = []
    for field, env_key in mapping.items():
        if body.get(field):
            update_env(env_key, body[field])
            saved.append(env_key)
    return {"status": "ok", "saved": saved}


@app.post("/api/settings/check/{marketplace}")
async def check_marketplace(marketplace: str, body: dict):
    if marketplace == "prom":
        token = body.get("token") or os.getenv("PROM_API_TOKEN", "")
        if not token:
            return {"status": "error", "message": "Токен не вказано"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://my.prom.ua/api/v1/products/list?limit=1",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if r.status_code == 200:
                return {"status": "ok", "message": "Підключено ✓"}
            return {"status": "error", "message": f"HTTP {r.status_code} — перевір токен"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif marketplace == "rozetka":
        login = body.get("login") or os.getenv("ROZETKA_LOGIN", "")
        pwd   = body.get("password") or os.getenv("ROZETKA_PASSWORD", "")
        if not login or not pwd:
            return {"status": "error", "message": "Логін або пароль не вказано"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    "https://seller.rozetka.com.ua/site/login",
                    json={"username": login, "password": pwd},
                    headers={"Content-Type": "application/json"},
                )
            data = r.json()
            if data.get("success"):
                return {"status": "ok", "message": "Підключено ✓"}
            msg = (data.get("errors") or {}).get("message") or "Помилка авторизації"
            return {"status": "error", "message": msg}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif marketplace == "epicentr":
        login = body.get("login") or os.getenv("EPICENTR_LOGIN", "")
        pwd   = body.get("password") or os.getenv("EPICENTR_PASSWORD", "")
        if not login or not pwd:
            return {"status": "error", "message": "Логін або пароль не вказано"}
        return {"status": "ok", "message": "Дані збережено (перевірка під час скрейпінгу)"}

    return {"status": "error", "message": "Невідомий маркетплейс"}


# ── WebSockets ────────────────────────────────────────────────────────────────

active_ws: list = []


@app.websocket("/ws")
async def ws_dashboard(ws: WebSocket):
    await ws.accept()
    active_ws.append(ws)
    try:
        while True:
            await ws.send_json(get_stats())
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        if ws in active_ws:
            active_ws.remove(ws)


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) as m FROM event_logs")
        last_id = cur.fetchone()["m"]
        cur.close(); conn.close()
    except Exception:
        last_id = 0

    try:
        while True:
            try:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    """SELECT el.id, el.level, el.message, el.created_at,
                              a.name as agent_name
                       FROM event_logs el
                       LEFT JOIN agents a ON el.agent_id = a.id
                       WHERE el.id > %s
                       ORDER BY el.id ASC LIMIT 30""",
                    (last_id,),
                )
                new_logs = fix_types([dict(r) for r in cur.fetchall()])

                cur.execute("SELECT name, status FROM agents ORDER BY name")
                agents = [dict(r) for r in cur.fetchall()]
                cur.close(); conn.close()

                if new_logs:
                    last_id = new_logs[-1]["id"]

                await ws.send_json({"type": "update", "logs": new_logs, "agents": agents})
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


# ── Pages (SPA) ───────────────────────────────────────────────────────────────

def _serve_html():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/")
def root():
    return _serve_html()


@app.get("/chat")
def page_chat():
    return _serve_html()


@app.get("/products")
def page_products():
    return _serve_html()


@app.get("/settings")
def page_settings():
    return _serve_html()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888, reload=False)

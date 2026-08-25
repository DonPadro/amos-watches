from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import (
    Cookie,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeSerializer
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

ROOT = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(ROOT / ".env")

import commerce

DATA = ROOT / "data"
UPLOADS = ROOT / "uploads"
DB_PATH = DATA / "amos.db"
SECRET_FILE = DATA / "secret.txt"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "AmosWatches")

DATA.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)

SEED_CATEGORIES = [
    ("watches", "שעונים", "כרונוגרפים, אוטומטיים ועיצובים קלאסיים שנבחרו בקפידה.", 1),
    ("jewelry", "תכשיטים", "זהב, יהלומים ופנינים — פריטים שמשלימים את השעון.", 2),
]

SEED_PRODUCTS = [
    (
        "watches",
        "Midnight Chronograph",
        24900,
        "כרונוגרף כהה עם מסגרת קרמית ולוח מחוונים עמוק. נוכחות חדה לערב וליום.",
        "https://images.unsplash.com/photo-1523170335258-f5ed11844a49?auto=format&fit=crop&w=900&q=80",
        1,
    ),
    (
        "watches",
        "Royal Gold Automatic",
        31500,
        "אוטומטי בזהב עם חיוג שמפניה. קלאסיקה חמה שמתאימה גם כשעון ירושה.",
        "https://images.unsplash.com/photo-1614164185128-e4ec99c436d7?auto=format&fit=crop&w=900&q=80",
        1,
    ),
    (
        "watches",
        "Steel Heritage",
        18400,
        "פלדה מוברשת, אינדקסים נקיים, קוטר מדויק ליד. השעון היומיומי של הבוטיק.",
        "https://images.unsplash.com/photo-1524592094714-0f0654e20314?auto=format&fit=crop&w=900&q=80",
        0,
    ),
    (
        "watches",
        "Moonphase Noir",
        27200,
        "פאזת ירח על רקע שחור. פריט שיחה עם תנועה מכנית גלויה.",
        "https://images.unsplash.com/photo-1547996160-81dfa63595aa?auto=format&fit=crop&w=900&q=80",
        0,
    ),
    (
        "jewelry",
        "Tennis Bracelet",
        14800,
        "צמיד טניס ביהלומים עגולים. ברק רציף שנלבש לבד או מעל חפת השעון.",
        "https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?auto=format&fit=crop&w=900&q=80",
        1,
    ),
    (
        "jewelry",
        "Solitaire Ring",
        22000,
        "טבעת סוליטר עם אבן מרכזית ושיבוץ נקי. מתאימה לאירוע ולכל יום.",
        "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=900&q=80",
        1,
    ),
    (
        "jewelry",
        "Pearl Strand",
        6900,
        "שרשרת פנינים עם סוגר זהב. רכות מול הקשיחות של שעון פלדה.",
        "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=900&q=80",
        0,
    ),
    (
        "jewelry",
        "Gold Chain",
        8400,
        "שרשרת זהב במשקל בינוני. שכבה בסיסית לארון תכשיטים של גבר או אישה.",
        "https://images.unsplash.com/photo-1611591437281-460bfbe1220a?auto=format&fit=crop&w=900&q=80",
        0,
    ),
]


def get_secret() -> str:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(32)
    SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


SIGNER = URLSafeSerializer(get_secret(), salt="amos-admin")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180_000)
        return secrets.compare_digest(digest.hex(), digest_hex)
    except ValueError:
        return False


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                price INTEGER NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                image TEXT NOT NULL,
                featured INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                address TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                zip TEXT NOT NULL DEFAULT '',
                shipping_method TEXT NOT NULL DEFAULT 'home',
                shipping_cost INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                paid_at INTEGER,
                finalized_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_id INTEGER,
                title TEXT NOT NULL,
                price INTEGER NOT NULL,
                qty INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                yaad_id TEXT,
                acode TEXT,
                ccode TEXT,
                amount INTEGER,
                status TEXT NOT NULL,
                payload TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                ip TEXT,
                actor_id INTEGER,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS google_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author TEXT NOT NULL,
                rating INTEGER NOT NULL,
                body TEXT NOT NULL,
                relative_time TEXT,
                fetched_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS presence (
                id TEXT PRIMARY KEY,
                last_seen INTEGER NOT NULL,
                page TEXT
            );
            """
        )
        existing = conn.execute("SELECT COUNT(*) AS n FROM categories").fetchone()["n"]
        if existing == 0:
            for slug, name, desc, order in SEED_CATEGORIES:
                conn.execute(
                    "INSERT INTO categories (slug, name, description, sort_order) VALUES (?,?,?,?)",
                    (slug, name, desc, order),
                )
            cats = {
                row["slug"]: row["id"]
                for row in conn.execute("SELECT id, slug FROM categories")
            }
            now = int(time.time())
            for i, (slug, title, price, desc, image, featured) in enumerate(SEED_PRODUCTS):
                conn.execute(
                    """INSERT INTO products
                    (category_id, title, price, description, image, featured, sort_order, created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (cats[slug], title, price, desc, image, featured, i, now),
                )
        if not conn.execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('admin_hash', ?)",
                (hash_password(ADMIN_PASSWORD),),
            )
        if conn.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()["n"] == 0:
            stored = conn.execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone()
            conn.execute(
                "INSERT INTO admin_users (email, password_hash, role, created_at) VALUES (?,?,?,?)",
                ("owner@amos", stored["value"] if stored else hash_password(ADMIN_PASSWORD), "owner", int(time.time())),
            )
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
        for name, spec in (
            ("address", "TEXT NOT NULL DEFAULT ''"),
            ("city", "TEXT NOT NULL DEFAULT ''"),
            ("zip", "TEXT NOT NULL DEFAULT ''"),
            ("shipping_method", "TEXT NOT NULL DEFAULT 'home'"),
            ("shipping_cost", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in existing_cols:
                conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {spec}")


init_db()

presence_lock = threading.Lock()
online: dict[str, float] = {}
sockets: set[WebSocket] = set()


def online_count() -> int:
    now = time.time()
    with presence_lock:
        stale = [k for k, ts in online.items() if now - ts > 45]
        for k in stale:
            online.pop(k, None)
        memory = len(online)
    with db() as conn:
        conn.execute("DELETE FROM presence WHERE last_seen < ?", (int(now) - 45,))
        persisted = conn.execute("SELECT COUNT(*) AS n FROM presence").fetchone()["n"]
    return max(memory, persisted, 1 if sockets else 0)


async def broadcast_presence() -> None:
    payload = json.dumps({"type": "presence", "count": online_count()})
    dead: list[WebSocket] = []
    for ws in list(sockets):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        sockets.discard(ws)


def slugify(name: str) -> str:
    hebrew_ok = re.sub(r"[^\w\u0590-\u05FF-]+", "-", name.strip(), flags=re.UNICODE)
    slug = hebrew_ok.strip("-").lower() or f"cat-{secrets.token_hex(3)}"
    return slug[:48]


def client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "")


def log_security(kind: str, message: str, ip: str = "", actor_id: int | None = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO security_events (kind, message, ip, actor_id, created_at) VALUES (?,?,?,?,?)",
            (kind, message, ip, actor_id, int(time.time())),
        )


def notify_admin_security_job(kind: str, message: str) -> dict[str, Any]:
    text = f"אבטחת AMOS [{kind}]\n{message}"
    result = commerce.notify_whatsapp(text)
    return {"kind": kind, **result}


def session_user(session: str | None) -> dict[str, Any]:
    if not session:
        raise HTTPException(status_code=401, detail="נדרשת התחברות")
    try:
        data = SIGNER.loads(session)
    except BadSignature as exc:
        raise HTTPException(status_code=401, detail="הסשן פג") from exc
    with db() as conn:
        row = conn.execute("SELECT * FROM admin_users WHERE id=?", (data.get("uid"),)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="משתמש לא נמצא")
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


def require_role(session: str | None, *roles: str) -> dict[str, Any]:
    user = session_user(session)
    if user["role"] not in roles:
        raise HTTPException(status_code=403, detail="אין הרשאה לפעולה הזו")
    return user


def require_admin(session: str | None) -> dict[str, Any]:
    return require_role(session, "owner", "admin", "staff")


def touch_presence(uid: str, page: str = "/") -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO presence (id, last_seen, page) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, page=excluded.page",
            (uid, int(time.time()), page),
        )
        conn.execute("DELETE FROM presence WHERE last_seen < ?", (int(time.time()) - 45,))


def fetch_order(conn: sqlite3.Connection, public_id: str) -> dict[str, Any] | None:
    order = conn.execute("SELECT * FROM orders WHERE public_id=?", (public_id,)).fetchone()
    if not order:
        return None
    items = [dict(row) for row in conn.execute("SELECT * FROM order_items WHERE order_id=?", (order["id"],))]
    data = dict(order)
    data["items"] = items
    return data


def seo_tags(
    title: str,
    description: str,
    path: str = "/",
    image: str = "",
    keywords: str = "",
    extra_json: list[dict[str, Any]] | None = None,
) -> str:
    url = f"{commerce.site_url()}{path}"
    img = image if image.startswith("http") else (commerce.site_url() + image if image else f"{commerce.site_url()}/")
    safe_title = html.escape(title)
    safe_desc = html.escape(description)
    keys = html.escape(keywords or "AMOS Watches, עמוס, שעונים, תכשיטים")
    graph: list[dict[str, Any]] = [
        {
            "@type": "JewelryStore",
            "@id": f"{commerce.site_url()}/#boutique",
            "name": "AMOS Watches | עמוס",
            "alternateName": ["עמוס שעונים", "AMOS Watches IL"],
            "url": commerce.site_url(),
            "description": description,
            "image": img,
            "inLanguage": "he-IL",
            "areaServed": {"@type": "Country", "name": "Israel"},
            "knowsAbout": ["שעונים", "תכשיטים"],
            "sameAs": ["https://www.instagram.com/amos_watches_il/"],
        },
        {
            "@type": "WebSite",
            "name": "AMOS Watches",
            "url": commerce.site_url(),
            "inLanguage": "he",
            "publisher": {"@id": f"{commerce.site_url()}/#boutique"},
        },
    ]
    if extra_json:
        graph.extend(extra_json)
    ld = {"@context": "https://schema.org", "@graph": graph}
    return f"""
    <title>{safe_title}</title>
    <meta name="description" content="{safe_desc}" />
    <meta name="keywords" content="{keys}" />
    <meta name="robots" content="index,follow,max-image-preview:large" />
    <meta name="geo.region" content="IL" />
    <meta name="language" content="Hebrew" />
    <link rel="canonical" href="{html.escape(url)}" />
    <link rel="alternate" hreflang="he-IL" href="{html.escape(url)}" />
    <link rel="alternate" hreflang="x-default" href="{html.escape(url)}" />
    <link rel="manifest" href="/manifest.json" />
    <meta property="og:type" content="website" />
    <meta property="og:locale" content="he_IL" />
    <meta property="og:site_name" content="AMOS Watches | שעוני יוקרה" />
    <meta property="og:title" content="{safe_title}" />
    <meta property="og:description" content="{safe_desc}" />
    <meta property="og:url" content="{html.escape(url)}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{safe_title}" />
    <meta name="twitter:description" content="{safe_desc}" />
    <script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
    """


def row_product(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "category_id": row["category_id"],
        "category": row["category_name"],
        "category_slug": row["category_slug"],
        "title": row["title"],
        "price": row["price"],
        "price_label": f"₪{row['price']:,}".replace(",", ","),
        "description": row["description"],
        "image": row["image"],
        "featured": bool(row["featured"]),
    }


def fetch_catalog(conn: sqlite3.Connection) -> dict[str, Any]:
    categories = [
        dict(row)
        for row in conn.execute(
            "SELECT id, slug, name, description, sort_order FROM categories ORDER BY sort_order, id"
        )
    ]
    products = [
        row_product(row)
        for row in conn.execute(
            """
            SELECT p.*, c.name AS category_name, c.slug AS category_slug
            FROM products p JOIN categories c ON c.id = p.category_id
            ORDER BY c.sort_order, p.sort_order, p.id
            """
        )
    ]
    return {"categories": categories, "products": products}


app = FastAPI(title="AMOS Watches")
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
app.mount("/css", StaticFiles(directory=ROOT / "css"), name="css")
app.mount("/js", StaticFiles(directory=ROOT / "js"), name="js")
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "index.html")


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(ROOT / "admin.html")


@app.get("/checkout")
def checkout_page() -> FileResponse:
    return FileResponse(ROOT / "checkout.html")


@app.get("/item/{product_id}")
def item_page(product_id: int) -> HTMLResponse:
    with db() as conn:
        row = conn.execute(
            """SELECT p.*, c.name AS category_name FROM products p
               JOIN categories c ON c.id = p.category_id WHERE p.id=?""",
            (product_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "הפריט לא נמצא")
    tags = seo_tags(
        f"{row['title']} | AMOS Watches",
        row["description"] or f"{row['title']} בבוטיק AMOS",
        f"/item/{product_id}",
        row["image"],
        extra_json=[
            {
                "@type": "Product",
                "name": row["title"],
                "description": row["description"],
                "image": row["image"],
                "brand": {"@type": "Brand", "name": "AMOS Watches"},
                "category": row["category_name"],
                "offers": {
                    "@type": "Offer",
                    "priceCurrency": "ILS",
                    "price": row["price"],
                    "availability": "https://schema.org/InStock",
                    "url": f"{commerce.site_url()}/item/{product_id}",
                },
            }
        ],
    )
    return HTMLResponse(
        f"""<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="UTF-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        {tags}<link rel="stylesheet" href="/css/styles.css"/></head>
        <body><header class="nav"><a class="logo" href="/"><span class="logo-en">AMOS Watches</span>
        <span class="logo-he">עמוס ⌚</span></a></header>
        <main class="collection"><p class="eyebrow">{html.escape(row['category_name'])}</p>
        <h1>{html.escape(row['title'])}</h1>
        <p class="price">₪{row['price']:,}</p>
        <p>{html.escape(row['description'])}</p>
        <img src="{html.escape(row['image'])}" alt="{html.escape(row['title'])}" style="max-width:420px"/>
        <p><a class="btn btn-gold" href="/checkout">לקופה</a> <a class="btn btn-ghost" href="/">חזרה</a></p>
        </main><script src="/js/seo.js"></script></body></html>"""
    )


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    with db() as conn:
        return fetch_catalog(conn)


@app.get("/api/presence")
def presence() -> dict[str, int]:
    return {"count": max(online_count(), 1)}


@app.post("/api/login")
def login(payload: dict[str, str], request: Request) -> JSONResponse:
    password = (payload or {}).get("password", "")
    email = ((payload or {}).get("email") or "owner@amos").strip().lower()
    with db() as conn:
        row = conn.execute("SELECT * FROM admin_users WHERE email=?", (email,)).fetchone()
        if not row:
            row = conn.execute("SELECT * FROM admin_users WHERE role='owner' ORDER BY id LIMIT 1").fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        log_security("login_failed", f"כניסה נכשלה עבור {email}", client_ip(request))
        notify_admin_security_job("login_failed", f"ניסיון כניסה נכשל: {email} מ-{client_ip(request)}")
        raise HTTPException(status_code=401, detail="סיסמה שגויה")
    token = SIGNER.dumps({"uid": row["id"], "role": row["role"], "t": int(time.time())})
    response = JSONResponse({"ok": True, "role": row["role"], "email": row["email"]})
    response.set_cookie(
        "amos_session",
        token,
        httponly=True,
        samesite="lax",
        secure=commerce.site_url().startswith("https"),
        max_age=60 * 60 * 24 * 7,
    )
    return response


@app.post("/api/logout")
def logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie("amos_session", secure=commerce.site_url().startswith("https"), samesite="lax")
    return response


@app.get("/api/me")
def me(amos_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    try:
        user = require_admin(amos_session)
        return {"admin": True, "role": user["role"], "email": user["email"]}
    except HTTPException:
        return {"admin": False}


@app.get("/api/admin/stats")
def stats(amos_session: str | None = Cookie(default=None)) -> dict[str, int]:
    require_admin(amos_session)
    with db() as conn:
        products = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
        categories = conn.execute("SELECT COUNT(*) AS n FROM categories").fetchone()["n"]
        featured = conn.execute("SELECT COUNT(*) AS n FROM products WHERE featured=1").fetchone()["n"]
        orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
        paid = conn.execute("SELECT COUNT(*) AS n FROM orders WHERE status IN ('paid','finalized')").fetchone()["n"]
    return {
        "products": products,
        "categories": categories,
        "featured": featured,
        "orders": orders,
        "paid": paid,
        "online": max(online_count(), 1),
    }


@app.post("/api/admin/categories")
def create_category(payload: dict[str, Any], amos_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    require_role(amos_session, "owner", "admin")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "חסר שם קטגוריה")
    slug = slugify(payload.get("slug") or name)
    description = (payload.get("description") or "").strip()
    sort_order = int(payload.get("sort_order") or 0)
    with db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO categories (slug, name, description, sort_order) VALUES (?,?,?,?)",
                (slug, name, description, sort_order),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(400, "הסלאג כבר קיים") from exc
        return {"id": cur.lastrowid, "slug": slug, "name": name, "description": description, "sort_order": sort_order}


@app.put("/api/admin/categories/{category_id}")
def update_category(
    category_id: int, payload: dict[str, Any], amos_session: str | None = Cookie(default=None)
) -> dict[str, str]:
    require_role(amos_session, "owner", "admin")
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    sort_order = int(payload.get("sort_order") or 0)
    slug = slugify(payload.get("slug") or name)
    with db() as conn:
        conn.execute(
            "UPDATE categories SET slug=?, name=?, description=?, sort_order=? WHERE id=?",
            (slug, name, description, sort_order, category_id),
        )
    return {"ok": "updated"}


@app.delete("/api/admin/categories/{category_id}")
def delete_category(category_id: int, amos_session: str | None = Cookie(default=None)) -> dict[str, str]:
    require_role(amos_session, "owner", "admin")
    with db() as conn:
        conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
    return {"ok": "deleted"}


@app.post("/api/admin/products")
async def create_product(
    amos_session: str | None = Cookie(default=None),
    category_id: int = Form(...),
    title: str = Form(...),
    price: int = Form(...),
    description: str = Form(""),
    featured: int = Form(0),
    image_url: str = Form(""),
    image: UploadFile | None = File(None),
) -> dict[str, Any]:
    require_role(amos_session, "owner", "admin")
    image_path = await save_image(image, image_url)
    with db() as conn:
        cur =         conn.execute(
            """INSERT INTO products
            (category_id, title, price, description, image, featured, sort_order, created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                category_id,
                title.strip(),
                price,
                description.strip(),
                image_path,
                1 if str(featured) in {"1", "true", "on"} else 0,
                0,
                int(time.time()),
            ),
        )
        return {"id": cur.lastrowid}


@app.put("/api/admin/products/{product_id}")
async def update_product(
    product_id: int,
    amos_session: str | None = Cookie(default=None),
    category_id: int = Form(...),
    title: str = Form(...),
    price: int = Form(...),
    description: str = Form(""),
    featured: int = Form(0),
    image_url: str = Form(""),
    image: UploadFile | None = File(None),
) -> dict[str, str]:
    require_role(amos_session, "owner", "admin")
    with db() as conn:
        current = conn.execute("SELECT image FROM products WHERE id=?", (product_id,)).fetchone()
        if not current:
            raise HTTPException(404, "הפריט לא נמצא")
        image_path = current["image"]
        uploaded = await save_image(image, image_url, allow_empty=True)
        if uploaded:
            image_path = uploaded
        conn.execute(
            """UPDATE products SET category_id=?, title=?, price=?, description=?, image=?, featured=?
            WHERE id=?""",
            (
                category_id,
                title.strip(),
                price,
                description.strip(),
                image_path,
                1 if str(featured) in {"1", "true", "on"} else 0,
                product_id,
            ),
        )
    return {"ok": "updated"}


@app.delete("/api/admin/products/{product_id}")
def delete_product(product_id: int, amos_session: str | None = Cookie(default=None)) -> dict[str, str]:
    require_role(amos_session, "owner", "admin")
    with db() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
    return {"ok": "deleted"}


async def save_image(image: UploadFile | None, image_url: str, allow_empty: bool = False) -> str:
    if image and image.filename:
        ext = Path(image.filename).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            raise HTTPException(400, "סוג קובץ לא נתמך")
        name = f"{uuid4().hex}{ext}"
        dest = UPLOADS / name
        dest.write_bytes(await image.read())
        return f"/uploads/{name}"
    url = (image_url or "").strip()
    if url:
        return url
    if allow_empty:
        return ""
    raise HTTPException(400, "חסרה תמונה")


@app.post("/api/ai")
def ai_chat(payload: dict[str, str]) -> dict[str, str]:
    message = (payload.get("message") or "").strip()
    if not message:
        return {"reply": "כתבו שאלה על שעון, תכשיט, מחיר או איך להזמין."}
    with db() as conn:
        catalog = fetch_catalog(conn)
    return {"reply": boutique_reply(message, catalog)}


def boutique_reply(message: str, catalog: dict[str, Any]) -> str:
    text = message.lower()
    products = catalog["products"]
    categories = catalog["categories"]

    if any(word in text for word in ("אינסטגרם", "instagram", "עקבו")):
        return "הפרופיל שלנו: @amos_watches_il — AMOS Watches | עמוס ⌚. אפשר לכתוב שם ישירות או לשלוח פנייה מהאתר."
    if any(word in text for word in ("וואטסאפ", "whatsapp", "הזמנ", "קשר", "טלפון")):
        return "אפשר לרכוש באתר בכרטיס אשראי, עם משלוח עד הבית על חשבוננו. אפשר גם להשאיר פרטים בטופס או לכתוב באינסטגרם."
    if any(word in text for word in ("משלוח", "אשראי", "כרטיס", "קופה", "רכיש")):
        return "רכישה מהאתר: ממלאים כתובת למשלוח עד הבית, המשלוח עלינו, ומשלמים בכרטיס אשראי מאובטח דרך הקופה."
    if any(word in text for word in ("אמיתי", "אותנטי", "מקורי", "fake")):
        return "הבוטיק עובד עם אימות ואמינות בפריטי יוקרה. לכל פריט נשמח לפרט מקור, מצב ואחריות לפני רכישה."
    if any(word in text for word in ("חסדי", "עמוס", "מי אתם", "עסק")):
        return "AMOS Watches | עמוס ⌚ — עסק שנבנה בחסדי השם 🙏. Luxury Watches • Premium Service. יוקרה בכל שנייה ⏱."

    scored: list[tuple[int, dict[str, Any]]] = []
    tokens = re.findall(r"[\w\u0590-\u05FF]+", text, flags=re.UNICODE)
    for product in products:
        hay = f"{product['title']} {product['description']} {product['category']}".lower()
        score = sum(2 if token in hay else 0 for token in tokens if len(token) > 2)
        if "שעון" in text and product["category_slug"] == "watches":
            score += 2
        if any(w in text for w in ("תכשיט", "טבעת", "צמיד", "שרשרת")) and product["category_slug"] == "jewelry":
            score += 2
        if product["featured"]:
            score += 1
        if score:
            scored.append((score, product))
    scored.sort(key=lambda item: (-item[0], item[1]["price"]))

    if scored:
        top = [item[1] for item in scored[:3]]
        lines = ["מצאתי התאמות מהאוסף:"]
        for item in top:
            badge = " · מומלץ" if item["featured"] else ""
            lines.append(f"• {item['title']} ({item['category']}) — {item['price_label']}{badge}")
        lines.append("אפשר לפתוח את הפריט באתר או לשאול עליו בוואטסאפ.")
        return "\n".join(lines)

    if any(word in text for word in ("זול", "תקציב", "מחיר", "התחל")):
        cheapest = sorted(products, key=lambda p: p["price"])[:3]
        lines = ["כמה פריטים נגישים יותר באוסף:"]
        lines.extend(f"• {p['title']} — {p['price_label']}" for p in cheapest)
        return "\n".join(lines)

    names = " · ".join(c["name"] for c in categories) or "האוסף"
    return (
        f"אני העוזר של AMOS. אפשר לשאול על {names}, המלצה לפי תקציב, או איך להזמין. "
        "יוקרה בכל שנייה ⏱"
    )


def apply_paid(conn: sqlite3.Connection, order: sqlite3.Row, payload: dict[str, Any], status: str = "paid") -> dict[str, Any]:
    now = int(time.time())
    conn.execute(
        "UPDATE orders SET status=?, paid_at=COALESCE(paid_at, ?) WHERE id=?",
        ("paid" if status == "paid" else status, now, order["id"]),
    )
    conn.execute(
        """INSERT INTO payments (order_id, provider, yaad_id, acode, ccode, amount, status, payload, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            order["id"],
            payload.get("provider", "yaad"),
            payload.get("Id") or payload.get("yaad_id"),
            payload.get("ACode"),
            payload.get("CCode"),
            int(float(payload.get("Amount") or order["total"])),
            "captured",
            json.dumps(payload, ensure_ascii=False),
            now,
        ),
    )
    return fetch_order(conn, order["public_id"])  # type: ignore[return-value]


def run_notify_order(public_id: str) -> dict[str, Any]:
    with db() as conn:
        order = fetch_order(conn, public_id)
    if not order:
        raise HTTPException(404, "ההזמנה לא נמצאה")
    result = commerce.notify_whatsapp(commerce.order_whatsapp_text(order, order["items"]))
    return {"order": public_id, **result}


def run_send_receipt(public_id: str) -> dict[str, Any]:
    with db() as conn:
        order = fetch_order(conn, public_id)
    if not order:
        raise HTTPException(404, "ההזמנה לא נמצאה")
    return {"order": public_id, **commerce.send_email_receipt(order, order["items"])}


@app.post("/api/orders")
def create_order(payload: dict[str, Any]) -> dict[str, Any]:
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    email = (payload.get("email") or "").strip()
    address = (payload.get("address") or "").strip()
    city = (payload.get("city") or "").strip()
    zip_code = (payload.get("zip") or "").strip()
    items_in = payload.get("items") or []
    if not name or not phone or not email or not address or not city or not items_in:
        raise HTTPException(400, "חסרים פרטי הזמנה או כתובת למשלוח")
    public_id = secrets.token_hex(5)
    with db() as conn:
        rows = []
        total = 0
        for item in items_in:
            product = conn.execute("SELECT * FROM products WHERE id=?", (item.get("product_id"),)).fetchone()
            if not product:
                raise HTTPException(400, "פריט לא קיים")
            qty = max(1, int(item.get("qty") or 1))
            total += product["price"] * qty
            rows.append((product, qty))
        cur = conn.execute(
            """INSERT INTO orders (public_id, status, customer_name, phone, email, address, city, zip,
               shipping_method, shipping_cost, total, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                public_id,
                "awaiting_payment",
                name,
                phone,
                email,
                address,
                city,
                zip_code,
                "home",
                0,
                total,
                (payload.get("notes") or "").strip(),
                int(time.time()),
            ),
        )
        order_id = cur.lastrowid
        for product, qty in rows:
            conn.execute(
                "INSERT INTO order_items (order_id, product_id, title, price, qty) VALUES (?,?,?,?,?)",
                (order_id, product["id"], product["title"], product["price"], qty),
            )
        order = fetch_order(conn, public_id)
    return order


@app.get("/api/checkout-info")
def checkout_info() -> dict[str, Any]:
    return {
        "shipping": "home",
        "shipping_label": "משלוח עד הבית — עלינו",
        "shipping_cost": 0,
        "pay_ready": commerce.yaad_configured(),
        "pay_label": "כרטיס אשראי מאובטח" if commerce.yaad_configured() else "סליקה ממתינה למספר מסוף",
    }


@app.post("/api/yaad-create-payment")
def yaad_create_payment(payload: dict[str, Any]) -> dict[str, Any]:
    public_id = (payload.get("order") or payload.get("public_id") or "").strip()
    with db() as conn:
        order = fetch_order(conn, public_id)
        if not order:
            raise HTTPException(404, "ההזמנה לא נמצאה")
        if order["status"] in {"paid", "finalized"}:
            raise HTTPException(400, "ההזמנה כבר שולמה")
    try:
        result = commerce.yaad_create_payment(order)
    except Exception as exc:
        log_security("yaad_sign_failed", str(exc)[:300])
        raise HTTPException(502, "יצירת סליקה נכשלה") from exc
    return result


@app.api_route("/api/yaad-callback", methods=["GET", "POST"])
async def yaad_callback(request: Request) -> dict[str, Any]:
    query = {k: str(v) for k, v in request.query_params.items()}
    if request.method == "POST":
        form = await request.form()
        query.update({k: str(v) for k, v in form.items()})
    return verify_and_capture(query, source="callback")


@app.post("/api/verify-yaad-payment")
def verify_yaad_payment(payload: dict[str, Any]) -> dict[str, Any]:
    return verify_and_capture({k: str(v) for k, v in payload.items()}, source="verify")


def verify_and_capture(query: dict[str, str], source: str) -> dict[str, Any]:
    public_id = query.get("Order") or query.get("order") or ""
    if not public_id:
        raise HTTPException(400, "חסר מספר הזמנה")
    ok = commerce.yaad_verify_callback(query)
    ccode = query.get("CCode", "")
    approved = ok and ccode in {"0", "00", ""}
    if query.get("demo") == "1" and not commerce.yaad_configured():
        approved = True
    if not approved:
        log_security("yaad_rejected", f"{source} order={public_id} ccode={ccode}")
        raise HTTPException(400, "התשלום לא אומת")
    with db() as conn:
        order = conn.execute("SELECT * FROM orders WHERE public_id=?", (public_id,)).fetchone()
        if not order:
            raise HTTPException(404, "ההזמנה לא נמצאה")
        if order["status"] in {"paid", "finalized"}:
            return fetch_order(conn, public_id)  # type: ignore[return-value]
        updated = apply_paid(conn, order, {**query, "provider": "yaad-demo" if query.get("demo") == "1" else "yaad"})
    run_notify_order(public_id)
    try:
        run_send_receipt(public_id)
    except Exception:
        pass
    return updated


@app.post("/api/finalize-order")
def finalize_order(payload: dict[str, Any], amos_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    require_admin(amos_session)
    public_id = (payload.get("order") or "").strip()
    with db() as conn:
        order = conn.execute("SELECT * FROM orders WHERE public_id=?", (public_id,)).fetchone()
        if not order:
            raise HTTPException(404, "ההזמנה לא נמצאה")
        if order["status"] != "paid":
            raise HTTPException(400, "אפשר לסגור רק הזמנה ששולמה")
        conn.execute(
            "UPDATE orders SET status='finalized', finalized_at=? WHERE id=?",
            (int(time.time()), order["id"]),
        )
        return fetch_order(conn, public_id)  # type: ignore[return-value]


@app.post("/api/mark-order-paid-manual")
def mark_order_paid_manual(
    payload: dict[str, Any], request: Request, amos_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    user = require_admin(amos_session)
    public_id = (payload.get("order") or "").strip()
    with db() as conn:
        order = conn.execute("SELECT * FROM orders WHERE public_id=?", (public_id,)).fetchone()
        if not order:
            raise HTTPException(404, "ההזמנה לא נמצאה")
        updated = apply_paid(conn, order, {"provider": "manual", "ACode": payload.get("note") or "manual", "CCode": "0", "Amount": order["total"]})
    log_security("manual_paid", f"{user['email']} אישר ידנית {public_id}", client_ip(request), user["id"])
    run_notify_order(public_id)
    try:
        run_send_receipt(public_id)
    except Exception:
        pass
    return updated


@app.post("/api/notify-order")
def notify_order(payload: dict[str, Any], amos_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    require_admin(amos_session)
    return run_notify_order((payload.get("order") or "").strip())


@app.post("/api/send-order-receipt")
def send_order_receipt(payload: dict[str, Any], amos_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    require_admin(amos_session)
    return run_send_receipt((payload.get("order") or "").strip())


@app.get("/api/admin/orders")
def admin_orders(amos_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    require_admin(amos_session)
    with db() as conn:
        orders = [dict(row) for row in conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 80")]
        for order in orders:
            order["items"] = [dict(r) for r in conn.execute("SELECT * FROM order_items WHERE order_id=?", (order["id"],))]
    return {"orders": orders}


@app.post("/api/admin-ai-assistant")
def admin_ai_assistant(payload: dict[str, str], amos_session: str | None = Cookie(default=None)) -> dict[str, str]:
    require_admin(amos_session)
    message = (payload.get("message") or "").strip()
    with db() as conn:
        catalog = fetch_catalog(conn)
        orders = [dict(r) for r in conn.execute("SELECT public_id, status, total, customer_name FROM orders ORDER BY id DESC LIMIT 8")]
        events = [dict(r) for r in conn.execute("SELECT kind, message, created_at FROM security_events ORDER BY id DESC LIMIT 5")]
    extra = "\n".join(f"{o['public_id']} {o['status']} ₪{o['total']} {o['customer_name']}" for o in orders) or "אין הזמנות"
    sec = "\n".join(f"{e['kind']}: {e['message']}" for e in events) or "אין אירועי אבטחה"
    base = boutique_reply(message, catalog)
    return {"reply": f"{base}\n\nהזמנות אחרונות:\n{extra}\n\nאבטחה:\n{sec}"}


@app.get("/api/google-reviews")
def google_reviews() -> dict[str, Any]:
    cached_at = 0
    cached: list[dict[str, Any]] = []
    with db() as conn:
        row = conn.execute("SELECT fetched_at FROM google_reviews ORDER BY fetched_at DESC LIMIT 1").fetchone()
        cached_at = row["fetched_at"] if row else 0
        cached = [dict(r) for r in conn.execute("SELECT author, rating, body, relative_time FROM google_reviews ORDER BY id DESC LIMIT 8")]
    if cached and int(time.time()) - cached_at < 6 * 3600:
        return {"configured": True, "cached": True, "reviews": cached}
    try:
        data = commerce.fetch_google_reviews()
    except Exception as exc:
        return {"configured": False, "error": str(exc)[:200], "reviews": cached}
    if data.get("reviews"):
        with db() as conn:
            conn.execute("DELETE FROM google_reviews")
            for review in data["reviews"][:8]:
                conn.execute(
                    "INSERT INTO google_reviews (author, rating, body, relative_time, fetched_at) VALUES (?,?,?,?,?)",
                    (review["author"], review["rating"], review["body"], review.get("relative_time") or "", int(time.time())),
                )
    return data if data.get("reviews") else {"configured": data.get("configured", False), "reviews": cached}


@app.post("/api/assign-admin-role")
def assign_admin_role(
    payload: dict[str, Any], request: Request, amos_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    actor = require_role(amos_session, "owner")
    email = (payload.get("email") or "").strip().lower()
    role = (payload.get("role") or "staff").strip()
    password = payload.get("password") or secrets.token_urlsafe(10)
    if role not in {"admin", "staff", "owner"}:
        raise HTTPException(400, "תפקיד לא חוקי")
    if not email:
        raise HTTPException(400, "חסר אימייל")
    created = False
    with db() as conn:
        existing = conn.execute("SELECT id FROM admin_users WHERE email=?", (email,)).fetchone()
        if existing:
            conn.execute("UPDATE admin_users SET role=? WHERE email=?", (role, email))
        else:
            created = True
            conn.execute(
                "INSERT INTO admin_users (email, password_hash, role, created_at) VALUES (?,?,?,?)",
                (email, hash_password(password), role, int(time.time())),
            )
    log_security("role_assigned", f"{actor['email']} קבע {role} ל-{email}", client_ip(request), actor["id"])
    notify_admin_security_job("role_assigned", f"{actor['email']} העניק תפקיד {role} למשתמש {email}")
    return {"ok": True, "email": email, "role": role, "temporary_password": password if created else None}


@app.get("/api/admin/users")
def admin_users(amos_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    require_role(amos_session, "owner")
    with db() as conn:
        users = [dict(r) for r in conn.execute("SELECT id, email, role, created_at FROM admin_users ORDER BY id")]
    return {"users": users}


@app.get("/api/admin/security")
def admin_security(amos_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    require_role(amos_session, "owner", "admin")
    with db() as conn:
        events = [dict(r) for r in conn.execute("SELECT * FROM security_events ORDER BY id DESC LIMIT 40")]
    return {"events": events}


@app.post("/api/notify-admin-security")
def notify_admin_security_route(
    payload: dict[str, Any], request: Request, amos_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    user = require_role(amos_session, "owner", "admin")
    kind = (payload.get("kind") or "manual").strip()
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "חסרה הודעה")
    log_security(kind, message, client_ip(request), user["id"])
    return notify_admin_security_job(kind, message)


@app.get("/sitemap.xml")
def sitemap() -> Response:
    with db() as conn:
        products = conn.execute("SELECT id FROM products").fetchall()
    urls = [
        ("/", "1.0"),
        ("/checkout", "0.4"),
    ] + [(f"/item/{row['id']}", "0.7") for row in products]
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    body += "".join(
        f"<url><loc>{commerce.site_url()}{path}</loc><changefreq>weekly</changefreq><priority>{prio}</priority></url>\n"
        for path, prio in urls
    )
    body += "</urlset>"
    return Response(body, media_type="application/xml")


@app.get("/robots.txt")
def robots() -> PlainTextResponse:
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /item/\n"
        "Disallow: /admin\n"
        "Disallow: /api/\n"
        "Disallow: /success\n"
        f"Sitemap: {commerce.site_url()}/sitemap.xml\n"
    )


@app.get("/llms.txt")
def llms() -> PlainTextResponse:
    return PlainTextResponse(
        "# AMOS Watches | עמוס\n"
        "בוטיק שעונים ותכשיטים בישראל. עסק שנבנה בחסדי השם.\n"
        f"אתר: {commerce.site_url()}\n"
        "Instagram: https://www.instagram.com/amos_watches_il/\n"
    )


@app.get("/manifest.json")
def manifest() -> JSONResponse:
    return JSONResponse(
        {
            "name": "AMOS Watches | עמוס",
            "short_name": "AMOS",
            "lang": "he",
            "dir": "rtl",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0b0a09",
            "theme_color": "#c9a962",
            "description": "בוטיק שעונים ותכשיטים | AMOS Watches עמוס",
        }
    )


@app.get("/api/seo")
def seo_api(page: str = "home", id: int | None = None) -> dict[str, str]:
    pages = {
        "home": (
            "AMOS Watches | עמוס ⌚",
            "AMOS Watches | עמוס — בוטיק שעונים ותכשיטים. עסק שנבנה בחסדי השם. יוקרה בכל שנייה.",
        ),
        "checkout": ("קופה | AMOS Watches", "השלמת הזמנה בבוטיק AMOS."),
        "admin": ("פאנל ניהול | AMOS", "ניהול קטלוג, הזמנות והרשאות."),
    }
    if page == "item" and id:
        with db() as conn:
            row = conn.execute("SELECT title, description FROM products WHERE id=?", (id,)).fetchone()
        if row:
            return {
                "title": f"{row['title']} | AMOS Watches",
                "description": row["description"],
            }
    title, description = pages.get(page, pages["home"])
    return {"title": title, "description": description}


@app.get("/g/{slug}")
@app.get("/sheonei-yokra")
@app.get("/luxury-watches")
@app.get("/seonim-meyuhadim")
@app.get("/super-complication")
@app.get("/grand-complication")
def retired_guides(slug: str = "") -> RedirectResponse:
    return RedirectResponse("/", status_code=301)


@app.get("/success")
def success_page(request: Request) -> HTMLResponse:
    query = {k: str(v) for k, v in request.query_params.items()}
    status = "failed" if query.get("failed") == "1" else "pending"
    detail = ""
    if query.get("Order") and query.get("failed") != "1":
        try:
            order = verify_and_capture(query, source="success")
            status = "paid"
            detail = f"הזמנה {order['public_id']} אושרה. קבלה תישלח למייל אם הוגדר SMTP."
        except HTTPException as exc:
            status = "failed"
            detail = str(exc.detail)
    tags = seo_tags("תשלום | AMOS Watches", "סטטוס הזמנה", "/success")
    return HTMLResponse(
        f"""<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="UTF-8"/>{tags}
        <link rel="stylesheet" href="/css/styles.css"/></head>
        <body><main class="collection"><p class="eyebrow">{status}</p>
        <h1>{"תודה" if status == "paid" else "תשלום"}</h1>
        <p>{html.escape(detail or "חוזרים לבוטיק.")}</p>
        <a class="btn btn-gold" href="/">לאתר</a></main></body></html>"""
    )


@app.websocket("/ws/presence")
async def presence_socket(ws: WebSocket) -> None:
    await ws.accept()
    uid = uuid4().hex
    sockets.add(ws)
    with presence_lock:
        online[uid] = time.time()
    touch_presence(uid, "/")
    await broadcast_presence()
    try:
        while True:
            await ws.receive_text()
            with presence_lock:
                online[uid] = time.time()
            touch_presence(uid, "/")
            await ws.send_text(json.dumps({"type": "presence", "count": online_count()}))
    except WebSocketDisconnect:
        pass
    finally:
        sockets.discard(ws)
        with presence_lock:
            online.pop(uid, None)
        await broadcast_presence()

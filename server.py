# -*- coding: utf-8 -*-
"""
price-app — مدیریت و مقایسه قیمت کالاهای فروشگاه (اکالا / دیجی‌کالا)

اجرا در Termux:
    cd ~/price-app
    pip install -r requirements.txt
    python -m uvicorn server:app --host 0.0.0.0 --port 7667

سپس در مرورگر موبایل:  http://127.0.0.1:7667

نکته امنیتی:
- هیچ توکن / Cookie کاربر استخراج یا ذخیره نمی‌شود.
- هیچ تلاشی برای دور زدن CAPTCHA / WAF / احراز هویت نمی‌شود.
- قیمت‌دهی فقط از API عمومی جستجوی دیجی‌کالا با یک درخواست کوتاه و مودبانه انجام می‌شود؛
  در هر خطا یا عدم دسترسی، خروجی همیشه JSON معتبر با پیام فارسی برمی‌گردد.
"""

import json
import sqlite3
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ------------------------------------------------------------------ مسیرها
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "price_app.db"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# ------------------------------------------------------------------ لینک‌ها
# فقط ساخت لینک جستجو + دریافت عمومی و مجاز؛ بدون هیچ دور زدن امنیتی
DIGIKALA_SEARCH_URL = "https://www.digikala.com/search/?q={q}"
DIGIKALA_API_URL = "https://api.digikala.com/v1/search/?q={q}"   # API عمومی جستجو
OKALA_SEARCH_URL = "https://www.okala.com/search/?q={q}"

NET_TIMEOUT = 8  # ثانیه — درخواست کوتاه و مودبانه
UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")

FALLBACK_MSG = "قیمت خودکار قابل دریافت نیست؛ برای مشاهده قیمت، صفحه جستجو را باز کنید."

# ------------------------------------------------------------------ پایگاه داده
_db_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db_lock:
        conn = get_db()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name           TEXT    NOT NULL,
                barcode        TEXT    DEFAULT '',
                store_price    INTEGER DEFAULT 0,
                okala_price    INTEGER,
                digikala_price INTEGER,
                ref_source     TEXT    DEFAULT '',
                check_date     TEXT,
                last_update    TEXT,
                okala_url      TEXT,
                digikala_url   TEXT
            );
            CREATE TABLE IF NOT EXISTS price_history (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id     INTEGER NOT NULL,
                check_date     TEXT,
                store_price    INTEGER,
                okala_price    INTEGER,
                digikala_price INTEGER
            );
            """)
            conn.commit()
        finally:
            conn.close()


init_db()  # ساخت جدول‌ها هنگام اجرا؛ فایل db خودکار ساخته می‌شود


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ------------------------------------------------------------------ ابزارها
def build_urls(name: str) -> dict:
    """ساخت لینک‌های جستجو برای اکالا و دیجی‌کالا (روش مجاز مرورگر)."""
    q = urllib.parse.quote(name)
    return {
        "okala": OKALA_SEARCH_URL.format(q=q),
        "digikala": DIGIKALA_SEARCH_URL.format(q=q),
    }


def try_digikala_price(name: str) -> Optional[int]:
    """
    یک تلاش مودبانه برای دریافت قیمت از API عمومی جستجوی دیجی‌کالا.
    در هر نوع خطا (شبکه، HTML، کپچا، تغییر ساختار) بدون خطا None برمی‌گرداند.
    """
    url = DIGIKALA_API_URL.format(q=urllib.parse.quote(name))
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
        for p in (payload.get("data") or {}).get("products") or []:
            variant = (p.get("default_variant") or {}).get("price") or {}
            price = variant.get("selling_price")
            if price:
                return int(price)
    except Exception:
        pass
    return None


def upsert_product(name: str, store_price: int,
                   okala_price: Optional[int] = None,
                   digikala_price: Optional[int] = None,
                   urls: Optional[dict] = None,
                   barcode: str = "") -> dict:
    """ایجاد یا به‌روزرسانی کالا + ثبت یک ردیف تاریخچه برای امروز."""
    now = now_str()
    today = today_str()
    urls = urls or {}
    okala_url = urls.get("okala") or ""
    digikala_url = urls.get("digikala") or ""

    refs = []
    if okala_price is not None:
        refs.append("اکالا")
    if digikala_price is not None:
        refs.append("دیجی‌کالا")
    ref_source = "، ".join(refs) if refs else ""

    with _db_lock:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id FROM products WHERE name = ?", (name,)).fetchone()
            if row:
                pid = row["id"]
                conn.execute("""
                    UPDATE products
                       SET store_price=?, barcode=?, okala_price=?, digikala_price=?,
                           ref_source=?, last_update=?, okala_url=?, digikala_url=?
                     WHERE id=?
                """, (store_price, barcode, okala_price, digikala_price,
                      ref_source, now, okala_url, digikala_url, pid))
            else:
                cur = conn.execute("""
                    INSERT INTO products
                        (name, barcode, store_price, okala_price, digikala_price,
                         ref_source, check_date, last_update, okala_url, digikala_url)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (name, barcode, store_price, okala_price, digikala_price,
                      ref_source, now, now, okala_url, digikala_url))
                pid = cur.lastrowid

            # تاریخچه: یک ردیف برای هر روز (امروز را جایگزین می‌کند)
            conn.execute(
                "DELETE FROM price_history WHERE product_id=? AND check_date=?",
                (pid, today))
            conn.execute("""
                INSERT INTO price_history
                    (product_id, check_date, store_price, okala_price, digikala_price)
                VALUES (?,?,?,?,?)
            """, (pid, today, store_price, okala_price, digikala_price))
            conn.commit()
            return {"id": pid, "last_update": now}
        finally:
            conn.close()


# ------------------------------------------------------------------ مدل‌های ورودی
class ProductIn(BaseModel):
    name: str
    barcode: str = ""
    store_price: int = 0
    okala_price: Optional[int] = None
    digikala_price: Optional[int] = None


class SearchIn(BaseModel):
    name: str
    store_price: int = 0
    barcode: str = ""


# ------------------------------------------------------------------ برنامه
app = FastAPI(title="price-app", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# هر خطای پیش‌بینی‌نشده هم باید JSON برگرداند؛ نه HTML
@app.exception_handler(Exception)
async def json_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500,
                        content={"ok": False, "error": str(exc)})


@app.get("/", response_class=FileResponse)
def index():
    return FileResponse(str(TEMPLATES_DIR / "index.html"))


@app.get("/api/health")
def health():
    return {"ok": True, "service": "price-app", "time": now_str()}


@app.post("/api/search-price")
def search_price(body: SearchIn):
    name = (body.name or "").strip()
    store_price = int(body.store_price or 0)
    urls = build_urls(name)

    # اکالا: API عمومی ندارد؛ فقط لینک جستجو ساخته می‌شود (found=False)
    okala_price = None

    # دیجی‌کالا: فقط یک تلاش مودبانه روی API عمومی
    digikala_price = try_digikala_price(name)

    saved = upsert_product(name, store_price, okala_price, digikala_price,
                           urls, barcode=(body.barcode or ""))
    when = saved["last_update"]

    return {
        "ok": True,
        "id": saved["id"],
        "product": name,
        "store_price": store_price,
        "checked_at": when,
        "references": {
            "okala": {
                "found": False,
                "price": None,
                "status": FALLBACK_MSG,
                "url": urls["okala"],
                "checked_at": when,
            },
            "digikala": {
                "found": digikala_price is not None,
                "price": digikala_price,
                "status": ("قیمت دریافت شد" if digikala_price is not None
                           else FALLBACK_MSG),
                "url": urls["digikala"],
                "checked_at": when,
            },
        },
    }


@app.post("/api/product")
def create_product(body: ProductIn):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="نام کالا لازم است")
    urls = build_urls(name)
    saved = upsert_product(name, int(body.store_price or 0),
                           body.okala_price, body.digikala_price, urls,
                           barcode=(body.barcode or ""))
    return {"ok": True, "id": saved["id"], "message": "کالا ذخیره شد",
            "urls": urls, "last_update": saved["last_update"]}


@app.get("/api/products")
def list_products():
    with _db_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM products ORDER BY id DESC").fetchall()
            products = [dict(r) for r in rows]
        finally:
            conn.close()
    return {"ok": True, "count": len(products), "products": products}


@app.get("/api/compare/{pid}")
def compare(pid: int):
    with _db_lock:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        finally:
            conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="کالا پیدا نشد")
    p = dict(row)

    def cmp(ref_price):
        if ref_price is None or ref_price <= 0:
            return None
        diff = p["store_price"] - ref_price
        percent = round(diff / ref_price * 100, 2)
        return {"price": ref_price,
                "diff": diff,
                "diff_percent": percent}

    return {"ok": True, "product": p, "comparisons": {
        "okala": cmp(p.get("okala_price")),
        "digikala": cmp(p.get("digikala_price")),
    }}


@app.get("/api/history/{pid}")
def history(pid: int):
    with _db_lock:
        conn = get_db()
        try:
            name_row = conn.execute(
                "SELECT name FROM products WHERE id=?", (pid,)).fetchone()
            rows = conn.execute("""
                SELECT * FROM price_history
                 WHERE product_id=?
                 ORDER BY check_date DESC, id DESC
            """, (pid,)).fetchall()
            hist = [dict(r) for r in rows]
        finally:
            conn.close()
    if not name_row:
        raise HTTPException(status_code=404, detail="کالا پیدا نشد")
    return {"ok": True, "product_id": pid, "name": name_row["name"],
            "history": hist}


@app.delete("/api/product/{pid}")
def delete_product(pid: int):
    with _db_lock:
        conn = get_db()
        try:
            cur = conn.execute("DELETE FROM products WHERE id=?", (pid,))
            conn.execute("DELETE FROM price_history WHERE product_id=?", (pid,))
            conn.commit()
            deleted = cur.rowcount > 0
        finally:
            conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="کالا پیدا نشد")
    return {"ok": True, "id": pid, "message": "کالا حذف شد"}

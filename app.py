import os
import json
import secrets
from datetime import datetime
from urllib.parse import urlencode

from flask import Flask, render_template, request, redirect, url_for, session, flash, g, Response

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change_this_demo_secret")

DEFAULT_LANG = "zh"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATIC_IMG_PREFIX = "img/"  # url_for('static', filename=STATIC_IMG_PREFIX + <path>)

PRODUCTS_PATH = os.path.join(DATA_DIR, "products.json")
ORDERS_PATH = os.path.join(DATA_DIR, "orders.json")
MESSAGES_PATH = os.path.join(DATA_DIR, "messages.json")

ADMIN_KEY = os.environ.get("DEMO_ADMIN_KEY", "demo")


# -------------------------
# Language
# -------------------------
def get_lang(default=DEFAULT_LANG):
    raw = (request.args.get("lang") or session.get("lang") or default).strip().lower()
    lang = "zh" if raw in ("zh", "cn", "zh-cn", "zh-hans") else "en"
    session["lang"] = lang
    g.lang = lang
    return lang


@app.context_processor
def inject_helpers():
    def switch_lang_url(target_lang: str):
        args = request.args.to_dict(flat=True)
        args["lang"] = "zh" if target_lang in ("zh", "cn", "zh-cn", "zh-hans") else "en"
        return request.path + "?" + urlencode(args)

    return {
        "lang": getattr(g, "lang", DEFAULT_LANG),
        "switch_lang_url": switch_lang_url,
        "ADMIN_KEY": ADMIN_KEY,
        "STATIC_IMG_PREFIX": STATIC_IMG_PREFIX,
    }


# -------------------------
# Storage helpers
# -------------------------
def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(PRODUCTS_PATH):
        _write_json(PRODUCTS_PATH, {"products": []})
    if not os.path.exists(ORDERS_PATH):
        _write_json(ORDERS_PATH, {"orders": []})
    if not os.path.exists(MESSAGES_PATH):
        _write_json(MESSAGES_PATH, {"messages": []})


def _catalog(include_inactive=False):
    _ensure_data()
    items = _read_json(PRODUCTS_PATH, {"products": []}).get("products", [])
    return items if include_inactive else [p for p in items if p.get("active", True)]


def _find(slug):
    slug = (slug or "").strip().lower()
    for p in _catalog(include_inactive=True):
        if p.get("slug") == slug:
            return p
    return None


# -------------------------
# Cart + Admin auth
# -------------------------
def _cart():
    c = session.get("cart")
    if not isinstance(c, dict):
        c = {}
    session["cart"] = c
    return c


def _cart_count():
    return sum(int(v) for v in _cart().values())


def _admin_allowed():
    return (request.args.get("k") or "") == ADMIN_KEY


# -------------------------
# Routes
# -------------------------
@app.get("/")
def index():
    get_lang()
    return render_template("index.html", products=_catalog(), cart_count=_cart_count())


@app.get("/p/<slug>")
def product(slug):
    get_lang()
    p = _find(slug)
    if not p or not p.get("active", True):
        return ("Not Found", 404)
    return render_template("product.html", p=p, cart_count=_cart_count())


@app.post("/cart/add")
def cart_add():
    lang = get_lang()
    slug = (request.form.get("slug") or "").strip().lower()
    qty = max(1, min(int(request.form.get("qty") or 1), 99))
    p = _find(slug)
    if not p or not p.get("active", True):
        return redirect(url_for("index", lang=lang))

    c = _cart()
    c[slug] = int(c.get(slug, 0)) + qty
    session["cart"] = c
    flash("已加入购物车" if lang == "zh" else "Added to cart.", "success")
    return redirect(url_for("cart", lang=lang))


@app.get("/cart")
def cart():
    get_lang()
    c = _cart()
    items = []
    total = 0.0
    for slug, qty in c.items():
        p = _find(slug)
        if not p:
            continue
        price = float(p.get("price") or 0)
        line = price * int(qty)
        total += line
        items.append({"slug": slug, "qty": int(qty), "price": price, "line_total": line, "p": p})
    return render_template("cart.html", items=items, total=total, cart_count=_cart_count())


@app.post("/cart/update")
def cart_update():
    lang = get_lang()
    c = _cart()
    for k, v in request.form.items():
        if not k.startswith("qty_"):
            continue
        slug = k.replace("qty_", "", 1)
        n = int(v or 0)
        if n <= 0:
            c.pop(slug, None)
        else:
            c[slug] = max(1, min(n, 99))
    session["cart"] = c
    flash("购物车已更新" if lang == "zh" else "Cart updated.", "success")
    return redirect(url_for("cart", lang=lang))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    lang = get_lang()
    c = _cart()
    if not c:
        return redirect(url_for("index", lang=lang))

    snapshot = []
    total = 0.0
    for slug, qty in c.items():
        p = _find(slug)
        if not p:
            continue
        price = float(p.get("price") or 0)
        line = price * int(qty)
        total += line
        snapshot.append({"slug": slug, "qty": int(qty), "price": price, "line_total": line})

    if request.method == "POST":
        buyer_name = (request.form.get("buyer_name") or "").strip()
        buyer_contact = (request.form.get("buyer_contact") or "").strip()
        address = (request.form.get("address") or "").strip()
        note = (request.form.get("note") or "").strip()

        if not buyer_name or not buyer_contact:
            flash("请填写姓名和联系方式" if lang == "zh" else "Please enter name and contact.", "warning")
            return render_template("checkout.html", items=snapshot, total=total, form=request.form, cart_count=_cart_count())

        order_id = "CH" + datetime.utcnow().strftime("%y%m%d") + secrets.token_hex(3)
        order = {
            "id": order_id,
            "created_at": datetime.utcnow().isoformat(),
            "buyer_name": buyer_name,
            "buyer_contact": buyer_contact,
            "address": address,
            "note": note,
            "line_items": snapshot,
            "total": total,
            "status": "new",
            "lang": lang
        }
        payload = _read_json(ORDERS_PATH, {"orders": []})
        payload["orders"].insert(0, order)
        _write_json(ORDERS_PATH, payload)

        session["cart"] = {}
        return redirect(url_for("success", order_id=order_id, lang=lang))

    return render_template("checkout.html", items=snapshot, total=total, form={}, cart_count=_cart_count())


@app.get("/success/<order_id>")
def success(order_id):
    get_lang()
    return render_template("success.html", order_id=order_id, cart_count=_cart_count())


@app.post("/message")
def message():
    lang = get_lang()
    name = (request.form.get("name") or "").strip()
    contact = (request.form.get("contact") or "").strip()
    msg = (request.form.get("message") or "").strip()

    if not msg:
        flash("请填写消息内容" if lang == "zh" else "Please enter a message.", "warning")
        return redirect(url_for("index", lang=lang))

    payload = _read_json(MESSAGES_PATH, {"messages": []})
    payload["messages"].insert(0, {
        "created_at": datetime.utcnow().isoformat(),
        "name": name,
        "contact": contact,
        "message": msg,
        "lang": lang
    })
    _write_json(MESSAGES_PATH, payload)
    flash("消息已发送" if lang == "zh" else "Message sent.", "success")
    return redirect(url_for("index", lang=lang))


@app.get("/admin")
def admin():
    lang = get_lang()
    if not _admin_allowed():
        return ("Forbidden", 403)

    products = _catalog(include_inactive=True)
    orders = _read_json(ORDERS_PATH, {"orders": []}).get("orders", [])
    messages = _read_json(MESSAGES_PATH, {"messages": []}).get("messages", [])

    return render_template("admin.html", products=products, orders=orders, messages=messages, k=request.args.get("k"), cart_count=_cart_count())


@app.post("/admin/product")
def admin_product():
    lang = get_lang()
    if not _admin_allowed():
        return ("Forbidden", 403)

    action = (request.form.get("action") or "").strip()
    payload = _read_json(PRODUCTS_PATH, {"products": []})
    products = payload.get("products", [])

    if action == "add":
        slug = (request.form.get("slug") or "").strip().lower() or ("p" + secrets.token_hex(4))
        images = [s.strip() for s in (request.form.get("images") or "").split(",") if s.strip()]
        products.insert(0, {
            "slug": slug,
            "active": True,
            "price": float(request.form.get("price") or 0),
            "title_zh": (request.form.get("title_zh") or "").strip() or "新窗花",
            "title_en": (request.form.get("title_en") or "").strip() or "New paper-cut",
            "short_zh": (request.form.get("short_zh") or "").strip(),
            "short_en": (request.form.get("short_en") or "").strip(),
            "desc_zh": (request.form.get("desc_zh") or "").strip(),
            "desc_en": (request.form.get("desc_en") or "").strip(),
            "images": images
        })
        payload["products"] = products
        _write_json(PRODUCTS_PATH, payload)
        flash("已添加商品" if lang == "zh" else "Product added.", "success")
        return redirect(url_for("admin", lang=lang, k=request.args.get("k")))

    slug = (request.form.get("slug") or "").strip().lower()
    for p in products:
        if p.get("slug") != slug:
            continue

        if action == "toggle":
            p["active"] = not bool(p.get("active", True))
        elif action == "save":
            p["price"] = float(request.form.get("price") or 0)
            p["title_zh"] = (request.form.get("title_zh") or "").strip()
            p["title_en"] = (request.form.get("title_en") or "").strip()
            p["short_zh"] = (request.form.get("short_zh") or "").strip()
            p["short_en"] = (request.form.get("short_en") or "").strip()
            p["desc_zh"] = (request.form.get("desc_zh") or "").strip()
            p["desc_en"] = (request.form.get("desc_en") or "").strip()
            p["images"] = [s.strip() for s in (request.form.get("images") or "").split(",") if s.strip()]
        elif action == "delete":
            payload["products"] = [x for x in products if x.get("slug") != slug]
            _write_json(PRODUCTS_PATH, payload)
            return redirect(url_for("admin", lang=lang, k=request.args.get("k")))

        payload["products"] = products
        _write_json(PRODUCTS_PATH, payload)
        break

    flash("已更新" if lang == "zh" else "Updated.", "success")
    return redirect(url_for("admin", lang=lang, k=request.args.get("k")))


@app.get("/admin/export/orders.csv")
def export_orders():
    if not _admin_allowed():
        return ("Forbidden", 403)

    orders = _read_json(ORDERS_PATH, {"orders": []}).get("orders", [])
    rows = [["order_id", "created_at", "buyer_name", "buyer_contact", "total", "status", "items"]]
    for o in orders:
        items = "; ".join([f"{i.get('slug')} x{i.get('qty')}" for i in (o.get("items") or [])])
        rows.append([o.get("id",""), o.get("created_at",""), o.get("buyer_name",""), o.get("buyer_contact",""),
                     str(o.get("total","")), o.get("status",""), items])

    out = []
    for r in rows:
        out.append(",".join(["\"" + str(x).replace("\"", "\"\"") + "\"" for x in r]))

    resp = Response("\n".join(out) + "\n", mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=chuanghua_orders.csv"
    return resp


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)

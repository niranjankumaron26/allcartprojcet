from decimal import Decimal

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from mysql.connector import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from database import commit, execute, one, query, rollback
from .common import PRICE, change_order, field, integer, order_items, require, valid_email, valid_phone
from .public import CATALOG, catalog

bp = Blueprint("account", __name__, url_prefix="/account")
user_only = require("USER")

def container(table):
    user_id = g.user["id"]
    one("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
    execute(f"INSERT INTO {table}(user_id) VALUES(%s) ON DUPLICATE KEY UPDATE user_id=user_id", (user_id,))
    return one(f"SELECT id FROM {table} WHERE user_id=%s FOR UPDATE", (user_id,))["id"]

def basket():
    return query(f"""SELECT p.*,i.quantity,{PRICE} AS sale_price FROM cart_items i
        JOIN cart c ON c.id=i.cart_id JOIN products p ON p.id=i.product_id
        WHERE c.user_id=%s ORDER BY p.id""", (g.user["id"],))

def totals(items):
    subtotal = sum((p["sale_price"] * p["quantity"] for p in items), Decimal(0))
    delivery = Decimal(49 if 0 < subtotal < 999 else 0)
    return subtotal, delivery, subtotal + delivery

@bp.get("/")
@user_only
def dashboard():
    user_id = g.user["id"]
    stats = one("""SELECT COUNT(*) AS total,COUNT(IF(status IN ('Pending','Confirmed','Processing','Shipped'),1,NULL)) AS pending,
        COUNT(IF(status='Delivered',1,NULL)) AS delivered FROM orders WHERE user_id=%s""", (user_id,))
    stats["wishlist"] = one("SELECT COUNT(*) AS total FROM wishlist_items i JOIN wishlist w ON w.id=i.wishlist_id WHERE w.user_id=%s", (user_id,))["total"]
    recent_ids = session.get("recent", [])
    recent = []
    if recent_ids:
        placeholders = ",".join(["%s"] * len(recent_ids))
        rows = query(CATALOG + f" WHERE p.active=1 AND p.id IN ({placeholders})", tuple(recent_ids))
        recent = sorted(rows, key=lambda p: recent_ids.index(p["id"]))
    return render_template("dashboard.html", area="account", title="Overview", stats=stats, recent=recent)

@bp.get("/browse")
@user_only
def browse():
    return catalog(account=True)

@bp.get("/cart")
@user_only
def cart():
    items = basket()
    return render_template("cart.html", area="account", items=items, totals=totals(items))

def save_cart(product_id, quantity, replace=False):
    cart_id = container("cart")
    existing = one("SELECT quantity FROM cart_items WHERE cart_id=%s AND product_id=%s FOR UPDATE", (cart_id, product_id))
    if quantity == 0:
        execute("DELETE FROM cart_items WHERE cart_id=%s AND product_id=%s", (cart_id, product_id))
        return
    p = one("SELECT stock,active FROM products WHERE id=%s FOR UPDATE", (product_id,))
    quantity += existing["quantity"] if existing and not replace else 0
    if not p or not p["active"] or quantity > min(99, p["stock"]):
        raise ValueError("The requested quantity is unavailable.")
    execute("""INSERT INTO cart_items(cart_id,product_id,quantity) VALUES(%s,%s,%s) AS incoming
        ON DUPLICATE KEY UPDATE quantity=incoming.quantity""", (cart_id, product_id, quantity))

@bp.post("/cart/<int:product_id>")
@user_only
def cart_change(product_id):
    action = request.form.get("action")
    if action not in ("add", "set", "remove", "buy"):
        abort(400)
    try:
        quantity = 0 if action == "remove" else integer(request.form.get("quantity", "1"), 1, 99)
        if action == "buy":
            product = one("SELECT active,stock FROM products WHERE id=%s", (product_id,))
            if not product or not product["active"] or quantity > product["stock"]:
                raise ValueError("The requested quantity is unavailable.")
            return redirect(url_for("account.checkout", product_id=product_id, quantity=quantity))
        save_cart(product_id, quantity, replace=action == "set")
        commit()
        flash("Cart updated.")
    except ValueError as error:
        rollback()
        flash(str(error))
    return redirect(url_for("account.cart"))

@bp.get("/wishlist")
@user_only
def wishlist():
    items = query(CATALOG + " JOIN wishlist_items i ON i.product_id=p.id JOIN wishlist w ON w.id=i.wishlist_id WHERE w.user_id=%s", (g.user["id"],))
    return render_template("wishlist.html", title="Wishlist", area="account", items=items)

@bp.post("/wishlist/<int:product_id>")
@user_only
def wishlist_change(product_id):
    action = request.form.get("action")
    try:
        wishlist_id = container("wishlist")
        if action in ("move", "remove"):
            if action == "move":
                if not one("SELECT product_id FROM wishlist_items WHERE wishlist_id=%s AND product_id=%s", (wishlist_id, product_id)):
                    abort(404)
                save_cart(product_id, 1)
            execute("DELETE FROM wishlist_items WHERE wishlist_id=%s AND product_id=%s", (wishlist_id, product_id))
        elif action == "add":
            if not one("SELECT id FROM products WHERE id=%s AND active=1", (product_id,)):
                abort(404)
            execute("INSERT INTO wishlist_items VALUES(%s,%s) ON DUPLICATE KEY UPDATE product_id=product_id", (wishlist_id, product_id))
        else:
            abort(400)
        commit()
        flash("Wishlist updated.")
    except ValueError as error:
        rollback()
        flash(str(error))
    return redirect(url_for("account.wishlist"))

@bp.route("/checkout", methods=["GET", "POST"])
@user_only
def checkout():
    user_id = g.user["id"]
    addresses = query("SELECT * FROM addresses WHERE user_id=%s ORDER BY id", (user_id,))
    source = request.form if request.method == "POST" else request.args
    try:
        product_id = integer(source["product_id"], 1, 2147483647) if source.get("product_id") else None
        quantity = integer(source.get("quantity"), 1, 99) if product_id else None
        if request.method == "POST":
            if not session.get("checkout_token") or source.get("checkout_token") != session["checkout_token"]:
                raise ValueError("Open a fresh checkout before placing an order.")
            token = source["checkout_token"]
            one("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
            existing_order = one("SELECT id FROM orders WHERE user_id=%s AND checkout_token=%s FOR UPDATE", (user_id, token))
            if existing_order:
                rollback()
                return redirect(url_for("account.order", order_id=existing_order["id"]))
            cart_id = None if product_id else container("cart")
            recipient, phone = field("recipient", 100), field("phone", 20)
            if source.get("address_id"):
                saved = next((a for a in addresses if str(a["id"]) == source["address_id"]), None)
                if not saved:
                    raise ValueError("Select one of your saved addresses.")
                address = saved["address"]
            else:
                address = field("address", 500, 5)
            payment = source.get("payment")
            if not valid_phone(phone) or payment not in ("COD", "SIMULATED"):
                raise ValueError("Enter a valid phone number and select a payment method.")
            requested = [{"product_id": product_id, "quantity": quantity}] if product_id else query(
                "SELECT * FROM cart_items WHERE cart_id=%s ORDER BY product_id FOR UPDATE", (cart_id,))
            items = []
            for entry in requested:
                product = one(CATALOG + " WHERE p.id=%s FOR UPDATE OF p", (entry["product_id"],))
                if not product or not product["active"] or entry["quantity"] > product["stock"]:
                    raise ValueError("An item is unavailable in the requested quantity. Update your selection and retry.")
                items.append(dict(product, quantity=entry["quantity"]))
            if not items:
                raise ValueError("Add products before checking out.")
            amounts = totals(items)
            if amounts[2] >= Decimal("1000000000000"):
                raise ValueError("Reduce the order quantity and try again.")
            order_id = execute("""INSERT INTO orders(user_id,checkout_token,recipient,phone,address,payment,subtotal,delivery,total)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (user_id, token, recipient, phone, address, payment, *amounts))
            for p in items:
                execute("INSERT INTO order_items(order_id,product_id,product_name,category_name,quantity,unit_price) VALUES(%s,%s,%s,%s,%s,%s)",
                        (order_id, p["id"], p["name"], p["category"], p["quantity"], p["sale_price"]))
                execute("UPDATE products SET stock=stock-%s WHERE id=%s", (p["quantity"], p["id"]))
            if cart_id:
                execute("DELETE FROM cart_items WHERE cart_id=%s", (cart_id,))
            commit()
            session.pop("checkout_token", None)
            flash("Order placed.")
            return redirect(url_for("account.order", order_id=order_id))
        if product_id:
            p = one(CATALOG + " WHERE p.id=%s AND p.active=1", (product_id,))
            if not p or quantity > p["stock"]:
                raise ValueError("The requested quantity is unavailable.")
            items = [dict(p, quantity=quantity)]
        else:
            items = basket()
        if not items:
            raise ValueError("Your cart is empty.")
    except ValueError as error:
        rollback()
        flash(str(error))
        if request.method == "POST" and source.get("product_id", "").isdigit() and source.get("quantity", "").isdigit():
            return redirect(url_for("account.checkout", product_id=source["product_id"], quantity=source["quantity"]))
        return redirect(url_for("account.cart"))
    from secrets import token_urlsafe
    session["checkout_token"] = token_urlsafe(24)
    return render_template("checkout.html", area="account", items=items, totals=totals(items), addresses=addresses,
                           product_id=product_id, quantity=quantity)

@bp.get("/orders")
@user_only
def orders():
    return render_template("orders.html", title="My orders", area="account",
                           orders=query("SELECT * FROM orders WHERE user_id=%s ORDER BY id DESC", (g.user["id"],)))

@bp.route("/orders/<int:order_id>", methods=["GET", "POST"])
@user_only
def order(order_id):
    order = one("SELECT * FROM orders WHERE id=%s AND user_id=%s", (order_id, g.user["id"]))
    if not order:
        abort(404)
    if request.method == "POST":
        try:
            change_order(order_id, "Cancelled", g.user["id"])
            flash("Order cancelled.")
        except ValueError as error:
            flash(str(error))
        return redirect(url_for("account.order", order_id=order_id))
    return render_template("order.html", area="account", order=order, items=order_items(order_id),
                           statuses=["Cancelled"] if order["status"] in ("Pending", "Confirmed") else [])

@bp.route("/profile", methods=["GET", "POST"])
@user_only
def profile():
    user_id = g.user["id"]
    if request.method == "POST":
        try:
            action = request.form.get("action")
            if action == "details":
                name, email, phone = field("name", 100), field("email", 254).lower(), field("phone", 20)
                if not valid_email(email) or not valid_phone(phone):
                    raise ValueError("Enter a valid email address and phone number.")
                execute("UPDATE users SET name=%s,email=%s,phone=%s WHERE id=%s", (name, email, phone, user_id))
            elif action == "password":
                current = request.form.get("current", "")
                password = request.form.get("password", "")
                stored = one("SELECT password_hash FROM users WHERE id=%s FOR UPDATE", (user_id,))
                if len(current) > 128 or not check_password_hash(stored["password_hash"], current):
                    raise ValueError("Your current password is incorrect.")
                if not 8 <= len(password) <= 128 or password != request.form.get("confirm"):
                    raise ValueError("Enter matching passwords of 8–128 characters.")
                execute("UPDATE users SET password_hash=%s WHERE id=%s", (generate_password_hash(password), user_id))
            elif action in ("address", "delete"):
                address_id = request.form.get("address_id", type=int)
                if address_id and not one("SELECT id FROM addresses WHERE id=%s AND user_id=%s", (address_id, user_id)):
                    abort(404)
                if action == "delete":
                    execute("DELETE FROM addresses WHERE id=%s AND user_id=%s", (address_id, user_id))
                elif address_id:
                    execute("UPDATE addresses SET label=%s,address=%s WHERE id=%s AND user_id=%s",
                            (field("label", 50), field("address", 500, 5), address_id, user_id))
                else:
                    execute("INSERT INTO addresses(user_id,label,address) VALUES(%s,%s,%s)",
                            (user_id, field("label", 50), field("address", 500, 5)))
            else:
                abort(400)
            commit()
            flash("Profile updated.")
        except IntegrityError:
            rollback()
            flash("This email is already registered.")
        except ValueError as error:
            rollback()
            flash(str(error))
        return redirect(url_for("account.profile"))
    return render_template("profile.html", area="account", addresses=query("SELECT * FROM addresses WHERE user_id=%s ORDER BY id", (user_id,)))

@bp.post("/reviews/<int:product_id>")
@user_only
def review(product_id):
    user_id = g.user["id"]
    if not one("""SELECT o.id FROM orders o JOIN order_items i ON i.order_id=o.id
        WHERE o.user_id=%s AND i.product_id=%s AND o.status='Delivered' LIMIT 1""", (user_id, product_id)):
        abort(403)
    try:
        execute("""INSERT INTO reviews(user_id,product_id,rating,body) VALUES(%s,%s,%s,%s) AS incoming
            ON DUPLICATE KEY UPDATE rating=incoming.rating,body=incoming.body""",
                (user_id, product_id, integer(request.form.get("rating"), 1, 5), field("body", 1000)))
        commit()
        flash("Review saved.")
    except ValueError as error:
        flash(str(error))
    return redirect(url_for("public.product", product_id=product_id, _anchor="reviews"))

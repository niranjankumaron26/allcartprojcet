from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from mysql.connector import IntegrityError
from PIL import Image, ImageOps, UnidentifiedImageError

from database import commit, execute, one, query, rollback
from .common import STATUS, change_order, field, integer, order_items, price, require
from .public import CATALOG

bp = Blueprint("admin", __name__, url_prefix="/admin")
admin_only = require("ADMIN")

def analytics():
    monthly = query("""SELECT DATE_FORMAT(created_at,'%Y-%m') AS label,SUM(total) AS amount
        FROM orders WHERE status='Delivered' GROUP BY label ORDER BY label DESC LIMIT 12""") 
    monthly.reverse()
    categories = query("""SELECT i.category_name AS label,SUM(i.unit_price*i.quantity) AS amount
        FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.status='Delivered' GROUP BY label ORDER BY amount DESC""")
    best = query("""SELECT i.product_id,MAX(i.product_name) AS label,SUM(i.quantity) AS amount
        FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.status='Delivered'
        GROUP BY i.product_id ORDER BY amount DESC LIMIT 10""")
    statuses = query("SELECT status AS label,COUNT(*) AS amount FROM orders GROUP BY status")
    return monthly, categories, best, statuses

def order_list():
    return query("SELECT o.*,u.name AS customer FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.id DESC")

@bp.get("/")
@admin_only
def dashboard():
    stats = one("""SELECT (SELECT COUNT(*) FROM products WHERE active=1) AS products,
        (SELECT COUNT(*) FROM categories) AS categories,(SELECT COUNT(*) FROM users WHERE role='USER') AS users,
        COUNT(*) AS orders,COUNT(IF(status='Pending',1,NULL)) AS pending,
        COUNT(IF(status='Delivered',1,NULL)) AS delivered,COALESCE(SUM(IF(status='Delivered',total,0)),0) AS sales
        FROM orders""")
    return render_template("dashboard.html", area="admin", title="Store overview", stats=stats,
                           monthly=analytics()[0], orders=order_list()[:6])

def save_image(existing=None):
    uploaded = request.files.get("image")
    if not uploaded or not uploaded.filename:
        if existing:
            return existing
        raise ValueError("Upload an image.")
    if Path(uploaded.filename).suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        raise ValueError("Use a JPEG, PNG or WebP image.")
    try:
        with Image.open(uploaded.stream) as original:
            if original.format not in ("JPEG", "PNG", "WEBP") or original.width * original.height > 12000000:
                raise ValueError("Use an image under 12 megapixels in JPEG, PNG or WebP format.")
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1400, 1400))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("That image could not be read.") from error
    folder = Path(current_app.static_folder, "images", "uploads")
    folder.mkdir(exist_ok=True, parents=True)
    name = uuid4().hex + ".jpg"
    image.save(folder / name, "JPEG", quality=88)
    return f"images/uploads/{name}"

@bp.get("/products")
@admin_only
def products():
    return render_template("manage.html", area="admin", title="Products", kind="products",
                           rows=query(CATALOG + " WHERE p.active=1 ORDER BY p.id DESC"))

@bp.route("/products/new", methods=["GET", "POST"])
@bp.route("/products/<int:item_id>", methods=["GET", "POST"])
@admin_only
def product(item_id=None):
    row = one("SELECT * FROM products WHERE id=%s AND active=1", (item_id,)) if item_id else None
    if item_id and not row:
        abort(404)
    categories = query("SELECT id,name FROM categories ORDER BY name")
    if request.method == "POST":
        try:
            if row and request.form.get("action") == "delete":
                execute("UPDATE products SET active=0 WHERE id=%s", (item_id,))
                flash("Product removed from the catalog.")
            else:
                category_id = integer(request.form.get("category_id"), 1, 2147483647)
                if category_id not in {c["id"] for c in categories}:
                    raise ValueError("Select an existing category.")
                name, description = field("name", 150), field("description", 5000)
                amount = price(request.form.get("price"), Decimal(".01"))
                discount = integer(request.form.get("discount"), 0, 99)
                stock = integer(request.form.get("stock"), 0, 1000000)
                offer = field("offer", 100, 0)
                image = save_image(row["image"] if row else None)
                values = (category_id, name, description, amount, discount, stock, image, "featured" in request.form)
                if row:
                    execute("""UPDATE products SET category_id=%s,name=%s,description=%s,price=%s,discount=%s,
                        stock=%s,image=%s,featured=%s WHERE id=%s AND active=1""", (*values, item_id))
                else:
                    item_id = execute("""INSERT INTO products(category_id,name,description,price,discount,stock,image,featured)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", values)
                execute("""INSERT INTO offers(product_id,title,active) VALUES(%s,%s,%s) AS incoming
                    ON DUPLICATE KEY UPDATE title=incoming.title,active=incoming.active""", (item_id, offer, bool(offer)))
                flash("Product saved.")
            commit()
            return redirect(url_for("admin.products"))
        except (IntegrityError, ValueError) as error:
            rollback()
            flash(str(error) if isinstance(error, ValueError) else "That product name is already in use.")
    offer = one("SELECT title FROM offers WHERE product_id=%s AND active=1", (item_id,)) if row else None
    return render_template("edit.html", area="admin", kind="product", row=row or {}, categories=categories, offer=offer)

@bp.get("/categories")
@admin_only
def categories():
    return render_template("manage.html", area="admin", title="Categories", kind="categories",
                           rows=query("SELECT * FROM categories ORDER BY name"))

@bp.route("/categories/new", methods=["GET", "POST"])
@bp.route("/categories/<int:item_id>", methods=["GET", "POST"])
@admin_only
def category(item_id=None):
    row = one("SELECT * FROM categories WHERE id=%s", (item_id,)) if item_id else None
    if item_id and not row:
        abort(404)
    if request.method == "POST":
        try:
            if row and request.form.get("action") == "delete":
                execute("DELETE FROM categories WHERE id=%s", (item_id,))
            else:
                values = (field("name", 100), field("description", 5000), save_image(row["image"] if row else None))
                if row:
                    execute("UPDATE categories SET name=%s,description=%s,image=%s WHERE id=%s", (*values, item_id))
                else:
                    execute("INSERT INTO categories(name,description,image) VALUES(%s,%s,%s)", values)
            commit()
            flash("Categories updated.")
            return redirect(url_for("admin.categories"))
        except (IntegrityError, ValueError) as error:
            rollback()
            flash(str(error) if isinstance(error, ValueError) else "Category names must be unique. Categories referenced by products cannot be deleted.")
    return render_template("edit.html", area="admin", kind="category", row=row or {})

@bp.get("/orders")
@admin_only
def orders():
    return render_template("orders.html", area="admin", title="Customer orders", orders=order_list())

@bp.route("/orders/<int:order_id>", methods=["GET", "POST"])
@admin_only
def order(order_id):
    order = one("SELECT o.*,u.name AS customer FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=%s", (order_id,))
    if not order:
        abort(404)
    if request.method == "POST":
        try:
            change_order(order_id, request.form.get("status"))
            flash("Order status updated.")
        except ValueError as error:
            flash(str(error))
        return redirect(url_for("admin.order", order_id=order_id))
    return render_template("order.html", area="admin", order=order, items=order_items(order_id), statuses=STATUS[order["status"]])

@bp.get("/users")
@admin_only
def users():
    term = request.args.get("q", "").strip()[:150]
    rows = query("""SELECT id,name,email,phone,active,created_at FROM users WHERE role='USER'
        AND (LOCATE(%s,name)>0 OR LOCATE(%s,email)>0 OR LOCATE(%s,phone)>0) ORDER BY id DESC""", (term, term, term))
    return render_template("manage.html", area="admin", title="Users", kind="users", rows=rows, term=term)

@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
@admin_only
def user(user_id):
    row = one("""SELECT id,name,email,phone,active,created_at,
        (SELECT COUNT(*) FROM orders WHERE user_id=%s) AS orders FROM users WHERE id=%s AND role='USER'""", (user_id, user_id))
    if not row:
        abort(404)
    if request.method == "POST":
        active = request.form.get("active")
        if active not in ("0", "1"):
            abort(400)
        execute("UPDATE users SET active=%s WHERE id=%s AND role='USER'", (int(active), user_id))
        commit()
        flash("Account status updated.")
        return redirect(url_for("admin.user", user_id=user_id))
    return render_template("admin_user.html", area="admin", row=row)

@bp.get("/inventory")
@admin_only
def inventory():
    scope = request.args.get("stock")
    condition = {"low": " AND p.stock BETWEEN 1 AND 5", "out": " AND p.stock=0"}.get(scope, "")
    return render_template("manage.html", area="admin", title="Inventory", kind="inventory",
                           rows=query(CATALOG + " WHERE p.active=1" + condition + " ORDER BY p.stock,p.name"))

@bp.post("/inventory/<int:item_id>")
@admin_only
def stock(item_id):
    try:
        stock = integer(request.form.get("stock"), 0, 1000000)
        if not one("SELECT id FROM products WHERE id=%s AND active=1", (item_id,)):
            abort(404)
        execute("UPDATE products SET stock=%s WHERE id=%s AND active=1", (stock, item_id))
        commit()
        flash("Stock updated.")
    except ValueError as error:
        flash(str(error))
    return redirect(url_for("admin.inventory"))

@bp.get("/reviews")
@admin_only
def reviews():
    rows = query("""SELECT r.id,r.rating,r.body,p.name AS product,u.name AS author
        FROM reviews r JOIN products p ON p.id=r.product_id JOIN users u ON u.id=r.user_id ORDER BY r.id DESC""")
    return render_template("manage.html", area="admin", title="Reviews", kind="reviews", rows=rows)

@bp.post("/reviews/<int:review_id>/remove")
@admin_only
def remove_review(review_id):
    execute("DELETE FROM reviews WHERE id=%s", (review_id,))
    commit()
    flash("Review removed.")
    return redirect(url_for("admin.reviews"))

@bp.get("/reports")
@admin_only
def reports():
    monthly, categories, best, statuses = analytics()
    total = one("SELECT COALESCE(SUM(total),0) AS amount FROM orders WHERE status='Delivered'")["amount"]
    return render_template("reports.html", area="admin", monthly=monthly, categories=categories, best=best,
                           statuses=statuses, total=total)

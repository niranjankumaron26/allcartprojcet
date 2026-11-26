from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from mysql.connector import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from database import commit, execute, one, query, rollback
from .common import PRICE, field, price, valid_email, valid_phone

bp = Blueprint("public", __name__)
CATALOG = f"SELECT p.*,c.name AS category,{PRICE} AS sale_price FROM products p JOIN categories c ON c.id=p.category_id"

@bp.get("/")
def home():
    return render_template("home.html",
        categories=query("SELECT * FROM categories ORDER BY id"),
        featured=query(CATALOG + " WHERE p.active=1 AND p.featured=1 ORDER BY p.id LIMIT 4"),
        trending=query(CATALOG + " WHERE p.active=1 ORDER BY p.views DESC,p.id DESC LIMIT 4"),
        offers=query(CATALOG.replace("SELECT p.*,", "SELECT p.*,o.title AS offer_title,") + " JOIN offers o ON o.product_id=p.id WHERE p.active=1 AND o.active=1 AND p.discount>0 ORDER BY p.discount DESC LIMIT 4"))

@bp.get("/categories")
def categories():
    return render_template("catalog.html", title="Shop by category", categories=query("SELECT * FROM categories ORDER BY id"))

@bp.get("/products")
@bp.get("/categories/<int:category_id>")
def products(category_id=None):
    return catalog(category_id)

def catalog(category_id=None, account=False):
    categories = query("SELECT * FROM categories ORDER BY id")
    criteria, values = ["p.active=1"], []
    category_id = category_id or request.args.get("category", type=int)
    category = next((item for item in categories if item["id"] == category_id), None)
    if category_id:
        if not category:
            abort(404)
        criteria.append("p.category_id=%s")
        values.append(category_id)
    term = request.args.get("q", "").strip()[:150]
    if term:
        criteria.append("(LOCATE(%s,p.name)>0 OR LOCATE(%s,p.description)>0 OR LOCATE(%s,c.name)>0)")
        values.extend([term] * 3)
    try:
        for name, operator in (("min", ">="), ("max", "<=")):
            if request.args.get(name):
                values.append(price(request.args[name]))
                criteria.append(f"{PRICE}{operator}%s")
        if request.args.get("min") and request.args.get("max") and values[-2] > values[-1]:
            raise ValueError("Minimum price must be at or below maximum price.")
    except ValueError as error:
        flash(str(error))
        return redirect(url_for("account.browse" if account else "public.products", category=category_id, q=term))
    sort = {"price_asc": "sale_price ASC", "price_desc": "sale_price DESC", "popular": "p.views DESC"}
    order = sort.get(request.args.get("sort"), "p.id DESC")
    items = query(CATALOG + " WHERE " + " AND ".join(criteria) + f" ORDER BY {order},p.id", tuple(values))
    return render_template("catalog.html", title=category["name"] if category else "All products",
                           category=category, categories=categories, products=items, term=term, area="account" if account else None)

@bp.get("/products/<int:product_id>")
def product(product_id):
    product = one(CATALOG + " WHERE p.id=%s AND p.active=1", (product_id,))
    if not product:
        abort(404)
    recent = session.get("recent", [])
    if not recent or product_id != recent[0]:
        execute("UPDATE products SET views=views+1 WHERE id=%s", (product_id,))
        commit()
    session["recent"] = [product_id] + [item for item in recent if item != product_id][:7]
    reviews = query("SELECT r.rating,r.body,u.name FROM reviews r JOIN users u ON u.id=r.user_id WHERE r.product_id=%s ORDER BY r.id DESC", (product_id,))
    can_review = g.user and g.user["role"] == "USER" and one(
        "SELECT o.id FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.user_id=%s AND o.status='Delivered' AND i.product_id=%s LIMIT 1",
        (g.user["id"], product_id))
    return render_template("product.html", p=product, reviews=reviews, can_review=can_review)

@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        try:
            name, email, phone = field("name", 100), field("email", 254).lower(), field("phone", 20)
            password = request.form.get("password", "")
            if not valid_email(email) or not valid_phone(phone):
                raise ValueError("Enter a valid email address and phone number.")
            if not 8 <= len(password) <= 128 or password != request.form.get("confirm"):
                raise ValueError("Use 8–128 characters and enter the same password twice.")
            execute("INSERT INTO users(name,email,phone,password_hash) VALUES(%s,%s,%s,%s)",
                    (name, email, phone, generate_password_hash(password)))
            commit()
            flash("Account created. Sign in to start shopping.")
            return redirect(url_for("public.login"))
        except IntegrityError:
            rollback()
            flash("This email is already registered.")
        except ValueError as error:
            flash(str(error))
    return render_template("auth.html", signup=True)

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = one("SELECT id,password_hash,role,active FROM users WHERE email=%s", (email,)) if valid_email(email) else None
        if user and user["active"] and 1 <= len(password) <= 128 and check_password_hash(user["password_hash"], password):
            recent = session.get("recent", [])
            session.clear()
            session.update(user_id=user["id"], recent=recent)
            return redirect(url_for("admin.dashboard" if user["role"] == "ADMIN" else "account.dashboard"))
        flash("Sign-in failed. Check your email and password.")
    return render_template("auth.html", signup=False)

@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("public.home"))

@bp.post("/newsletter")
def newsletter():
    email = request.form.get("email", "").strip().lower()
    if valid_email(email):
        execute("INSERT INTO newsletter_subscribers(email) VALUES(%s) ON DUPLICATE KEY UPDATE email=email", (email,))
        commit()
        flash("You're subscribed to AllCart updates.")
    else:
        flash("Enter a valid email address.")
    return redirect(url_for("public.home", _anchor="newsletter"))

@bp.get("/about")
def about():
    return render_template("info.html", title="About us")

@bp.get("/contact")
def contact():
    import os
    return render_template("info.html", title="Contact us", contact=True, email=os.getenv("SHOPSPHERE_CONTACT_EMAIL", ""))

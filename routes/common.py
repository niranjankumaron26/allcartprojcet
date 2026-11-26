import re
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import abort, flash, g, redirect, request, url_for

from database import commit, execute, one, query, rollback

PRICE = "ROUND(p.price*(100-p.discount)/100,2)"
STATUS = {
    "Pending": ("Confirmed", "Cancelled"),
    "Confirmed": ("Processing", "Cancelled"),
    "Processing": ("Shipped", "Cancelled"),
    "Shipped": ("Delivered",),
    "Delivered": (),
    "Cancelled": (),
}

def require(role):
    def decorator(view):
        @wraps(view)
        def protected(*args, **kwargs):
            if not g.user:
                flash("Please sign in to continue.")
                return redirect(url_for("public.login"))
            if g.user["role"] != role:
                abort(403)
            return view(*args, **kwargs)
        return protected
    return decorator

def valid_email(value):
    return len(value) <= 254 and bool(re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value))

def valid_phone(value):
    return bool(re.fullmatch(r"\+?[0-9][0-9 ()-]{6,18}[0-9]", value))

def field(name, maximum, minimum=1):
    value = request.form.get(name, "").strip()
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"Enter a valid {name.replace('_', ' ')}.")
    return value

def integer(value, minimum, maximum):
    try:
        result = int(value)
        if minimum <= result <= maximum:
            return result
    except (TypeError, ValueError):
        pass
    raise ValueError(f"Enter a whole number from {minimum} to {maximum}.")

def price(value, minimum=0):
    try:
        result = Decimal(value)
        if result.is_finite() and minimum <= result <= 9999999999 and result == result.quantize(Decimal(".01")):
            return result
    except (InvalidOperation, TypeError):
        pass
    raise ValueError("Enter a valid price with up to two decimal places.")

def change_order(order_id, target, owner=None):
    order = one("SELECT * FROM orders WHERE id=%s FOR UPDATE", (order_id,))
    if not order or (owner is not None and order["user_id"] != owner):
        abort(404)
    if target not in STATUS[order["status"]] or (owner is not None and order["status"] not in ("Pending", "Confirmed")):
        rollback()
        raise ValueError("That status change is unavailable.")
    if target == "Cancelled":
        for item in query("SELECT product_id,quantity FROM order_items WHERE order_id=%s ORDER BY product_id", (order_id,)):
            execute("UPDATE products SET stock=stock+%s WHERE id=%s", (item["quantity"], item["product_id"]))
    execute("UPDATE orders SET status=%s WHERE id=%s", (target, order_id))
    commit()

def order_items(order_id):
    return query("SELECT * FROM order_items WHERE order_id=%s ORDER BY id", (order_id,))

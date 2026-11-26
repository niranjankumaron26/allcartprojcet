if __name__ == "__main__":
    import os
    import subprocess
    from pathlib import Path

    project = Path(__file__).resolve().parent
    interpreter = project / ".venv" / "Scripts" / "python.exe"
    launcher = project.parent / "work" / "start_shopsphere.py"
    if not interpreter.is_file() or not launcher.is_file():
        raise SystemExit("Local AllCart setup is missing. See README.md.")
    environment = dict(os.environ, SHOPSPHERE_WEB_PORT="8765", SHOPSPHERE_OPEN_BROWSER="1")
    try:
        raise SystemExit(subprocess.call(
            [str(interpreter), str(launcher)], cwd=project, env=environment,
        ))
    except KeyboardInterrupt:
        raise SystemExit(0)


from pathlib import Path
from secrets import compare_digest, token_urlsafe

import click
from flask import Flask, abort, g, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from config import Config
from database import commit, execute, mysql, one
from routes import public, account, admin
from routes.common import valid_email, valid_phone

def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Set SHOPSPHERE_SECRET_KEY before starting Flask.")
    mysql.init_app(app)
    for blueprint in (public.bp, account.bp, admin.bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def load_session():
        if request.endpoint == "static":
            return
        if request.method == "POST":
            expected = session.get("csrf", "")
            actual = request.form.get("csrf", "")
            if not expected or not compare_digest(expected.encode(), actual.encode()):
                abort(400, "This form has expired. Reload the page and try again.")
        g.user = None
        if session.get("user_id"):
            g.user = one("SELECT id,name,email,phone,role FROM users WHERE id=%s AND active=1", (session["user_id"],))
            if not g.user:
                session.clear()

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = token_urlsafe(32)
        return session["csrf"]

    @app.context_processor
    def helpers():
        return {"csrf_token": csrf_token, "image_url": lambda image: url_for("static", filename=image),
                "money": lambda value: f"₹{value:,.2f}"}

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if getattr(g, "user", None):
            response.headers["Cache-Control"] = "no-store"
        return response

    for code in (400, 403, 404, 413):
        app.register_error_handler(code, lambda error: (render_template("error.html", error=error), error.code))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    @app.cli.command("seed")
    def seed():
        script = Path(app.root_path, "seed.sql").read_text(encoding="utf-8")
        for statement in script.split(";"):
            if statement.strip():
                execute(statement)
        commit()
        click.echo("Sample catalog loaded.")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", default="AllCart Admin")
    @click.option("--phone", prompt=True)
    @click.password_option()
    def create_admin(email, name, phone, password):
        email = email.strip().lower()
        if not valid_email(email) or not valid_phone(phone) or not 12 <= len(password) <= 128 or not 1 <= len(name.strip()) <= 100:
            raise click.ClickException("Provide valid details and a password of 12–128 characters.")
        if one("SELECT id FROM users WHERE email=%s", (email,)):
            raise click.ClickException("This email already belongs to an account.")
        execute("INSERT INTO users(name,email,phone,password_hash,role) VALUES(%s,%s,%s,%s,'ADMIN')",
                (name.strip(), email, phone, generate_password_hash(password)))
        commit()
        click.echo("Admin account created.")

    return app

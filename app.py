import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash

import db as dblib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)


def _load_secret_key():
    key = ""
    for k, v in os.environ.items():
        if k.lower() == "secret_key":
            key = v.strip()
            break
    if key:
        return key
    key_file = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = os.urandom(32).hex()
    try:
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(key)
    except Exception:
        pass
    return key


app.secret_key = _load_secret_key()

# Куда ведёт кнопка «Скачать клиент» (jar с Google Drive / ссылка на лаунчер).
CLIENT_JAR_URL = "https://drive.google.com/uc?export=download&id=1GjB02yZc0fYc5-G_hTfowj7RNdI7vjyF"
LAUNCHER_ZIP_URL = "https://drive.google.com/uc?export=download&id=1s85aO0Dd4t8eNKpESlhZswHKDnjBXYsj"

TOKEN_TTL_DAYS = 30
HWID_LIMIT = 3
HWID_RE = re.compile(r"^[A-Za-z0-9\-:]{8,128}$")

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at    TEXT DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS hwids (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        hwid       TEXT NOT NULL,
        label      TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_hwid ON hwids (user_id, hwid);",
    """
    CREATE TABLE IF NOT EXISTS tokens (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token      TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT NOT NULL
    );
    """,
]


def init_db():
    d = dblib.Database()
    try:
        d.init_schema(SCHEMA)
    finally:
        d.close()


def get_db():
    d = getattr(g, "_db", None)
    if d is None:
        d = g._db = dblib.Database()
    return d


@app.teardown_appcontext
def close_db(_exc):
    d = getattr(g, "_db", None)
    if d is not None:
        d.close()


@app.after_request
def _diag_headers(resp):
    resp.headers["X-Asgard-Build"] = "turso-v1"
    resp.headers["X-Asgard-Backend"] = "turso" if (dblib.TURSO_URL and dblib.TURSO_TOKEN) else "sqlite"
    return resp


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    rows = get_db().query("SELECT * FROM users WHERE id = ?", (uid,))
    return rows[0] if rows else None


@app.route("/")
def index():
    return render_template("index.html", user=current_user())


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id") is not None:
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not username or not password:
            error = "Заполни все поля."
        elif len(username) < 3 or len(username) > 20:
            error = "Логин должен быть от 3 до 20 символов."
        elif len(password) < 6:
            error = "Пароль минимум 6 символов."
        elif password != confirm:
            error = "Пароли не совпадают."
        else:
            db = get_db()
            if db.query("SELECT id FROM users WHERE username = ?", (username,)):
                error = "Такой логин уже занят."
            else:
                try:
                    db.run(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)),
                    )
                except dblib.IntegrityError:
                    error = "Такой логин уже занят."
                else:
                    return redirect(url_for("login"))

    return render_template("register.html", user=None, error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id") is not None:
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        rows = db.query("SELECT * FROM users WHERE username = ?", (username,))
        user = rows[0] if rows else None
        if user is None or not check_password_hash(user["password_hash"], password):
            error = "Неверный логин или пароль."
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))

    return render_template("login.html", user=None, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    hwids = get_db().query(
        "SELECT * FROM hwids WHERE user_id = ? ORDER BY id", (user["id"],)
    )
    return render_template("dashboard.html", user=user, hwids=hwids)


@app.route("/dashboard/add-hwid", methods=["POST"])
@login_required
def add_hwid():
    user = current_user()
    hwid = request.form.get("hwid", "").strip()
    label = request.form.get("label", "").strip()

    if not hwid:
        flash("Введи HWID.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    count = db.query(
        "SELECT COUNT(*) AS c FROM hwids WHERE user_id = ?", (user["id"],)
    )[0]["c"]
    if count >= HWID_LIMIT:
        flash(f"Лимит HWID ({HWID_LIMIT}) исчерпан. Сначала удали один из существующих.", "error")
        return redirect(url_for("dashboard"))

    try:
        db.run(
            "INSERT INTO hwids (user_id, hwid, label) VALUES (?, ?, ?)",
            (user["id"], hwid, label),
        )
        flash("HWID добавлен.", "ok")
    except dblib.IntegrityError:
        flash("Этот HWID уже привязан к аккаунту.", "error")

    return redirect(url_for("dashboard"))


@app.route("/dashboard/delete-hwid/<int:hwid_id>", methods=["POST"])
@login_required
def delete_hwid(hwid_id):
    user = current_user()
    db = get_db()
    db.run("DELETE FROM hwids WHERE id = ? AND user_id = ?", (hwid_id, user["id"]))
    flash("HWID удалён.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/download")
def download():
    return render_template(
        "download.html",
        user=current_user(),
        jar_url=CLIENT_JAR_URL,
        launcher_url=LAUNCHER_ZIP_URL,
    )


def _now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _expires_utc(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _token_user(db, token):
    rows = db.query(
        """SELECT t.token, t.expires_at, u.*
           FROM tokens t JOIN users u ON u.id = t.user_id
           WHERE t.token = ?""",
        (token,),
    )
    row = rows[0] if rows else None
    if row is None or row["expires_at"] < _now_utc():
        return None
    return row


def _hwid_bound(db, user_id, hwid):
    return bool(
        db.query(
            "SELECT id FROM hwids WHERE user_id = ? AND hwid = ?",
            (user_id, hwid),
        )
    )


def _hwid_count(db, user_id):
    return db.query(
        "SELECT COUNT(*) AS c FROM hwids WHERE user_id = ?", (user_id,)
    )[0]["c"]


@app.route("/api/launcher/auth", methods=["POST"])
def api_launcher_auth():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    hwid = (data.get("hwid") or "").strip()

    if not username or not password:
        return jsonify({"ok": False, "error": "Введи логин и пароль."}), 400
    if not hwid or not HWID_RE.match(hwid):
        return jsonify({"ok": False, "error": "Не удалось определить HWID этого компьютера."}), 400

    db = get_db()
    rows = db.query("SELECT * FROM users WHERE username = ?", (username,))
    user = rows[0] if rows else None
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"ok": False, "error": "Неверный логин или пароль."}), 401

    if not _hwid_bound(db, user["id"], hwid):
        if _hwid_count(db, user["id"]) >= HWID_LIMIT:
            return jsonify(
                {
                    "ok": False,
                    "error": f"Лимит HWID ({HWID_LIMIT}) исчерпан. Удали старый HWID в личном кабинете на сайте.",
                }
            ), 403
        db.run(
            "INSERT INTO hwids (user_id, hwid, label) VALUES (?, ?, ?)",
            (user["id"], hwid, "auto"),
        )

    token = secrets.token_hex(32)
    db.run(
        "INSERT INTO tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], token, _expires_utc(TOKEN_TTL_DAYS)),
    )
    return jsonify(
        {
            "ok": True,
            "token": token,
            "username": user["username"],
            "expires_in_days": TOKEN_TTL_DAYS,
        }
    )


@app.route("/api/launcher/status", methods=["POST"])
def api_launcher_status():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    hwid = (data.get("hwid") or "").strip()

    if not token or not hwid:
        return jsonify({"ok": False, "error": "Нет токена или HWID."}), 400

    db = get_db()
    row = _token_user(db, token)
    if row is None:
        return jsonify({"ok": False, "error": "Сессия истекла. Войди в лаунчер заново."}), 401
    if not _hwid_bound(db, row["id"], hwid):
        return jsonify({"ok": False, "error": "HWID не привязан к этому аккаунту."}), 403

    return jsonify({"ok": True, "username": row["username"]})


@app.route("/api/launcher/logout", methods=["POST"])
def api_launcher_logout():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if token:
        db = get_db()
        db.run("DELETE FROM tokens WHERE token = ?", (token,))
    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
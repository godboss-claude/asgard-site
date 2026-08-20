import os
import sqlite3
from functools import wraps

from flask import Flask, g, redirect, render_template, request, session, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "asgard.db")

app = Flask(__name__)

def _load_secret_key():
    key_file = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = os.urandom(32).hex()
    with open(key_file, "w", encoding="utf-8") as f:
        f.write(key)
    return key

app.secret_key = _load_secret_key()

# Куда ведёт кнопка «Скачать клиент» (jar с Google Drive / ссылка на лоадер).
CLIENT_JAR_URL = "https://drive.google.com/uc?export=download&id=1GjB02yZc0fYc5-G_hTfowj7RNdI7vjyF"
LOADER_ZIP_URL = ""  # можно поставить ссылку на Asgard-Loader.zip


def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(_exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS hwids (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                hwid       TEXT NOT NULL,
                label      TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_hwid ON hwids (user_id, hwid);
            """
        )


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
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


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
            if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
                error = "Такой логин уже занят."
            else:
                db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                db.commit()
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
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
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
    hwids = get_db().execute(
        "SELECT * FROM hwids WHERE user_id = ? ORDER BY id", (user["id"],)
    ).fetchall()
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
    try:
        db.execute(
            "INSERT INTO hwids (user_id, hwid, label) VALUES (?, ?, ?)",
            (user["id"], hwid, label),
        )
        db.commit()
        flash("HWID добавлен.", "ok")
    except sqlite3.IntegrityError:
        flash("Этот HWID уже привязан к аккаунту.", "error")

    return redirect(url_for("dashboard"))


@app.route("/dashboard/delete-hwid/<int:hwid_id>", methods=["POST"])
@login_required
def delete_hwid(hwid_id):
    user = current_user()
    db = get_db()
    db.execute("DELETE FROM hwids WHERE id = ? AND user_id = ?", (hwid_id, user["id"]))
    db.commit()
    flash("HWID удалён.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/download")
def download():
    return render_template(
        "download.html",
        user=current_user(),
        jar_url=CLIENT_JAR_URL,
        loader_url=LOADER_ZIP_URL,
    )


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
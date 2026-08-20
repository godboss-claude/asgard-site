# -*- coding: utf-8 -*-
"""БД для Asgard: SQLite локально (dev) / Turso через HTTP API (prod)."""
import os
import sqlite3

import requests

TURSO_URL = os.environ.get("TURSO_URL", "").strip().rstrip("/")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "").strip()


class IntegrityError(Exception):
    pass


class _SqliteBackend:
    def __init__(self, path):
        self._path = path
        self._conn = None

    def _get(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self._path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def query(self, sql, params):
        cur = self._get().execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def run(self, sql, params):
        try:
            cur = self._get().execute(sql, params)
            self._get().commit()
            return cur.lastrowid
        except sqlite3.IntegrityError as e:
            raise IntegrityError(str(e)) from e

    def init_schema(self, statements):
        conn = self._get()
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class _TursoBackend:
    def __init__(self, url, token):
        self._url = url + "/v2/pipeline"
        self._headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        self._session = requests.Session()

    @staticmethod
    def _args(params):
        out = []
        for p in params:
            if p is None:
                out.append({"type": "null", "value": None})
            elif isinstance(p, bool):
                out.append({"type": "integer", "value": int(p)})
            elif isinstance(p, int):
                out.append({"type": "integer", "value": p})
            elif isinstance(p, float):
                out.append({"type": "float", "value": p})
            else:
                out.append({"type": "text", "value": str(p)})
        return out

    def _execute(self, sql, params):
        body = {
            "requests": [
                {"type": "execute", "stmt": {"sql": sql, "args": self._args(params)}},
                {"type": "close"},
            ]
        }
        r = self._session.post(self._url, headers=self._headers, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        if not results:
            raise RuntimeError("Turso: пустой ответ")
        res = results[0]
        if res.get("type") == "error":
            err = res.get("error") or {}
            msg = err.get("message") or "SQL error"
            if "unique" in msg.lower() or "constraint" in msg.lower():
                raise IntegrityError(msg)
            raise RuntimeError("Turso SQL: " + msg)
        resp = res.get("response") or {}
        return resp.get("result") or {}

    def query(self, sql, params):
        result = self._execute(sql, params)
        cols = []
        for c in result.get("cols", []):
            cols.append(c.get("name") if isinstance(c, dict) else c)
        rows = result.get("rows", [])
        out = []
        for r in rows:
            d = {}
            for i, cell in enumerate(r):
                if isinstance(cell, dict):
                    d[cols[i]] = cell.get("value")
                else:
                    d[cols[i]] = cell
            out.append(d)
        return out

    def run(self, sql, params):
        result = self._execute(sql, params)
        return result.get("last_insert_rowid")

    def init_schema(self, statements):
        for stmt in statements:
            self._execute(stmt, ())

    def close(self):
        pass


class Database:
    def __init__(self):
        if TURSO_URL and TURSO_TOKEN:
            self._b = _TursoBackend(TURSO_URL, TURSO_TOKEN)
        else:
            self._b = _SqliteBackend(os.environ.get("ASGARD_DB", "asgard.db"))

    def query(self, sql, params=()):
        return self._b.query(sql, tuple(params))

    def run(self, sql, params=()):
        return self._b.run(sql, tuple(params))

    def commit(self):
        pass

    def init_schema(self, statements):
        self._b.init_schema(statements)

    def close(self):
        self._b.close()
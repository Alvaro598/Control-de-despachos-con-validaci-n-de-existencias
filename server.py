"""Small standard-library server for the La Quinta dispatch UI."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / ".data"
DB_PATH = DATA_DIR / "la_quinta.sqlite3"


def load_local_env() -> None:
    """Load simple KEY=VALUE settings without making a dotenv dependency."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_local_env()
MAKE_WEBHOOK_URL = os.environ.get("MAKE_WEBHOOK_URL", "").strip()
ALLOWED_MOTIVES = {"despacho", "traslado entre sedes", "avería"}
ALLOWED_RESULTS = {"APROBADO", "APROBADO CON ALERTA", "RECHAZADO", "RUTA DE RESPALDO"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DB_LOCK = threading.Lock()


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def initialize_db() -> None:
    with connect_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS movimientos (
            id_movimiento TEXT PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            solicitante TEXT NOT NULL,
            correo TEXT NOT NULL,
            codigo_producto TEXT NOT NULL,
            cantidad REAL NOT NULL,
            destino TEXT NOT NULL,
            motivo TEXT NOT NULL,
            resultado TEXT NOT NULL,
            saldo_anterior REAL,
            saldo_posterior REAL,
            observacion TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS incidencias (
            id_incidencia TEXT PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            solicitante TEXT NOT NULL,
            correo TEXT NOT NULL,
            codigo_producto TEXT NOT NULL,
            cantidad REAL NOT NULL,
            destino TEXT NOT NULL,
            motivo TEXT NOT NULL,
            resultado TEXT NOT NULL,
            observacion TEXT
        )""")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_payload(data: object) -> tuple[dict | None, str | None]:
    if not isinstance(data, dict):
        return None, "El cuerpo debe ser un objeto JSON."
    expected = ("solicitante", "correo", "codigo_producto", "cantidad", "destino", "motivo")
    clean = {key: str(data.get(key, "")).strip() for key in expected}
    missing = [key for key in expected if not clean[key]]
    if missing:
        return None, "Faltan campos requeridos: " + ", ".join(missing)
    if len(clean["solicitante"]) > 120 or len(clean["codigo_producto"]) > 32 or len(clean["destino"]) > 160:
        return None, "Uno o más campos superan la longitud permitida."
    if len(clean["correo"]) > 254 or not EMAIL_RE.fullmatch(clean["correo"]):
        return None, "El correo no tiene un formato válido."
    if not re.fullmatch(r"[A-Za-z0-9-]+", clean["codigo_producto"]):
        return None, "El código del producto no tiene un formato válido."
    if clean["motivo"].casefold() not in ALLOWED_MOTIVES:
        return None, "El motivo seleccionado no está permitido."
    try:
        quantity = float(clean["cantidad"])
    except ValueError:
        return None, "La cantidad debe ser numérica."
    if quantity <= 0 or quantity == float("inf") or quantity != quantity:
        return None, "La cantidad debe ser un número positivo."
    clean["cantidad"] = quantity
    return clean, None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/history":
            with DB_LOCK, connect_db() as db:
                rows = db.execute("SELECT * FROM movimientos ORDER BY fecha_hora DESC LIMIT 500").fetchall()
            self.send_json(200, {"movimientos": [dict(row) for row in rows]})
            return
        if self.path == "/api/products":
            try:
                products = json.loads((ROOT / "products.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.send_json(500, {"error": "No se pudo leer el catálogo de productos."})
                return
            self.send_json(200, {"productos": products})
            return
        if self.path == "/":
            self.path = "/index.html"
        if self.path.startswith("/api/"):
            self.send_json(404, {"error": "Ruta no encontrada."})
            return
        if self.path not in {"/index.html", "/styles.css", "/app.js"}:
            self.send_json(404, {"error": "Recurso no encontrado."})
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/dispatch":
            self.send_json(404, {"error": "Ruta no encontrada."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                self.send_json(413, {"error": "Tamaño de solicitud no permitido."})
                return
            data = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "JSON inválido."})
            return
        payload, error = validate_payload(data)
        if error:
            self.send_json(400, {"error": error})
            return
        if not MAKE_WEBHOOK_URL:
            self.send_json(503, {"error": "Falta configurar MAKE_WEBHOOK_URL en el servidor."})
            return

        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(MAKE_WEBHOOK_URL, data=request_body,
            headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                raw = response.read(65_536)
                make_result = json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # URL errors can include the webhook URL, which contains its secret token.
            print(f"Make webhook request failed: {type(exc).__name__}")
            self.send_json(502, {"error": "No se recibió respuesta confiable de Make."})
            return
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"Make response parsing failed: {type(exc).__name__}")
            print(f"Make response body: {raw[:2000]!r}")
            self.send_json(502, {
                "error": "Make respondió con un cuerpo que no es JSON válido.",
                "detalle": raw[:1000].decode("utf-8", errors="replace")
            })
            return
       
        if not isinstance(make_result, dict):
            self.send_json(502, {"error": "La respuesta de Make debe ser un objeto JSON."})
            return
        result = str(make_result.get("resultado", make_result.get("result", ""))).strip().upper()
        if result not in ALLOWED_RESULTS:
            self.send_json(502, {"error": "La respuesta de Make no contiene un resultado reconocido."})
            return

        timestamp = now_iso()
        note = str(make_result.get("mensaje", make_result.get("observacion", "")))[:1000]
        saldo_anterior = make_result.get("saldo_anterior")
        saldo_posterior = make_result.get("saldo_posterior", make_result.get("saldo"))
        if result in {"APROBADO", "APROBADO CON ALERTA"}:
            movement = {
                "id_movimiento": str(uuid.uuid4()), "fecha_hora": timestamp, **payload,
                "resultado": result, "saldo_anterior": saldo_anterior,
                "saldo_posterior": saldo_posterior, "observacion": note,
            }
            with DB_LOCK, connect_db() as db:
                db.execute("""INSERT INTO movimientos VALUES
                    (:id_movimiento,:fecha_hora,:solicitante,:correo,:codigo_producto,:cantidad,:destino,:motivo,
                     :resultado,:saldo_anterior,:saldo_posterior,:observacion)""", movement)
        elif result == "RUTA DE RESPALDO":
            incident = {"id_incidencia": str(uuid.uuid4()), "fecha_hora": timestamp,
                        **payload, "resultado": result, "observacion": note}
            with DB_LOCK, connect_db() as db:
                db.execute("""INSERT INTO incidencias VALUES
                    (:id_incidencia,:fecha_hora,:solicitante,:correo,:codigo_producto,:cantidad,:destino,:motivo,
                     :resultado,:observacion)""", incident)
        self.send_json(200, {**make_result, "resultado": result})


if __name__ == "__main__":
    initialize_db()
    port = int(os.environ.get("PORT", "8000"))
    print(f"La Quinta disponible en http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

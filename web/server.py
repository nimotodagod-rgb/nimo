from __future__ import annotations

import io
import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode, urlsplit, urlunsplit

from flask import Flask, jsonify, render_template, request, send_file, session
from PIL import Image, ImageOps

from ooxml_worker import build_pptx
from parser import parse_quick_text, validate_parsed
from pptx_importer import convert_legacy_powerpoint, import_powerpoint


WEB_DIR = Path(__file__).resolve().parent
PROJECT_DIR = WEB_DIR.parent
ASSET_DIR = PROJECT_DIR / "assets"
WORKER = PROJECT_DIR / "office_worker.py"
BRAND_FILES = {
    "br-sport": (
        ASSET_DIR / "BR SPORT CONQUISTANDO.pptx",
        ASSET_DIR / "BR SPORT header.png",
        "BR-SPORT",
    ),
    "actvitta": (
        ASSET_DIR / "ACTVITTA CONQUISTANDO.pptx",
        ASSET_DIR / "ACTVITTA header.png",
        "ACTVITTA",
    ),
}

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("APP_SECRET_KEY", os.environ.get("SECRET_KEY", "conquistando-dev-secret"))
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
    days=int(os.environ.get("APP_SESSION_DAYS", "30"))
)
generation_lock = threading.Lock()
accounts_lock = threading.Lock()
database_schema_lock = threading.Lock()
database_schema_ready = False


def libreoffice_paths() -> tuple[str, str]:
    soffice = shutil.which("soffice")
    if os.name == "nt":
        folder = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "LibreOffice" / "program"
        soffice = soffice or str(folder / "soffice.exe")
        worker_python = str(folder / "python.exe")
    else:
        soffice = soffice or "/usr/bin/soffice"
        worker_python = sys.executable
    if not Path(soffice).is_file() or not Path(worker_python).is_file():
        raise RuntimeError("LibreOffice não está disponível no servidor.")
    return soffice, worker_python


def check_pin_value(pin: str) -> bool:
    expected = os.environ.get("APP_PIN", "").strip()
    if not expected:
        return False
    return hmac.compare_digest(str(pin or "").strip(), expected)


def check_pin() -> bool:
    return check_pin_value(request.headers.get("X-App-Pin", ""))


def payment_url() -> str:
    return os.environ.get("APP_PAYMENT_URL", "").strip()


def public_base_url() -> str:
    configured = os.environ.get("APP_PUBLIC_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    return request.host_url.rstrip("/")


def mercadopago_access_token() -> str:
    return os.environ.get("MERCADOPAGO_ACCESS_TOKEN", os.environ.get("MP_ACCESS_TOKEN", "")).strip()


def plan_amount() -> float:
    raw = os.environ.get("APP_PLAN_AMOUNT", "").strip().replace(",", ".")
    if not raw:
        raise ValueError("Configure APP_PLAN_AMOUNT no Render antes de criar assinaturas.")
    amount = float(raw)
    if amount <= 0:
        raise ValueError("APP_PLAN_AMOUNT precisa ser maior que zero.")
    return round(amount, 2)


def plan_title() -> str:
    return os.environ.get("APP_PLAN_TITLE", "Editor Conquistando").strip() or "Editor Conquistando"


def paid_email_set() -> set[str]:
    raw = os.environ.get("APP_PAID_EMAILS", "").strip()
    return {
        item.strip().casefold()
        for item in raw.replace(";", ",").split(",")
        if item.strip()
    }


def mp_api(method: str, path: str, payload: dict | None = None) -> dict:
    token = mercadopago_access_token()
    if not token:
        raise RuntimeError("Configure MERCADOPAGO_ACCESS_TOKEN no Render.")
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        f"https://api.mercadopago.com{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Mercado Pago recusou a solicitação: {detail[:500]}") from exc


def webhook_data_id(payload: dict) -> str:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    for key in ("id", "resource"):
        if request.args.get(key):
            return str(request.args[key])
    return ""


def validate_mp_webhook_signature(payload: dict) -> bool:
    secret = os.environ.get("MERCADOPAGO_WEBHOOK_SECRET", os.environ.get("MP_WEBHOOK_SECRET", "")).strip()
    if not secret:
        return True
    signature = request.headers.get("x-signature", "")
    request_id = request.headers.get("x-request-id", "")
    parts = dict(
        item.split("=", 1)
        for item in signature.split(",")
        if "=" in item
    )
    ts = parts.get("ts", "")
    received = parts.get("v1", "")
    data_id = webhook_data_id(payload)
    if not ts or not received or not request_id or not data_id:
        return False
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    calculated = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calculated, received)


def payment_link_for(email: str = "", name: str = "") -> str:
    base = payment_url()
    if not base:
        return ""
    query = {
        key: value
        for key, value in {
            "email": str(email or "").strip(),
            "name": str(name or "").strip(),
        }.items()
        if value
    }
    if not query:
        return base
    parts = urlsplit(base)
    extra = urlencode(query)
    current = parts.query
    joined = f"{current}&{extra}" if current else extra
    return urlunsplit((parts.scheme, parts.netloc, parts.path, joined, parts.fragment))


def accounts_file() -> Path:
    configured = os.environ.get("APP_ACCOUNTS_FILE", "").strip()
    if configured:
        return Path(configured)
    data_dir = os.environ.get("APP_DATA_DIR", os.environ.get("RENDER_DISK_PATH", "")).strip()
    base = Path(data_dir) if data_dir else PROJECT_DIR / "runtime"
    return base / "users.json"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def postgres_connection():
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError(
            "O suporte ao banco PostgreSQL não está instalado no servidor."
        ) from exc
    return psycopg2.connect(database_url(), connect_timeout=10)


def ensure_database_schema() -> None:
    global database_schema_ready
    if not database_url() or database_schema_ready:
        return
    with database_schema_lock:
        if database_schema_ready:
            return
        with postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS editor_accounts (
                        email TEXT PRIMARY KEY,
                        data JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
        database_schema_ready = True


def save_raw_user(email: str, user: dict) -> None:
    normalized_email = str(email or "").strip().casefold()
    record = {**user, "email": normalized_email}
    if database_url():
        ensure_database_schema()
        with postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO editor_accounts (email, data, updated_at)
                    VALUES (%s, %s::jsonb, NOW())
                    ON CONFLICT (email) DO UPDATE
                    SET data = EXCLUDED.data, updated_at = NOW()
                    """,
                    (normalized_email, json.dumps(record, ensure_ascii=False)),
                )
        return

    path = accounts_file()
    users = raw_registered_users()
    users[normalized_email] = record
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    rounds = 150_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), rounds).hex()
    return f"pbkdf2_sha256${rounds}${salt}${digest}"


def password_matches(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt, digest = stored.split("$", 3)
            calculated = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt),
                int(rounds),
            ).hex()
            return hmac.compare_digest(calculated, digest)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(password, stored)


def registered_users() -> dict[str, dict]:
    raw = raw_registered_users()
    if isinstance(raw, list):
        raw = {str(item.get("email", "")).casefold(): item for item in raw if isinstance(item, dict)}
    users: dict[str, dict] = {}
    items = raw.items() if isinstance(raw, dict) else []
    for email, item in items:
        if not isinstance(item, dict):
            continue
        normalized = str(item.get("email", email)).strip().casefold()
        stored = str(item.get("password_hash", item.get("password", "")))
        if normalized and stored:
            users[normalized] = {
                "password": stored,
                "active": bool(item.get("active", False)),
                "name": str(item.get("name", normalized)).strip() or normalized,
                "razao_social": str(item.get("razao_social", "")).strip(),
                "registered": True,
            }
    return users


def raw_registered_users() -> dict[str, dict]:
    if database_url():
        ensure_database_schema()
        with postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT email, data FROM editor_accounts")
                rows = cursor.fetchall()
        users: dict[str, dict] = {}
        for email, data in rows:
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    continue
            if isinstance(data, dict):
                users[str(email).strip().casefold()] = data
        return users

    path = accounts_file()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(raw, list):
        return {
            str(item.get("email", "")).strip().casefold(): item
            for item in raw
            if isinstance(item, dict) and str(item.get("email", "")).strip()
        }
    return raw if isinstance(raw, dict) else {}


def save_registered_user(email: str, name: str, password: str) -> None:
    with accounts_lock:
        users = registered_users()
        if email in users:
            raise ValueError("Esta conta já existe. Use Entrar.")
        save_raw_user(email, {
            "email": email,
            "name": name,
            "password_hash": password_hash(password),
            "active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })


def save_account_razao(email: str, razao: str) -> str:
    normalized_email = str(email or "").strip().casefold()
    normalized_razao = str(razao or "").strip()
    if not normalized_email or not normalized_razao:
        raise ValueError("Informe a razao social.")
    with accounts_lock:
        users = raw_registered_users()
        user = users.get(normalized_email)
        if not isinstance(user, dict):
            user = {
                "email": normalized_email,
                "name": str(session.get("name", normalized_email)).strip() or normalized_email,
                "active": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        current = str(user.get("razao_social", "")).strip()
        if current and current != normalized_razao:
            return current
        user["razao_social"] = current or normalized_razao
        save_raw_user(normalized_email, user)
        return user["razao_social"]


def set_account_active(email: str, active: bool, **extra: str) -> bool:
    normalized_email = str(email or "").strip().casefold()
    if not normalized_email:
        return False
    with accounts_lock:
        users = raw_registered_users()
        user = users.get(normalized_email)
        if not isinstance(user, dict):
            user = {"email": normalized_email, "name": normalized_email, "created_at": datetime.now(timezone.utc).isoformat()}
        user["active"] = bool(active)
        user["updated_at"] = datetime.now(timezone.utc).isoformat()
        for key, value in extra.items():
            if value is not None:
                user[key] = str(value)
        save_raw_user(normalized_email, user)
    return True


def known_users() -> dict[str, dict]:
    raw_registered = raw_registered_users()
    users = registered_users()
    configured = configured_users()
    for email, user in configured.items():
        extra = raw_registered.get(email)
        if isinstance(extra, dict):
            razao = str(extra.get("razao_social", "")).strip()
            if razao:
                user = {**user, "razao_social": razao}
            if "active" in extra:
                user = {**user, "active": bool(extra.get("active"))}
            for key in ("mercadopago_subscription_id", "mercadopago_payment_id", "payment_status"):
                if extra.get(key):
                    user = {**user, key: str(extra.get(key))}
        users[email] = user
    for email in paid_email_set():
        if email in users:
            users[email] = {**users[email], "active": True}
    return users


def refresh_session_from_account() -> None:
    if session.get("access") == "dev":
        return
    email = str(session.get("email", "")).strip().casefold()
    if not email:
        return
    user = known_users().get(email)
    if not user:
        return
    session["name"] = user.get("name") or session.get("name") or email
    session["razao_social"] = str(user.get("razao_social", session.get("razao_social", ""))).strip()
    session["access"] = "user" if user.get("active") else "trial"


def start_user_session(email: str, user: dict) -> dict:
    active = bool(user.get("active"))
    role = "user" if active else "trial"
    session.permanent = True
    session["access"] = role
    session["email"] = email
    session["name"] = user.get("name") or email
    session["razao_social"] = str(user.get("razao_social", "")).strip()
    return {
        "ok": True,
        "has_access": True,
        "role": role,
        "email": email,
        "name": session["name"],
        "razao_social": session["razao_social"],
        "razao_locked": bool(session["razao_social"]),
        "payment_required": not active,
        "payment_url": "" if active else payment_link_for(email, session["name"]),
    }


def configured_users() -> dict[str, dict]:
    raw_json = os.environ.get("APP_USERS_JSON", "").strip()
    users: dict[str, dict] = {}
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                parsed = [
                    {"email": email, **(data if isinstance(data, dict) else {})}
                    for email, data in parsed.items()
                ]
            for item in parsed if isinstance(parsed, list) else []:
                if not isinstance(item, dict):
                    continue
                email = str(item.get("email", "")).strip().casefold()
                password = str(item.get("password", ""))
                if email and password:
                    users[email] = {
                        "password": password,
                        "active": bool(item.get("active", True)),
                        "name": str(item.get("name", email)).strip() or email,
                        "razao_social": str(item.get("razao_social", "")).strip(),
                    }
        except json.JSONDecodeError:
            app.logger.warning("APP_USERS_JSON inválido.")

    raw_users = os.environ.get("APP_USERS", "").strip()
    if raw_users:
        for chunk in raw_users.split(","):
            parts = [part.strip() for part in chunk.split(":")]
            if len(parts) < 2:
                continue
            email, password = parts[0].casefold(), parts[1]
            active = len(parts) < 3 or parts[2].casefold() not in {
                "0",
                "false",
                "no",
                "inactive",
                "inativo",
            }
            if email and password:
                users[email] = {"password": password, "active": active, "name": email}
    return users


def has_access() -> bool:
    refresh_session_from_account()
    if session.get("access") in {"dev", "user", "trial"}:
        return True
    return check_pin()


def has_paid_access() -> bool:
    refresh_session_from_account()
    if session.get("access") in {"dev", "user"}:
        return True
    return check_pin()


def access_error():
    return jsonify(
        {
            "ok": False,
            "error": "Faça login para usar o editor.",
            "requires_login": True,
            "payment_url": payment_url(),
        }
    ), 401


def payment_required_error():
    return jsonify(
        {
            "ok": False,
            "error": "É necessário realizar a assinatura para usar o editor.",
            "requires_payment": True,
            "payment_url": payment_link_for(session.get("email", ""), session.get("name", "")),
        }
    ), 402


def error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def crop_photo(source, destination: Path) -> None:
    ratio = 379 / 351
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        width, height = image.size
        if width < 20 or height < 20:
            raise ValueError("Uma das fotos é pequena ou inválida.")
        current = width / height
        if current > ratio:
            new_width = int(height * ratio)
            left = (width - new_width) // 2
            image = image.crop((left, 0, left + new_width, height))
        else:
            new_height = int(width / ratio)
            top = (height - new_height) // 2
            image = image.crop((0, top, width, top + new_height))
        # A proporção 1200 × 1109 acompanha os quadros originais do template
        # (aprox. 1,082:1), evitando qualquer aparência de foto esticada.
        image = image.resize((1200, 1109), Image.Resampling.LANCZOS)
        image.save(destination, "JPEG", quality=94, optimize=True)


def run_worker(payload: dict, job_dir: Path) -> dict:
    payload_file = job_dir / "job.json"
    (job_dir / "home").mkdir(parents=True, exist_ok=True)
    payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    soffice, worker_python = libreoffice_paths()
    payload["soffice"] = soffice
    payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    result = subprocess.run(
        [worker_python, str(WORKER), str(payload_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=150,
        env={**os.environ, "HOME": str(job_dir / "home")},
    )
    parsed = None
    for line in reversed(result.stdout.splitlines()):
        if line.strip().startswith("{"):
            parsed = json.loads(line)
            break
    if not parsed:
        raise RuntimeError(result.stderr.strip() or "O gerador não respondeu.")
    if not parsed.get("ok"):
        raise RuntimeError(parsed.get("error", "Falha ao gerar o PowerPoint."))
    return parsed


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "version": os.environ.get("RENDER_GIT_COMMIT", "")[:7],
            "account_storage": "postgres" if database_url() else "temporary-file",
        }
    )


@app.get("/api/session")
def current_session():
    refresh_session_from_account()
    role = session.get("access", "")
    paid_user = role in {"dev", "user"}
    payment_required = role == "trial"
    razao_social = str(session.get("razao_social", "")).strip()
    return jsonify(
        {
            "ok": True,
            "has_access": role in {"dev", "user", "trial"},
            "role": role,
            "email": session.get("email", ""),
            "name": session.get("name", ""),
            "razao_social": razao_social,
            "razao_locked": bool(razao_social),
            "payment_required": payment_required,
            "payment_url": "" if paid_user else payment_link_for(session.get("email", ""), session.get("name", "")),
        }
    )


@app.post("/api/account-razao")
def account_razao():
    if not has_access():
        return access_error()
    if not has_paid_access():
        return payment_required_error()
    if session.get("access") == "dev":
        body = request.get_json(silent=True) or {}
        razao = str(body.get("razao_social", body.get("razao", ""))).strip()
        session["razao_social"] = razao
        return jsonify({"ok": True, "razao_social": razao, "razao_locked": bool(razao)})

    body = request.get_json(silent=True) or {}
    requested = str(body.get("razao_social", body.get("razao", ""))).strip()
    current = str(session.get("razao_social", "")).strip()
    if current:
        return jsonify({"ok": True, "razao_social": current, "razao_locked": True})
    try:
        saved = save_account_razao(session.get("email", ""), requested)
    except LookupError:
        return error("Nao foi possivel travar a razao social desta conta. Fale com o suporte.", 404)
    except ValueError as exc:
        return error(str(exc))
    session["razao_social"] = saved
    return jsonify({"ok": True, "razao_social": saved, "razao_locked": True})


@app.post("/api/create-subscription")
def create_subscription():
    if not has_access():
        return access_error()
    refresh_session_from_account()
    if has_paid_access():
        return jsonify({"ok": True, "already_active": True})
    email = str(session.get("email", "")).strip().casefold()
    name = str(session.get("name", email)).strip() or email
    if not email:
        return error("Faça login antes de assinar.", 401)
    if payment_url() and not mercadopago_access_token():
        return jsonify({"ok": True, "init_point": payment_link_for(email, name)})
    try:
        amount = plan_amount()
        payload = {
            "reason": plan_title(),
            "external_reference": email,
            "payer_email": email,
            "back_url": public_base_url(),
            "notification_url": f"{public_base_url()}/api/mercadopago/webhook",
            "auto_recurring": {
                "frequency": int(os.environ.get("APP_PLAN_FREQUENCY", "1")),
                "frequency_type": os.environ.get("APP_PLAN_FREQUENCY_TYPE", "months"),
                "transaction_amount": amount,
                "currency_id": os.environ.get("APP_PLAN_CURRENCY", "BRL"),
            },
        }
        created = mp_api("POST", "/preapproval", payload)
    except ValueError as exc:
        return error(str(exc), 500)
    except Exception as exc:
        app.logger.exception("mercadopago subscription creation failed")
        return error(str(exc), 502)

    subscription_id = str(created.get("id", "")).strip()
    if subscription_id:
        set_account_active(
            email,
            False,
            mercadopago_subscription_id=subscription_id,
            payment_status=str(created.get("status", "pending")),
        )
    init_point = created.get("init_point") or created.get("sandbox_init_point")
    if not init_point:
        return error("Mercado Pago não retornou o link da assinatura.", 502)
    return jsonify({"ok": True, "init_point": init_point, "subscription_id": subscription_id})


def email_from_mp_resource(resource: dict) -> str:
    for key in ("external_reference", "payer_email"):
        value = str(resource.get(key, "") or "").strip().casefold()
        if "@" in value:
            return value
    payer = resource.get("payer")
    if isinstance(payer, dict):
        value = str(payer.get("email", "") or "").strip().casefold()
        if "@" in value:
            return value
    metadata = resource.get("metadata")
    if isinstance(metadata, dict):
        value = str(metadata.get("email", "") or "").strip().casefold()
        if "@" in value:
            return value
    return ""


def process_mp_resource(kind: str, resource_id: str) -> dict:
    kind = (kind or "").lower()
    if not resource_id:
        return {"processed": False, "reason": "missing id"}

    if kind in {"preapproval", "subscription_preapproval", "plan", "plans", "plan_subscription"}:
        resource = mp_api("GET", f"/preapproval/{resource_id}")
        email = email_from_mp_resource(resource)
        status = str(resource.get("status", "")).lower()
        active = status in {"authorized", "active"}
        if email:
            set_account_active(
                email,
                active,
                mercadopago_subscription_id=str(resource.get("id", resource_id)),
                payment_status=status,
            )
        return {"processed": True, "kind": "preapproval", "email": email, "status": status, "active": active}

    if kind in {"payment", "payments"}:
        resource = mp_api("GET", f"/v1/payments/{resource_id}")
        email = email_from_mp_resource(resource)
        status = str(resource.get("status", "")).lower()
        active = status == "approved"
        if email and active:
            set_account_active(
                email,
                True,
                mercadopago_payment_id=str(resource.get("id", resource_id)),
                payment_status=status,
            )
        return {"processed": True, "kind": "payment", "email": email, "status": status, "active": active}

    if kind in {"subscription_authorized_payment", "authorized_payment", "authorized_payments"}:
        resource = mp_api("GET", f"/authorized_payments/{resource_id}")
        preapproval_id = str(resource.get("preapproval_id", "") or "").strip()
        if preapproval_id:
            return process_mp_resource("preapproval", preapproval_id)
        email = email_from_mp_resource(resource)
        status = str(resource.get("status", "")).lower()
        active = status in {"processed", "approved", "authorized"}
        if email and active:
            set_account_active(email, True, payment_status=status)
        return {"processed": True, "kind": "authorized_payment", "email": email, "status": status, "active": active}

    return {"processed": False, "kind": kind, "id": resource_id}


@app.post("/api/mercadopago/webhook")
def mercadopago_webhook():
    payload = request.get_json(silent=True) or {}
    if not validate_mp_webhook_signature(payload):
        return error("Assinatura do webhook inválida.", 401)
    kind = str(
        payload.get("type")
        or payload.get("topic")
        or request.args.get("type")
        or request.args.get("topic")
        or ""
    )
    resource_id = webhook_data_id(payload)
    try:
        processed = process_mp_resource(kind, resource_id)
        app.logger.info("mercadopago webhook processed: %s", processed)
    except Exception:
        app.logger.exception("mercadopago webhook failed")
    return jsonify({"ok": True})


@app.post("/api/login")
def login():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().casefold()
    password = str(body.get("password", ""))
    if not email or not password:
        return error("Preencha e-mail e senha.")

    users = known_users()
    user = users.get(email)
    if not user:
        return error(
            "Conta nao encontrada. Se voce criou antes da ultima atualizacao, clique em Criar conta e cadastre novamente.",
            404,
        )
    if not password_matches(password, user["password"]):
        return error("E-mail ou senha incorretos.", 401)
    return jsonify(start_user_session(email, user))


@app.post("/api/signup")
def signup():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    email = str(body.get("email", "")).strip().casefold()
    password = str(body.get("password", ""))
    confirmation = str(body.get("password_confirm", body.get("passwordConfirm", "")))
    if not name or not email or not password:
        return error("Preencha nome, e-mail e senha.")
    if confirmation and not hmac.compare_digest(password, confirmation):
        return error("As senhas não conferem.")
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return error("Informe um e-mail válido.")
    if len(password) < 6:
        return error("Use uma senha com pelo menos 6 caracteres.")

    if known_users().get(email):
        return error("Esta conta ja existe. Use Entrar.", 409)
    try:
        save_registered_user(email, name, password)
    except ValueError as exc:
        return error(str(exc), 409)
    except OSError:
        return error("Nao foi possivel salvar a conta agora. Tente novamente.", 500)

    link = payment_link_for(email, name)
    paid_email = email in paid_email_set()
    session.permanent = True
    session["access"] = "user" if paid_email else "trial"
    session["email"] = email
    session["name"] = name
    session["razao_social"] = ""
    return jsonify(
        {
            "ok": True,
            "has_access": True,
            "role": "user" if paid_email else "trial",
            "email": email,
            "name": name,
            "payment_required": not paid_email,
            "payment_url": "" if paid_email else link,
            "message": (
                "Conta criada com acesso liberado."
                if paid_email
                else "Conta criada. O pagamento fica disponível no topo."
            ),
        }
    )


@app.post("/api/dev-pin")
def dev_pin():
    body = request.get_json(silent=True) or {}
    pin = str(body.get("pin", "")).strip()
    if not check_pin_value(pin):
        return error("PIN incorreto.", 401)
    session.permanent = True
    session["access"] = "dev"
    session["email"] = ""
    session["name"] = "Desenvolvedor"
    return jsonify({"ok": True, "has_access": True, "role": "dev"})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/brand-header/<brand>.png")
def brand_header(brand):
    if brand not in BRAND_FILES:
        return error("Marca inválida.", 404)
    return send_file(BRAND_FILES[brand][1], mimetype="image/png", max_age=3600)


@app.post("/api/parse")
def parse_text():
    if not has_access():
        return access_error()
    if not has_paid_access():
        return payment_required_error()
    body = request.get_json(silent=True) or {}
    values, missing = parse_quick_text(body.get("text", ""))
    return jsonify({"ok": True, "data": values, "missing": missing})


@app.post("/api/import-powerpoint")
def import_existing_powerpoint():
    if not has_access():
        return access_error()
    if not has_paid_access():
        return payment_required_error()
    uploaded = request.files.get("powerpoint")
    if not uploaded or not uploaded.filename:
        return error("Selecione um arquivo PowerPoint .ppt ou .pptx.")
    suffix = Path(uploaded.filename).suffix.casefold()
    if suffix not in {".ppt", ".pptx"}:
        return error("Use um arquivo PowerPoint .ppt ou .pptx.")
    raw = uploaded.read()
    if not raw:
        return error("O PowerPoint selecionado está vazio.")
    try:
        converted_from_legacy = suffix == ".ppt"
        if converted_from_legacy:
            with generation_lock:
                raw = convert_legacy_powerpoint(raw)
        imported = import_powerpoint(raw)
    except ValueError as exc:
        return error(str(exc), 422)
    except Exception:
        app.logger.exception("powerpoint import failed")
        return error("Não foi possível ler este PowerPoint.", 422)
    return jsonify(
        {"ok": True, "converted_from_legacy": converted_from_legacy, **imported}
    )


@app.post("/api/process")
def process():
    if not has_access():
        return access_error()
    if not has_paid_access():
        return payment_required_error()
    brand = request.form.get("brand", "br-sport")
    if brand not in BRAND_FILES:
        return error("Marca inválida.")
    mode = request.form.get("mode", "generate")
    if mode != "generate":
        return error("Operação inválida.")

    raw = request.form.get("text", "")
    supplied = request.form.get("parsed_json", "")
    if supplied:
        try:
            data = json.loads(supplied)
        except json.JSONDecodeError:
            return error("Os dados interpretados são inválidos.")
    else:
        data, _ = parse_quick_text(raw)
    locked_razao = str(session.get("razao_social", "")).strip()
    if locked_razao:
        data["razao"] = locked_razao
    missing = validate_parsed(data)
    if missing:
        return error("Faltam informações: " + "; ".join(missing))

    photos = request.files.getlist("photos")
    if len(photos) != 3:
        return error("Selecione exatamente três fotos.")

    template, header_image, brand_label = BRAND_FILES[brand]
    job_dir = Path(tempfile.mkdtemp(prefix="conquistando-web-"))
    try:
        prepared = []
        for index, uploaded in enumerate(photos, start=1):
            if not uploaded.filename:
                return error(f"A foto {index} está vazia.")
            target = job_dir / f"photo-{index}.jpg"
            try:
                crop_photo(uploaded.stream, target)
            except Exception:
                return error(f"Não foi possível ler a foto {index}.")
            caption = (data.get("fotos") or [{}, {}, {}])[index - 1]
            prepared.append(
                {
                    "arquivo": str(target),
                    "cliente": str(caption.get("cliente", "")),
                    "cidade": str(caption.get("cidade", "")),
                    "pares": str(caption.get("pares", "")),
                }
            )

        code = str(data.get("codigo", "")).strip() or "NOVO"
        safe_code = "".join(char if char.isalnum() or char in "-_" else "-" for char in code)
        output = job_dir / f"{brand_label}_CONQUISTANDO_{safe_code}.pptx"
        payload = {
            **data,
            "fotos": prepared,
            "template": str(template),
            "header_image": str(header_image),
            "output": str(output),
        }
        with generation_lock:
            build_pptx(payload)

        target = output
        content_type = (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        download_name = target.name
        content = target.read_bytes()
        return send_file(
            io.BytesIO(content),
            mimetype=content_type,
            as_attachment=True,
            download_name=download_name,
            max_age=0,
        )
    except subprocess.TimeoutExpired:
        return error("A geração demorou demais. Tente novamente.", 504)
    except Exception as exc:
        app.logger.exception("generation failed")
        return error(str(exc), 500)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


@app.errorhandler(413)
def too_large(_error):
    return error("As fotos ultrapassam o limite total de 40 MB.", 413)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )

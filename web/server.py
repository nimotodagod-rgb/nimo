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
    path = accounts_file()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        app.logger.warning("Arquivo de contas invÃ¡lido ou indisponÃ­vel.")
        return {}
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
    path = accounts_file()
    with accounts_lock:
        users = registered_users()
        if email in users:
            raise ValueError("Esta conta jÃ¡ existe. Use Entrar.")
        users[email] = {
            "email": email,
            "name": name,
            "password_hash": password_hash(password),
            "active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def save_account_razao(email: str, razao: str) -> str:
    normalized_email = str(email or "").strip().casefold()
    normalized_razao = str(razao or "").strip()
    if not normalized_email or not normalized_razao:
        raise ValueError("Informe a razao social.")
    path = accounts_file()
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
        users[normalized_email] = user
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        return user["razao_social"]


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
        users[email] = user
    return users


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
    if session.get("access") in {"dev", "user", "trial"}:
        return True
    return check_pin()


def has_paid_access() -> bool:
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
    return jsonify({"ok": True})


@app.get("/api/session")
def current_session():
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
    session.permanent = True
    session["access"] = "trial"
    session["email"] = email
    session["name"] = name
    session["razao_social"] = ""
    return jsonify(
        {
            "ok": True,
            "has_access": True,
            "role": "trial",
            "email": email,
            "name": name,
            "payment_required": True,
            "payment_url": link,
            "message": "Conta criada. O pagamento fica disponível no topo.",
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

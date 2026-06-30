from __future__ import annotations

import io
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from flask import Flask, jsonify, render_template, request, send_file, session
from PIL import Image, ImageOps

from ooxml_worker import build_pptx
from parser import parse_quick_text, validate_parsed


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
generation_lock = threading.Lock()


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
        image = image.resize((1200, 1111), Image.Resampling.LANCZOS)
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
    return jsonify(
        {
            "ok": True,
            "has_access": role in {"dev", "user", "trial"},
            "role": role,
            "email": session.get("email", ""),
            "name": session.get("name", ""),
            "payment_required": payment_required,
            "payment_url": "" if paid_user else payment_link_for(session.get("email", ""), session.get("name", "")),
        }
    )


@app.post("/api/login")
def login():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().casefold()
    password = str(body.get("password", ""))
    if not email or not password:
        return error("Preencha e-mail e senha.")

    users = configured_users()
    user = users.get(email)
    if user and not hmac.compare_digest(password, user["password"]):
        return error("E-mail ou senha incorretos.", 401)
    if user and user.get("active"):
        session["access"] = "user"
        session["email"] = email
        session["name"] = user.get("name") or email
        return jsonify({"ok": True, "has_access": True, "email": email, "name": session["name"]})

    return jsonify(
        {
            "ok": False,
            "requires_payment": True,
            "payment_url": payment_link_for(email),
            "error": "Acesso ainda não liberado. Faça o pagamento para ativar.",
        }
    ), 402


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

    user = configured_users().get(email)
    if user and user.get("active"):
        return error("Esta conta já está liberada. Use Entrar.", 409)

    link = payment_link_for(email, name)
    session["access"] = "trial"
    session["email"] = email
    session["name"] = name
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

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image, ImageOps

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


def check_pin() -> bool:
    expected = os.environ.get("APP_PIN", "").strip()
    return not expected or request.headers.get("X-App-Pin", "").strip() == expected


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


@app.post("/api/parse")
def parse_text():
    if not check_pin():
        return error("PIN incorreto.", 401)
    body = request.get_json(silent=True) or {}
    values, missing = parse_quick_text(body.get("text", ""))
    return jsonify({"ok": True, "data": values, "missing": missing})


@app.post("/api/process")
def process():
    if not check_pin():
        return error("PIN incorreto.", 401)
    brand = request.form.get("brand", "br-sport")
    if brand not in BRAND_FILES:
        return error("Marca inválida.")
    mode = request.form.get("mode", "preview")
    if mode not in {"preview", "generate"}:
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
        preview_dir = job_dir / "preview"
        payload = {
            **data,
            "fotos": prepared,
            "template": str(template),
            "header_image": str(header_image),
            "output": str(output),
            "preview_dir": str(preview_dir),
        }
        with generation_lock:
            generated = run_worker(payload, job_dir)

        if mode == "preview":
            target = Path(generated["preview_pdf"])
            content_type = "application/pdf"
            download_name = "preview-conquistando.pdf"
        else:
            target = Path(generated["output"])
            content_type = (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            )
            download_name = target.name
        content = target.read_bytes()
        return send_file(
            io.BytesIO(content),
            mimetype=content_type,
            as_attachment=mode == "generate",
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

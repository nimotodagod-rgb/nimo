"""Gera e renderiza o PowerPoint usando a instalação local do LibreOffice."""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import uno

from com.sun.star.awt.FontWeight import BOLD, NORMAL
from com.sun.star.style.ParagraphAdjust import CENTER, LEFT
from com.sun.star.style.LineSpacingMode import PROP
from com.sun.star.drawing.TextVerticalAdjust import TOP


def prop(name, value):
    item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    item.Name = name
    item.Value = value
    return item


def point(x, y):
    value = uno.createUnoStruct("com.sun.star.awt.Point")
    value.X, value.Y = int(x), int(y)
    return value


def size(width, height):
    value = uno.createUnoStruct("com.sun.star.awt.Size")
    value.Width, value.Height = int(width), int(height)
    return value


def file_url(path):
    return uno.systemPathToFileUrl(str(Path(path).resolve()))


def string_of(shape):
    try:
        return str(shape.String or "")
    except Exception:
        return ""


def page_shapes(page):
    return [page.getByIndex(index) for index in range(page.getCount())]


def style_text(shape, font_size, alignment=LEFT):
    text = shape.getText()
    cursor = text.createTextCursor()
    cursor.gotoEnd(True)
    cursor.CharFontName = "Times New Roman"
    cursor.CharHeight = float(font_size)
    cursor.ParaAdjust = alignment
    spacing = uno.createUnoStruct("com.sun.star.style.LineSpacing")
    spacing.Mode = PROP
    spacing.Height = 100
    cursor.ParaLineSpacing = spacing
    try:
        shape.TextVerticalAdjust = TOP
        shape.TextAutoGrowHeight = False
        shape.TextAutoGrowWidth = False
    except Exception:
        pass


def fill_body(shape, values):
    text = shape.getText()
    text.String = ""
    cursor = text.createTextCursor()
    cursor.CharFontName = "Times New Roman"
    cursor.CharHeight = 20.0
    cursor.CharWeight = NORMAL
    labels = ("1.", "2.", "3.")
    for index, (label, value) in enumerate(zip(labels, values), start=1):
        cursor.CharWeight = BOLD
        text.insertString(cursor, label, False)
        cursor.CharWeight = NORMAL
        text.insertString(cursor, f" {str(value).strip()}", False)
        if index != 3:
            text.insertString(cursor, "\n", False)
    style_text(shape, 20, LEFT)


def largest_text_shape(page, minimum_chars=80):
    candidates = []
    for shape in page_shapes(page):
        content = string_of(shape)
        if len(content) < minimum_chars:
            continue
        try:
            area = int(shape.Size.Width) * int(shape.Size.Height)
        except Exception:
            area = len(content)
        candidates.append((area, shape))
    if not candidates:
        raise RuntimeError("Não encontrei a caixa de texto principal do template.")
    return max(candidates, key=lambda item: item[0])[1]


def clean_duplicate_image_title(page):
    matches = []
    for shape in page_shapes(page):
        if string_of(shape).strip().casefold() == "imagens":
            matches.append((int(shape.Size.Width) * int(shape.Size.Height), shape))
    if len(matches) < 2:
        return
    matches.sort(key=lambda item: item[0])
    for _, shape in matches[1:]:
        page.remove(shape)


def caption_shapes(page):
    matches = [shape for shape in page_shapes(page) if "Cliente:" in string_of(shape)]
    return sorted(matches, key=lambda shape: int(shape.Position.X))[:3]


def image_frames(page):
    matches = []
    for shape in page_shapes(page):
        if string_of(shape).strip():
            continue
        try:
            width, height = int(shape.Size.Width), int(shape.Size.Height)
            x = int(shape.Position.X)
        except Exception:
            continue
        if 8_500 <= width <= 11_500 and 7_500 <= height <= 10_500:
            matches.append((x, shape))
    return [shape for _, shape in sorted(matches, key=lambda item: item[0])[:3]]


def add_rectangle(doc, page, x, y, width, height, color):
    shape = doc.createInstance("com.sun.star.drawing.RectangleShape")
    shape.Position = point(x, y)
    shape.Size = size(width, height)
    shape.FillColor = int(color)
    shape.FillTransparence = 0
    shape.LineTransparence = 100
    page.add(shape)
    return shape


def add_text(
    doc,
    page,
    value,
    x,
    y,
    width,
    height,
    font_size=12.5,
    bold=False,
    font_name="Arial",
):
    shape = doc.createInstance("com.sun.star.drawing.TextShape")
    shape.Position = point(x, y)
    shape.Size = size(width, height)
    shape.FillTransparence = 100
    shape.LineTransparence = 100
    page.add(shape)
    shape.String = value
    cursor = shape.getText().createTextCursor()
    cursor.gotoEnd(True)
    cursor.CharFontName = font_name
    cursor.CharHeight = float(font_size)
    cursor.CharWeight = BOLD if bold else NORMAL
    cursor.ParaAdjust = CENTER
    shape.TextVerticalAdjust = TOP
    return shape


def add_graphic(doc, page, image_path, x, y, width, height, context):
    provider = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.graphic.GraphicProvider", context
    )
    graphic = provider.queryGraphic((prop("URL", file_url(image_path)),))
    picture = doc.createInstance("com.sun.star.drawing.GraphicObjectShape")
    picture.Position = point(x, y)
    picture.Size = size(width, height)
    picture.Graphic = graphic
    page.add(picture)
    return picture


def rebuild_image_header(doc, image_page, header_image, context):
    # O cabeçalho do slide de imagens do .ppt antigo possui transparências que
    # ficam pretas na conversão. Reaproveitamos os logos autênticos do slide 2.
    add_rectangle(doc, image_page, 0, 0, 33_867, 2_650, 0xFFFFFF)
    add_graphic(doc, image_page, header_image, 0, 0, 33_867, 2_540, context)
    add_rectangle(doc, image_page, 11_800, 430, 9_100, 1_550, 0xFFFFFF)
    add_text(
        doc,
        image_page,
        "Imagens",
        12_300,
        770,
        8_250,
        1_150,
        18,
        False,
        "Segoe UI Semibold",
    )


def add_header(doc, page, data):
    code = str(data.get("codigo", "")).strip() or "cód."
    reason = str(data.get("razao", "")).strip() or "razão"
    regional = str(data.get("regional", "")).strip() or "SPO"
    micro = str(data.get("microrregiao", "")).strip() or "microrregião"

    # Cobre o texto-modelo original, preservando o restante do cabeçalho.
    add_rectangle(doc, page, 20_550, 260, 7_650, 1_710, 0xFFFFFF)
    add_rectangle(doc, page, 20_650, 430, 7_450, 620, 0xFFF200)
    add_rectangle(doc, page, 20_650, 1_070, 7_450, 620, 0xFFF200)
    add_text(doc, page, f"{code} – {reason}", 20_650, 440, 7_450, 570, 8.5, True)
    add_text(doc, page, f"{regional} – {micro}", 20_650, 1_080, 7_450, 570, 10.5, False)


def add_photo(doc, page, frame, photo_path, context):
    if not photo_path or not Path(photo_path).is_file():
        return
    provider = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.graphic.GraphicProvider", context
    )
    graphic = provider.queryGraphic((prop("URL", file_url(photo_path)),))
    picture = doc.createInstance("com.sun.star.drawing.GraphicObjectShape")
    inset = 28
    picture.Position = point(frame.Position.X + inset, frame.Position.Y + inset)
    picture.Size = size(frame.Size.Width - inset * 2, frame.Size.Height - inset * 2)
    picture.Graphic = graphic
    page.add(picture)


def export_page(context, page, output_path):
    target = Path(output_path)
    if target.exists():
        target.unlink()
    exporter = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.drawing.GraphicExportFilter", context
    )
    exporter.setSourceDocument(page)
    filter_data = (
        prop("PixelWidth", 1280),
        prop("PixelHeight", 720),
        prop("Translucent", False),
    )
    exporter.filter(
        (
            prop("URL", file_url(output_path)),
            prop("MediaType", "image/png"),
            prop("FilterData", filter_data),
        )
    )


def connect_office(soffice_path):
    port = random.randint(20_000, 49_000)
    profile = Path(tempfile.mkdtemp(prefix="conquistando-lo-"))
    log_path = profile / "soffice.log"
    accept = f"socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(
            [
                soffice_path,
                f"-env:UserInstallation={file_url(profile)}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--norestore",
                "--nofirststartwizard",
                f"--accept={accept}",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_context
    )
    last_error = None
    # A primeira inicialização no Render Free (CPU compartilhada) pode levar
    # bem mais que os poucos segundos necessários em um computador local.
    for _ in range(450):
        try:
            context = resolver.resolve(
                f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
            )
            return process, profile, context
        except Exception as error:
            last_error = error
            if process.poll() is not None:
                break
            time.sleep(0.1)
    if process.poll() is None:
        process.terminate()
    try:
        details = log_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        details = ""
    reason = details or str(last_error)
    shutil.rmtree(profile, ignore_errors=True)
    raise RuntimeError(f"Não foi possível iniciar o LibreOffice: {reason}")


def build(payload):
    process, profile, context = connect_office(payload["soffice"])
    document = None
    try:
        desktop = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", context
        )
        document = desktop.loadComponentFromURL(
            file_url(payload["template"]),
            "_blank",
            0,
            (prop("Hidden", True), prop("ReadOnly", False), prop("Silent", True)),
        )
        if document is None:
            raise RuntimeError("O LibreOffice não conseguiu abrir o template.")

        pages = document.getDrawPages()
        if pages.getCount() != 5:
            raise RuntimeError("O template deveria conter exatamente 5 slides.")

        page_actions = pages.getByIndex(1)
        page_improvements = pages.getByIndex(2)
        page_images = pages.getByIndex(4)

        fill_body(
            largest_text_shape(page_actions),
            (
                payload["acoes"]["vendas"],
                payload["acoes"]["marketing"],
                payload["acoes"]["carteira"],
            ),
        )
        fill_body(
            largest_text_shape(page_improvements),
            (
                payload["melhorias"]["vendas"],
                payload["melhorias"]["marketing"],
                payload["melhorias"]["carteira"],
            ),
        )

        clean_duplicate_image_title(page_images)
        rebuild_image_header(document, page_images, payload["header_image"], context)
        captions = caption_shapes(page_images)
        frames = image_frames(page_images)
        if len(captions) != 3 or len(frames) != 3:
            raise RuntimeError("Não encontrei os três espaços de fotos/legendas no template.")

        for index, item in enumerate(payload["fotos"][:3]):
            captions[index].String = (
                f"Cliente: {str(item.get('cliente', '')).strip()}\n"
                f"Cidade: {str(item.get('cidade', '')).strip()}\n"
                f"Pares: {str(item.get('pares', '')).strip()}"
            )
            style_text(captions[index], 12, LEFT)
            add_photo(document, page_images, frames[index], item.get("arquivo"), context)

        for page in (page_actions, page_improvements, page_images):
            add_header(document, page, payload)

        # Slides 1 e 4 são apenas instruções e não aparecem no arquivo final.
        pages.remove(pages.getByIndex(3))
        pages.remove(pages.getByIndex(0))

        output_path = Path(payload["output"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()
        stale_lock = output_path.parent / f".~lock.{output_path.name}#"
        if stale_lock.exists():
            stale_lock.unlink()
        document.storeAsURL(
            file_url(output_path),
            (
                prop("FilterName", "Impress MS PowerPoint 2007 XML"),
                prop("Overwrite", True),
            ),
        )

        preview_paths = []
        preview_pdf = ""
        preview_dir = payload.get("preview_dir")
        if preview_dir:
            preview_root = Path(preview_dir).resolve()
            preview_root.mkdir(parents=True, exist_ok=True)
            pdf_target = preview_root / "preview.pdf"
            if pdf_target.exists():
                pdf_target.unlink()
            document.storeToURL(
                file_url(pdf_target),
                (
                    prop("FilterName", "impress_pdf_Export"),
                    prop("Overwrite", True),
                ),
            )
            preview_pdf = str(pdf_target)

        return {
            "ok": True,
            "output": str(output_path),
            "previews": preview_paths,
            "preview_pdf": preview_pdf,
        }
    finally:
        if document is not None:
            try:
                document.close(True)
            except Exception:
                try:
                    document.dispose()
                except Exception:
                    pass
        try:
            context.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", context
            ).terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except Exception:
            process.terminate()
        shutil.rmtree(profile, ignore_errors=True)


def main():
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        result = build(payload)
    except Exception as error:
        result = {"ok": False, "error": str(error), "traceback": traceback.format_exc()}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

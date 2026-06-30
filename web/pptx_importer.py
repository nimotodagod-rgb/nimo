from __future__ import annotations

import base64
import io
import posixpath
import re
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from PIL import Image, ImageOps

from parser import empty_result, normalize, validate_parsed


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _shape_text(shape: ET.Element) -> str:
    return "\n".join(
        "".join((node.text or "") for node in paragraph.findall(".//a:t", NS))
        for paragraph in shape.findall("./p:txBody/a:p", NS)
    )


def _shape_name(shape: ET.Element) -> str:
    node = shape.find("./p:nvSpPr/p:cNvPr", NS)
    if node is None:
        node = shape.find("./p:nvPicPr/p:cNvPr", NS)
    return node.get("name", "") if node is not None else ""


def _shape_bounds(shape: ET.Element) -> tuple[int, int, int, int]:
    transform = shape.find("./p:spPr/a:xfrm", NS)
    if transform is None:
        return 0, 0, 0, 0
    offset = transform.find("a:off", NS)
    extent = transform.find("a:ext", NS)
    if offset is None or extent is None:
        return 0, 0, 0, 0
    return (
        int(offset.get("x", "0")),
        int(offset.get("y", "0")),
        int(extent.get("cx", "0")),
        int(extent.get("cy", "0")),
    )


def _paragraph_segments(paragraph: ET.Element) -> list[tuple[str, bool]]:
    segments: list[tuple[str, bool]] = []
    for run in paragraph.findall("./a:r", NS):
        text = "".join((node.text or "") for node in run.findall("./a:t", NS))
        props = run.find("./a:rPr", NS)
        bold = props is not None and props.get("b", "0").casefold() in {"1", "true"}
        if text:
            segments.append((text, bold))
    for field in paragraph.findall("./a:fld", NS):
        text = "".join((node.text or "") for node in field.findall("./a:t", NS))
        if text:
            segments.append((text, False))
    return segments


def _marked_text_after(segments: list[tuple[str, bool]], start: int) -> str:
    remaining: list[tuple[str, bool]] = []
    consumed = 0
    for text, bold in segments:
        end = consumed + len(text)
        if end > start:
            remaining.append((text[max(0, start - consumed) :], bold))
        consumed = end
    if not remaining:
        return ""
    remaining[0] = (remaining[0][0].lstrip(), remaining[0][1])
    remaining[-1] = (remaining[-1][0].rstrip(), remaining[-1][1])
    merged: list[tuple[str, bool]] = []
    for text, bold in remaining:
        if not text:
            continue
        if merged and merged[-1][1] == bold:
            merged[-1] = (merged[-1][0] + text, bold)
        else:
            merged.append((text, bold))
    return "".join(f"**{text}**" if bold else text for text, bold in merged).strip()


def _extract_rows(
    shape: ET.Element,
    labels: list[tuple[re.Pattern[str], str]],
) -> dict[str, str]:
    values: dict[str, str] = {}
    paragraphs = shape.findall("./p:txBody/a:p", NS)
    for paragraph in paragraphs:
        segments = _paragraph_segments(paragraph)
        plain = "".join(text for text, _bold in segments)
        for pattern, key in labels:
            match = pattern.match(plain)
            if match:
                values[key] = _marked_text_after(segments, match.end())
                break
    if len(values) == len(labels):
        return values

    plain = "\n".join(_shape_text(shape).splitlines())
    matches: list[tuple[int, int, str]] = []
    for pattern, key in labels:
        for match in pattern.finditer(plain):
            matches.append((match.start(), match.end(), key))
    matches.sort()
    for index, (_start, end, key) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(plain)
        values[key] = plain[end:next_start].strip()
    return values


BODY_LABELS = [
    (re.compile(r"\s*VENDAS?\s*:\s*", re.IGNORECASE), "vendas"),
    (re.compile(r"\s*(?:MKT|MARKETING)\s*:\s*", re.IGNORECASE), "marketing"),
    (
        re.compile(r"\s*CARTEIRA(?:\s+DE\s+CLIENTES?)?\s*:\s*", re.IGNORECASE),
        "carteira",
    ),
]
CAPTION_LABELS = [
    (re.compile(r"\s*CLIENTE\s*:\s*", re.IGNORECASE), "cliente"),
    (re.compile(r"\s*CIDADE\s*:\s*", re.IGNORECASE), "cidade"),
    (re.compile(r"\s*PARES\s*:\s*", re.IGNORECASE), "pares"),
]


def _main_body(root: ET.Element) -> ET.Element | None:
    candidates = []
    for shape in root.findall(".//p:sp", NS):
        text = normalize(_shape_text(shape))
        if "vendas:" not in text or "mkt:" not in text or "carteira" not in text:
            continue
        _x, _y, width, height = _shape_bounds(shape)
        candidates.append((width * height, shape))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def _split_header(value: str) -> tuple[str, str]:
    parts = re.split(r"\s+[–—-]\s+", str(value or "").strip(), maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ("", "")


def _extract_header(slides: list[tuple[str, ET.Element]]) -> dict[str, str]:
    result = {"codigo": "", "razao": "", "regional": "", "microrregiao": ""}
    for _name, root in slides:
        top_shapes = []
        for shape in root.findall(".//p:sp", NS):
            x, y, width, height = _shape_bounds(shape)
            if x < 6_000_000 or y > 1_100_000 or not width or not height:
                continue
            text = _shape_text(shape).strip()
            if text:
                top_shapes.append((y, x, normalize(_shape_name(shape)), text))
        for _y, _x, name, text in sorted(top_shapes):
            if "codigo e razao" in name:
                result["codigo"], result["razao"] = _split_header(text)
            elif "regional e microrregiao" in name:
                result["regional"], result["microrregiao"] = _split_header(text)
        if all(result.values()):
            return result

        dashed = [item for item in sorted(top_shapes) if _split_header(item[3]) != ("", "")]
        if len(dashed) >= 2:
            if not result["codigo"]:
                result["codigo"], result["razao"] = _split_header(dashed[0][3])
            if not result["regional"]:
                result["regional"], result["microrregiao"] = _split_header(dashed[1][3])
            return result
    return result


def _relationship_map(archive: ZipFile, slide_name: str) -> dict[str, str]:
    slide_path = PurePosixPath(slide_name)
    rels_name = str(slide_path.parent / "_rels" / f"{slide_path.name}.rels")
    if rels_name not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read(rels_name))
    return {
        node.get("Id", ""): node.get("Target", "")
        for node in root.findall("./pr:Relationship", NS)
    }


def _photo_payload(raw: bytes, index: int) -> dict[str, str]:
    with Image.open(io.BytesIO(raw)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, "JPEG", quality=91, optimize=True)
    return {
        "name": f"foto-importada-{index}.jpg",
        "type": "image/jpeg",
        "data": base64.b64encode(output.getvalue()).decode("ascii"),
    }


def _extract_photos(
    archive: ZipFile,
    slide_name: str,
    root: ET.Element,
) -> list[dict[str, str]]:
    relationships = _relationship_map(archive, slide_name)
    found = []
    for picture in root.findall(".//p:pic", NS):
        name = _shape_name(picture)
        match = re.search(r"Foto\s+Conquistando\s+([123])", name, re.IGNORECASE)
        x, y, width, height = _shape_bounds(picture)
        if not match and not (y > 1_000_000 and width > 2_000_000 and height > 2_000_000):
            continue
        blip = picture.find("./p:blipFill/a:blip", NS)
        relation_id = blip.get(f"{{{NS['r']}}}embed", "") if blip is not None else ""
        target = relationships.get(relation_id, "")
        if not target:
            continue
        media_name = posixpath.normpath(posixpath.join("ppt/slides", target))
        if media_name not in archive.namelist():
            continue
        order = int(match.group(1)) if match else len(found) + 1
        found.append((order, x, archive.read(media_name)))
    payload = []
    for index, (_order, _x, raw) in enumerate(sorted(found)[:3], start=1):
        try:
            payload.append(_photo_payload(raw, index))
        except Exception:
            continue
    return payload


def import_powerpoint(raw: bytes) -> dict:
    try:
        archive = ZipFile(io.BytesIO(raw))
    except BadZipFile as error:
        raise ValueError("O arquivo não é um PowerPoint .pptx válido.") from error

    with archive:
        entries = archive.infolist()
        if len(entries) > 2_000 or sum(item.file_size for item in entries) > 160 * 1024 * 1024:
            raise ValueError("Este PowerPoint é grande demais para ser importado com segurança.")
        names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=lambda name: int(re.search(r"\d+", name).group()),
        )
        if not names:
            raise ValueError("Não encontrei slides editáveis neste PowerPoint.")
        slides = [(name, ET.fromstring(archive.read(name))) for name in names]
        data = empty_result()
        action_slide = None
        improvement_slide = None
        image_slide = None

        for name, root in slides:
            text = normalize("\n".join(_shape_text(shape) for shape in root.findall(".//p:sp", NS)))
            if "acoes bem sucedidas" in text or "acoes bem-sucedidas" in text:
                action_slide = (name, root)
            elif "pontos de melhoria" in text or "ponto de melhoria" in text:
                improvement_slide = (name, root)
            if "cliente:" in text and "cidade:" in text and "pares:" in text:
                image_slide = (name, root)

        for target, slide in (("acoes", action_slide), ("melhorias", improvement_slide)):
            if not slide:
                continue
            body = _main_body(slide[1])
            if body is not None:
                data[target].update(_extract_rows(body, BODY_LABELS))

        if image_slide:
            captions = []
            for shape in image_slide[1].findall(".//p:sp", NS):
                text = normalize(_shape_text(shape))
                if "cliente:" not in text or "cidade:" not in text or "pares:" not in text:
                    continue
                x, _y, _width, _height = _shape_bounds(shape)
                captions.append((x, _extract_rows(shape, CAPTION_LABELS)))
            for index, (_x, caption) in enumerate(sorted(captions)[:3]):
                data["fotos"][index].update(caption)

        data.update(_extract_header(slides))
        photos = _extract_photos(archive, *image_slide) if image_slide else []
        missing = validate_parsed(data)
        recovered = sum(
            bool(str(data[section][field]).strip())
            for section in ("acoes", "melhorias")
            for field in ("vendas", "marketing", "carteira")
        )
        if not recovered:
            raise ValueError(
                "Não reconheci os campos deste arquivo. Use um .pptx gerado pelo Editor Conquistando."
            )
        return {
            "data": data,
            "missing": missing,
            "photos": photos,
            "photo_count": len(photos),
        }

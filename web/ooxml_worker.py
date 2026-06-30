"""Gera o PPTX final editando diretamente o pacote OOXML.

Este motor é usado na versão web para evitar o alto consumo de memória do
LibreOffice. O executável do Windows continua usando o motor UNO original.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
}
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
for prefix in ("a", "p", "r"):
    ET.register_namespace(prefix, NS[prefix])
ET.register_namespace("", NS["pr"])


def q(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def shape_text(shape: ET.Element) -> str:
    return "\n".join((node.text or "") for node in shape.findall(".//a:t", NS))


def shape_id(shape: ET.Element) -> int:
    node = shape.find("./p:nvSpPr/p:cNvPr", NS)
    if node is None:
        node = shape.find("./p:nvPicPr/p:cNvPr", NS)
    return int(node.get("id", "0")) if node is not None else 0


def shape_bounds(shape: ET.Element) -> tuple[int, int, int, int]:
    xfrm = shape.find("./p:spPr/a:xfrm", NS)
    if xfrm is None:
        return 0, 0, 0, 0
    off = xfrm.find("a:off", NS)
    ext = xfrm.find("a:ext", NS)
    if off is None or ext is None:
        return 0, 0, 0, 0
    return (
        int(off.get("x", "0")),
        int(off.get("y", "0")),
        int(ext.get("cx", "0")),
        int(ext.get("cy", "0")),
    )


def expand_body_box(shape: ET.Element) -> None:
    """Sobe discretamente o texto e amplia a área sem alterar a tipografia."""
    xfrm = shape.find("./p:spPr/a:xfrm", NS)
    if xfrm is None:
        return
    off = xfrm.find("a:off", NS)
    ext = xfrm.find("a:ext", NS)
    if off is not None:
        off.set("y", "1240000")
    if ext is not None:
        ext.set("cy", "5000000")


def expand_caption_box(shape: ET.Element) -> None:
    """Mantém fonte 14 e aumenta a altura da legenda para evitar corte."""
    xfrm = shape.find("./p:spPr/a:xfrm", NS)
    if xfrm is None:
        return
    ext = xfrm.find("a:ext", NS)
    if ext is not None:
        ext.set("cy", str(max(int(ext.get("cy", "0")), 1_250_000)))


def max_shape_id(root: ET.Element) -> int:
    values = [
        int(node.get("id", "0"))
        for node in root.findall(".//p:cNvPr", NS)
        if node.get("id", "0").isdigit()
    ]
    return max(values, default=1)


def add_run(
    paragraph: ET.Element,
    text: str,
    *,
    size: int,
    bold: bool,
    font: str = "Times New Roman",
    align: str | None = None,
) -> None:
    run = ET.SubElement(paragraph, q("a", "r"))
    attrs = {"lang": "pt-BR", "sz": str(size), "b": "1" if bold else "0", "dirty": "0"}
    run_props = ET.SubElement(run, q("a", "rPr"), attrs)
    ET.SubElement(run_props, q("a", "solidFill")).append(
        ET.Element(q("a", "srgbClr"), {"val": "000000"})
    )
    ET.SubElement(run_props, q("a", "latin"), {"typeface": font})
    ET.SubElement(run_props, q("a", "ea"), {"typeface": font})
    ET.SubElement(run_props, q("a", "cs"), {"typeface": font})
    text_node = ET.SubElement(run, q("a", "t"))
    if text[:1].isspace() or text[-1:].isspace():
        text_node.set(XML_SPACE, "preserve")
    text_node.text = text


def replace_text_rows(
    shape: ET.Element,
    rows: list[tuple[str, str]],
    *,
    size: int,
    bold_labels: bool,
    blank_between: bool = False,
) -> None:
    body = shape.find("./p:txBody", NS)
    if body is None:
        raise RuntimeError("A caixa de texto do template não possui conteúdo editável.")
    body_props = body.find("./a:bodyPr", NS)
    if body_props is not None:
        body_props.set("anchor", "t")
        body_props.set("wrap", "square")
    for paragraph in list(body.findall("./a:p", NS)):
        body.remove(paragraph)
    for index, (label, value) in enumerate(rows):
        paragraph = ET.SubElement(body, q("a", "p"))
        p_props = ET.SubElement(paragraph, q("a", "pPr"), {"algn": "l"})
        line_spacing = ET.SubElement(p_props, q("a", "lnSpc"))
        ET.SubElement(line_spacing, q("a", "spcPct"), {"val": "100000"})
        add_run(paragraph, label, size=size, bold=bold_labels)
        add_run(paragraph, f" {str(value).strip()}", size=size, bold=False)
        end = ET.SubElement(paragraph, q("a", "endParaRPr"), {"lang": "pt-BR", "sz": str(size)})
        ET.SubElement(end, q("a", "latin"), {"typeface": "Times New Roman"})
        if blank_between and index != len(rows) - 1:
            spacer = ET.SubElement(body, q("a", "p"))
            spacer_props = ET.SubElement(spacer, q("a", "pPr"), {"algn": "l"})
            spacer_line = ET.SubElement(spacer_props, q("a", "lnSpc"))
            ET.SubElement(spacer_line, q("a", "spcPct"), {"val": "100000"})
            spacer_end = ET.SubElement(
                spacer, q("a", "endParaRPr"), {"lang": "pt-BR", "sz": str(size)}
            )
            ET.SubElement(spacer_end, q("a", "latin"), {"typeface": "Times New Roman"})


def add_rectangle(
    sp_tree: ET.Element,
    next_id: int,
    *,
    name: str,
    x: int,
    y: int,
    width: int,
    height: int,
    color: str,
) -> int:
    shape = ET.SubElement(sp_tree, q("p", "sp"))
    non_visual = ET.SubElement(shape, q("p", "nvSpPr"))
    ET.SubElement(non_visual, q("p", "cNvPr"), {"id": str(next_id), "name": name})
    ET.SubElement(non_visual, q("p", "cNvSpPr"))
    ET.SubElement(non_visual, q("p", "nvPr"))
    props = ET.SubElement(shape, q("p", "spPr"))
    transform = ET.SubElement(props, q("a", "xfrm"))
    ET.SubElement(transform, q("a", "off"), {"x": str(x), "y": str(y)})
    ET.SubElement(transform, q("a", "ext"), {"cx": str(width), "cy": str(height)})
    geometry = ET.SubElement(props, q("a", "prstGeom"), {"prst": "rect"})
    ET.SubElement(geometry, q("a", "avLst"))
    fill = ET.SubElement(props, q("a", "solidFill"))
    ET.SubElement(fill, q("a", "srgbClr"), {"val": color})
    line = ET.SubElement(props, q("a", "ln"))
    ET.SubElement(line, q("a", "noFill"))
    body = ET.SubElement(shape, q("p", "txBody"))
    ET.SubElement(body, q("a", "bodyPr"))
    ET.SubElement(body, q("a", "lstStyle"))
    ET.SubElement(body, q("a", "p"))
    return next_id + 1


def add_textbox(
    sp_tree: ET.Element,
    next_id: int,
    *,
    name: str,
    text: str,
    x: int,
    y: int,
    width: int,
    height: int,
    size: int,
    bold: bool = False,
    font: str = "Arial",
) -> int:
    shape = ET.SubElement(sp_tree, q("p", "sp"))
    non_visual = ET.SubElement(shape, q("p", "nvSpPr"))
    ET.SubElement(non_visual, q("p", "cNvPr"), {"id": str(next_id), "name": name})
    ET.SubElement(non_visual, q("p", "cNvSpPr"), {"txBox": "1"})
    ET.SubElement(non_visual, q("p", "nvPr"))
    props = ET.SubElement(shape, q("p", "spPr"))
    transform = ET.SubElement(props, q("a", "xfrm"))
    ET.SubElement(transform, q("a", "off"), {"x": str(x), "y": str(y)})
    ET.SubElement(transform, q("a", "ext"), {"cx": str(width), "cy": str(height)})
    geometry = ET.SubElement(props, q("a", "prstGeom"), {"prst": "rect"})
    ET.SubElement(geometry, q("a", "avLst"))
    ET.SubElement(props, q("a", "noFill"))
    line = ET.SubElement(props, q("a", "ln"))
    ET.SubElement(line, q("a", "noFill"))
    body = ET.SubElement(shape, q("p", "txBody"))
    ET.SubElement(
        body,
        q("a", "bodyPr"),
        {
            "anchor": "ctr",
            "wrap": "none",
            "lIns": "0",
            "rIns": "0",
            "tIns": "0",
            "bIns": "0",
        },
    )
    ET.SubElement(body, q("a", "lstStyle"))
    paragraph = ET.SubElement(body, q("a", "p"))
    ET.SubElement(paragraph, q("a", "pPr"), {"algn": "ctr"})
    add_run(paragraph, text, size=size, bold=bold, font=font)
    ET.SubElement(paragraph, q("a", "endParaRPr"), {"lang": "pt-BR", "sz": str(size)})
    return next_id + 1


def next_relationship_id(rels_root: ET.Element) -> str:
    numbers = []
    for rel in rels_root:
        value = rel.get("Id", "")
        if value.startswith("rId") and value[3:].isdigit():
            numbers.append(int(value[3:]))
    return f"rId{max(numbers, default=0) + 1}"


def add_image_relationship(rels_root: ET.Element, target: str) -> str:
    relation_id = next_relationship_id(rels_root)
    ET.SubElement(
        rels_root,
        q("pr", "Relationship"),
        {
            "Id": relation_id,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": target,
        },
    )
    return relation_id


def add_picture(
    sp_tree: ET.Element,
    next_id: int,
    *,
    name: str,
    relation_id: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> int:
    picture = ET.SubElement(sp_tree, q("p", "pic"))
    non_visual = ET.SubElement(picture, q("p", "nvPicPr"))
    ET.SubElement(non_visual, q("p", "cNvPr"), {"id": str(next_id), "name": name})
    locks = ET.SubElement(non_visual, q("p", "cNvPicPr"))
    ET.SubElement(locks, q("a", "picLocks"), {"noChangeAspect": "1"})
    ET.SubElement(non_visual, q("p", "nvPr"))
    fill = ET.SubElement(picture, q("p", "blipFill"))
    ET.SubElement(fill, q("a", "blip"), {q("r", "embed"): relation_id})
    stretch = ET.SubElement(fill, q("a", "stretch"))
    ET.SubElement(stretch, q("a", "fillRect"))
    props = ET.SubElement(picture, q("p", "spPr"))
    transform = ET.SubElement(props, q("a", "xfrm"))
    ET.SubElement(transform, q("a", "off"), {"x": str(x), "y": str(y)})
    ET.SubElement(transform, q("a", "ext"), {"cx": str(width), "cy": str(height)})
    geometry = ET.SubElement(props, q("a", "prstGeom"), {"prst": "rect"})
    ET.SubElement(geometry, q("a", "avLst"))
    return next_id + 1


def add_identification_header(root: ET.Element, data: dict) -> None:
    sp_tree = root.find(".//p:spTree", NS)
    if sp_tree is None:
        raise RuntimeError("Estrutura do slide não encontrada.")
    next_id = max_shape_id(root) + 1
    next_id = add_rectangle(
        sp_tree,
        next_id,
        name="Cobertura do cabeçalho",
        x=7_398_000,
        y=93_600,
        width=2_754_000,
        height=615_600,
        color="FFFFFF",
    )
    next_id = add_rectangle(
        sp_tree,
        next_id,
        name="Identificação amarela 1",
        x=7_434_000,
        y=154_800,
        width=2_682_000,
        height=223_200,
        color="FFF200",
    )
    next_id = add_rectangle(
        sp_tree,
        next_id,
        name="Identificação amarela 2",
        x=7_434_000,
        y=385_200,
        width=2_682_000,
        height=223_200,
        color="FFF200",
    )
    code = str(data.get("codigo", "")).strip() or "cód."
    reason = str(data.get("razao", "")).strip() or "razão"
    regional = str(data.get("regional", "")).strip() or "regional"
    micro = str(data.get("microrregiao", "")).strip() or "microrregião"
    next_id = add_textbox(
        sp_tree,
        next_id,
        name="Código e razão",
        text=f"{code} – {reason}",
        x=7_434_000,
        y=158_400,
        width=2_682_000,
        height=205_200,
        size=850,
        bold=True,
    )
    add_textbox(
        sp_tree,
        next_id,
        name="Regional e microrregião",
        text=f"{regional} – {micro}",
        x=7_434_000,
        y=388_800,
        width=2_682_000,
        height=205_200,
        size=1050,
    )


def remove_duplicate_image_title(root: ET.Element) -> None:
    sp_tree = root.find(".//p:spTree", NS)
    if sp_tree is None:
        return
    matches = []
    for shape in sp_tree.findall("./p:sp", NS):
        if shape_text(shape).strip().casefold() == "imagens":
            _, _, width, height = shape_bounds(shape)
            matches.append((width * height, shape))
    for _, shape in sorted(matches, key=lambda item: item[0])[1:]:
        sp_tree.remove(shape)


def serialize(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def ensure_content_type(files: dict[str, bytes], extension: str, content_type: str) -> None:
    root = ET.fromstring(files["[Content_Types].xml"])
    if any(
        node.get("Extension", "").casefold() == extension.casefold()
        for node in root.findall("./ct:Default", NS)
    ):
        return
    ET.SubElement(
        root,
        q("ct", "Default"),
        {"Extension": extension, "ContentType": content_type},
    )
    files["[Content_Types].xml"] = serialize(root)


def keep_final_slides(files: dict[str, bytes]) -> None:
    root = ET.fromstring(files["ppt/presentation.xml"])
    slide_list = root.find("./p:sldIdLst", NS)
    if slide_list is None or len(slide_list) < 5:
        raise RuntimeError("O template deveria conter exatamente cinco slides.")
    original = list(slide_list)
    for node in original:
        slide_list.remove(node)
    for index in (1, 2, 4):
        slide_list.append(deepcopy(original[index]))
    files["ppt/presentation.xml"] = serialize(root)

    app_name = "docProps/app.xml"
    if app_name in files:
        app_root = ET.fromstring(files[app_name])
        slides = app_root.find("./ep:Slides", NS)
        if slides is not None:
            slides.text = "3"
        files[app_name] = serialize(app_root)


def build_pptx(payload: dict) -> str:
    template = Path(payload["template"])
    output = Path(payload["output"])
    if not template.is_file():
        raise RuntimeError("Template do PowerPoint não encontrado.")

    with ZipFile(template) as source:
        files = {item.filename: source.read(item.filename) for item in source.infolist()}

    slide2 = ET.fromstring(files["ppt/slides/slide2.xml"])
    slide3 = ET.fromstring(files["ppt/slides/slide3.xml"])
    slide5 = ET.fromstring(files["ppt/slides/slide5.xml"])

    action_shape = max(
        (
            shape
            for shape in slide2.findall(".//p:sp", NS)
            if "VENDAS:" in shape_text(shape)
        ),
        key=lambda shape: shape_bounds(shape)[2] * shape_bounds(shape)[3],
    )
    improvement_shape = max(
        (
            shape
            for shape in slide3.findall(".//p:sp", NS)
            if "VENDAS:" in shape_text(shape)
        ),
        key=lambda shape: shape_bounds(shape)[2] * shape_bounds(shape)[3],
    )
    expand_body_box(action_shape)
    expand_body_box(improvement_shape)
    replace_text_rows(
        action_shape,
        [
            ("1.", payload["acoes"]["vendas"]),
            ("2.", payload["acoes"]["marketing"]),
            ("3.", payload["acoes"]["carteira"]),
        ],
        size=2000,
        bold_labels=True,
        blank_between=True,
    )
    replace_text_rows(
        improvement_shape,
        [
            ("1.", payload["melhorias"]["vendas"]),
            ("2.", payload["melhorias"]["marketing"]),
            ("3.", payload["melhorias"]["carteira"]),
        ],
        size=2000,
        bold_labels=True,
        blank_between=True,
    )

    remove_duplicate_image_title(slide5)
    frames = sorted(
        (
            shape
            for shape in slide5.findall(".//p:sp", NS)
            if not shape_text(shape).strip()
            and 3_500_000 <= shape_bounds(shape)[2] <= 3_700_000
            and 3_250_000 <= shape_bounds(shape)[3] <= 3_450_000
        ),
        key=lambda shape: shape_bounds(shape)[0],
    )[:3]
    captions = sorted(
        (
            shape
            for shape in slide5.findall(".//p:sp", NS)
            if "Cliente:" in shape_text(shape)
        ),
        key=lambda shape: shape_bounds(shape)[0],
    )[:3]
    if len(frames) != 3 or len(captions) != 3:
        raise RuntimeError("Não encontrei os três espaços de fotos/legendas no template.")

    for index, caption in enumerate(captions):
        item = payload["fotos"][index]
        expand_caption_box(caption)
        replace_text_rows(
            caption,
            [
                ("Cliente:", item.get("cliente", "")),
                ("Cidade:", item.get("cidade", "")),
                ("Pares:", item.get("pares", "")),
            ],
            size=1400,
            bold_labels=False,
        )

    rels_name = "ppt/slides/_rels/slide5.xml.rels"
    rels_root = ET.fromstring(files[rels_name])
    sp_tree = slide5.find(".//p:spTree", NS)
    if sp_tree is None:
        raise RuntimeError("Estrutura do slide de imagens não encontrada.")
    next_id = max_shape_id(slide5) + 1
    inset = 10_080
    for index, frame in enumerate(frames, start=1):
        photo = Path(payload["fotos"][index - 1]["arquivo"])
        media_name = f"ppt/media/conquistando-photo-{index}.jpeg"
        files[media_name] = photo.read_bytes()
        relation_id = add_image_relationship(
            rels_root, f"../media/conquistando-photo-{index}.jpeg"
        )
        x, y, width, height = shape_bounds(frame)
        next_id = add_picture(
            sp_tree,
            next_id,
            name=f"Foto Conquistando {index}",
            relation_id=relation_id,
            x=x + inset,
            y=y + inset,
            width=width - inset * 2,
            height=height - inset * 2,
        )

    header = Path(payload["header_image"])
    header_media = "ppt/media/conquistando-header.png"
    files[header_media] = header.read_bytes()
    header_rel = add_image_relationship(rels_root, "../media/conquistando-header.png")
    next_id = add_rectangle(
        sp_tree,
        next_id,
        name="Fundo branco do cabeçalho",
        x=0,
        y=0,
        width=12_192_000,
        height=954_000,
        color="FFFFFF",
    )
    next_id = add_picture(
        sp_tree,
        next_id,
        name="Cabeçalho da marca",
        relation_id=header_rel,
        x=0,
        y=0,
        width=12_192_000,
        height=914_400,
    )
    next_id = add_rectangle(
        sp_tree,
        next_id,
        name="Fundo do título Imagens",
        x=4_248_000,
        y=154_800,
        width=3_276_000,
        height=558_000,
        color="FFFFFF",
    )
    add_textbox(
        sp_tree,
        next_id,
        name="Título Imagens",
        text="Imagens",
        x=4_428_000,
        y=277_200,
        width=2_970_000,
        height=414_000,
        size=1800,
        font="Segoe UI Semibold",
    )

    for root in (slide2, slide3, slide5):
        add_identification_header(root, payload)

    files["ppt/slides/slide2.xml"] = serialize(slide2)
    files["ppt/slides/slide3.xml"] = serialize(slide3)
    files["ppt/slides/slide5.xml"] = serialize(slide5)
    files[rels_name] = serialize(rels_root)
    ensure_content_type(files, "jpeg", "image/jpeg")
    keep_final_slides(files)

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as destination:
        for name, content in files.items():
            destination.writestr(name, content)
    return str(output)

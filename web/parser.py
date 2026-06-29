from __future__ import annotations

import re
import unicodedata


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip()


def empty_result() -> dict:
    return {
        "codigo": "",
        "razao": "",
        "regional": "SPO",
        "microrregiao": "",
        "acoes": {"vendas": "", "marketing": "", "carteira": ""},
        "melhorias": {"vendas": "", "marketing": "", "carteira": ""},
        "fotos": [
            {"cliente": "", "cidade": "", "pares": ""},
            {"cliente": "", "cidade": "", "pares": ""},
            {"cliente": "", "cidade": "", "pares": ""},
        ],
    }


def parse_quick_text(raw: str) -> tuple[dict, list[str]]:
    values = empty_result()
    section = None
    current = None
    photo_index = None
    photo_field_index = 0
    chunks: list[str] = []

    def flush() -> None:
        nonlocal chunks
        if section and current and chunks:
            text = " ".join(part.strip() for part in chunks if part.strip()).strip()
            if text:
                values[section][current] = text
        chunks = []

    for original_line in str(raw or "").splitlines():
        line = original_line.strip()
        if not line:
            continue
        clean = normalize(line)

        photo_match = re.match(r"^(?:foto|imagem)\s*([123])\b", clean)
        if photo_match:
            flush()
            section, current = None, None
            photo_index = int(photo_match.group(1)) - 1
            photo_field_index = 0
            inline_value = re.sub(
                r"^\s*(?:foto|imagem)\s*[123]\s*[:\-]?\s*",
                "",
                line,
                flags=re.IGNORECASE,
            ).strip()
            if inline_value:
                values["fotos"][photo_index]["cliente"] = inline_value
                photo_field_index = 1
            continue

        if clean in {"fotos", "imagens", "legendas das fotos"}:
            flush()
            section, current = None, None
            photo_index = 0
            photo_field_index = 0
            continue

        if "acoes bem sucedidas" in clean or "acoes bem-sucedidas" in clean:
            flush()
            section, current, photo_index = "acoes", None, None
            continue
        if "pontos de melhoria" in clean or clean == "ponto de melhoria":
            flush()
            section, current, photo_index = "melhorias", None, None
            continue

        if photo_index is not None:
            caption_match = re.match(
                r"^(c[oó]digo/cliente|codigo/cliente|cliente|cidade|pares)\s*[:\-]\s*(.*)$",
                line,
                re.IGNORECASE,
            )
            if caption_match:
                field = normalize(caption_match.group(1))
                if field == "codigo/cliente":
                    field = "cliente"
                values["fotos"][photo_index][field] = caption_match.group(2).strip()
                photo_field_index = max(
                    photo_field_index,
                    {"cliente": 1, "cidade": 2, "pares": 3}[field],
                )
                continue
            fields = ("cliente", "cidade", "pares")
            if photo_field_index < 3:
                values["fotos"][photo_index][fields[photo_field_index]] = line
                photo_field_index += 1
                if photo_field_index == 3 and photo_index < 2:
                    photo_index += 1
                    photo_field_index = 0
                continue

        header_match = re.match(
            r"^\s*(c[oó]digo|c[oó]d\.?|raz[aã]o|regional|microrregi[aã]o)"
            r"\s*[:\-]\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if header_match:
            key = normalize(header_match.group(1)).replace(".", "")
            target = {
                "codigo": "codigo",
                "cod": "codigo",
                "razao": "razao",
                "regional": "regional",
                "microrregiao": "microrregiao",
            }.get(key)
            if target:
                values[target] = header_match.group(2).strip()
            continue

        content_line = re.sub(r"^\s*\d+\s*[\.\)\-]\s*", "", line)
        field_match = re.match(
            r"^(vendas?|mkt|marketing|carteira(?:\s+de\s+clientes?)?)"
            r"\s*[:\-]\s*(.*)$",
            content_line,
            re.IGNORECASE,
        )
        if field_match and section:
            flush()
            label = normalize(field_match.group(1))
            if label.startswith("vend"):
                current = "vendas"
            elif label in {"mkt", "marketing"}:
                current = "marketing"
            else:
                current = "carteira"
            chunks = [field_match.group(2).strip()]
        elif section and current:
            chunks.append(line)

    flush()
    first_photo = values["fotos"][0]
    combined_client = str(first_photo.get("cliente", "")).strip()
    combined_match = re.match(r"^(\S+)\s+(.+)$", combined_client)
    if combined_match:
        if not values["codigo"]:
            values["codigo"] = combined_match.group(1).strip()
        if not values["razao"]:
            values["razao"] = combined_match.group(2).strip()
    if not values["microrregiao"] and first_photo.get("cidade"):
        values["microrregiao"] = str(first_photo["cidade"]).strip()

    labels = {
        ("acoes", "vendas"): "Ações Bem Sucedidas — Vendas",
        ("acoes", "marketing"): "Ações Bem Sucedidas — MKT",
        ("acoes", "carteira"): "Ações Bem Sucedidas — Carteira",
        ("melhorias", "vendas"): "Pontos de Melhoria — Vendas",
        ("melhorias", "marketing"): "Pontos de Melhoria — MKT",
        ("melhorias", "carteira"): "Pontos de Melhoria — Carteira",
    }
    missing = [
        label
        for (section_key, field), label in labels.items()
        if not values[section_key][field].strip()
    ]
    return values, missing


def validate_parsed(data: dict) -> list[str]:
    missing = []
    for section, title in (("acoes", "Ações Bem Sucedidas"), ("melhorias", "Pontos de Melhoria")):
        for field, label in (
            ("vendas", "Vendas"),
            ("marketing", "MKT"),
            ("carteira", "Carteira"),
        ):
            if not str(data.get(section, {}).get(field, "")).strip():
                missing.append(f"{title} — {label}")
    return missing

"""Editor simples dos templates Conquistando (BR Sport e Actvitta)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
import ctypes
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import fitz
from PIL import Image, ImageOps, ImageTk

fitz.TOOLS.mupdf_display_errors(False)
fitz.TOOLS.mupdf_display_warnings(False)


APP_NAME = "Editor Conquistando"
BG = "#101114"
PANEL = "#17191F"
CARD = "#20232B"
INPUT = "#292D36"
LINE = "#343945"
TEXT = "#F4F5F7"
MUTED = "#9AA0AC"
ACCENT = "#FFB02E"
ACCENT_2 = "#D94FE8"
SUCCESS = "#7BD88F"
ERROR = "#FF7474"
QUICK_TEMPLATE = """AÇÕES BEM SUCEDIDAS
VENDAS: escreva aqui a primeira ação bem-sucedida
MKT: escreva aqui a segunda ação bem-sucedida
CARTEIRA DE CLIENTES: escreva aqui a terceira ação bem-sucedida

PONTOS DE MELHORIA
VENDAS: escreva aqui o primeiro ponto de melhoria
MKT: escreva aqui o segundo ponto de melhoria
CARTEIRA DE CLIENTES: escreva aqui o terceiro ponto de melhoria

FOTO 1
código/loja Nome do cliente
Cidade
Pares

FOTO 2
código/loja Nome do cliente
Cidade
Pares

FOTO 3
código/loja Nome do cliente
Cidade
Pares"""


def resource_path(*parts):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def find_libreoffice():
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "LibreOffice"
        / "program",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "LibreOffice"
        / "program",
    ]
    command = shutil.which("soffice")
    if command:
        candidates.insert(0, Path(command).resolve().parent)
    for folder in candidates:
        soffice = folder / "soffice.exe"
        python = folder / "python.exe"
        if soffice.exists() and python.exists():
            return soffice, python
    return None, None


class ScrollFrame(tk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, width=485)
        self.scrollbar = tk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview, bg=CARD
        )
        self.body = tk.Frame(self.canvas, bg=PANEL)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.body.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self.window, width=event.width),
        )
        for widget in (self.canvas, self.body):
            widget.bind("<Enter>", self._bind_wheel)
            widget.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _event):
        self.canvas.bind_all(
            "<MouseWheel>",
            lambda event: self.canvas.yview_scroll(int(-event.delta / 120), "units"),
        )

    def _unbind_wheel(self, _event):
        self.canvas.unbind_all("<MouseWheel>")


class Editor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1380x880")
        self.minsize(1120, 720)
        self.configure(bg=BG)
        try:
            self.iconbitmap(resource_path("assets", "icon.ico"))
        except Exception:
            pass

        self.brand = tk.StringVar(value="br-sport")
        self.codigo = tk.StringVar()
        self.razao = tk.StringVar()
        self.regional = tk.StringVar(value="SPO")
        self.microrregiao = tk.StringVar()
        self.text_fields = {}
        self.photos = []
        self.preview_paths = []
        self.preview_index = 0
        self.preview_image = None
        self.busy = False
        self.cache_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.soffice, self.lo_python = find_libreoffice()

        self._build()
        self.after(700, self.refresh_preview)

    def _build(self):
        left = ScrollFrame(self, bg=PANEL)
        left.pack(side="left", fill="y")
        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        form = left.body
        self._header(form)
        self._section_brand(form)
        self._section_quick(form)
        self._section_photos(form)
        self._section_advanced_toggle(form)
        self.advanced_container = tk.Frame(form, bg=PANEL)
        self._section_header(self.advanced_container)
        self._section_texts(self.advanced_container, "Ações bem-sucedidas", "acoes")
        self._section_texts(self.advanced_container, "Pontos de melhoria", "melhorias")
        self._section_photo_details(self.advanced_container)
        self._actions(form)
        self._preview(right)

    def _header(self, parent):
        box = tk.Frame(parent, bg=PANEL)
        box.pack(fill="x", padx=24, pady=(24, 15))
        tk.Label(
            box,
            text="CONQUISTANDO",
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            box,
            text="Editor de PowerPoint",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI Semibold", 24),
        ).pack(anchor="w")
        tk.Label(
            box,
            text="Preencha, visualize e gere a apresentação pronta.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(5, 0))

    def _card(self, parent, title):
        card = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x", padx=20, pady=8)
        tk.Label(
            card,
            text=title,
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI Semibold", 12),
        ).pack(anchor="w", padx=15, pady=(13, 10))
        return card

    def _section_brand(self, parent):
        card = self._card(parent, "1. Escolha a versão")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=14, pady=(0, 14))
        self.brand_buttons = {}
        for key, label in (("br-sport", "BR SPORT"), ("actvitta", "ACTVITTA")):
            button = tk.Button(
                row,
                text=label,
                command=lambda value=key: self.select_brand(value),
                relief="flat",
                bd=0,
                cursor="hand2",
                font=("Segoe UI Semibold", 10),
                padx=15,
                pady=10,
            )
            button.pack(side="left", fill="x", expand=True, padx=3)
            self.brand_buttons[key] = button
        self._paint_brand_buttons()

    def _label(self, parent, text):
        tk.Label(
            parent, text=text, bg=CARD, fg=MUTED, font=("Segoe UI Semibold", 9)
        ).pack(anchor="w", padx=15, pady=(7, 4))

    def _entry(self, parent, variable, placeholder=""):
        entry = tk.Entry(
            parent,
            textvariable=variable,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
        )
        entry.pack(fill="x", padx=15, ipady=8)
        variable.trace_add("write", lambda *_args: self.mark_dirty())
        return entry

    def _section_header(self, parent):
        card = self._card(parent, "Edição manual · Identificação no cabeçalho")
        self._label(card, "Código")
        self._entry(card, self.codigo)
        self._label(card, "Razão")
        self._entry(card, self.razao)
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=10, pady=(5, 14))
        for title, variable in (
            ("Regional (ex.: SPO)", self.regional),
            ("Microrregião", self.microrregiao),
        ):
            column = tk.Frame(row, bg=CARD)
            column.pack(side="left", fill="x", expand=True, padx=5)
            tk.Label(
                column,
                text=title,
                bg=CARD,
                fg=MUTED,
                font=("Segoe UI Semibold", 9),
            ).pack(anchor="w", pady=(6, 4))
            entry = tk.Entry(
                column,
                textvariable=variable,
                bg=INPUT,
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                font=("Segoe UI", 10),
            )
            entry.pack(fill="x", ipady=8)
            variable.trace_add("write", lambda *_args: self.mark_dirty())

    def _section_texts(self, parent, title, key):
        card = self._card(parent, f"Edição manual · {title}")
        tk.Label(
            card,
            text="Times New Roman 20 · esquerda · topo · espaçamento 1,0",
            bg=CARD,
            fg=ACCENT,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=15, pady=(0, 5))
        for field, label in (
            ("vendas", "Vendas"),
            ("marketing", "Marketing"),
            ("carteira", "Carteira de clientes"),
        ):
            self._label(card, label)
            text = tk.Text(
                card,
                height=4,
                wrap="word",
                bg=INPUT,
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                font=("Segoe UI", 10),
                padx=9,
                pady=7,
                undo=True,
            )
            text.pack(fill="x", padx=15)
            text.bind("<KeyRelease>", lambda _event: self.mark_dirty())
            self.text_fields[(key, field)] = text
        tk.Frame(card, bg=CARD, height=12).pack()

    def _section_photos(self, parent):
        card = self._card(parent, "3. Envie as três fotos")
        tk.Label(
            card,
            text="As imagens serão recortadas e encaixadas automaticamente nos quadrados.",
            bg=CARD,
            fg=ACCENT,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=15, pady=(0, 6))
        tk.Button(
            card,
            text="SELECIONAR AS 3 FOTOS DE UMA VEZ…",
            command=self.choose_three_photos,
            bg=ACCENT_2,
            fg="white",
            activebackground="#B83BC7",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
        ).pack(fill="x", padx=14, pady=(0, 7), ipady=7)
        for index in range(3):
            photo = {
                "arquivo": tk.StringVar(),
                "cliente": tk.StringVar(),
                "cidade": tk.StringVar(),
                "pares": tk.StringVar(),
            }
            self.photos.append(photo)
            item = tk.Frame(card, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
            item.pack(fill="x", padx=14, pady=6)
            top = tk.Frame(item, bg=PANEL)
            top.pack(fill="x", padx=10, pady=(9, 5))
            tk.Label(
                top,
                text=f"FOTO {index + 1}",
                bg=PANEL,
                fg=TEXT,
                font=("Segoe UI Semibold", 9),
            ).pack(side="left")
            filename = tk.Label(
                top,
                text="Nenhuma imagem",
                bg=PANEL,
                fg=MUTED,
                font=("Segoe UI", 8),
            )
            filename.pack(side="right")
            photo["filename_label"] = filename
            tk.Button(
                item,
                text="Escolher imagem…",
                command=lambda i=index: self.choose_photo(i),
                bg=INPUT,
                fg=TEXT,
                activebackground=LINE,
                activeforeground=TEXT,
                relief="flat",
                cursor="hand2",
                font=("Segoe UI Semibold", 9),
            ).pack(fill="x", padx=10, pady=(0, 5), ipady=5)
            tk.Frame(item, bg=PANEL, height=7).pack()
        tk.Frame(card, bg=CARD, height=8).pack()

    def _section_photo_details(self, parent):
        card = self._card(parent, "Edição manual · Legendas das fotos")
        tk.Label(
            card,
            text="Times New Roman 14 · esquerda · topo · espaçamento 1,0",
            bg=CARD,
            fg=ACCENT,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=15, pady=(0, 6))
        for index, photo in enumerate(self.photos):
            item = tk.Frame(card, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
            item.pack(fill="x", padx=14, pady=6)
            tk.Label(
                item,
                text=f"LEGENDA DA FOTO {index + 1}",
                bg=PANEL,
                fg=TEXT,
                font=("Segoe UI Semibold", 9),
            ).pack(anchor="w", padx=10, pady=(9, 5))
            for label, field in (
                ("Cliente", "cliente"),
                ("Cidade", "cidade"),
                ("Pares", "pares"),
            ):
                row = tk.Frame(item, bg=PANEL)
                row.pack(fill="x", padx=10, pady=3)
                tk.Label(
                    row,
                    text=label,
                    width=8,
                    anchor="w",
                    bg=PANEL,
                    fg=MUTED,
                    font=("Segoe UI", 9),
                ).pack(side="left")
                entry = tk.Entry(
                    row,
                    textvariable=photo[field],
                    bg=INPUT,
                    fg=TEXT,
                    insertbackground=TEXT,
                    relief="flat",
                    font=("Segoe UI", 9),
                )
                entry.pack(side="left", fill="x", expand=True, ipady=5)
                photo[field].trace_add("write", lambda *_args: self.mark_dirty())
            tk.Frame(item, bg=PANEL, height=7).pack()
        tk.Frame(card, bg=CARD, height=8).pack()

    def _section_advanced_toggle(self, parent):
        self.advanced_visible = False
        self.advanced_toggle_frame = tk.Frame(parent, bg=PANEL)
        self.advanced_toggle_frame.pack(fill="x", padx=20, pady=(8, 2))
        self.advanced_button = tk.Button(
            self.advanced_toggle_frame,
            text="EDITAR CAMPOS MANUALMENTE  ▾",
            command=self.toggle_advanced,
            bg=CARD,
            fg=MUTED,
            activebackground=LINE,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
        )
        self.advanced_button.pack(fill="x", ipady=8)

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_container.pack(
                fill="x", before=self.actions_frame, pady=(2, 0)
            )
            self.advanced_button.configure(
                text="OCULTAR EDIÇÃO MANUAL  ▴", fg=TEXT
            )
        else:
            self.advanced_container.pack_forget()
            self.advanced_button.configure(
                text="EDITAR CAMPOS MANUALMENTE  ▾", fg=MUTED
            )

    def _section_quick(self, parent):
        card = self._card(parent, "2. Entrada rápida — cole tudo aqui")
        tk.Label(
            card,
            text=(
                "O app reconhece Código, Razão, Regional, Microrregião, "
                "Ações Bem Sucedidas, Pontos de Melhoria e as legendas FOTO 1, 2 e 3."
            ),
            wraplength=420,
            justify="left",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=15, pady=(0, 7))
        template_row = tk.Frame(card, bg=CARD)
        template_row.pack(fill="x", padx=15, pady=(0, 8))
        tk.Button(
            template_row,
            text="COPIAR MODELO",
            command=self.copy_quick_template,
            bg=INPUT,
            fg=TEXT,
            activebackground=LINE,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 8),
        ).pack(side="left", fill="x", expand=True, padx=(0, 5), ipady=7)
        tk.Button(
            template_row,
            text="INSERIR MODELO",
            command=self.insert_quick_template,
            bg=INPUT,
            fg=TEXT,
            activebackground=LINE,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 8),
        ).pack(side="left", fill="x", expand=True, padx=(5, 0), ipady=7)
        self.quick_text = tk.Text(
            card,
            height=12,
            wrap="word",
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
            padx=10,
            pady=9,
            undo=True,
        )
        self.quick_text.pack(fill="x", padx=15)
        self.quick_text.bind("<KeyRelease>", lambda _event: self.mark_dirty())
        tk.Button(
            card,
            text="APLICAR E REVISAR",
            command=self.apply_quick_text,
            bg=ACCENT,
            fg="#171717",
            activebackground="#FFC15A",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Black", 9),
        ).pack(fill="x", padx=15, pady=(9, 5), ipady=8)
        tk.Button(
            card,
            text="APLICAR E GERAR POWERPOINT",
            command=self.quick_generate,
            bg=ACCENT_2,
            fg="white",
            activebackground="#B83BC7",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Black", 9),
        ).pack(fill="x", padx=15, pady=(0, 14), ipady=8)

    def _actions(self, parent):
        box = tk.Frame(parent, bg=PANEL)
        box.pack(fill="x", padx=20, pady=(12, 28))
        self.actions_frame = box
        self.preview_button = tk.Button(
            box,
            text="ATUALIZAR PRÉVIA",
            command=self.refresh_preview,
            bg=CARD,
            fg=TEXT,
            activebackground=LINE,
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 10),
        )
        self.preview_button.pack(fill="x", ipady=10)
        self.generate_button = tk.Button(
            box,
            text="GERAR POWERPOINT",
            command=self.generate_powerpoint,
            bg=ACCENT,
            fg="#161616",
            activebackground="#FFC15A",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Black", 11),
        )
        self.generate_button.pack(fill="x", pady=(8, 0), ipady=12)

    def _preview(self, parent):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", padx=35, pady=(30, 16))
        tk.Label(
            head,
            text="Prévia real do PowerPoint",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 18),
        ).pack(side="left")
        self.dirty_label = tk.Label(
            head,
            text="",
            bg=BG,
            fg=ACCENT,
            font=("Segoe UI", 9),
        )
        self.dirty_label.pack(side="right")

        tabs = tk.Frame(parent, bg=BG)
        tabs.pack(fill="x", padx=35)
        self.preview_tabs = []
        for index, label in enumerate(("AÇÕES", "MELHORIAS", "IMAGENS")):
            button = tk.Button(
                tabs,
                text=label,
                command=lambda value=index: self.show_preview(value),
                bg=CARD,
                fg=MUTED,
                activebackground=LINE,
                activeforeground=TEXT,
                relief="flat",
                cursor="hand2",
                font=("Segoe UI Semibold", 9),
            )
            button.pack(side="left", padx=(0, 6), ipadx=12, ipady=6)
            self.preview_tabs.append(button)

        stage = tk.Frame(parent, bg="#090A0C", highlightbackground=LINE, highlightthickness=1)
        stage.pack(fill="both", expand=True, padx=35, pady=(12, 15))
        self.preview_label = tk.Label(
            stage,
            text="Preparando a primeira prévia…",
            bg="#090A0C",
            fg=MUTED,
            font=("Segoe UI", 12),
        )
        self.preview_label.pack(fill="both", expand=True, padx=20, pady=20)
        self.preview_label.bind("<Configure>", lambda _event: self._paint_preview())

        footer = tk.Frame(parent, bg=BG)
        footer.pack(fill="x", padx=35, pady=(0, 28))
        self.status = tk.Label(
            footer,
            text="",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.status.pack(side="left", fill="x", expand=True)
        tk.Label(
            footer,
            text="Slides de instrução removidos automaticamente",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(side="right")
        self._paint_preview_tabs()

    def select_brand(self, value):
        if self.brand.get() == value:
            return
        self.brand.set(value)
        self._paint_brand_buttons()
        self.mark_dirty()
        self.refresh_preview()

    def _paint_brand_buttons(self):
        for key, button in self.brand_buttons.items():
            selected = self.brand.get() == key
            button.configure(
                bg=ACCENT_2 if selected else INPUT,
                fg="white" if selected else MUTED,
                activebackground=ACCENT_2 if selected else LINE,
                activeforeground="white",
            )

    def choose_photo(self, index):
        path = filedialog.askopenfilename(
            title=f"Escolha a foto {index + 1}",
            filetypes=[
                ("Imagens", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if not path:
            return
        photo = self.photos[index]
        photo["arquivo"].set(path)
        photo["filename_label"].configure(text=Path(path).name[:34])
        self.mark_dirty()

    def choose_three_photos(self):
        paths = filedialog.askopenfilenames(
            title="Selecione as 3 fotos na ordem em que devem aparecer",
            filetypes=[
                ("Imagens", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if not paths:
            return
        if len(paths) != 3:
            messagebox.showwarning(
                APP_NAME, "Selecione exatamente 3 fotos para preencher os três quadrados."
            )
            return
        for index, path in enumerate(paths):
            self.photos[index]["arquivo"].set(path)
            self.photos[index]["filename_label"].configure(text=Path(path).name[:34])
        self.mark_dirty()

    @staticmethod
    def _clean_heading(value):
        value = value.casefold()
        value = (
            value.replace("ç", "c")
            .replace("ã", "a")
            .replace("á", "a")
            .replace("à", "a")
            .replace("â", "a")
            .replace("é", "e")
            .replace("ê", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ô", "o")
            .replace("õ", "o")
            .replace("ú", "u")
        )
        return re.sub(r"\s+", " ", value).strip()

    def copy_quick_template(self):
        self.clipboard_clear()
        self.clipboard_append(QUICK_TEMPLATE)
        self.update()
        messagebox.showinfo(APP_NAME, "Modelo copiado. Cole no Bloco de Notas, WhatsApp ou e-mail.")

    def insert_quick_template(self):
        current = self.quick_text.get("1.0", "end-1c").strip()
        if current and not messagebox.askyesno(
            APP_NAME,
            "O campo já tem texto. Deseja substituir pelo modelo?",
        ):
            return
        self.quick_text.delete("1.0", "end")
        self.quick_text.insert("1.0", QUICK_TEMPLATE)
        self.quick_text.focus_set()
        self.mark_dirty()

    def apply_quick_text(self):
        raw = self.quick_text.get("1.0", "end-1c").strip()
        if not raw:
            messagebox.showwarning(APP_NAME, "Cole as informações antes de aplicar.")
            return False

        values = {
            "codigo": "",
            "razao": "",
            "regional": "",
            "microrregiao": "",
            "acoes": {"vendas": "", "marketing": "", "carteira": ""},
            "melhorias": {"vendas": "", "marketing": "", "carteira": ""},
            "fotos": [
                {"cliente": "", "cidade": "", "pares": ""},
                {"cliente": "", "cidade": "", "pares": ""},
                {"cliente": "", "cidade": "", "pares": ""},
            ],
        }
        section = None
        current = None
        photo_index = None
        chunks = []

        def flush():
            nonlocal chunks
            if section and current and chunks:
                text = " ".join(part.strip() for part in chunks if part.strip()).strip()
                if text:
                    values[section][current] = text
            chunks = []

        for original_line in raw.splitlines():
            line = original_line.strip()
            if not line:
                continue
            normalized = self._clean_heading(line)
            photo_match = re.match(r"^(?:foto|imagem)\s*([123])\b", normalized)
            if photo_match:
                flush()
                section, current = None, None
                photo_index = int(photo_match.group(1)) - 1
                continue
            if "acoes bem sucedidas" in normalized or "acoes bem-sucedidas" in normalized:
                flush()
                section, current = "acoes", None
                photo_index = None
                continue
            if "pontos de melhoria" in normalized or "ponto de melhoria" == normalized:
                flush()
                section, current = "melhorias", None
                photo_index = None
                continue

            if photo_index is not None:
                caption_match = re.match(
                    r"^(cliente|cidade|pares)\s*[:\-]\s*(.*)$",
                    line,
                    re.IGNORECASE,
                )
                if caption_match:
                    field = self._clean_heading(caption_match.group(1))
                    values["fotos"][photo_index][field] = caption_match.group(2).strip()
                    continue

            header_match = re.match(
                r"^\s*(c[oó]digo|c[oó]d\.?|raz[aã]o|regional|microrregi[aã]o)\s*[:\-]\s*(.+)$",
                line,
                re.IGNORECASE,
            )
            if header_match:
                key = self._clean_heading(header_match.group(1)).replace(".", "")
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
                r"^(vendas?|mkt|marketing|carteira(?:\s+de\s+clientes?)?)\s*[:\-]\s*(.*)$",
                content_line,
                re.IGNORECASE,
            )
            if field_match and section:
                flush()
                label = self._clean_heading(field_match.group(1))
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

        self.codigo.set(values["codigo"] or self.codigo.get())
        self.razao.set(values["razao"] or self.razao.get())
        self.regional.set(values["regional"] or self.regional.get())
        self.microrregiao.set(values["microrregiao"] or self.microrregiao.get())
        applied = 0
        for section_key in ("acoes", "melhorias"):
            for field in ("vendas", "marketing", "carteira"):
                value = values[section_key][field]
                if not value:
                    continue
                widget = self.text_fields[(section_key, field)]
                widget.delete("1.0", "end")
                widget.insert("1.0", value)
                applied += 1
        for index, photo_values in enumerate(values["fotos"]):
            for field in ("cliente", "cidade", "pares"):
                if photo_values[field]:
                    self.photos[index][field].set(photo_values[field])
        if not applied:
            messagebox.showwarning(
                APP_NAME,
                "Não encontrei os títulos Vendas, MKT/Marketing e Carteira dentro "
                "das seções Ações Bem Sucedidas e Pontos de Melhoria.",
            )
            return False
        self.mark_dirty()
        self.status.configure(
            text=f"{applied} textos distribuídos automaticamente. Revise e gere o PowerPoint.",
            fg=SUCCESS,
        )
        return True

    def quick_generate(self):
        if not self.apply_quick_text():
            return
        selected = [photo["arquivo"].get() for photo in self.photos]
        if len([path for path in selected if path]) != 3:
            messagebox.showwarning(
                APP_NAME,
                "Antes de gerar, use “Selecionar as 3 fotos de uma vez” na seção Fotos.",
            )
            return
        self.generate_powerpoint()

    def mark_dirty(self):
        if hasattr(self, "dirty_label"):
            self.dirty_label.configure(text="● prévia desatualizada")

    def get_text(self, section, field):
        return self.text_fields[(section, field)].get("1.0", "end-1c").strip()

    def collect_data(self):
        return {
            "codigo": self.codigo.get().strip(),
            "razao": self.razao.get().strip(),
            "regional": self.regional.get().strip(),
            "microrregiao": self.microrregiao.get().strip(),
            "acoes": {
                field: self.get_text("acoes", field)
                for field in ("vendas", "marketing", "carteira")
            },
            "melhorias": {
                field: self.get_text("melhorias", field)
                for field in ("vendas", "marketing", "carteira")
            },
            "fotos": [
                {
                    "arquivo": photo["arquivo"].get(),
                    "cliente": photo["cliente"].get(),
                    "cidade": photo["cidade"].get(),
                    "pares": photo["pares"].get(),
                }
                for photo in self.photos
            ],
        }

    def template_path(self):
        filename = (
            "BR SPORT CONQUISTANDO.pptx"
            if self.brand.get() == "br-sport"
            else "ACTVITTA CONQUISTANDO.pptx"
        )
        return resource_path("assets", filename)

    def header_image_path(self):
        filename = (
            "BR SPORT header.png"
            if self.brand.get() == "br-sport"
            else "ACTVITTA header.png"
        )
        return resource_path("assets", filename)

    def prepare_photos(self, data):
        prepared = []
        ratio = 379 / 351
        for index, item in enumerate(data["fotos"], start=1):
            clone = dict(item)
            source = Path(item["arquivo"]) if item["arquivo"] else None
            if source and source.is_file():
                destination = self.cache_dir / f"photo-{index}.jpg"
                with Image.open(source) as image:
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    width, height = image.size
                    current = width / max(height, 1)
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
                clone["arquivo"] = str(destination)
            prepared.append(clone)
        data["fotos"] = prepared
        return data

    def _run_worker(self, output, render_preview):
        if not self.soffice or not self.lo_python:
            raise RuntimeError(
                "LibreOffice não encontrado. Instale o LibreOffice para gerar e visualizar."
            )
        data = self.prepare_photos(self.collect_data())
        data.update(
            {
                "template": str(self.template_path()),
                "header_image": str(self.header_image_path()),
                "output": str(output),
                "soffice": str(self.soffice),
                "preview_dir": str(self.cache_dir / "previews") if render_preview else "",
            }
        )
        payload = self.cache_dir / "job.json"
        payload.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        packaged_worker = resource_path("office_worker.py")
        worker = self.cache_dir / "office_worker.py"
        shutil.copy2(packaged_worker, worker)
        child_env = os.environ.copy()
        for key in list(child_env):
            if key.startswith("_PYI_") or key in {"PYTHONHOME", "PYTHONPATH"}:
                child_env.pop(key, None)
        child_env["PATH"] = str(self.lo_python.parent) + os.pathsep + child_env.get(
            "PATH", ""
        )
        reset_dll_path = os.name == "nt" and getattr(sys, "frozen", False)
        if reset_dll_path:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            result = subprocess.run(
                [str(self.lo_python), str(worker), str(payload)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=child_env,
                creationflags=0x08000000 if os.name == "nt" else 0,
                timeout=120,
            )
        finally:
            if reset_dll_path:
                ctypes.windll.kernel32.SetDllDirectoryW(str(resource_path()))
        parsed = None
        for line in reversed(result.stdout.splitlines()):
            if line.strip().startswith("{"):
                parsed = json.loads(line)
                break
        if not parsed:
            details = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(details or "O gerador não retornou uma resposta válida.")
        if not parsed.get("ok"):
            raise RuntimeError(parsed.get("error", "Falha ao gerar o PowerPoint."))
        if render_preview and parsed.get("preview_pdf"):
            parsed["previews"] = self._render_pdf(parsed["preview_pdf"])
        return parsed

    def _render_pdf(self, pdf_path):
        preview_root = self.cache_dir / "previews"
        preview_root.mkdir(parents=True, exist_ok=True)
        paths = []
        with fitz.open(pdf_path) as document:
            for index, page in enumerate(document):
                target = preview_root / f"slide-{index + 1}.png"
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.45, 1.45), alpha=False)
                pixmap.save(str(target))
                paths.append(str(target))
        return paths

    def _set_busy(self, value, message=""):
        self.busy = value
        state = "disabled" if value else "normal"
        self.preview_button.configure(state=state)
        self.generate_button.configure(state=state)
        self.status.configure(text=message, fg=ACCENT if value else MUTED)

    def refresh_preview(self):
        if self.busy:
            return
        self._set_busy(True, "Gerando prévia real…")
        output = self.cache_dir / "preview.pptx"

        def task():
            try:
                result = self._run_worker(output, True)
                self.after(0, lambda: self._preview_done(result))
            except Exception as error:
                self.after(0, lambda: self._failed(str(error)))

        threading.Thread(target=task, daemon=True).start()

    def _preview_done(self, result):
        self.preview_paths = result.get("previews", [])
        self.dirty_label.configure(text="")
        self._set_busy(False, "Prévia atualizada.")
        self.show_preview(min(self.preview_index, max(len(self.preview_paths) - 1, 0)))

    def show_preview(self, index):
        self.preview_index = index
        self._paint_preview_tabs()
        self._paint_preview()

    def _paint_preview_tabs(self):
        for index, button in enumerate(self.preview_tabs):
            selected = index == self.preview_index
            button.configure(
                bg=ACCENT if selected else CARD,
                fg="#171717" if selected else MUTED,
            )

    def _paint_preview(self):
        if not self.preview_paths or self.preview_index >= len(self.preview_paths):
            return
        path = Path(self.preview_paths[self.preview_index])
        if not path.exists():
            return
        width = max(self.preview_label.winfo_width() - 40, 400)
        height = max(self.preview_label.winfo_height() - 40, 260)
        with Image.open(path) as image:
            preview = ImageOps.contain(image.convert("RGB"), (width, height))
            self.preview_image = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.preview_image, text="")

    def generate_powerpoint(self):
        if self.busy:
            return
        brand = "BR-SPORT" if self.brand.get() == "br-sport" else "ACTVITTA"
        code = self.codigo.get().strip().replace("/", "-") or "NOVO"
        output = filedialog.asksaveasfilename(
            title="Salvar PowerPoint",
            defaultextension=".pptx",
            initialfile=f"{brand}_CONQUISTANDO_{code}.pptx",
            filetypes=[("PowerPoint", "*.pptx")],
        )
        if not output:
            return
        self._set_busy(True, "Gerando o PowerPoint final…")

        def task():
            try:
                result = self._run_worker(Path(output), True)
                self.after(0, lambda: self._export_done(result))
            except Exception as error:
                self.after(0, lambda: self._failed(str(error)))

        threading.Thread(target=task, daemon=True).start()

    def _export_done(self, result):
        self.preview_paths = result.get("previews", [])
        self.dirty_label.configure(text="")
        self._set_busy(False, "PowerPoint gerado com sucesso.")
        self.show_preview(self.preview_index)
        output = result["output"]
        if messagebox.askyesno(
            APP_NAME,
            f"PowerPoint gerado com sucesso:\n\n{output}\n\nDeseja abrir a pasta?",
        ):
            os.startfile(str(Path(output).parent))

    def _failed(self, error):
        self._set_busy(False, "")
        self.status.configure(text=error, fg=ERROR)
        messagebox.showerror(APP_NAME, error)


def smoke_test():
    root = Editor()
    root.withdraw()
    report_path = root.cache_dir / "smoke-test.json"
    try:
        result = root._run_worker(root.cache_dir / "smoke-test.pptx", True)
        report = {
            "ok": True,
            "output": result["output"],
            "previews": result["previews"],
        }
        code = 0
    except Exception as error:
        report = {"ok": False, "error": repr(error), "traceback": traceback.format_exc()}
        code = 1
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    root.destroy()
    return code


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        raise SystemExit(smoke_test())
    Editor().mainloop()

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  brand: "br-sport",
  drafts: {
    "br-sport": { text: "", photos: [], parsed: null, textVersion: "", data: null, status: "" },
    actvitta: { text: "", photos: [], parsed: null, textVersion: "", data: null, status: "" },
  },
  previewUrls: [],
};

const fieldIds = {
  codigo: "codigo",
  razao: "razao",
  regional: "regional",
  microrregiao: "microrregiao",
};
const sectionIds = {
  acoes: {
    vendas: "acoesVendas",
    marketing: "acoesMarketing",
    carteira: "acoesCarteira",
  },
  melhorias: {
    vendas: "melhoriasVendas",
    marketing: "melhoriasMarketing",
    carteira: "melhoriasCarteira",
  },
};

function activeDraft() {
  return state.drafts[state.brand];
}

function emptyFields() {
  return {
    codigo: "",
    razao: "",
    regional: "SPO",
    microrregiao: "",
    acoes: { vendas: "", marketing: "", carteira: "" },
    melhorias: { vendas: "", marketing: "", carteira: "" },
    fotos: [
      { cliente: "", cidade: "", pares: "" },
      { cliente: "", cidade: "", pares: "" },
      { cliente: "", cidade: "", pares: "" },
    ],
  };
}

function pinHeaders() {
  const pin = $("#pin").value.trim();
  return pin ? { "X-App-Pin": pin } : {};
}

function setMessage(text, kind = "") {
  const box = $("#message");
  box.textContent = text;
  box.className = `message ${kind}`.trim();
}

function setBusy(value) {
  $("#busy").hidden = !value;
  $("#previewButton").disabled = value;
  $("#generateButton").disabled = value;
}

function buildCaptionEditor() {
  $("#captionGrid").replaceChildren(
    ...[0, 1, 2].map((index) => {
      const card = document.createElement("div");
      card.className = "caption-card";
      card.innerHTML = `
        <strong>FOTO ${index + 1}</strong>
        <label>Cliente<input id="foto${index}Cliente"></label>
        <label>Cidade<input id="foto${index}Cidade"></label>
        <label>Pares<input id="foto${index}Pares" inputmode="numeric"></label>`;
      return card;
    })
  );
}

function fillFields(data) {
  Object.entries(fieldIds).forEach(([key, id]) => {
    $(`#${id}`).value = data[key] || "";
  });
  Object.entries(sectionIds).forEach(([section, fields]) => {
    Object.entries(fields).forEach(([key, id]) => {
      $(`#${id}`).value = data[section]?.[key] || "";
    });
  });
  [0, 1, 2].forEach((index) => {
    const photo = data.fotos?.[index] || {};
    $(`#foto${index}Cliente`).value = photo.cliente || "";
    $(`#foto${index}Cidade`).value = photo.cidade || "";
    $(`#foto${index}Pares`).value = photo.pares || "";
  });
}

function collectFields() {
  const data = {
    fotos: [0, 1, 2].map((index) => ({
      cliente: $(`#foto${index}Cliente`).value.trim(),
      cidade: $(`#foto${index}Cidade`).value.trim(),
      pares: $(`#foto${index}Pares`).value.trim(),
    })),
    acoes: {},
    melhorias: {},
  };
  Object.entries(fieldIds).forEach(([key, id]) => {
    data[key] = $(`#${id}`).value.trim();
  });
  Object.entries(sectionIds).forEach(([section, fields]) => {
    Object.entries(fields).forEach(([key, id]) => {
      data[section][key] = $(`#${id}`).value.trim();
    });
  });
  return data;
}

function clearPreview() {
  state.previewUrls.forEach((url) => URL.revokeObjectURL(url));
  state.previewUrls = [];
  $("#previewDeck").replaceChildren();
  $("#previewDeck").hidden = true;
  $("#emptyPreview").style.display = "";
  $("#openPreview").hidden = true;
}

function saveActiveDraft() {
  const draft = activeDraft();
  draft.text = $("#quickText").value;
  draft.data = collectFields();
}

function loadActiveDraft() {
  const draft = activeDraft();
  $("#quickText").value = draft.text;
  fillFields(draft.data || emptyFields());
  $("#parseStatus").textContent = draft.status;
  $("#photos").value = "";
  $("#brandDataTitle").textContent =
    state.brand === "br-sport" ? "Informações BR SPORT" : "Informações ACTVITTA";
  renderPhotos();
  clearPreview();
  setMessage("");
}

async function interpret(force = false) {
  const draft = activeDraft();
  const text = $("#quickText").value.trim();
  if (!text) throw new Error("Cole as informações antes de continuar.");
  if (!force && draft.parsed && draft.textVersion === text) return draft.parsed;
  const response = await fetch("/api/parse", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...pinHeaders() },
    body: JSON.stringify({ text }),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || "Não foi possível interpretar.");
  draft.parsed = result.data;
  draft.textVersion = text;
  draft.text = text;
  draft.data = result.data;
  fillFields(result.data);
  draft.status = result.missing.length
    ? `${result.missing.length} campo(s) precisam de revisão`
    : "Informações prontas";
  $("#parseStatus").textContent = draft.status;
  if (result.missing.length) $("#manualEditor").open = true;
  return result.data;
}

function renderPhotos() {
  const photos = activeDraft().photos;
  const slots = $$("#photoGrid .photo-slot");
  slots.forEach((slot, index) => {
    const file = photos[index];
    const number = `<b>${index + 1}</b>`;
    if (!file) {
      slot.innerHTML = `${number}<span>Nenhuma foto</span>`;
      return;
    }
    const url = URL.createObjectURL(file);
    slot.innerHTML = `${number}<img alt="Foto ${index + 1}">`;
    slot.querySelector("img").src = url;
    slot.querySelector("img").onload = () => URL.revokeObjectURL(url);
  });
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function addSlideHeader(slide, title, data) {
  const header = element("img", "ppt-header");
  header.alt = "";
  header.src = `/brand-header/${state.brand}.png`;
  slide.append(header);
  slide.append(element("div", "ppt-title", title));

  const identification = element("div", "ppt-ident");
  identification.append(
    element("div", "", `${data.codigo || "cód."} – ${data.razao || "razão"}`),
    element(
      "div",
      "",
      `${data.regional || "SPO"} – ${data.microrregiao || "microrregião"}`
    )
  );
  slide.append(identification);
}

function createTextSlide(title, values, data) {
  const slide = element("article", "ppt-slide");
  addSlideHeader(slide, title, data);
  const body = element("div", "ppt-body");
  [
    ["VENDAS:", values.vendas],
    ["MKT:", values.marketing],
    ["CARTEIRA DE CLIENTES:", values.carteira],
  ].forEach(([label, value]) => {
    const row = element("p");
    row.append(element("strong", "", label), document.createTextNode(` ${value}`));
    body.append(row);
  });
  slide.append(body);
  return slide;
}

function createPhotoSlide(data) {
  const slide = element("article", "ppt-slide");
  addSlideHeader(slide, "Imagens", data);
  const grid = element("div", "ppt-photos");
  activeDraft().photos.forEach((file, index) => {
    const figure = element("figure", "ppt-photo");
    const image = element("img");
    image.alt = `Foto ${index + 1}`;
    const url = URL.createObjectURL(file);
    state.previewUrls.push(url);
    image.src = url;
    const caption = element("figcaption");
    const values = data.fotos[index];
    caption.append(
      element("span", "", `Cliente: ${values.cliente || ""}`),
      element("span", "", `Cidade: ${values.cidade || ""}`),
      element("span", "", `Pares: ${values.pares || ""}`)
    );
    figure.append(image, caption);
    grid.append(figure);
  });
  slide.append(grid);
  return slide;
}

function validatePreviewData(data) {
  const missing = [];
  [
    ["Ações — Vendas", data.acoes.vendas],
    ["Ações — MKT", data.acoes.marketing],
    ["Ações — Carteira", data.acoes.carteira],
    ["Melhorias — Vendas", data.melhorias.vendas],
    ["Melhorias — MKT", data.melhorias.marketing],
    ["Melhorias — Carteira", data.melhorias.carteira],
  ].forEach(([label, value]) => {
    if (!value) missing.push(label);
  });
  if (missing.length) throw new Error(`Faltam informações: ${missing.join("; ")}`);
}

async function renderPreview({ automatic = false } = {}) {
  const draft = activeDraft();
  if (draft.photos.length !== 3) throw new Error("Selecione exatamente três fotos.");
  await interpret(false);
  const data = collectFields();
  draft.data = data;
  validatePreviewData(data);
  state.previewUrls.forEach((url) => URL.revokeObjectURL(url));
  state.previewUrls = [];
  const deck = $("#previewDeck");
  deck.replaceChildren(
    createTextSlide("Ações Bem Sucedidas", data.acoes, data),
    createTextSlide("Pontos de Melhoria", data.melhorias, data),
    createPhotoSlide(data)
  );
  deck.hidden = false;
  $("#emptyPreview").style.display = "none";
  $("#openPreview").hidden = false;
  if (!automatic) {
    $("#previewSection").scrollIntoView({ behavior: "smooth", block: "start" });
    setMessage("Prévia atualizada.", "success");
  }
}

let previewTimer = null;
function schedulePreview() {
  clearTimeout(previewTimer);
  if (activeDraft().photos.length !== 3 || !$("#quickText").value.trim()) return;
  previewTimer = setTimeout(async () => {
    try {
      await renderPreview({ automatic: true });
    } catch (_error) {
      // A prévia aparece assim que todos os campos obrigatórios estiverem prontos.
    }
  }, 650);
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 3000);
}

function filenameFromDisposition(response) {
  const value = response.headers.get("Content-Disposition") || "";
  const utf = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf) return decodeURIComponent(utf[1]);
  const basic = value.match(/filename="?([^";]+)"?/i);
  return basic?.[1] || "CONQUISTANDO.pptx";
}

async function processPowerPoint() {
  const draft = activeDraft();
  if (draft.photos.length !== 3) throw new Error("Selecione exatamente três fotos.");
  await interpret(false);
  draft.data = collectFields();
  const form = new FormData();
  form.append("brand", state.brand);
  form.append("mode", "generate");
  form.append("text", $("#quickText").value);
  form.append("parsed_json", JSON.stringify(draft.data));
  draft.photos.forEach((photo) => form.append("photos", photo, photo.name));

  const response = await fetch("/api/process", {
    method: "POST",
    headers: pinHeaders(),
    body: form,
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(result.error || "Não foi possível gerar o PowerPoint.");
  }
  const blob = await response.blob();
  downloadBlob(blob, filenameFromDisposition(response));
  setMessage("PowerPoint gerado. Confira seus downloads.", "success");
}

async function guardedProcess() {
  setBusy(true);
  setMessage("");
  try {
    await processPowerPoint();
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function guardedPreview() {
  setBusy(true);
  setMessage("");
  try {
    await renderPreview();
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setBusy(false);
  }
}

buildCaptionEditor();
$("#pin").value = localStorage.getItem("conquistando-pin") || "";
$("#confirmPin").addEventListener("click", async () => {
  const pin = $("#pin").value.trim();
  const status = $("#pinStatus");
  status.textContent = "Verificando…";
  status.className = "";
  try {
    const response = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-App-Pin": pin },
      body: JSON.stringify({ text: "" }),
    });
    if (!response.ok) throw new Error("PIN incorreto");
    localStorage.setItem("conquistando-pin", pin);
    status.textContent = "PIN confirmado";
    status.className = "success";
  } catch (_error) {
    status.textContent = "PIN incorreto";
    status.className = "error";
  }
});
$$(".brand-option").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.brand === state.brand) return;
    saveActiveDraft();
    state.brand = button.dataset.brand;
    $$(".brand-option").forEach((item) => item.classList.toggle("active", item === button));
    loadActiveDraft();
    schedulePreview();
  });
});
$("#quickText").addEventListener("input", () => {
  const draft = activeDraft();
  draft.text = $("#quickText").value;
  draft.parsed = null;
  draft.textVersion = "";
  draft.status = "";
  $("#parseStatus").textContent = "";
  schedulePreview();
});
$("#manualEditor").addEventListener("input", () => {
  activeDraft().data = collectFields();
  schedulePreview();
});
$("#parseButton").addEventListener("click", async () => {
  setMessage("");
  try {
    await interpret(true);
    setMessage("Informações distribuídas. Você já pode visualizar.", "success");
  } catch (error) {
    setMessage(error.message, "error");
  }
});
$("#photos").addEventListener("change", (event) => {
  const files = [...event.target.files];
  const draft = activeDraft();
  if (files.length !== 3) {
    draft.photos = [];
    renderPhotos();
    setMessage("Selecione exatamente três fotos.", "error");
    return;
  }
  draft.photos = files;
  renderPhotos();
  setMessage("Três fotos selecionadas.", "success");
  schedulePreview();
});
$("#previewButton").addEventListener("click", guardedPreview);
$("#generateButton").addEventListener("click", guardedProcess);
$("#openPreview").addEventListener("click", async () => {
  const deck = $("#previewDeck");
  if (deck.requestFullscreen) {
    try {
      await deck.requestFullscreen();
      return;
    } catch (_error) {
      // O Safari antigo pode bloquear a tela cheia.
    }
  }
  deck.scrollIntoView({ behavior: "smooth", block: "start" });
});
$("#installHelp").addEventListener("click", () => $("#installDialog").showModal());
$("#closeInstall").addEventListener("click", () => $("#installDialog").close());
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/static/sw.js"));
}
loadActiveDraft();

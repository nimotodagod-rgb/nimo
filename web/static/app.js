const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const DRAFT_STORAGE_KEY = "conquistando-drafts-v1";
const FIXED_HEADER_KEY = "conquistando-fixed-header-v1";
const PHOTO_DB_NAME = "conquistando-local";
const PHOTO_STORE = "brand-photos";

const state = {
  brand: "br-sport",
  fixedHeader: { codigo: "", razao: "", regional: "SPO", microrregiao: "" },
  drafts: {
    "br-sport": { text: "", photos: [], parsed: null, textVersion: "", data: null, status: "" },
    actvitta: { text: "", photos: [], parsed: null, textVersion: "", data: null, status: "" },
  },
  previewUrls: [],
  slideIndex: 0,
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

function setFixedHeaderStatus(text, kind = "") {
  const status = $("#fixedHeaderStatus");
  status.textContent = text;
  status.className = kind;
}

function fillFixedHeaderForm() {
  $("#fixedCodigo").value = state.fixedHeader.codigo;
  $("#fixedRazao").value = state.fixedHeader.razao;
  $("#fixedRegional").value = state.fixedHeader.regional || "SPO";
  $("#fixedMicrorregiao").value = state.fixedHeader.microrregiao;
}

function restoreFixedHeader() {
  try {
    const saved = JSON.parse(localStorage.getItem(FIXED_HEADER_KEY) || "null");
    if (!saved || typeof saved !== "object") return;
    state.fixedHeader = {
      codigo: String(saved.codigo || "").trim(),
      razao: String(saved.razao || "").trim(),
      regional: String(saved.regional || "SPO").trim(),
      microrregiao: String(saved.microrregiao || "").trim(),
    };
  } catch (_error) {
    localStorage.removeItem(FIXED_HEADER_KEY);
  }
}

function applyFixedHeader(data) {
  const target = data || emptyFields();
  Object.keys(state.fixedHeader).forEach((key) => {
    const value = String(state.fixedHeader[key] || "").trim();
    if (value) target[key] = value;
  });
  return target;
}

function updateDraftsWithFixedHeader() {
  Object.values(state.drafts).forEach((draft) => {
    draft.data = applyFixedHeader(draft.data || emptyFields());
    if (draft.parsed) draft.parsed = applyFixedHeader(draft.parsed);
  });
  persistDraftMetadata();
  loadActiveDraft();
  schedulePreview();
}

function setDraftStatus(text, kind = "") {
  const status = $("#draftStatus");
  status.textContent = text;
  status.className = `draft-status ${kind}`.trim();
}

function persistDraftMetadata() {
  const saved = {};
  Object.entries(state.drafts).forEach(([brand, draft]) => {
    saved[brand] = {
      text: draft.text,
      data: draft.data,
      status: draft.status,
      textVersion: draft.textVersion,
    };
  });
  localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(saved));
}

function restoreDraftMetadata() {
  try {
    const saved = JSON.parse(localStorage.getItem(DRAFT_STORAGE_KEY) || "{}");
    Object.keys(state.drafts).forEach((brand) => {
      const source = saved[brand];
      if (!source || typeof source !== "object") return;
      const draft = state.drafts[brand];
      draft.text = typeof source.text === "string" ? source.text : "";
      draft.data = source.data && typeof source.data === "object" ? source.data : null;
      draft.status = typeof source.status === "string" ? source.status : "";
      draft.textVersion =
        typeof source.textVersion === "string" ? source.textVersion : "";
      draft.parsed =
        draft.data && draft.textVersion === draft.text.trim() ? draft.data : null;
    });
  } catch (_error) {
    try {
      localStorage.removeItem(DRAFT_STORAGE_KEY);
    } catch (_storageError) {
      // O aplicativo continua funcionando mesmo se o navegador bloquear armazenamento.
    }
  }
}

let metadataTimer = null;
function queueMetadataSave() {
  clearTimeout(metadataTimer);
  setDraftStatus("Salvando rascunho…");
  metadataTimer = setTimeout(() => {
    try {
      persistDraftMetadata();
      setDraftStatus("Rascunho salvo neste aparelho.", "success");
    } catch (_error) {
      setDraftStatus("Não foi possível salvar o texto neste aparelho.", "error");
    }
  }, 180);
}

let photoDatabasePromise = null;
function openPhotoDatabase() {
  if (photoDatabasePromise) return photoDatabasePromise;
  photoDatabasePromise = new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) {
      reject(new Error("Armazenamento de fotos indisponível."));
      return;
    }
    const request = indexedDB.open(PHOTO_DB_NAME, 1);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(PHOTO_STORE)) {
        database.createObjectStore(PHOTO_STORE, { keyPath: "brand" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Falha ao abrir armazenamento."));
  });
  return photoDatabasePromise;
}

async function saveBrandPhotos(brand) {
  const database = await openPhotoDatabase();
  const photos = state.drafts[brand].photos.map((file, index) => ({
    blob: file,
    name: file.name || `foto-${index + 1}.jpg`,
    type: file.type || "image/jpeg",
    lastModified: file.lastModified || Date.now(),
  }));
  await new Promise((resolve, reject) => {
    const transaction = database.transaction(PHOTO_STORE, "readwrite");
    transaction.objectStore(PHOTO_STORE).put({ brand, photos });
    transaction.oncomplete = () => resolve();
    transaction.onerror = () =>
      reject(transaction.error || new Error("Falha ao salvar as fotos."));
    transaction.onabort = () =>
      reject(transaction.error || new Error("Salvamento das fotos cancelado."));
  });
}

async function readBrandPhotos(brand) {
  const database = await openPhotoDatabase();
  const record = await new Promise((resolve, reject) => {
    const transaction = database.transaction(PHOTO_STORE, "readonly");
    const request = transaction.objectStore(PHOTO_STORE).get(brand);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error || new Error("Falha ao ler as fotos."));
  });
  if (!record?.photos?.length) return [];
  return record.photos.map(
    (item, index) =>
      new File([item.blob], item.name || `foto-${index + 1}.jpg`, {
        type: item.type || item.blob?.type || "image/jpeg",
        lastModified: item.lastModified || Date.now(),
      })
  );
}

async function restoreAllPhotos() {
  for (const brand of Object.keys(state.drafts)) {
    state.drafts[brand].photos = await readBrandPhotos(brand);
  }
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

function autoResizeTextarea(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.max(textarea.scrollHeight, 92)}px`;
}

function resizeManualTextareas() {
  $$("#manualEditor textarea").forEach(autoResizeTextarea);
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
  if ($("#manualEditor").open) requestAnimationFrame(resizeManualTextareas);
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
  state.slideIndex = 0;
  $("#slideCounter").hidden = true;
}

function showSlide(index) {
  const slides = [...$("#previewDeck").children];
  if (!slides.length) return;
  state.slideIndex = (index + slides.length) % slides.length;
  slides.forEach((slide, slideIndex) => {
    slide.classList.toggle("active", slideIndex === state.slideIndex);
  });
  $("#slideCounter").textContent = `${state.slideIndex + 1} / ${slides.length}`;
  $("#slideCounter").hidden = false;
}

function saveActiveDraft() {
  const draft = activeDraft();
  draft.text = $("#quickText").value;
  draft.data = collectFields();
  try {
    persistDraftMetadata();
  } catch (_error) {
    setDraftStatus("Não foi possível salvar o rascunho neste aparelho.", "error");
  }
}

function loadActiveDraft() {
  const draft = activeDraft();
  $("#quickText").value = draft.text;
  draft.data = applyFixedHeader(draft.data || emptyFields());
  fillFields(draft.data);
  $("#parseStatus").textContent = draft.status;
  $("#photos").value = "";
  $("#brandDataTitle").textContent =
    state.brand === "br-sport" ? "Informações BR SPORT" : "Informações ACTVITTA";
  renderPhotos();
  clearPreview();
  setMessage("");
  const hasSavedContent = Boolean(draft.text || draft.data || draft.photos.length);
  setDraftStatus(
    hasSavedContent
      ? "Rascunho desta marca restaurado."
      : "Salvamento automático ativado para esta marca.",
    hasSavedContent ? "success" : ""
  );
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
  result.data = applyFixedHeader(result.data);
  draft.parsed = result.data;
  draft.textVersion = text;
  draft.text = text;
  draft.data = result.data;
  fillFields(result.data);
  draft.status = result.missing.length
    ? `${result.missing.length} campo(s) precisam de revisão`
    : "Informações prontas";
  $("#parseStatus").textContent = draft.status;
  queueMetadataSave();
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
    ["1.", values.vendas],
    ["2.", values.marketing],
    ["3.", values.carteira],
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
  showSlide(0);
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

function brandLabel(brand) {
  return brand === "br-sport" ? "BR SPORT" : "ACTVITTA";
}

async function prepareBrandDraft(brand) {
  if (brand === state.brand) saveActiveDraft();
  const draft = state.drafts[brand];
  const text = draft.text.trim();
  if (!text) throw new Error(`${brandLabel(brand)}: cole as informações.`);
  if (draft.photos.length !== 3) {
    throw new Error(`${brandLabel(brand)}: selecione exatamente três fotos.`);
  }
  if (!draft.parsed || draft.textVersion !== text) {
    const response = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...pinHeaders() },
      body: JSON.stringify({ text }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(`${brandLabel(brand)}: ${result.error || "falha ao interpretar."}`);
    }
    draft.parsed = applyFixedHeader(result.data);
    draft.data = draft.parsed;
    draft.textVersion = text;
    draft.status = result.missing.length
      ? `${result.missing.length} campo(s) precisam de revisão`
      : "Informações prontas";
  } else {
    draft.data = applyFixedHeader(draft.data || draft.parsed);
  }
  validatePreviewData(draft.data);
  persistDraftMetadata();
  return draft;
}

async function processBrandPowerPoint(brand, draft) {
  const form = new FormData();
  form.append("brand", brand);
  form.append("mode", "generate");
  form.append("text", draft.text);
  form.append("parsed_json", JSON.stringify(draft.data));
  draft.photos.forEach((photo) => form.append("photos", photo, photo.name));

  const response = await fetch("/api/process", {
    method: "POST",
    headers: pinHeaders(),
    body: form,
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(
      `${brandLabel(brand)}: ${result.error || "não foi possível gerar o PowerPoint."}`
    );
  }
  const blob = await response.blob();
  downloadBlob(blob, filenameFromDisposition(response));
}

async function guardedGenerate(brands) {
  setBusy(true);
  setMessage("");
  $("#generateDialog").close();
  try {
    const prepared = [];
    for (const brand of brands) {
      prepared.push([brand, await prepareBrandDraft(brand)]);
    }
    for (const [brand, draft] of prepared) {
      await processBrandPowerPoint(brand, draft);
    }
    setMessage(
      brands.length === 2
        ? "Os dois PowerPoints foram gerados. Confira seus downloads."
        : `${brandLabel(brands[0])} gerado. Confira seus downloads.`,
      "success"
    );
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
$("#saveFixedHeader").addEventListener("click", () => {
  const fixed = {
    codigo: $("#fixedCodigo").value.trim(),
    razao: $("#fixedRazao").value.trim(),
    regional: $("#fixedRegional").value.trim(),
    microrregiao: $("#fixedMicrorregiao").value.trim(),
  };
  if (Object.values(fixed).some((value) => !value)) {
    setFixedHeaderStatus("Preencha os quatro campos.", "error");
    $("#fixedHeaderSettings").open = true;
    return;
  }
  try {
    state.fixedHeader = fixed;
    localStorage.setItem(FIXED_HEADER_KEY, JSON.stringify(fixed));
    updateDraftsWithFixedHeader();
    setFixedHeaderStatus("Salvo para BR SPORT e ACTVITTA.", "success");
  } catch (_error) {
    setFixedHeaderStatus("Não foi possível salvar neste aparelho.", "error");
  }
});
$("#clearFixedHeader").addEventListener("click", () => {
  state.fixedHeader = { codigo: "", razao: "", regional: "SPO", microrregiao: "" };
  localStorage.removeItem(FIXED_HEADER_KEY);
  Object.values(state.drafts).forEach((draft) => {
    if (draft.data) {
      draft.data.codigo = "";
      draft.data.razao = "";
      draft.data.regional = "SPO";
      draft.data.microrregiao = "";
    }
    draft.parsed = null;
    draft.textVersion = "";
  });
  fillFixedHeaderForm();
  persistDraftMetadata();
  loadActiveDraft();
  setFixedHeaderStatus("Dados fixos removidos.");
});
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
  queueMetadataSave();
  schedulePreview();
});
$("#manualEditor").addEventListener("input", (event) => {
  if (event.target.matches("textarea")) autoResizeTextarea(event.target);
  activeDraft().data = collectFields();
  queueMetadataSave();
  schedulePreview();
});
$("#manualEditor").addEventListener("toggle", () => {
  if ($("#manualEditor").open) requestAnimationFrame(resizeManualTextareas);
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
$("#photos").addEventListener("change", async (event) => {
  const files = [...event.target.files];
  const brand = state.brand;
  const draft = activeDraft();
  if (files.length !== 3) {
    draft.photos = [];
    renderPhotos();
    setMessage("Selecione exatamente três fotos.", "error");
    try {
      await saveBrandPhotos(brand);
    } catch (_error) {
      setDraftStatus("Não foi possível atualizar as fotos salvas.", "error");
    }
    return;
  }
  draft.photos = files;
  renderPhotos();
  schedulePreview();
  setDraftStatus("Salvando as três fotos…");
  try {
    await saveBrandPhotos(brand);
    setMessage("Três fotos selecionadas.", "success");
    setDraftStatus("Texto e fotos salvos neste aparelho.", "success");
  } catch (_error) {
    setMessage("As fotos foram selecionadas, mas não puderam ser salvas.", "error");
    setDraftStatus("Mantenha o aplicativo aberto até gerar o PowerPoint.", "error");
  }
});
$("#previewButton").addEventListener("click", guardedPreview);
$("#generateButton").addEventListener("click", () => $("#generateDialog").showModal());
$("#closeGenerateDialog").addEventListener("click", () => $("#generateDialog").close());
$$("[data-generate-brand]").forEach((button) => {
  button.addEventListener("click", () => {
    const selected = button.dataset.generateBrand;
    guardedGenerate(selected === "all" ? ["br-sport", "actvitta"] : [selected]);
  });
});
$("#openPreview").addEventListener("click", async () => {
  const viewer = $("#previewViewer");
  viewer.classList.add("slide-show-mode");
  document.body.classList.add("slide-show-open");
  showSlide(0);
  const requestFullscreen = viewer.requestFullscreen || viewer.webkitRequestFullscreen;
  if (requestFullscreen) {
    try {
      await requestFullscreen.call(viewer);
      return;
    } catch (_error) {
      // O modo sobreposto permanece ativo quando o Safari não aceita Fullscreen.
    }
  }
});
$("#previousSlide").addEventListener("click", () => showSlide(state.slideIndex - 1));
$("#nextSlide").addEventListener("click", () => showSlide(state.slideIndex + 1));
$("#closeFullscreen").addEventListener("click", async () => {
  const fullscreenElement = document.fullscreenElement || document.webkitFullscreenElement;
  const exitFullscreen = document.exitFullscreen || document.webkitExitFullscreen;
  if (fullscreenElement && exitFullscreen) {
    try {
      await exitFullscreen.call(document);
    } catch (_error) {
      // O modo visual também é encerrado abaixo.
    }
  }
  $("#previewViewer").classList.remove("slide-show-mode");
  document.body.classList.remove("slide-show-open");
});
function handleFullscreenExit() {
  if (!document.fullscreenElement && !document.webkitFullscreenElement) {
    $("#previewViewer").classList.remove("slide-show-mode");
    document.body.classList.remove("slide-show-open");
  }
}
document.addEventListener("fullscreenchange", handleFullscreenExit);
document.addEventListener("webkitfullscreenchange", handleFullscreenExit);
$("#installHelp").addEventListener("click", () => $("#installDialog").showModal());
$("#closeInstall").addEventListener("click", () => $("#installDialog").close());
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/static/sw.js"));
}

function saveBeforeLeaving() {
  try {
    saveActiveDraft();
  } catch (_error) {
    // A gravação normal por digitação continua sendo a principal proteção.
  }
}
window.addEventListener("pagehide", saveBeforeLeaving);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") saveBeforeLeaving();
});

async function initializeDraftStorage() {
  restoreFixedHeader();
  fillFixedHeaderForm();
  if (Object.values(state.fixedHeader).every((value) => String(value).trim())) {
    setFixedHeaderStatus("Dados fixos carregados.", "success");
  }
  restoreDraftMetadata();
  setDraftStatus("Restaurando o rascunho deste aparelho…");
  try {
    if (navigator.storage?.persist) await navigator.storage.persist();
    await restoreAllPhotos();
    loadActiveDraft();
    schedulePreview();
  } catch (_error) {
    loadActiveDraft();
    setDraftStatus(
      "Textos restaurados. As fotos precisarão ser selecionadas novamente.",
      "error"
    );
  }
}

initializeDraftStorage();

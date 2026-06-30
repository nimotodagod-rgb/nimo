const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const DRAFT_STORAGE_KEY = "conquistando-drafts-v1";
const FIXED_HEADER_KEY = "conquistando-fixed-header-v1";
const PHOTO_DB_NAME = "conquistando-local";
const PHOTO_STORE = "brand-photos";
const QUICK_TEMPLATE = `AÇÕES BEM SUCEDIDAS
VENDAS:


MKT:


CARTEIRA DE CLIENTES:

PONTOS DE MELHORIA
VENDAS:


MKT:


CARTEIRA DE CLIENTES:

FOTO 1

código/cliente:
Cidade:
Pares:

FOTO 2

código/cliente:
Cidade:
Pares:

FOTO 3

código/cliente:
Cidade:
Pares:`;

const state = {
  brand: "br-sport",
  fixedHeader: { codigo: "", razao: "", regional: "", microrregiao: "" },
  drafts: {
    "br-sport": { text: "", photos: [], parsed: null, textVersion: "", data: null, status: "" },
    actvitta: { text: "", photos: [], parsed: null, textVersion: "", data: null, status: "" },
  },
  previewUrls: [],
  slideIndex: 0,
  draftsInitialized: false,
  paymentRequired: false,
  paymentUrl: "",
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
    regional: "",
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

function setTemplateStatus(text, kind = "") {
  const status = $("#templateStatus");
  status.textContent = text;
  status.className = kind;
}

function setLoginStatus(text, kind = "") {
  const status = $("#loginStatus");
  status.textContent = text;
  status.className = `message ${kind}`.trim();
}

function setPaymentLink(url = "") {
  const button = $("#paymentButton");
  if (!url) {
    button.hidden = true;
    button.removeAttribute("href");
    return;
  }
  button.hidden = false;
  button.href = url;
}

function setTopPayment(session = {}) {
  const button = $("#topPaymentButton");
  const needsPayment = Boolean(session.payment_required);
  const url = session.payment_url || "";
  button.hidden = !needsPayment;
  button.classList.toggle("disabled", needsPayment && !url);
  if (!needsPayment) {
    button.removeAttribute("href");
    return;
  }
  button.textContent = "Assinar";
  if (url) {
    button.href = url;
  } else {
    button.removeAttribute("href");
  }
}

function setSubscriptionState(session = {}) {
  state.paymentRequired = Boolean(session.payment_required);
  state.paymentUrl = session.payment_url || "";
  $("#quickText").readOnly = state.paymentRequired;
  $$("#manualEditor textarea, #manualEditor input, #fixedHeaderSettings input").forEach((field) => {
    field.readOnly = state.paymentRequired;
  });
  $("#photos").disabled = false;
  $$(".single-photo-input").forEach((field) => {
    field.disabled = false;
  });
  $("#appShell").classList.toggle("subscription-locked", state.paymentRequired);
}

function showSubscriptionRequired() {
  const url = state.paymentUrl || "";
  const link = $("#subscriptionPaymentLink");
  link.hidden = !url;
  if (url) link.href = url;
  else link.removeAttribute("href");
  setMessage("É necessário realizar a assinatura para editar e gerar PowerPoint.", "error");
  const dialog = $("#subscriptionDialog");
  if (dialog?.showModal) dialog.showModal();
}

function requiresSubscription() {
  if (!state.paymentRequired) return false;
  showSubscriptionRequired();
  return true;
}

function setAuthMode(mode) {
  const signup = mode === "signup";
  $("#loginForm").hidden = signup;
  $("#signupForm").hidden = !signup;
  $("#loginTab").classList.toggle("active", !signup);
  $("#signupTab").classList.toggle("active", signup);
  $("#authTitle").textContent = signup
    ? "Crie sua conta no Editor Conquistando"
    : "Entre para usar o Editor Conquistando";
  $("#authCopy").textContent = signup
    ? "Informe seus dados para iniciar o cadastro. Depois você será enviado para o pagamento."
    : "O editor comercial usa login. Se o acesso ainda não estiver liberado, você será enviado para o pagamento.";
  setLoginStatus("");
  setPaymentLink("");
}

function setAuthenticated(session = {}) {
  $("#authPanel").hidden = true;
  $("#appShell").hidden = false;
  $("#appShell").classList.remove("auth-locked");
  $("#sessionChip").hidden = false;
  $("#sessionLabel").textContent =
    session.role === "dev"
      ? "Desenvolvedor"
      : session.name || session.email || "Usuário liberado";
  setTopPayment(session);
  setSubscriptionState(session);
  setLoginStatus("");
}

function setLocked(session = {}) {
  $("#authPanel").hidden = false;
  $("#appShell").hidden = false;
  $("#appShell").classList.add("auth-locked");
  $("#sessionChip").hidden = true;
  setTopPayment({});
  setSubscriptionState({});
  setPaymentLink(session.payment_url || "");
}

async function readSession() {
  const response = await fetch("/api/session");
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error("Não foi possível verificar o acesso.");
  return result;
}

async function unlockWithSavedPin() {
  const savedPin = localStorage.getItem("conquistando-pin") || "";
  if (!savedPin) return false;
  const response = await fetch("/api/dev-pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin: savedPin }),
  });
  return response.ok;
}

async function initializeEditorOnce() {
  if (state.draftsInitialized) return;
  state.draftsInitialized = true;
  await initializeDraftStorage();
}

async function refreshAccess() {
  try {
    let session = await readSession();
    if (!session.has_access && (await unlockWithSavedPin())) {
      session = await readSession();
    }
    await initializeEditorOnce();
    if (session.has_access) {
      setAuthenticated(session);
    } else {
      setLocked(session);
    }
  } catch (error) {
    setLocked({});
    setLoginStatus(error.message, "error");
  }
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const helper = document.createElement("textarea");
  helper.value = text;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.left = "-9999px";
  document.body.append(helper);
  helper.select();
  const ok = document.execCommand("copy");
  helper.remove();
  if (!ok) throw new Error("Não foi possível copiar automaticamente.");
}

function fillFixedHeaderForm() {
  $("#fixedCodigo").value = state.fixedHeader.codigo;
  $("#fixedRazao").value = state.fixedHeader.razao;
  $("#fixedRegional").value = state.fixedHeader.regional;
  $("#fixedMicrorregiao").value = state.fixedHeader.microrregiao;
}

function restoreFixedHeader() {
  try {
    const saved = JSON.parse(localStorage.getItem(FIXED_HEADER_KEY) || "null");
    if (!saved || typeof saved !== "object") return;
    state.fixedHeader = {
      codigo: String(saved.codigo || "").trim(),
      razao: String(saved.razao || "").trim(),
      regional: String(saved.regional || "").trim(),
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
  const photos = normalizePhotoList(state.drafts[brand].photos).map((file, index) =>
    file
      ? {
          blob: file,
          name: file.name || `foto-${index + 1}.jpg`,
          type: file.type || "image/jpeg",
          lastModified: file.lastModified || Date.now(),
        }
      : null
  );
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
  return normalizePhotoList(record.photos).map((item, index) =>
    item?.blob
      ? new File([item.blob], item.name || `foto-${index + 1}.jpg`, {
        type: item.type || item.blob?.type || "image/jpeg",
        lastModified: item.lastModified || Date.now(),
      })
      : null
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

function normalizePhotoList(photos = []) {
  return [0, 1, 2].map((index) => photos[index] || null);
}

function hasThreePhotos(photos = []) {
  return normalizePhotoList(photos).every(Boolean);
}

function quickTextFromData(data) {
  return `AÇÕES BEM SUCEDIDAS
VENDAS:
${data.acoes?.vendas || ""}

MKT:
${data.acoes?.marketing || ""}

CARTEIRA DE CLIENTES:
${data.acoes?.carteira || ""}

PONTOS DE MELHORIA
VENDAS:
${data.melhorias?.vendas || ""}

MKT:
${data.melhorias?.marketing || ""}

CARTEIRA DE CLIENTES:
${data.melhorias?.carteira || ""}

FOTO 1
${data.fotos?.[0]?.cliente || ""}
${data.fotos?.[0]?.cidade || ""}
${data.fotos?.[0]?.pares || ""}

FOTO 2
${data.fotos?.[1]?.cliente || ""}
${data.fotos?.[1]?.cidade || ""}
${data.fotos?.[1]?.pares || ""}

FOTO 3
${data.fotos?.[2]?.cliente || ""}
${data.fotos?.[2]?.cidade || ""}
${data.fotos?.[2]?.pares || ""}`;
}

function importedPhotoFile(photo, index) {
  const binary = atob(photo.data || "");
  const bytes = new Uint8Array(binary.length);
  for (let position = 0; position < binary.length; position += 1) {
    bytes[position] = binary.charCodeAt(position);
  }
  return new File([bytes], photo.name || `foto-importada-${index + 1}.jpg`, {
    type: photo.type || "image/jpeg",
    lastModified: Date.now(),
  });
}

function activateBrand(brand) {
  if (!state.drafts[brand] || brand === state.brand) return;
  saveActiveDraft();
  state.brand = brand;
  $$(".brand-option").forEach((item) =>
    item.classList.toggle("active", item.dataset.brand === brand)
  );
  loadActiveDraft();
  schedulePreview();
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

function updateSlideShowSize() {
  const viewer = $("#previewViewer");
  if (!viewer.classList.contains("slide-show-mode")) return;
  const compact = window.innerWidth <= 600;
  const horizontalReserve = compact ? 92 : 150;
  const verticalReserve = compact ? 128 : 76;
  const widthByScreen = window.innerWidth - horizontalReserve;
  const widthByHeight = (window.innerHeight - verticalReserve) * (16 / 9);
  const width = Math.max(280, Math.min(1200, widthByScreen, widthByHeight));
  viewer.style.setProperty("--slide-show-width", `${Math.floor(width)}px`);
}

function closeSlideShowMode() {
  const viewer = $("#previewViewer");
  viewer.classList.remove("slide-show-mode");
  viewer.style.removeProperty("--slide-show-width");
  document.body.classList.remove("slide-show-open");
  window.removeEventListener("resize", updateSlideShowSize);
  window.removeEventListener("orientationchange", updateSlideShowSize);
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
  const photos = normalizePhotoList(activeDraft().photos);
  const slots = $$("#photoGrid .photo-slot");
  slots.forEach((slot, index) => {
    const file = photos[index];
    const number = `<b>${index + 1}</b>`;
    if (!file) {
      slot.classList.remove("has-photo");
      slot.innerHTML = `${number}<span>Escolher foto ${index + 1}</span>`;
      return;
    }
    const url = URL.createObjectURL(file);
    slot.classList.add("has-photo");
    slot.innerHTML = `${number}<img alt="Foto ${index + 1}">`;
    slot.querySelector("img").src = url;
    slot.querySelector("img").onload = () => URL.revokeObjectURL(url);
  });
}

async function savePhotoSelection(brand, successMessage) {
  renderPhotos();
  schedulePreview();
  setDraftStatus("Salvando fotos…");
  try {
    await saveBrandPhotos(brand);
    setMessage(successMessage, "success");
    setDraftStatus("Texto e fotos salvos neste aparelho.", "success");
  } catch (_error) {
    setMessage("As fotos foram selecionadas, mas não puderam ser salvas.", "error");
    setDraftStatus("Mantenha o aplicativo aberto até gerar o PowerPoint.", "error");
  }
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function appendMarkedText(parent, value = "") {
  const text = String(value || "");
  const pattern = /\*\*(.+?)\*\*/g;
  let cursor = 0;
  let match;
  while ((match = pattern.exec(text))) {
    if (match.index > cursor) {
      parent.append(document.createTextNode(text.slice(cursor, match.index)));
    }
    parent.append(element("strong", "", match[1]));
    cursor = pattern.lastIndex;
  }
  if (cursor < text.length) parent.append(document.createTextNode(text.slice(cursor)));
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
      `${data.regional || "regional"} – ${data.microrregiao || "microrregião"}`
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
    row.append(element("strong", "", label), document.createTextNode(" "));
    appendMarkedText(row, value);
    body.append(row);
  });
  slide.append(body);
  return slide;
}

function createPhotoSlide(data) {
  const slide = element("article", "ppt-slide");
  addSlideHeader(slide, "Imagens", data);
  const grid = element("div", "ppt-photos");
  normalizePhotoList(activeDraft().photos).forEach((file, index) => {
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
    ["Representante — Código", data.codigo],
    ["Representante — Razão social", data.razao],
    ["Representante — Regional", data.regional],
    ["Representante — Microrregião", data.microrregiao],
  ].forEach(([label, value]) => {
    if (!value) missing.push(label);
  });
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
  if (!hasThreePhotos(draft.photos)) throw new Error("Selecione exatamente três fotos.");
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
  if (!hasThreePhotos(activeDraft().photos) || !$("#quickText").value.trim()) return;
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
  if (!hasThreePhotos(draft.photos)) {
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
  normalizePhotoList(draft.photos).forEach((photo) => form.append("photos", photo, photo.name));

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
$("#templateText").value = QUICK_TEMPLATE;
$("#pin").value = localStorage.getItem("conquistando-pin") || "";
$("#copyTemplate").addEventListener("click", async () => {
  try {
    await copyTextToClipboard(QUICK_TEMPLATE);
    setTemplateStatus("Modelo copiado.", "success");
  } catch (_error) {
    $("#templateText").focus();
    $("#templateText").select();
    setTemplateStatus("Selecione e copie manualmente.", "error");
  }
});
$("#insertTemplate").addEventListener("click", () => {
  if (requiresSubscription()) return;
  if ($("#quickText").value.trim()) {
    setTemplateStatus("O campo já tem texto. Copie o modelo se quiser usar fora.", "error");
    return;
  }
  $("#quickText").value = QUICK_TEMPLATE;
  $("#quickText").dispatchEvent(new Event("input", { bubbles: true }));
  $("#quickText").focus();
  setTemplateStatus("Modelo colocado no campo.", "success");
});
function toggleBoldSelection() {
  if (requiresSubscription()) return;
  const field = $("#quickText");
  const start = field.selectionStart;
  const end = field.selectionEnd;
  const value = field.value;
  const selected = value.slice(start, end);
  let replacement;
  let selectionStart;
  let selectionEnd;
  let replaceStart = start;
  let replaceEnd = end;
  if (selected.startsWith("**") && selected.endsWith("**") && selected.length >= 4) {
    replacement = selected.slice(2, -2);
    selectionStart = start;
    selectionEnd = start + replacement.length;
  } else if (
    start >= 2 &&
    value.slice(start - 2, start) === "**" &&
    value.slice(end, end + 2) === "**"
  ) {
    replacement = selected;
    replaceStart = start - 2;
    replaceEnd = end + 2;
    selectionStart = replaceStart;
    selectionEnd = replaceStart + replacement.length;
  } else {
    replacement = `**${selected}**`;
    selectionStart = start + 2;
    selectionEnd = selected ? end + 2 : start + 2;
  }
  field.setRangeText(replacement, replaceStart, replaceEnd, "end");
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.focus();
  field.setSelectionRange(selectionStart, selectionEnd);
}
$("#boldButton").addEventListener("pointerdown", (event) => {
  // Mantém a seleção do textarea ao tocar no botão, inclusive no Safari/iPad.
  event.preventDefault();
});
$("#boldButton").addEventListener("click", toggleBoldSelection);
$("#quickText").addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "b") {
    event.preventDefault();
    toggleBoldSelection();
  }
});
$("#saveFixedHeader").addEventListener("click", () => {
  if (requiresSubscription()) return;
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
    setFixedHeaderStatus("Representante salvo para BR SPORT e ACTVITTA.", "success");
    setMessage(
      "Representante confirmado. Revise código, razão social, regional e microrregião antes de gerar o PowerPoint.",
      "success"
    );
  } catch (_error) {
    setFixedHeaderStatus("Não foi possível salvar neste aparelho.", "error");
  }
});
$("#clearFixedHeader").addEventListener("click", () => {
  if (requiresSubscription()) return;
  state.fixedHeader = { codigo: "", razao: "", regional: "", microrregiao: "" };
  localStorage.removeItem(FIXED_HEADER_KEY);
  Object.values(state.drafts).forEach((draft) => {
    if (draft.data) {
      draft.data.codigo = "";
      draft.data.razao = "";
      draft.data.regional = "";
      draft.data.microrregiao = "";
    }
    draft.parsed = null;
    draft.textVersion = "";
  });
  fillFixedHeaderForm();
  persistDraftMetadata();
  loadActiveDraft();
  setFixedHeaderStatus("Representante removido.");
});
$("#confirmPin").addEventListener("click", async () => {
  const pin = $("#pin").value.trim();
  const status = $("#pinStatus");
  status.textContent = "Verificando…";
  status.className = "";
  try {
    const response = await fetch("/api/dev-pin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    if (!response.ok) throw new Error("PIN incorreto");
    localStorage.setItem("conquistando-pin", pin);
    status.textContent = "Acesso desenvolvedor liberado";
    status.className = "success";
    await refreshAccess();
  } catch (_error) {
    status.textContent = "PIN incorreto";
    status.className = "error";
  }
});
$("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  setLoginStatus("Verificando acesso…");
  setPaymentLink("");
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: $("#loginEmail").value.trim(),
        password: $("#loginPassword").value,
      }),
    });
    const result = await response.json();
    if (response.status === 402 && result.payment_url) {
      setLoginStatus("Acesso ainda não liberado. Indo para o pagamento…", "error");
      setPaymentLink(result.payment_url);
      window.location.href = result.payment_url;
      return;
    }
    if (!response.ok || !result.ok) throw new Error(result.error || "Não foi possível entrar.");
    $("#loginPassword").value = "";
    setLoginStatus("Acesso liberado.", "success");
    await refreshAccess();
  } catch (error) {
    setLoginStatus(error.message, "error");
  }
});
$("#signupForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  setLoginStatus("Criando conta…");
  setPaymentLink("");
  const password = $("#signupPassword").value;
  const confirmation = $("#signupPasswordConfirm").value;
  if (password !== confirmation) {
    setLoginStatus("As senhas não conferem.", "error");
    $("#signupPasswordConfirm").focus();
    return;
  }
  try {
    const response = await fetch("/api/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("#signupName").value.trim(),
        email: $("#signupEmail").value.trim(),
        password,
        password_confirm: confirmation,
      }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "Não foi possível criar a conta.");
    $("#signupPassword").value = "";
    $("#signupPasswordConfirm").value = "";
    setLoginStatus(result.message || "Conta criada.", "success");
    await refreshAccess();
  } catch (error) {
    setLoginStatus(error.message, "error");
  }
});
$$(".toggle-password").forEach((button) => {
  button.addEventListener("click", () => {
    const input = $(`#${button.dataset.togglePassword}`);
    const showing = input.type === "text";
    input.type = showing ? "password" : "text";
    button.textContent = showing ? "Ver" : "Ocultar";
    button.setAttribute("aria-label", showing ? "Ver senha" : "Ocultar senha");
  });
});
$("#loginTab").addEventListener("click", () => setAuthMode("login"));
$("#signupTab").addEventListener("click", () => setAuthMode("signup"));
$("#logoutButton").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" }).catch(() => {});
  localStorage.removeItem("conquistando-pin");
  $("#pin").value = "";
  state.draftsInitialized = false;
  $("#appShell").classList.add("auth-locked");
  $("#sessionChip").hidden = true;
  setTopPayment({});
  await refreshAccess();
});
$$(".brand-option").forEach((button) => {
  button.addEventListener("click", () => activateBrand(button.dataset.brand));
});
$("#importPowerPointButton").addEventListener("click", () => {
  if (requiresSubscription()) return;
  $("#powerPointImport").click();
});
$("#powerPointImport").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".pptx")) {
    setMessage("Use um arquivo .pptx. No PowerPoint antigo, escolha Salvar como .pptx.", "error");
    event.target.value = "";
    return;
  }
  const inferredBrand = /actvitta/i.test(file.name)
    ? "actvitta"
    : /br[\s_-]*sport/i.test(file.name)
      ? "br-sport"
      : state.brand;
  const brandName = brandLabel(inferredBrand);
  const confirmed = window.confirm(
    `Abrir este PowerPoint em ${brandName}? As informações atuais desta marca serão substituídas.`
  );
  if (!confirmed) {
    event.target.value = "";
    return;
  }
  activateBrand(inferredBrand);
  setBusy(true);
  setMessage("Lendo o PowerPoint…");
  try {
    const form = new FormData();
    form.append("powerpoint", file, file.name);
    const response = await fetch("/api/import-powerpoint", {
      method: "POST",
      headers: pinHeaders(),
      body: form,
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || "Não foi possível abrir este PowerPoint.");
    }

    const importedHeader = {
      codigo: String(result.data?.codigo || "").trim(),
      razao: String(result.data?.razao || "").trim(),
      regional: String(result.data?.regional || "").trim(),
      microrregiao: String(result.data?.microrregiao || "").trim(),
    };
    if (Object.values(importedHeader).every(Boolean)) {
      state.fixedHeader = importedHeader;
      localStorage.setItem(FIXED_HEADER_KEY, JSON.stringify(importedHeader));
      fillFixedHeaderForm();
      updateDraftsWithFixedHeader();
    }

    const data = applyFixedHeader(result.data || emptyFields());
    const text = quickTextFromData(data);
    const draft = activeDraft();
    draft.text = text;
    draft.data = data;
    draft.parsed = data;
    draft.textVersion = text.trim();
    draft.status = result.missing?.length
      ? `${result.missing.length} campo(s) precisam de revisão`
      : "PowerPoint importado e pronto para revisão";
    draft.photos = normalizePhotoList(
      (result.photos || []).map((photo, index) => importedPhotoFile(photo, index))
    );
    $("#quickText").value = text;
    fillFields(data);
    $("#parseStatus").textContent = draft.status;
    renderPhotos();
    persistDraftMetadata();
    await saveBrandPhotos(state.brand).catch(() => {});
    clearPreview();
    schedulePreview();
    if (result.missing?.length) $("#manualEditor").open = true;

    const photoMessage =
      result.photo_count === 3
        ? "As três fotos também foram recuperadas."
        : `Foram recuperadas ${result.photo_count || 0} de 3 fotos; selecione as restantes.`;
    setMessage(
      `PowerPoint aberto. Revise as informações antes de gerar novamente. ${photoMessage}`,
      result.missing?.length ? "error" : "success"
    );
    setDraftStatus("PowerPoint importado e salvo neste aparelho.", "success");
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    event.target.value = "";
    setBusy(false);
  }
});
$("#quickText").addEventListener("input", () => {
  if (state.paymentRequired) return;
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
  if (state.paymentRequired) return;
  if (event.target.matches("textarea")) autoResizeTextarea(event.target);
  activeDraft().data = collectFields();
  queueMetadataSave();
  schedulePreview();
});
$("#manualEditor").addEventListener("toggle", () => {
  if ($("#manualEditor").open) requestAnimationFrame(resizeManualTextareas);
});
$$(
  "#quickText, #manualEditor textarea, #manualEditor input, #fixedHeaderSettings input"
).forEach((field) => {
  field.addEventListener("pointerdown", (event) => {
    if (!state.paymentRequired) return;
    event.preventDefault();
    showSubscriptionRequired();
  });
});
$(".upload").addEventListener("click", (event) => {
  if (!state.paymentRequired) return;
  event.preventDefault();
  showSubscriptionRequired();
});
$("#parseButton").addEventListener("click", async () => {
  if (requiresSubscription()) return;
  setMessage("");
  try {
    await interpret(true);
    setMessage("Informações distribuídas. Você já pode visualizar.", "success");
  } catch (error) {
    setMessage(error.message, "error");
  }
});
$("#photos").addEventListener("change", async (event) => {
  if (requiresSubscription()) {
    event.target.value = "";
    return;
  }
  const files = [...event.target.files];
  const brand = state.brand;
  const draft = activeDraft();
  if (files.length !== 3) {
    draft.photos = [null, null, null];
    renderPhotos();
    setMessage("Selecione exatamente três fotos.", "error");
    try {
      await saveBrandPhotos(brand);
    } catch (_error) {
      setDraftStatus("Não foi possível atualizar as fotos salvas.", "error");
    }
    return;
  }
  draft.photos = normalizePhotoList(files);
  await savePhotoSelection(brand, "Três fotos selecionadas.");
});
$$("#photoGrid .photo-slot").forEach((slot) => {
  slot.addEventListener("click", () => {
    if (requiresSubscription()) return;
    const index = Number(slot.dataset.photoIndex);
    $(`#photoSingle${index}`).click();
  });
});
$$(".single-photo-input").forEach((input, index) => {
  input.addEventListener("change", async (event) => {
    if (requiresSubscription()) {
      event.target.value = "";
      return;
    }
    const file = event.target.files?.[0];
    if (!file) return;
    const brand = state.brand;
    const draft = activeDraft();
    draft.photos = normalizePhotoList(draft.photos);
    draft.photos[index] = file;
    event.target.value = "";
    await savePhotoSelection(brand, `Foto ${index + 1} selecionada.`);
  });
});
$("#previewButton").addEventListener("click", () => {
  if (requiresSubscription()) return;
  guardedPreview();
});
$("#generateButton").addEventListener("click", () => {
  if (requiresSubscription()) return;
  $("#generateDialog").showModal();
});
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
  updateSlideShowSize();
  window.addEventListener("resize", updateSlideShowSize);
  window.addEventListener("orientationchange", updateSlideShowSize);
  requestAnimationFrame(updateSlideShowSize);
  const requestFullscreen = viewer.requestFullscreen || viewer.webkitRequestFullscreen;
  if (requestFullscreen) {
    try {
      await requestFullscreen.call(viewer);
      requestAnimationFrame(updateSlideShowSize);
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
  closeSlideShowMode();
});
function handleFullscreenExit() {
  if (!document.fullscreenElement && !document.webkitFullscreenElement) {
    closeSlideShowMode();
  } else {
    updateSlideShowSize();
  }
}
document.addEventListener("fullscreenchange", handleFullscreenExit);
document.addEventListener("webkitfullscreenchange", handleFullscreenExit);
$("#installHelp").addEventListener("click", () => $("#installDialog").showModal());
$("#closeInstall").addEventListener("click", () => $("#installDialog").close());
$("#closeSubscriptionDialog").addEventListener("click", () => $("#subscriptionDialog").close());

function saveBeforeLeaving() {
  try {
    saveActiveDraft();
  } catch (_error) {
    // A gravação normal por digitação continua sendo a principal proteção.
  }
}

function showUpdateNotice(registration) {
  const notice = $("#updateNotice");
  notice.hidden = false;
  $("#updateNow").onclick = () => {
    saveBeforeLeaving();
    if (registration?.waiting) {
      registration.waiting.postMessage({ type: "SKIP_WAITING" });
    } else {
      window.location.reload();
    }
  };
}

function watchServiceWorker(registration) {
  if (registration.waiting && navigator.serviceWorker.controller) {
    showUpdateNotice(registration);
  }
  registration.addEventListener("updatefound", () => {
    const worker = registration.installing;
    if (!worker) return;
    worker.addEventListener("statechange", () => {
      if (worker.state === "installed" && navigator.serviceWorker.controller) {
        showUpdateNotice(registration);
      }
    });
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") registration.update();
  });
  setInterval(() => registration.update(), 30 * 60 * 1000);
}

function setupServiceWorkerUpdates() {
  if (!("serviceWorker" in navigator)) return;
  let refreshing = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (refreshing) return;
    refreshing = true;
    window.location.reload();
  });
  window.addEventListener("load", async () => {
    try {
      const registration = await navigator.serviceWorker.register("/static/sw.js");
      watchServiceWorker(registration);
      registration.update();
    } catch (_error) {
      // O app continua funcionando sem cache offline.
    }
  });
}

setupServiceWorkerUpdates();
window.addEventListener("pagehide", saveBeforeLeaving);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") saveBeforeLeaving();
});

async function initializeDraftStorage() {
  restoreFixedHeader();
  fillFixedHeaderForm();
  if (Object.values(state.fixedHeader).every((value) => String(value).trim())) {
    setFixedHeaderStatus("Representante carregado.", "success");
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

refreshAccess();

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  brand: "br-sport",
  photos: [],
  parsed: null,
  textVersion: "",
  previewUrl: null,
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

async function interpret(force = false) {
  const text = $("#quickText").value.trim();
  if (!text) throw new Error("Cole as informações antes de continuar.");
  if (!force && state.parsed && state.textVersion === text) return state.parsed;
  const response = await fetch("/api/parse", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...pinHeaders() },
    body: JSON.stringify({ text }),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || "Não foi possível interpretar.");
  state.parsed = result.data;
  state.textVersion = text;
  fillFields(result.data);
  $("#parseStatus").textContent = result.missing.length
    ? `${result.missing.length} campo(s) precisam de revisão`
    : "Informações prontas";
  if (result.missing.length) $("#manualEditor").open = true;
  return result.data;
}

function renderPhotos() {
  const slots = $$("#photoGrid .photo-slot");
  slots.forEach((slot, index) => {
    const file = state.photos[index];
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

async function processPowerPoint(mode) {
  if (state.photos.length !== 3) throw new Error("Selecione exatamente três fotos.");
  await interpret(false);
  const form = new FormData();
  form.append("brand", state.brand);
  form.append("mode", mode);
  form.append("text", $("#quickText").value);
  form.append("parsed_json", JSON.stringify(collectFields()));
  state.photos.forEach((photo) => form.append("photos", photo, photo.name));

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
  if (mode === "preview") {
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = URL.createObjectURL(blob);
    $("#previewFrame").src = state.previewUrl;
    $("#previewFrame").style.display = "block";
    $("#emptyPreview").style.display = "none";
    $("#openPreview").href = state.previewUrl;
    $("#previewSection").scrollIntoView({ behavior: "smooth", block: "start" });
    setMessage("Prévia atualizada.", "success");
  } else {
    downloadBlob(blob, filenameFromDisposition(response));
    setMessage("PowerPoint gerado. Confira seus downloads.", "success");
  }
}

async function guardedProcess(mode) {
  setBusy(true);
  setMessage("");
  try {
    await processPowerPoint(mode);
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setBusy(false);
  }
}

buildCaptionEditor();
$("#pin").value = localStorage.getItem("conquistando-pin") || "";
$("#pin").addEventListener("input", () => {
  localStorage.setItem("conquistando-pin", $("#pin").value.trim());
});
$$(".brand-option").forEach((button) => {
  button.addEventListener("click", () => {
    state.brand = button.dataset.brand;
    $$(".brand-option").forEach((item) => item.classList.toggle("active", item === button));
  });
});
$("#quickText").addEventListener("input", () => {
  state.parsed = null;
  $("#parseStatus").textContent = "";
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
  if (files.length !== 3) {
    state.photos = [];
    renderPhotos();
    setMessage("Selecione exatamente três fotos.", "error");
    return;
  }
  state.photos = files;
  renderPhotos();
  setMessage("Três fotos selecionadas.", "success");
});
$("#previewButton").addEventListener("click", () => guardedProcess("preview"));
$("#generateButton").addEventListener("click", () => guardedProcess("generate"));
$("#installHelp").addEventListener("click", () => $("#installDialog").showModal());
$("#closeInstall").addEventListener("click", () => $("#installDialog").close());
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/static/sw.js"));
}

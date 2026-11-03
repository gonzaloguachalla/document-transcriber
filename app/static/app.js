"use strict";
const $ = (id) => document.getElementById(id);
const audio = $("audio"), cont = $("texto");
const PRECARGA = 2;
let docId = null, oraciones = [], botones = [], actual = -1, activo = false;
const urls = new Map(); // "voz:índice" -> promesa de blob URL

function mostrarError(txt) { const m = $("mensaje"); m.textContent = txt; m.hidden = !txt; }
function estado(txt) { $("estado").textContent = txt || ""; }

async function leerError(resp) {
  try { const j = await resp.json(); if (j.detail) return typeof j.detail === "string" ? j.detail : "Solicitud inválida."; } catch (_) {}
  return `Error del servidor (${resp.status}).`;
}

async function subir(file) {
  mostrarError("");
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".docx")) return mostrarError("Solo se admiten archivos .docx.");
  if (file.size > (window.MAX_MB || 10) * 1024 * 1024) return mostrarError(`El archivo supera el máximo de ${window.MAX_MB || 10} MB.`);
  if (file.size === 0) return mostrarError("El archivo está vacío.");
  detener(); estado("Procesando documento…");
  const fd = new FormData(); fd.append("archivo", file);
  try {
    const r = await fetch("/api/documento", { method: "POST", body: fd });
    if (!r.ok) throw new Error(await leerError(r));
    const d = await r.json();
    docId = d.id; oraciones = d.oraciones; urls.forEach((p) => p.then(URL.revokeObjectURL).catch(() => {})); urls.clear();
    pintar(); $("lector").hidden = false; estado(`${oraciones.length} oraciones listas.`);
    $("btn-play").focus();
  } catch (e) {
    estado(""); mostrarError(e.message === "Failed to fetch" ? "No se pudo conectar con el servidor." : e.message);
  }
}

function pintar() {
  cont.replaceChildren(); botones = [];
  oraciones.forEach((t, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "oracion"; b.textContent = t; b.setAttribute("role", "listitem");
    b.addEventListener("click", () => reproducirDesde(i));
    cont.appendChild(b); botones.push(b);
  });
  progreso(-1);
}

function progreso(i) {
  $("progreso").max = Math.max(oraciones.length, 1);
  $("progreso").value = Math.max(i + 1, 0);
  $("progreso-txt").textContent = `${Math.max(i + 1, 0)} / ${oraciones.length}`;
}

function obtenerUrl(i) {
  const clave = `${$("voz").value}:${i}`;
  if (!urls.has(clave)) {
    const p = fetch(`/api/audio/${docId}/${i}?voz=${encodeURIComponent($("voz").value)}`).then(async (r) => {
      if (!r.ok) throw new Error(await leerError(r));
      return URL.createObjectURL(await r.blob());
    });
    p.catch(() => urls.delete(clave)); // permite reintentar
    urls.set(clave, p);
  }
  return urls.get(clave);
}

function precargar(i) { for (let k = 1; k <= PRECARGA && i + k < oraciones.length; k++) obtenerUrl(i + k).catch(() => {}); }

async function reproducirDesde(i) {
  if (!docId || i < 0 || i >= oraciones.length) return;
  mostrarError(""); activo = true; const token = ++reproToken;
  marcar(i); estado("Generando audio…");
  try {
    const url = await obtenerUrl(i);
    if (token !== reproToken) return;
    audio.src = url; audio.playbackRate = parseFloat($("velocidad").value); audio.preservesPitch = true;
    await audio.play(); estado(""); precargar(i);
  } catch (e) {
    if (token !== reproToken) return;
    activo = false; estado("");
    mostrarError("No se pudo generar el audio: " + e.message);
  }
}
let reproToken = 0;

function marcar(i) {
  if (actual >= 0 && botones[actual]) { botones[actual].classList.remove("activa"); botones[actual].removeAttribute("aria-current"); }
  actual = i;
  if (botones[i]) { botones[i].classList.add("activa"); botones[i].setAttribute("aria-current", "true"); botones[i].scrollIntoView({ block: "nearest", behavior: "smooth" }); }
  progreso(i);
}

function detener() {
  reproToken++; activo = false; audio.pause(); audio.removeAttribute("src"); audio.load();
  if (actual >= 0 && botones[actual]) botones[actual].classList.remove("activa");
  actual = -1; if (oraciones.length) progreso(-1); estado("");
}

audio.addEventListener("ended", () => {
  if (activo && actual + 1 < oraciones.length) reproducirDesde(actual + 1);
  else if (activo) { activo = false; estado("Lectura terminada."); }
});
audio.addEventListener("error", () => { if (audio.getAttribute("src")) { activo = false; mostrarError("Error al reproducir el audio."); } });

$("btn-play").addEventListener("click", () => reproducirDesde(Math.max(actual, 0)));
$("btn-pausa").addEventListener("click", () => audio.pause());
$("btn-continuar").addEventListener("click", () => {
  if (audio.getAttribute("src") && audio.paused) { activo = true; audio.play(); } else if (!activo) reproducirDesde(Math.max(actual, 0));
});
$("btn-stop").addEventListener("click", detener);
$("voz").addEventListener("change", () => {
  try { localStorage.setItem("voz", $("voz").value); } catch (_) {}
  if (activo && actual >= 0) reproducirDesde(actual); // continúa con la nueva voz
});
$("velocidad").addEventListener("change", (e) => { audio.playbackRate = parseFloat(e.target.value); });

$("btn-descargar").addEventListener("click", async () => {
  if (!docId) return;
  const b = $("btn-descargar"); b.disabled = true; mostrarError(""); estado("Generando audio completo, puede tardar…");
  try {
    const r = await fetch(`/api/audio/${docId}/completo?voz=${encodeURIComponent($("voz").value)}`);
    if (!r.ok) throw new Error(await leerError(r));
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a"); a.href = url; a.download = "documento.wav"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000); estado("Descarga lista.");
  } catch (e) { estado(""); mostrarError("No se pudo descargar el audio: " + e.message); }
  finally { b.disabled = false; }
});

const zona = $("zona"), input = $("archivo");
$("btn-elegir").addEventListener("click", () => input.click());
input.addEventListener("change", () => { subir(input.files[0]); input.value = ""; });
["dragenter", "dragover"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add("sobre"); }));
["dragleave", "drop"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove("sobre"); }));
zona.addEventListener("drop", (e) => subir(e.dataTransfer.files[0]));
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

fetch("/health").then((r) => r.json()).then((h) => {
  if (h.max_mb) { window.MAX_MB = h.max_mb; $("nota-limite").textContent = `Tamaño máximo: ${h.max_mb} MB.`; }
  if (h.estado !== "ok") mostrarError("El motor de voz no está disponible: " + (h.error || "error desconocido"));
}).catch(() => {});

async function cargarVoces(seleccionar) {
  try {
    const d = await (await fetch("/api/voces")).json();
    let guardada = null; try { guardada = localStorage.getItem("voz"); } catch (_) {}
    const sel = $("voz"), previa = seleccionar || sel.value || guardada;
    sel.replaceChildren();
    d.voces.forEach((v) => { const o = new Option(v.nombre, v.id); sel.add(o); });
    sel.value = d.voces.some((v) => v.id === previa) ? previa : d.defecto;
  } catch (_) {}
}

cargarVoces();

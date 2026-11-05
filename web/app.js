"use strict";

const TEXT = {
  hint: "Артикулды немесе тауар атауын жазып, іздеңіз.",
  recent: "Соңғы іздеулер",
  tooShort: "Кемінде 2 таңба жазыңыз.",
  found: (n) => `${n} тауар табылды`,
  narrow: (n) => `Алғашқы ${n} тауар көрсетілді. Толығырақ жазсаңыз, тізім қысқарады.`,
  notFoundTitle: "Тауар табылмады",
  notFound: (q) => `«${q}» бойынша ештеңе жоқ. Артикулды тексеріп, қайта іздеңіз.`,
  total: "Қоймаларда барлығы",
  free: "Сатуға бос",
  reserved: "Резервте",
  reservedShort: "резерв",
  noStock: "Бұл тауар қоймаларда қалмаған.",
  noWarehouse: "Қойма көрсетілмеген",
  updated: (time) => `Жаңартылды ${time}`,
  refresh: "Жаңарту",
  retry: "Қайталау",
  noAccessTitle: "Рұқсат жоқ",
  noAccess: "Әкімшіге осы ID-ні жіберіңіз: ",
  outsideTitle: "Telegram арқылы ашыңыз",
  outside: "Бұл бет тек ботқа кірген кезде жұмыс істейді.",
  sessionTitle: "Сессия ескірді",
  session: "Қосымшаны жауып, ботта қайта ашыңыз.",
  onecDownTitle: "1С жауап бермей тұр",
  onecDown: "Сервер қосулы екенін тексеріп, қайталаңыз.",
  onecConfigTitle: "1С сұранысы орындалмады",
  onecConfig: "Бот баптауын тексеру керек. Әкімшіге хабарлаңыз.",
  networkTitle: "Байланыс үзілді",
  network: "Интернетті тексеріп, қайталаңыз.",
};

const RECENT_KEY = "ceramo.recent";
const RECENT_LIMIT = 6;
const REQUEST_TIMEOUT_MS = 25000;

const tg = window.Telegram && window.Telegram.WebApp;
const view = document.getElementById("view");
const form = document.getElementById("search");
const input = document.getElementById("q");
const number = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 });
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

let lastList = null;
let requestId = 0;

class ApiError extends Error {
  constructor(status, detail) {
    super(`API ${status}`);
    this.status = status;
    this.detail = detail || {};
  }
}

/* All text from 1C goes through textContent, so it can never run as markup. */
function h(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function show(...nodes) {
  view.replaceChildren(...nodes.filter(Boolean));
  window.scrollTo(0, 0);
}

function haptic(kind) {
  if (tg && tg.isVersionAtLeast("6.1")) tg.HapticFeedback.notificationOccurred(kind);
}

function setBack(enabled) {
  if (!tg || !tg.isVersionAtLeast("6.1")) return;
  if (enabled) tg.BackButton.show();
  else tg.BackButton.hide();
}

function readRecent() {
  try {
    const value = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(value) ? value.filter((entry) => typeof entry === "string") : [];
  } catch {
    return [];
  }
}

function remember(query) {
  const next = [query, ...readRecent().filter((entry) => entry !== query)].slice(0, RECENT_LIMIT);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* Recent searches are only a convenience. */
  }
}

async function api(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      headers: { Authorization: `tma ${tg.initData}` },
      signal: controller.signal,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiError(response.status, body.detail);
    return body;
  } finally {
    clearTimeout(timer);
  }
}

function note(title, text, action) {
  return h("section", { class: "note" }, h("h2", null, title), h("p", null, text), action || null);
}

function showError(error, retry) {
  haptic("error");
  setBack(false);
  const again = h("button", { class: "link", type: "button", onclick: retry }, TEXT.retry);
  if (error instanceof ApiError) {
    if (error.status === 401) return show(note(TEXT.sessionTitle, TEXT.session));
    if (error.status === 403) {
      const id = h("code", null, String(error.detail.user_id ?? ""));
      return show(h("section", { class: "note" },
        h("h2", null, TEXT.noAccessTitle), h("p", null, TEXT.noAccess, id)));
    }
    if (error.detail.code === "onec_unavailable") return show(note(TEXT.onecDownTitle, TEXT.onecDown, again));
    return show(note(TEXT.onecConfigTitle, TEXT.onecConfig, again));
  }
  return show(note(TEXT.networkTitle, TEXT.network, again));
}

function skeleton(slab) {
  const rows = [slab ? h("div", { class: "slab" }) : null, h("div", { class: "pick" }), h("div", { class: "pick" })];
  return h("div", { class: "laid skeleton", "aria-label": "Жүктелуде" }, rows);
}

function showIdle() {
  lastList = null;
  setBack(false);
  const recent = readRecent();
  show(
    h("p", { class: "hint" }, TEXT.hint),
    recent.length ? h("h2", { class: "section-title" }, TEXT.recent) : null,
    recent.length
      ? h("div", { class: "chips" }, recent.map((query) =>
          h("button", { class: "chip", type: "button", onclick: () => { input.value = query; runSearch(query); } }, query)))
      : null,
  );
}

async function runSearch(rawQuery) {
  const query = rawQuery.trim();
  if (query.length < 2) {
    show(h("p", { class: "hint" }, TEXT.tooShort));
    return;
  }
  input.blur();
  remember(query);
  setBack(false);
  const id = ++requestId;
  show(skeleton(false));
  try {
    const result = await api(`/api/search?q=${encodeURIComponent(query)}`);
    if (id !== requestId) return;
    if (result.items.length === 1 && !result.truncated) {
      lastList = null;
      await openItem(result.items[0]);
    } else if (result.items.length === 0) {
      haptic("warning");
      lastList = null;
      show(note(TEXT.notFoundTitle, TEXT.notFound(query)));
    } else {
      lastList = result;
      showList(result);
    }
  } catch (error) {
    if (id === requestId) showError(error, () => runSearch(query));
  }
}

function showList(result) {
  setBack(false);
  show(
    h("h2", { class: "section-title" }, TEXT.found(result.items.length)),
    h("ul", { class: "laid" }, result.items.map((item) =>
      h("li", null, h("button", { class: "pick", type: "button", onclick: () => openItem(item) },
        h("b", null, item.article || item.name),
        item.article ? h("span", null, item.name) : null)))),
    result.truncated ? h("p", { class: "hint" }, TEXT.narrow(result.items.length)) : null,
  );
}

async function openItem(item) {
  const id = ++requestId;
  setBack(Boolean(lastList));
  show(itemHead(item), skeleton(true));
  try {
    const stock = await api(`/api/stock/${encodeURIComponent(item.id)}`);
    if (id !== requestId) return;
    showStock(item, stock);
    haptic("success");
  } catch (error) {
    if (id === requestId) showError(error, () => openItem(item));
  }
}

function itemHead(item) {
  return h("div", { class: "item-head" },
    h("h1", null, item.article || item.name),
    item.article ? h("p", null, item.name) : null);
}

function amount(value, unit) {
  return unit ? `${number.format(value)} ${unit}` : number.format(value);
}

/* The total counts up once when it arrives: the one moment of motion in the app. */
function countUp(node, target) {
  if (reducedMotion.matches || target <= 0) {
    node.firstChild.textContent = number.format(target);
    return;
  }
  const started = performance.now();
  const duration = 420;
  const decimals = Number.isInteger(target) ? 0 : 1;
  const step = (now) => {
    const progress = Math.min((now - started) / duration, 1);
    const eased = 1 - (1 - progress) ** 3;
    node.firstChild.textContent = progress < 1
      ? number.format(Number((target * eased).toFixed(decimals)))
      : number.format(target);
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function showStock(item, stock) {
  const empty = stock.warehouses.length === 0;
  const hasReserve = stock.total_reserved !== 0;
  const total = h("p", { class: `total${empty ? " is-empty" : ""}` },
    h("span", null, "0"), item.unit ? " " : null, item.unit ? h("small", null, item.unit) : null);

  const rows = stock.warehouses.map((row) => h("div", { class: "row" },
    h("span", { class: "row-name" }, row.name || TEXT.noWarehouse),
    h("span", { class: `row-qty${row.quantity < 0 ? " is-negative" : ""}` },
      amount(row.quantity, item.unit),
      row.reserved ? h("small", null, `${TEXT.reservedShort} ${number.format(row.reserved)}`) : null)));

  const tiles = [
    h("div", { class: "slab" }, h("p", { class: "slab-label" }, TEXT.total), total),
    hasReserve
      ? h("div", { class: "pair" },
          h("div", { class: "cell" }, h("span", null, TEXT.free),
            h("b", null, amount(stock.total_quantity - stock.total_reserved, item.unit))),
          h("div", { class: "cell" }, h("span", null, TEXT.reserved),
            h("b", null, amount(stock.total_reserved, item.unit))))
      : null,
    ...rows,
    empty ? h("div", { class: "row" }, h("span", { class: "row-name" }, TEXT.noStock)) : null,
  ];

  const time = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  show(
    itemHead(item),
    h("div", { class: "laid" }, tiles),
    h("div", { class: "foot" }, h("span", null, TEXT.updated(time)),
      h("button", { class: "link", type: "button", onclick: () => openItem(item) }, TEXT.refresh)),
  );
  countUp(total, stock.total_quantity);
}

function applyTheme() {
  const dark = tg && tg.colorScheme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  if (tg && tg.isVersionAtLeast("6.1")) {
    tg.setHeaderColor("#010144");
    tg.setBackgroundColor(dark ? "#07071f" : "#f4f4f9");
  }
}

async function start() {
  if (!tg || !tg.initData) {
    form.hidden = true;
    show(note(TEXT.outsideTitle, TEXT.outside));
    return;
  }
  tg.ready();
  tg.expand();
  applyTheme();
  tg.onEvent("themeChanged", applyTheme);
  if (tg.isVersionAtLeast("6.1")) {
    tg.BackButton.onClick(() => {
      if (lastList) showList(lastList);
      else showIdle();
    });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    runSearch(input.value);
  });
  input.addEventListener("input", () => {
    if (!input.value) {
      requestId += 1;
      showIdle();
    }
  });

  showIdle();
  input.focus();
  try {
    await api("/api/me");
  } catch (error) {
    /* Other failures surface on the first search, with a retry button. */
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      form.hidden = true;
      showError(error);
    }
  }
}

start();

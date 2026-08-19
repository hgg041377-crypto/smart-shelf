// price-app — رابط کاربری (فارسی / RTL / موبایل‌محور)
"use strict";

const $ = (id) => document.getElementById(id);
const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const FALLBACK_MSG = "قیمت خودکار قابل دریافت نیست؛ برای مشاهده قیمت، صفحه جستجو را باز کنید.";

// نقشه کالاها (برای بررسی مجدد بدون درخواست اضافه)
let PRODUCTS = {};

/* ---------- ابزارها ---------- */

const toFa = (s) => String(s).replace(/\d/g, (d) => FA_DIGITS[d]);

function priceStr(n) {
  if (n === null || n === undefined || n === "") return "—";
  const num = Number(n);
  if (!isFinite(num)) return "—";
  return toFa(num.toLocaleString("en-US"));
}

// واکشی امن: هرگز اجازه «Unexpected token» یا HTML به‌جای JSON ندهیم
async function safeFetch(url, opts) {
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    throw new Error("اتصال به سرور برقرار نشد؛ مطمئن شوید برنامه در حال اجراست.");
  }
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    throw new Error("پاسخ سرور قابل خواندن نبود (JSON نامعتبر).");
  }
  if (typeof data === "object" && data !== null && data.ok === false) {
    throw new Error(data.error || "خطای ناشناخته از سرور.");
  }
  return data;
}

function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("err", !!isErr);
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 4000);
}

function setLoading(on) {
  $("loading").classList.toggle("hidden", !on);
  $("searchBtn").disabled = on;
  $("searchBtn").textContent = on ? "⏳ در حال بررسی…" : "🔎 جستجوی قیمت";
}

/* ---------- ردیف اختلاف قیمت ---------- */

function diffRow(storePrice, refPrice) {
  if (refPrice === null || refPrice === undefined || refPrice <= 0) return "";
  const diff = storePrice - refPrice;
  const percent = (diff / refPrice) * 100;
  let cls = "neutral", label = "هم‌قیمت با مرجع";
  if (diff > 0) { cls = "bad"; label = "گران‌تر از مرجع"; }
  else if (diff < 0) { cls = "good"; label = "ارزان‌تر از مرجع"; }
  const sign = diff > 0 ? "+" : "";
  return `
    <div class="diff ${cls}">
      <div class="diff-title">${label}</div>
      <div class="diff-line">اختلاف: ${sign}${priceStr(diff)} تومان</div>
      <div class="diff-line">درصد اختلاف: ${sign}${toFa(percent.toFixed(2))}٪</div>
    </div>`;
}

/* ---------- بلوک مرجع (اکالا / دیجی‌کالا) ---------- */

function refBlock(label, ref, storePrice) {
  const url = ref && ref.url ? ref.url : "#";
  let priceHtml, cmpHtml = "", statusHtml;

  if (ref && ref.found && ref.price !== null && ref.price !== undefined) {
    priceHtml = `<div class="price">${priceStr(ref.price)} <small>تومان</small></div>`;
    statusHtml = `<div class="status ok">✅ ${toFaLabel(ref.status) || "قیمت دریافت شد"}</div>`;
    cmpHtml = diffRow(storePrice, ref.price);
  } else {
    priceHtml = `<div class="price muted">—</div>`;
    statusHtml = `<div class="status warn">${ref && ref.status ? ref.status : FALLBACK_MSG}</div>`;
  }

  const checked = ref && ref.checked_at ? `<div class="meta">🕒 بررسی: ${toFa(ref.checked_at)}</div>` : "";

  return `
    <div class="ref-block">
      <h3>${label}</h3>
      ${priceHtml}
      ${statusHtml}
      ${cmpHtml}
      ${checked}
      <a class="btn ghost big" href="${url}" target="_blank" rel="noopener">🔗 باز کردن در ${label}</a>
    </div>`;
}

function toFaLabel(s) {
  return s ? toFa(s) : "";
}

/* ---------- نمایش کارت نتیجه ---------- */

function renderResult(data) {
  const ref = data.references || {};
  const body = document.createElement("div");
  body.className = "card result";
  body.innerHTML = `
    <h2 class="result-name">${escapeHtml(data.product)}</h2>
    <div class="store-price-row">
      <span>قیمت فروشگاه من:</span>
      <span class="price store">${priceStr(data.store_price)} <small>تومان</small></span>
    </div>
    <div class="refs">
      ${refBlock("اکالا", ref.okala, data.store_price)}
      ${refBlock("دیجی‌کالا", ref.digikala, data.store_price)}
    </div>
    <div class="meta">🕒 آخرین بررسی: ${toFa(data.checked_at || "")}</div>
    <div class="result-actions">
      <button class="btn primary" onclick="reCheck(${data.id || 0})">🔄 بررسی مجدد قیمت</button>
      <button class="btn" onclick="showHistory(${data.id || 0})">📊 تاریخچه قیمت</button>
      <button class="btn danger" onclick="deleteProduct(${data.id || 0})">🗑️ حذف</button>
    </div>`;
  const wrap = $("resultWrap");
  wrap.innerHTML = "";
  wrap.appendChild(body);
  wrap.dataset.id = data.id || "";
  wrap.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ---------- جستجوی قیمت ---------- */

async function submitSearch(ev) {
  ev.preventDefault();
  const name = $("name").value.trim();
  const storePrice = parseInt($("storePrice").value, 10) || 0;
  if (!name) { toast("نام کالا را وارد کنید.", true); return; }
  if (storePrice <= 0) { toast("قیمت فروشگاه را وارد کنید.", true); return; }
  const barcode = $("barcode").value.trim();

  setLoading(true);
  try {
    const data = await safeFetch("/api/search-price", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, store_price: storePrice, barcode }),
    });
    if (data.id) PRODUCTS[data.id] = data;
    renderResult(data);
    toast("بررسی انجام شد.");
    await loadProducts();
  } catch (err) {
    toast(err.message, true);
  } finally {
    setLoading(false);
  }
}

/* ---------- کالاهای ذخیره‌شده ---------- */

async function loadProducts() {
  try {
    const data = await safeFetch("/api/products");
    PRODUCTS = {};
    (data.products || []).forEach((p) => { PRODUCTS[p.id] = p; });
    renderList(data.products || []);
  } catch (err) {
    $("productList").innerHTML = `<p class="empty">${escapeHtml(err.message)}</p>`;
  }
}

function renderList(products) {
  const box = $("productList");
  if (!products.length) {
    box.innerHTML = `<p class="empty">هنوز کالایی ذخیره نشده است.</p>`;
    return;
  }
  box.innerHTML = products.map((p) => `
    <div class="saved-item">
      <div class="saved-head">
        <strong>${escapeHtml(p.name)}</strong>
        <span class="tag">${priceStr(p.store_price)} تومان</span>
      </div>
      <div class="saved-refs">
        <span class="mini ${p.okala_price != null ? "ok" : "muted"}">اکالا: ${p.okala_price != null ? priceStr(p.okala_price) : "—"}</span>
        <span class="mini ${p.digikala_price != null ? "ok" : "muted"}">دیجی‌کالا: ${p.digikala_price != null ? priceStr(p.digikala_price) : "—"}</span>
      </div>
      <div class="meta">🕒 ${p.last_update ? toFa(p.last_update) : ""}</div>
      <div class="saved-actions">
        <button class="btn small primary" onclick="reCheck(${p.id})">🔄 بررسی مجدد</button>
        <button class="btn small" onclick="showHistory(${p.id})">📊 تاریخچه</button>
        <button class="btn small danger" onclick="deleteProduct(${p.id})">🗑️ حذف</button>
      </div>
    </div>`).join("");
}

/* ---------- بررسی مجدد ---------- */

async function reCheck(id) {
  const p = PRODUCTS[id];
  if (!p) { toast("کالا پیدا نشد.", true); return; }
  toast("⏳ در حال بررسی مجدد…");
  try {
    const data = await safeFetch("/api/search-price", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: p.name, store_price: p.store_price, barcode: p.barcode || "" }),
    });
    if (data.id) PRODUCTS[data.id] = data;
    renderResult(data);
    toast("بررسی مجدد انجام شد.");
    await loadProducts();
  } catch (err) {
    toast(err.message, true);
  }
}

/* ---------- تاریخچه ---------- */

async function showHistory(id) {
  const p = PRODUCTS[id];
  $("historyTitle").textContent = `📊 تاریخچه قیمت — ${p ? p.name : ""}`;
  $("historyModal").classList.remove("hidden");
  const body = $("historyBody");
  body.innerHTML = `<p class="empty">در حال بارگذاری…</p>`;
  try {
    const data = await safeFetch(`/api/history/${id}`);
    const rows = data.history || [];
    if (!rows.length) {
      body.innerHTML = `<p class="empty">تاریخچه‌ای ثبت نشده است.</p>`;
      return;
    }
    body.innerHTML = `
      <table>
        <thead><tr><th>تاریخ</th><th>فروشگاه</th><th>اکالا</th><th>دیجی‌کالا</th></tr></thead>
        <tbody>
          ${rows.map((r) => `
            <tr>
              <td>${toFa(r.check_date || "")}</td>
              <td>${priceStr(r.store_price)}</td>
              <td>${r.okala_price != null ? priceStr(r.okala_price) : "—"}</td>
              <td>${r.digikala_price != null ? priceStr(r.digikala_price) : "—"}</td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  } catch (err) {
    body.innerHTML = `<p class="empty">${escapeHtml(err.message)}</p>`;
  }
}

function closeHistory() {
  $("historyModal").classList.add("hidden");
}

/* ---------- حذف ---------- */

async function deleteProduct(id) {
  if (!confirm("این کالا و تاریخچه آن حذف شود؟")) return;
  try {
    await safeFetch(`/api/product/${id}`, { method: "DELETE" });
    delete PRODUCTS[id];
    toast("کالا حذف شد.");
    await loadProducts();
    const wrap = $("resultWrap");
    if (wrap.dataset.id === String(id)) { wrap.classList.add("hidden"); wrap.innerHTML = ""; }
  } catch (err) {
    toast(err.message, true);
  }
}

/* ---------- راه‌اندازی ---------- */

$("searchForm").addEventListener("submit", submitSearch);
$("closeHistoryBtn").addEventListener("click", closeHistory);
$("historyModal").addEventListener("click", (e) => {
  if (e.target === $("historyModal")) closeHistory();
});

loadProducts();

"use strict";

const editor = document.getElementById("editor");
const popup = document.getElementById("popup");
const statusEl = document.getElementById("status");
const fileInput = document.getElementById("fileInput");
const recheckBtn = document.getElementById("recheckBtn");
const downloadBtn = document.getElementById("downloadBtn");

const TYPE_LABEL = {
  ocr_char: "OCR nhầm ký tự",
  missing_diacritic: "Sai/mất dấu",
  spacing_merge: "Dính từ",
  spacing_split: "Thừa dấu cách",
  spelling: "Sai chính tả",
  phrase: "Gợi ý cụm từ ghép",
  capitalization: "Viết hoa",
  unknown: "Không nhận dạng",
};

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escapeAttr(s) {
  return escapeHtml(s).replace(/"/g, "&quot;");
}

// Dựng HTML 1 đoạn: bọc các đoạn lỗi bằng <span class="err">
function paragraphHtml(text, issues) {
  if (!text) return "<br>";
  const sorted = (issues || []).slice().sort((a, b) => a.start - b.start);
  let html = "";
  let pos = 0;
  for (const it of sorted) {
    if (it.start < pos) continue; // bỏ lỗi chồng lấn
    html += escapeHtml(text.slice(pos, it.start));
    const payload = escapeAttr(JSON.stringify({
      type: it.type, suggestions: it.suggestions || [],
    }));
    html += `<span class="err" data-info="${payload}">` +
            escapeHtml(text.slice(it.start, it.end)) + `</span>`;
    pos = it.end;
  }
  html += escapeHtml(text.slice(pos));
  return html;
}

function render(paragraphs) {
  editor.innerHTML = paragraphs
    .map((p) => `<p>${paragraphHtml(p.text, p.issues)}</p>`)
    .join("");
}

// Lấy nội dung hiện tại theo từng đoạn (giữ được chỉnh sửa của người dùng).
// Đọc trực tiếp từng KHỐI đoạn để tránh việc innerText chèn dòng trống giữa các <p>.
function collectParagraphs() {
  const blocks = [];
  editor.childNodes.forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.textContent.trim() !== "") blocks.push(node.textContent.replace(/ /g, " "));
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      // mỗi <p>/<div> = 1 đoạn; bỏ ký tự xuống dòng dư ở cuối
      blocks.push(node.innerText.replace(/ /g, " ").replace(/\n$/, ""));
    }
  });
  if (blocks.length === 0) {  // dự phòng nếu trình duyệt không bọc bằng thẻ khối
    return editor.innerText.replace(/ /g, " ").replace(/\n+$/g, "").split("\n");
  }
  return blocks;
}

function countErrors() {
  return editor.querySelectorAll(".err").length;
}
function updateStatus(extra) {
  const n = countErrors();
  statusEl.textContent = (extra ? extra + " · " : "") +
    (n ? `${n} từ nghi sai` : "không còn lỗi nghi ngờ");
}

// ---- Tải file lên ---- //
fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;
  statusEl.textContent = "Đang đọc & kiểm tra…";
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Lỗi tải lên");
    render(data.paragraphs);
    recheckBtn.disabled = false;
    downloadBtn.disabled = false;
    updateStatus(`Đã mở “${data.filename}”`);
  } catch (e) {
    statusEl.textContent = "❌ " + e.message;
  }
  fileInput.value = "";
});

// ---- Kiểm tra lại sau khi sửa ---- //
recheckBtn.addEventListener("click", async () => {
  hidePopup();
  statusEl.textContent = "Đang kiểm tra lại…";
  const paragraphs = collectParagraphs();
  try {
    const res = await fetch("/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paragraphs }),
    });
    const data = await res.json();
    render(data.paragraphs);
    updateStatus("Đã kiểm tra lại");
  } catch (e) {
    statusEl.textContent = "❌ " + e.message;
  }
});

// ---- Tải file đã sửa ---- //
downloadBtn.addEventListener("click", async () => {
  hidePopup();
  const paragraphs = collectParagraphs();
  try {
    const res = await fetch("/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paragraphs }),
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "da-chinh-sua.docx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    statusEl.textContent = "❌ " + e.message;
  }
});

// ---- Popup gợi ý ---- //
let activeSpan = null;

function hidePopup() {
  popup.classList.add("hidden");
  activeSpan = null;
}

function showPopup(span) {
  let info;
  try { info = JSON.parse(span.dataset.info); } catch { info = { suggestions: [] }; }
  activeSpan = span;

  const label = TYPE_LABEL[info.type] || "Nghi sai";
  let html = `<div class="ptitle">${label}: <b>${escapeHtml(span.textContent)}</b></div>`;
  if (info.suggestions && info.suggestions.length) {
    for (const s of info.suggestions) {
      html += `<button class="sugg" data-val="${escapeAttr(s)}">${escapeHtml(s)}</button>`;
    }
  } else {
    html += `<div class="none">Không có gợi ý</div>`;
  }
  html += `<button class="sugg ignore" data-ignore="1">Bỏ qua (giữ nguyên)</button>`;
  popup.innerHTML = html;

  const r = span.getBoundingClientRect();
  popup.classList.remove("hidden");
  popup.style.top = (r.bottom + window.scrollY + 6) + "px";
  popup.style.left = (r.left + window.scrollX) + "px";
}

// click vào từ nghi sai
editor.addEventListener("click", (e) => {
  const span = e.target.closest(".err");
  if (span) {
    e.preventDefault();
    showPopup(span);
  } else {
    hidePopup();
  }
});

// chọn gợi ý / bỏ qua
popup.addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn || !activeSpan) return;
  if (btn.dataset.ignore) {
    activeSpan.classList.remove("err");
    activeSpan.removeAttribute("data-info");
  } else {
    activeSpan.textContent = btn.dataset.val;
    activeSpan.classList.remove("err");
    activeSpan.removeAttribute("data-info");
  }
  hidePopup();
  updateStatus("Đã sửa");
});

// click ra ngoài -> ẩn popup
document.addEventListener("click", (e) => {
  if (!e.target.closest(".err") && !e.target.closest("#popup")) hidePopup();
});
window.addEventListener("scroll", hidePopup, true);

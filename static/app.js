const BASE = window.APP_BASE || "";
const COV_CLASS = { off: "cov-off", ok: "cov-ok", tight: "cov-tight", low: "cov-low" };
const pop = document.getElementById("pop");
const toast = document.getElementById("toast");
let active = null; // {member, dates: [iso, ...]}
let toastTimer = null;

function showToast(message, type = "error") {
  toast.innerHTML = `<span class="toast-msg"></span><button type="button" class="toast-close" aria-label="Dismiss">×</button>`;
  toast.querySelector(".toast-msg").textContent = message;
  toast.className = "toast " + type;
  toast.hidden = false;
  toast.querySelector(".toast-close").addEventListener("click", hideToast);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, 5000);
}

function hideToast() {
  clearTimeout(toastTimer);
  toast.classList.add("hide");
  setTimeout(() => { toast.hidden = true; }, 200);
}

function chipHtml(status) {
  if (!status) return '<span class="empty">–</span>';
  if (status === "hva") return '<span class="chip half"><span class="half-text">HVA</span></span>';
  const s = window.STATUS[status];
  return `<span class="chip" style="color:${s.color};background:${s.color}24">${status.toUpperCase()}</span>`;
}

function setSelecting(dates, on) {
  dates.forEach((d) => {
    const cell = document.querySelector(`.cell.mine[data-date="${d}"]`);
    if (cell) cell.classList.toggle("selecting", on);
  });
}

function openPicker(anchorCell, member, dates) {
  active = { member, dates };

  const sorted = [...dates].sort();
  const head = sorted.length > 1 ? `${sorted.length} days selected` : sorted[0];
  let html = `<div class="head">${head}</div>`;
  window.ORDER.forEach((k) => {
    const s = window.STATUS[k];
    html += `<div class="opt" data-set="${k}">
        <span class="code" style="color:${s.color}">${k.toUpperCase()}</span>${s.label}</div>`;
  });
  html += `<div class="opt clear" data-set=""><span class="code" style="text-align:center">×</span>Clear / default</div>`;
  pop.innerHTML = html;
  pop.hidden = false;

  const r = anchorCell.getBoundingClientRect();
  const left = Math.min(r.left, window.innerWidth - 180);
  const top = Math.min(r.bottom + 4, window.innerHeight - 300);
  pop.style.left = left + "px";
  pop.style.top = top + "px";

  pop.querySelectorAll(".opt").forEach((opt) => {
    opt.addEventListener("click", () => applyStatus(opt.dataset.set));
  });
}

function closePicker() {
  pop.hidden = true;
  if (active) setSelecting(active.dates, false);
  active = null;
}

async function applyStatus(status) {
  if (!active) return;
  const { member, dates } = active;
  closePicker();
  try {
    const res = await fetch(BASE + "/api/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ member_id: member, dates, status: status || null, me_id: window.ME_ID }),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      showToast(data.error || "Could not save.");
      return;
    }

    // repaint edited cells — a member can appear under more than one team
    // block, so update every matching cell, not just the first
    (data.cells || []).forEach((c) => {
      document.querySelectorAll(`.cell[data-member="${member}"][data-date="${c.date}"]`).forEach((cell) => {
        cell.dataset.status = c.status || "";
        cell.innerHTML = chipHtml(c.status);
      });
    });
    // repaint coverage rows for every team this member belongs to
    (data.teams || []).forEach((teamResult) => {
      (teamResult.coverage || []).forEach((c) => {
        const cov = document.querySelector(`[data-cov][data-team="${teamResult.team_id}"][data-date="${c.iso}"]`);
        if (!cov) return;
        cov.classList.remove("cov-off", "cov-ok", "cov-tight", "cov-low");
        cov.classList.add(COV_CLASS[c.state]);
        cov.title = c.state === "off" ? "Weekend / holiday" : `${c.working} working · minimum ${c.min}`;
        cov.querySelector(".cnum").textContent = c.state === "off" ? "·" : c.working;
        const low = cov.querySelector(".low");
        if (c.state === "low" && !low) {
          const s = document.createElement("span");
          s.className = "low"; s.textContent = "LOW";
          cov.appendChild(s);
        } else if (c.state !== "low" && low) {
          low.remove();
        }
      });
    });

    // repaint my allowance stats, if this is my own row
    if (data.my_stats) {
      const usedEl = document.getElementById("statUsed");
      const remEl = document.getElementById("statRemaining");
      if (usedEl) usedEl.textContent = data.my_stats.used_days + " d";
      if (remEl) remEl.textContent = data.my_stats.rem_days + " d";
    }
  } catch (e) {
    showToast("Could not save — is the server running?");
  }
}

// ------------------------------------------------------------------ //
//  Drag-to-select across my own cells, then pick one status for all  //
// ------------------------------------------------------------------ //
let dragging = false;
let dragMember = null;
let dragDates = [];
let suppressNextClick = false;

document.querySelectorAll(".cell.mine:not(.holiday):not(.weekend)").forEach((cell) => {
  cell.addEventListener("mousedown", (e) => {
    e.preventDefault();
    closePicker();
    dragging = true;
    dragMember = cell.dataset.member;
    dragDates = [cell.dataset.date];
    cell.classList.add("selecting");
  });
  cell.addEventListener("mouseenter", () => {
    if (!dragging || cell.dataset.member !== dragMember) return;
    if (!dragDates.includes(cell.dataset.date)) {
      dragDates.push(cell.dataset.date);
      cell.classList.add("selecting");
    }
  });
});

document.addEventListener("mouseup", () => {
  if (!dragging) return;
  dragging = false;
  if (!dragDates.length) return;
  const lastCell = document.querySelector(`.cell.mine[data-date="${dragDates[dragDates.length - 1]}"]`);
  if (lastCell) {
    openPicker(lastCell, dragMember, dragDates);
    // mousedown+mouseup on the same cell also fires a native "click" right
    // after — swallow that one so it doesn't immediately close the picker.
    suppressNextClick = true;
  }
});

document.addEventListener("selectstart", (e) => {
  if (dragging) e.preventDefault();
});

document.addEventListener("click", (e) => {
  if (suppressNextClick) {
    suppressNextClick = false;
    return;
  }
  if (!pop.hidden && !pop.contains(e.target)) closePicker();
});
window.addEventListener("scroll", closePicker, true);
window.addEventListener("resize", closePicker);

// ------------------------------------------------------------------ //
//  Admin sign-in / sign-out                                          //
// ------------------------------------------------------------------ //
const adminLoginBtn = document.getElementById("adminLoginBtn");
const adminLogoutBtn = document.getElementById("adminLogout");
const adminModal = document.getElementById("adminModal");
const adminForm = document.getElementById("adminForm");
const adminCancel = document.getElementById("adminCancel");
const adminError = document.getElementById("adminError");

if (adminLoginBtn) {
  adminLoginBtn.addEventListener("click", () => {
    adminError.hidden = true;
    adminForm.reset();
    adminModal.hidden = false;
  });
}

if (adminCancel) {
  adminCancel.addEventListener("click", () => { adminModal.hidden = true; });
}

if (adminModal) {
  adminModal.addEventListener("click", (e) => {
    if (e.target === adminModal) adminModal.hidden = true;
  });
}

if (adminForm) {
  adminForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(adminForm);
    try {
      const res = await fetch(BASE + "/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: fd.get("username"), password: fd.get("password") }),
      });
      const data = await res.json();
      if (data.ok) {
        window.location.reload();
      } else {
        adminError.hidden = false;
      }
    } catch (e2) {
      adminError.hidden = false;
    }
  });
}

if (adminLogoutBtn) {
  adminLogoutBtn.addEventListener("click", async () => {
    await fetch(BASE + "/admin/logout", { method: "POST" });
    window.location.reload();
  });
}

// ------------------------------------------------------------------ //
//  Manage teams & people — stays open across edits, AJAX-saved,      //
//  only a real navigation happens when "Save" is clicked.            //
// ------------------------------------------------------------------ //
const manageOpenBtn = document.getElementById("manageOpenBtn");
const manage = document.getElementById("manage");

if (manageOpenBtn) {
  manageOpenBtn.addEventListener("click", () => {
    document.body.classList.add("manage-mode");
  });
}

function wireManageForms() {
  if (!manage) return;
  const saveBtn = document.getElementById("manageSaveBtn");
  if (saveBtn && !saveBtn.dataset.wired) {
    saveBtn.dataset.wired = "1";
    saveBtn.addEventListener("click", () => window.location.reload());
  }
  manage.querySelectorAll("form").forEach((form) => {
    if (form.dataset.wired) return;
    form.dataset.wired = "1";
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const confirmMsg = form.dataset.confirm;
      if (confirmMsg) {
        const btn = form.querySelector("button[type=submit]");
        if (!btn) return;
        if (!btn.dataset.confirming) {
          btn.dataset.confirming = "1";
          const orig = btn.textContent;
          btn.textContent = "Sure?";
          btn.classList.add("confirming");
          setTimeout(() => {
            btn.textContent = orig;
            btn.classList.remove("confirming");
            delete btn.dataset.confirming;
          }, 2500);
          return;
        }
        delete btn.dataset.confirming;
      }
      const fd = new FormData(form);
      try {
        const res = await fetch(form.action, { method: "POST", body: fd });
        const html = await res.text();
        const doc = new DOMParser().parseFromString(html, "text/html");
        const newManage = doc.getElementById("manage");
        if (newManage) {
          const openDetail = manage.querySelector("details[open]");
          const openMember = openDetail ? openDetail.dataset.member : null;
          manage.innerHTML = newManage.innerHTML;
          if (openMember) {
            const reopened = manage.querySelector(`details[data-member="${openMember}"]`);
            if (reopened) reopened.open = true;
          }
          wireManageForms();
        }
      } catch (err) {
        showToast("Could not save the change — is the server running?");
      }
    });
  });
  wireAllowanceBtns();
}

wireManageForms();

function toggleAllowanceUnit(radio) {
  const input = document.getElementById("allowanceInput");
  const hint = document.getElementById("allowanceHint");
  if (!input || !hint) return;
  if (radio.value === "days") {
    input.value = Math.round(parseInt(input.value || 200, 10) / 8) || 25;
  } else {
    input.value = (parseInt(input.value || 25, 10) * 8) || 200;
  }
  updateAllowanceHint();
}

function updateAllowanceHint() {
  const input = document.getElementById("allowanceInput");
  const hint = document.getElementById("allowanceHint");
  if (!input || !hint) return;
  const checked = document.querySelector('input[name="allowance_unit"]:checked');
  const v = parseInt(input.value, 10) || 0;
  hint.textContent = checked && checked.value === "days"
    ? v + " days = " + (v * 8) + " hours"
    : v + " hours = " + Math.round(v / 8) + " days";
}

document.addEventListener("input", (e) => {
  if (e.target.id === "allowanceInput") updateAllowanceHint();
});

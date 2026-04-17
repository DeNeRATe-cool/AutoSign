const state = {
  rows: [],
  events: [],
  loading: false,
};

const weekBody = document.getElementById("weekBody");
const emptyHint = document.getElementById("emptyHint");
const refreshBtn = document.getElementById("refreshBtn");
const logoutBtn = document.getElementById("logoutBtn");
const eventList = document.getElementById("eventList");
const systemMessage = document.getElementById("systemMessage");
const statTotal = document.getElementById("statTotal");
const statToday = document.getElementById("statToday");
const statPending = document.getElementById("statPending");

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  });
}

function formatTimeRange(startIso, endIso) {
  const start = new Date(startIso);
  const end = new Date(endIso);
  const fmt = (d) =>
    d.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  return `${fmt(start)} - ${fmt(end)}`;
}

function formatCountdown(totalSeconds) {
  const safe = Math.max(0, totalSeconds);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  const hh = String(hours).padStart(2, "0");
  const mm = String(minutes).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function attendanceMeta(attendance) {
  if (attendance === "正常出勤") {
    return { cls: "status status-ok", text: "正常" };
  }
  if (attendance === "迟到") {
    return { cls: "status status-late", text: "迟到" };
  }
  return { cls: "status status-miss", text: "未出勤" };
}

function attendanceMetaForRow(row, nowMs) {
  const startMs = new Date(row.startTime).getTime();
  if (Number.isFinite(startMs) && nowMs < startMs) {
    return { cls: "status status-not-started", text: "未开始" };
  }
  return attendanceMeta(row.attendance);
}

function sameDay(isoDate, now) {
  const date = new Date(isoDate);
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  );
}

function announce(message, type = "info") {
  if (!systemMessage) return;

  systemMessage.classList.remove("hidden", "error", "info");
  if (type === "error") {
    systemMessage.classList.add("error");
    systemMessage.setAttribute("role", "alert");
    systemMessage.setAttribute("aria-live", "assertive");
  } else {
    systemMessage.classList.add("info");
    systemMessage.setAttribute("role", "status");
    systemMessage.setAttribute("aria-live", "polite");
  }

  systemMessage.textContent = message;
}

function renderStats() {
  const now = new Date();
  const total = state.rows.length;
  const today = state.rows.filter((row) => sameDay(row.startTime, now)).length;
  const pending = state.rows.filter((row) => {
    const startMs = new Date(row.startTime).getTime();
    return Number.isFinite(startMs) && startMs <= now.getTime() && row.attendance !== "正常出勤";
  }).length;

  statTotal.textContent = String(total);
  statToday.textContent = String(today);
  statPending.textContent = String(pending);
}

function resolveCountdownText(row, nowMs) {
  const attendance = row.attendance || "";
  if (attendance === "正常出勤" || attendance === "迟到") {
    return { text: "已签到", state: "done" };
  }

  const startMs = new Date(row.startTime).getTime();
  const endMs = new Date(row.endTime).getTime();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) {
    return { text: "--:--:--", state: "waiting" };
  }

  const preSignStartMs = startMs - 10 * 60 * 1000;
  if (nowMs < preSignStartMs) {
    return {
      text: formatCountdown(Math.ceil((preSignStartMs - nowMs) / 1000)),
      state: "waiting",
    };
  }

  if (nowMs > endMs) {
    return { text: "无法签到", state: "unavailable" };
  }

  if (nowMs < startMs) {
    return { text: "可签到", state: "presign" };
  }

  if (nowMs <= endMs) {
    return { text: "上课中", state: "due" };
  }

  return { text: "无法签到", state: "unavailable" };
}

function updateCountdownElements() {
  const nowMs = Date.now();
  document.querySelectorAll("[data-countdown]").forEach((node) => {
    const row = {
      attendance: node.getAttribute("data-attendance") || "",
      startTime: node.getAttribute("data-start-time") || "",
      endTime: node.getAttribute("data-end-time") || "",
    };
    const { text, state } = resolveCountdownText(row, nowMs);
    node.textContent = text;
    node.setAttribute("data-state", state);
  });
}

function signButtonMeta(row, nowMs) {
  const attendance = row.attendance || "";
  const startMs = new Date(row.startTime).getTime();
  const endMs = new Date(row.endTime).getTime();
  const preSignStartMs = Number.isFinite(startMs) ? startMs - 10 * 60 * 1000 : NaN;
  const canSignNow =
    Number.isFinite(startMs) &&
    Number.isFinite(endMs) &&
    nowMs >= preSignStartMs &&
    nowMs <= endMs;

  if (attendance === "正常出勤" || attendance === "迟到") {
    return { canSign: false, text: "已签到", mode: "done" };
  }

  if (!canSignNow) {
    return { canSign: false, text: "无法签到", mode: "blocked" };
  }

  return { canSign: true, text: "迟到签到", mode: "late" };
}

async function apiGet(path) {
  const res = await fetch(path, {
    credentials: "same-origin",
  });
  return await res.json();
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    credentials: "same-origin",
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.message || "请求失败");
  }
  return data;
}

function renderWeekRows() {
  renderStats();
  weekBody.innerHTML = "";
  if (state.rows.length === 0) {
    emptyHint.classList.remove("hidden");
    return;
  }

  emptyHint.classList.add("hidden");
  const nowMs = Date.now();

  for (const row of state.rows) {
    const tr = document.createElement("tr");
    const teacherInfo = row.teacher ? `<div class="course-sub">${row.teacher}</div>` : "";
    const courseInfo = `<div class="course-main">${row.courseName}</div>${teacherInfo}`;
    const countdown = resolveCountdownText(row, nowMs);
    const signMeta = signButtonMeta(row, nowMs);
    const meta = attendanceMetaForRow(row, nowMs);
    const opBtn = signMeta.canSign
      ? `<button class="btn" type="button" data-sign="${row.key}" data-sign-mode="${signMeta.mode}" aria-label="${signMeta.text}：${row.courseName} ${formatTimeRange(row.startTime, row.endTime)}">${signMeta.text}</button>`
      : `<button class="btn" type="button" disabled>${signMeta.text}</button>`;

    tr.innerHTML = `
      <th scope="row">${formatDate(row.startTime)}</th>
      <td>${formatTimeRange(row.startTime, row.endTime)}</td>
      <td>
        <span class="countdown-chip" data-countdown data-start-time="${row.startTime}" data-end-time="${row.endTime}" data-attendance="${row.attendance}" data-state="${countdown.state}">
          ${countdown.text}
        </span>
      </td>
      <td>${courseInfo}</td>
      <td><span class="${meta.cls}">${meta.text}</span></td>
      <td>${opBtn}</td>
    `;
    weekBody.appendChild(tr);
  }

  updateCountdownElements();

  document.querySelectorAll("button[data-sign]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const key = btn.getAttribute("data-sign");
      const mode = btn.getAttribute("data-sign-mode") || "normal";
      if (!key) return;

      btn.disabled = true;
      btn.textContent = mode === "late" ? "迟到签到中..." : "签到中...";
      try {
        const result = await apiPost("/api/sign-now", { key });
        announce(result.message || "签到请求已提交", "info");
      } catch (err) {
        announce(err.message || "签到失败", "error");
      } finally {
        await refreshAll();
      }
    });
  });
}

function renderEvents() {
  eventList.innerHTML = "";
  for (const event of state.events.slice(-40).reverse()) {
    const li = document.createElement("li");
    li.className = `level-${event.level}`;
    const ts = new Date(event.at).toLocaleTimeString("zh-CN", {
      hour12: false,
    });
    const line1 = document.createElement("div");
    line1.className = "event-line";
    line1.textContent = `${ts} · ${event.message}`;
    li.appendChild(line1);
    eventList.appendChild(li);
  }
}

async function refreshWeek() {
  const data = await apiGet("/api/week");
  if (!data.ok) {
    throw new Error(data.message || "获取课表失败");
  }
  state.rows = data.data || [];
  renderWeekRows();
}

async function refreshRuntime() {
  const data = await apiGet("/api/runtime");
  if (!data.ok) {
    throw new Error(data.message || "获取运行状态失败");
  }
  state.events = data.events || [];
  renderEvents();
}

async function refreshAll() {
  if (state.loading) return;
  state.loading = true;
  refreshBtn.disabled = true;

  try {
    await refreshWeek();
    await refreshRuntime();
  } catch (err) {
    announce(err.message || "刷新失败", "error");
    console.error(err);
  } finally {
    state.loading = false;
    refreshBtn.disabled = false;
  }
}

refreshBtn.addEventListener("click", () => {
  void refreshAll();
});

logoutBtn.addEventListener("click", async () => {
  try {
    await apiPost("/logout", {});
  } finally {
    window.location.href = "/";
  }
});

void refreshAll();
setInterval(() => {
  updateCountdownElements();
}, 1000);
setInterval(() => {
  void refreshAll();
}, 15000);

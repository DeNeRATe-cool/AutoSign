const state = {
  rows: [],
  notifications: [],
  events: [],
  activePrompt: null,
  loading: false,
  lastFocus: null,
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

const promptModal = document.getElementById("promptModal");
const promptText = document.getElementById("promptText");
const promptYes = document.getElementById("promptYes");
const promptNo = document.getElementById("promptNo");
const SIGN_ADVANCE_SECONDS = 5 * 60;

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

function signAtMs(startIso) {
  return new Date(startIso).getTime() - SIGN_ADVANCE_SECONDS * 1000;
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
  const pending = state.rows.filter((row) => row.attendance === "未出勤").length;

  statTotal.textContent = String(total);
  statToday.textContent = String(today);
  statPending.textContent = String(pending);
}

function resolveCountdownText(attendance, targetMs, nowMs) {
  if (attendance !== "未出勤") {
    return { text: "已完成", state: "done" };
  }

  if (!Number.isFinite(targetMs)) {
    return { text: "--:--:--", state: "waiting" };
  }

  const diffSeconds = Math.floor((targetMs - nowMs) / 1000);
  if (diffSeconds > 0) {
    return { text: formatCountdown(diffSeconds), state: "waiting" };
  }

  if (diffSeconds >= -30 * 60) {
    return { text: "已到时点", state: "due" };
  }

  return { text: "已过时点", state: "overdue" };
}

function updateCountdownElements() {
  const nowMs = Date.now();
  document.querySelectorAll("[data-countdown]").forEach((node) => {
    const attendance = node.getAttribute("data-attendance") || "";
    const targetMs = Number(node.getAttribute("data-sign-at") || "0");
    const { text, state } = resolveCountdownText(attendance, targetMs, nowMs);
    node.textContent = text;
    node.setAttribute("data-state", state);
  });
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
  for (const row of state.rows) {
    const tr = document.createElement("tr");
    const meta = attendanceMeta(row.attendance);
    const teacherInfo = row.teacher ? `<div class="course-sub">${row.teacher}</div>` : "";
    const courseInfo = `<div class="course-main">${row.courseName}</div>${teacherInfo}`;

    const canManualSign = row.attendance === "未出勤";
    const signTargetMs = signAtMs(row.startTime);
    const countdown = resolveCountdownText(row.attendance, signTargetMs, Date.now());
    const opBtn = canManualSign
      ? `<button class="btn" type="button" data-sign="${row.key}" aria-label="立即签到：${row.courseName} ${formatTimeRange(row.startTime, row.endTime)}">立即签到</button>`
      : `<button class="btn" type="button" disabled>完成</button>`;

    tr.innerHTML = `
      <th scope="row">${formatDate(row.startTime)}</th>
      <td>${formatTimeRange(row.startTime, row.endTime)}</td>
      <td>
        <span class="countdown-chip" data-countdown data-sign-at="${signTargetMs}" data-attendance="${row.attendance}" data-state="${countdown.state}">
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
      if (!key) return;

      btn.disabled = true;
      btn.textContent = "签到中...";
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
  for (const event of state.events.slice(-30).reverse()) {
    const li = document.createElement("li");
    li.className = `level-${event.level}`;
    const ts = new Date(event.at).toLocaleTimeString("zh-CN", {
      hour12: false,
    });
    li.textContent = `${ts} · ${event.message}`;
    eventList.appendChild(li);
  }
}

function showPrompt(notification) {
  state.activePrompt = notification;
  state.lastFocus = document.activeElement;

  const t = new Date(notification.startTime).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  promptText.textContent = `${notification.courseName} 将于 ${t} 开始，是否立即签到？`;
  promptModal.classList.remove("hidden");
  promptModal.focus();
  promptYes.focus();
}

function hidePrompt() {
  state.activePrompt = null;
  promptModal.classList.add("hidden");
  if (state.lastFocus && typeof state.lastFocus.focus === "function") {
    state.lastFocus.focus();
  }
}

async function handlePromptDecision(action) {
  if (!state.activePrompt) return;

  const key = state.activePrompt.key;
  try {
    const result = await apiPost("/api/prompt-action", { key, action });
    announce(result.message || "操作已处理", "info");
  } catch (err) {
    announce(err.message || "操作失败", "error");
  } finally {
    hidePrompt();
    await refreshAll();
  }
}

function trapModalKeyboard(event) {
  if (promptModal.classList.contains("hidden")) return;

  if (event.key === "Escape") {
    event.preventDefault();
    void handlePromptDecision("later");
    return;
  }

  if (event.key !== "Tab") return;

  const focusable = [promptNo, promptYes].filter((el) => !el.disabled);
  if (focusable.length === 0) return;

  const currentIndex = focusable.indexOf(document.activeElement);
  if (event.shiftKey) {
    if (currentIndex <= 0) {
      event.preventDefault();
      focusable[focusable.length - 1].focus();
    }
  } else if (currentIndex === focusable.length - 1) {
    event.preventDefault();
    focusable[0].focus();
  }
}

function processNotifications() {
  if (state.activePrompt) return;
  if (state.notifications.length === 0) return;

  showPrompt(state.notifications[0]);
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
  state.notifications = data.notifications || [];
  state.events = data.events || [];
  renderEvents();
  processNotifications();
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

promptYes.addEventListener("click", () => {
  void handlePromptDecision("sign_now");
});

promptNo.addEventListener("click", () => {
  void handlePromptDecision("later");
});

promptModal.addEventListener("keydown", trapModalKeyboard);

void refreshAll();
setInterval(() => {
  updateCountdownElements();
}, 1000);
setInterval(() => {
  void refreshAll();
}, 15000);

/**
 * ============================================================================
 * SOBER CAFE MANAGEMENT SYSTEM — CLIENT LOGIC
 * Clean • Modern • Minimal • Highly Responsive Cafe Management SaaS
 * ============================================================================
 */

// ── Application State ────────────────────────────────────────────────────────
const AppState = {
  user: null,               // { id, username, nickname, is_admin, role, full_name, ... }
  role: "Pha Chế",          // 'Pha Chế' | 'Phục Vụ' | 'Quản Lý'
  token: null,              // X-Auth-Token
  activeTab: null,
  bootstrapData: null,
  weekInfo: null,           // Current week metadata (days, dates, labels)
  weekOffset: 0,            // Offset in weeks from current
  currentRoster: null,      // Active weekly roster
  shiftSchedules: {},       // Employee availability registrations
  swaps: [],                // Shift swap requests
  notifications: [],        // Notifications list
  personalSummary: null,    // Payroll & attendance summary

  // Roster Planning Context (Admin)
  selectedSlot: null,       // { day: 'T2', ca: 'Sáng', dateStr: '05/10', key: 'T2_Sáng' }
  drawerTab: "registered",  // 'registered' | 'unregistered'
  adminSelectedDay: "T2",   // For mobile admin day selector

  // Shift Swap Wizard (Employee)
  swapWizard: {
    step: 1,
    myShift: null,          // { day, ca, date, time }
    partnerShift: null,     // { nickname, role, day, ca, date, time }
    partnerNickname: null,
    reason: "",
    activeFilter: "all",    // 'all' | 'pending' | 'approved' | 'rejected'
  },

  scheduleViewMode: "week", // 'week' | 'month'
};

// ── SVG Icons Library (Lucide Crisp Vectors) ─────────────────────────────────
const SVG_ICONS = {
  home: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>',
  calendar: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>',
  swap: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/></svg>',
  dollar: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 18V6"/></svg>',
  bell: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>',
  user: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  users: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  matrix: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/><path d="M15 3v18"/></svg>',
  box: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>',
  megaphone: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>',
  settings: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  check: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>',
  close: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  plus: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
  clock: '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
};

function getIcon(name, size = 18) {
  const tpl = SVG_ICONS[name] || SVG_ICONS.home;
  return tpl.replace(/{s}/g, size);
}

// ── Format Helpers ───────────────────────────────────────────────────────────
function formatCurrency(amount) {
  if (amount === null || amount === undefined) return "0đ";
  const num = Math.round(Number(amount) || 0);
  return new Intl.NumberFormat("vi-VN").format(num) + "đ";
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function normalizeName(str) {
  if (!str) return "";
  return String(str)
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "d")
    .replace(/\s+/g, " ");
}

// ── Toast Notifications ──────────────────────────────────────────────────────
function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span>${type === 'success' ? '✓' : (type === 'error' ? '✕' : 'ℹ')}</span>
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(-8px)";
    toast.style.transition = "all 0.25s ease";
    setTimeout(() => toast.remove(), 250);
  }, 3200);
}

// ── Modal Dialog Manager ─────────────────────────────────────────────────────
function openModal(title, bodyHtml, actionsHtml = "") {
  const overlay = document.getElementById("modal-overlay");
  const titleEl = document.getElementById("modal-title");
  const bodyEl = document.getElementById("modal-body");
  const actionsEl = document.getElementById("modal-actions");

  if (!overlay || !titleEl || !bodyEl) return;
  titleEl.textContent = title;
  bodyEl.innerHTML = bodyHtml;
  actionsEl.innerHTML = actionsHtml;
  overlay.classList.add("active");
}

function closeModal() {
  const overlay = document.getElementById("modal-overlay");
  if (overlay) overlay.classList.remove("active");
}

function closeModalOnBackdrop(e) {
  if (e.target && e.target.id === "modal-overlay") {
    closeModal();
  }
}

// ── API Fetch Wrapper ────────────────────────────────────────────────────────
async function apiRequest(endpoint, methodOrOptions = {}, bodyData = null) {
  let options = {};
  if (typeof methodOrOptions === "string") {
    options = {
      method: methodOrOptions,
      body: bodyData,
    };
  } else if (methodOrOptions && typeof methodOrOptions === "object") {
    options = { ...methodOrOptions };
  }

  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  // Attach token if stored
  const token = AppState.token || localStorage.getItem("sober_token");
  if (token) {
    headers["X-Auth-Token"] = token;
  }

  // Attach Telegram initData if available
  if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
    headers["X-Telegram-Init-Data"] = window.Telegram.WebApp.initData;
  }

  const fetchOptions = {
    ...options,
    headers,
  };

  if (fetchOptions.body && typeof fetchOptions.body === "object" && !(fetchOptions.body instanceof FormData)) {
    fetchOptions.body = JSON.stringify(fetchOptions.body);
  }

  try {
    const resp = await fetch(endpoint, fetchOptions);
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 401) {
      // Token expired or invalid
      localStorage.removeItem("sober_token");
      AppState.token = null;
      showLoginScreen();
      return { success: false, error: "unauthorized", message: "Phiên đăng nhập hết hạn" };
    }
    return { ...data, _status: resp.status, _ok: resp.ok };
  } catch (err) {
    console.error("API error at " + endpoint + ":", err);
    return { success: false, error: "network_error", message: "Lỗi kết nối máy chủ" };
  }
}

// ── Application Initialization ───────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  // Telegram WebApp setup
  if (window.Telegram && window.Telegram.WebApp) {
    try {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
    } catch (e) {
      console.warn("Telegram WebApp API error:", e);
    }
  }

  // Handle forced logout parameter
  if (window.location.search.includes("logout")) {
    localStorage.removeItem("sober_token");
    AppState.token = null;
    const url = new URL(window.location.href);
    url.searchParams.delete("logout");
    window.history.replaceState({}, "", url.pathname + url.search);
  }

  // Restore stored token if exists
  const storedToken = localStorage.getItem("sober_token");
  if (storedToken) {
    AppState.token = storedToken;
  }

  // Check login state via bootstrap
  await initApp();
});

async function initApp() {
  const storedToken = localStorage.getItem("sober_token");
  const hasTelegram = Boolean(window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData);

  // If visiting directly from browser without existing login token, show login screen immediately
  if (!storedToken && !hasTelegram) {
    showLoginScreen();
    loadPublicUsers();
    return;
  }

  const bootResp = await apiRequest("/api/bootstrap");
  const user = bootResp && bootResp.user;
  const isAuth = user && (user.authenticated === true || user.authenticated === undefined) && user.username !== "web_employee";

  if (bootResp && bootResp.success && isAuth) {
    // Authenticated!
    AppState.bootstrapData = bootResp;
    AppState.user = bootResp.user;
    AppState.role = bootResp.user.role || (bootResp.user.is_admin ? "Quản Lý" : "Pha Chế");
    AppState.weekInfo = bootResp.week_info;
    AppState.currentRoster = bootResp.current_roster;
    AppState.shiftSchedules = bootResp.shift_schedules || {};
    AppState.swaps = bootResp.swaps || [];
    AppState.notifications = bootResp.notifications || [];
    AppState.employees = bootResp.employees || [];
    AppState.openSessions = bootResp.open_sessions || [];
    AppState.materials = bootResp.materials || [];
    AppState.materialGroups = bootResp.material_groups || [];
    AppState.pendingRewardsCount = bootResp.pending_rewards_count || 0;

    showMainApp();
  } else {
    // Needs login
    localStorage.removeItem("sober_token");
    AppState.token = null;
    showLoginScreen();
    loadPublicUsers();
  }
}

// ── Authentication & Login Screen ────────────────────────────────────────────
function showLoginScreen() {
  const loginView = document.getElementById("view-login");
  const mainView = document.getElementById("view-main");
  const sidebar = document.getElementById("desktop-sidebar");

  if (loginView) loginView.classList.remove("hidden");
  if (mainView) mainView.classList.add("hidden");
  if (sidebar) sidebar.style.display = "none";
}

function showMainApp() {
  document.getElementById("view-login").classList.add("hidden");
  document.getElementById("view-main").classList.remove("hidden");
  if (window.innerWidth >= 1024) {
    document.getElementById("desktop-sidebar").style.display = "flex";
  }

  renderNavigation();
  updateUserUI();

  // Bắt đầu đồng bộ dữ liệu thời gian thực
  startRealtimeSync();

  // Route to default role tab
  if (AppState.user && AppState.user.is_admin) {
    switchTab("tab-admin-dashboard");
  } else {
    switchTab("tab-emp-home");
  }
}

// ── Real-Time Auto-Sync Engine (Cập nhật song song không cần reload trang) ────
let syncIntervalId = null;
let lastSchedulesHash = "";
let lastRosterHash = "";
let isSyncing = false;

function startRealtimeSync() {
  if (syncIntervalId) return;
  lastSchedulesHash = JSON.stringify(AppState.shiftSchedules || {});
  lastRosterHash = JSON.stringify(AppState.currentRoster || {});

  syncIntervalId = setInterval(performRealtimeSync, 3500);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      performRealtimeSync();
    }
  });
}

async function performRealtimeSync(force = false) {
  if (!AppState.user || isSyncing || (document.hidden && !force)) return;
  isSyncing = true;

  try {
    const offset = AppState.weekOffset || 0;
    const resp = await apiRequest(`/api/sync?offset=${offset}`);

    if (resp && resp.success) {
      const newSchedulesJson = JSON.stringify(resp.shift_schedules || {});
      const newRosterJson = JSON.stringify(resp.roster || {});

      const schedulesChanged = lastSchedulesHash !== newSchedulesJson;
      const rosterChanged = lastRosterHash !== newRosterJson;

      lastSchedulesHash = newSchedulesJson;
      lastRosterHash = newRosterJson;

      AppState.shiftSchedules = resp.shift_schedules || {};
      if (resp.roster) AppState.currentRoster = resp.roster;
      if (resp.week_info) AppState.weekInfo = resp.week_info;
      if (resp.notifications) AppState.notifications = resp.notifications;

      // Cập nhật ngay màn hình nếu dữ liệu lịch thay đổi
      if (schedulesChanged || rosterChanged || force) {
        if (AppState.activeTab === "tab-admin-roster") {
          renderDesktopRosterGrid();
          if (AppState.selectedSlot) {
            renderContextualAssignmentDrawer();
          }
        } else if (AppState.activeTab === "tab-admin-matrix") {
          renderAdminAvailabilityMatrix();
        } else if (AppState.activeTab === "tab-emp-schedule") {
          renderEmployeeSchedule();
        }
      }

      // Live update Admin Dashboard khi có nhân viên báo thưởng ca mới
      if (resp.pending_rewards_count !== undefined) {
        if (AppState.pendingRewardsCount !== undefined && AppState.pendingRewardsCount !== resp.pending_rewards_count) {
          if (AppState.activeTab === "tab-admin-dashboard") {
            loadAdminDashboardData();
          }
          if (AppState.user && AppState.user.is_admin && resp.pending_rewards_count > AppState.pendingRewardsCount) {
            showToast(`🎁 Có ${resp.pending_rewards_count} yêu cầu thưởng ca mới cần duyệt!`, "info");
          }
        }
        AppState.pendingRewardsCount = resp.pending_rewards_count;
      }
    }
  } catch (e) {
    console.debug("Background sync error:", e);
  } finally {
    isSyncing = false;
  }
}

async function manualRefreshRoster() {
  await performRealtimeSync(true);
  showToast("✅ Đã cập nhật dữ liệu lịch mới nhất!", "success");
}

let _publicEmployeesCache = [];

async function loadPublicUsers() {
  const resp = await apiRequest("/api/auth/public-users");
  const container = document.getElementById("login-staff-chips");
  if (!container) return;

  let employees = [];
  if (resp && resp.success && Array.isArray(resp.employees) && resp.employees.length > 0) {
    employees = resp.employees;
  } else {
    employees = [
      { nickname: "An", full_name: "Nguyễn An", role: "Pha Chế" },
      { nickname: "Bình", full_name: "Trần Bình", role: "Phục Vụ" },
      { nickname: "Đại", full_name: "Lê Đại", role: "Barista" },
    ];
  }
  _publicEmployeesCache = employees;

  let html = `
    <button type="button" class="staff-quick-btn admin-card" data-username="admin" onclick="selectLoginUser('admin', 'Quản Lý', 'Admin quán', '⚡')">
      <div class="staff-btn-avatar">⚡</div>
      <div class="staff-btn-info">
        <div class="staff-btn-name">Quản Lý (Admin quán)</div>
        <div class="staff-btn-role">Toàn quyền quản trị & xếp lịch</div>
      </div>
      <span class="badge badge-primary" style="font-size: 11px;">Admin</span>
    </button>
  `;

  for (const emp of employees) {
    const nick = emp.nickname || emp.full_name;
    const role = emp.role || "Pha Chế";
    const initial = nick.charAt(0).toUpperCase();
    if (nick) {
      html += `
        <button type="button" class="staff-quick-btn" data-username="${escapeHtml(nick)}" onclick="selectLoginUser('${escapeHtml(nick)}', '${escapeHtml(nick)}', '${escapeHtml(role)}', '${escapeHtml(initial)}')">
          <div class="staff-btn-avatar">${escapeHtml(initial)}</div>
          <div class="staff-btn-info">
            <div class="staff-btn-name">${escapeHtml(nick)}</div>
            <div class="staff-btn-role">${escapeHtml(role)}</div>
          </div>
        </button>
      `;
    }
  }

  container.innerHTML = html;
}

function selectLoginUser(username, displayName, role, avatarLetter) {
  const hiddenInput = document.getElementById("login-username");
  const pwdInput = document.getElementById("login-password");
  const banner = document.getElementById("login-selected-banner");
  const avatarEl = document.getElementById("login-selected-avatar");
  const nameEl = document.getElementById("login-selected-name");
  const roleEl = document.getElementById("login-selected-role");

  if (hiddenInput) hiddenInput.value = username;

  if (banner && avatarEl && nameEl && roleEl) {
    avatarEl.textContent = avatarLetter || (displayName ? displayName.charAt(0).toUpperCase() : "U");
    nameEl.textContent = displayName || username;
    roleEl.textContent = role || "Nhân viên";
    banner.classList.remove("hidden");
  }

  // Highlight active staff button
  document.querySelectorAll(".staff-quick-btn").forEach(btn => {
    if (btn.getAttribute("data-username") === username) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });

  if (pwdInput) {
    if (!pwdInput.value) {
      pwdInput.value = "123456789";
    }
    pwdInput.focus();
  }
}

function clearLoginUserSelection() {
  const hiddenInput = document.getElementById("login-username");
  const banner = document.getElementById("login-selected-banner");
  if (hiddenInput) hiddenInput.value = "";
  if (banner) banner.classList.add("hidden");
  document.querySelectorAll(".staff-quick-btn").forEach(btn => btn.classList.remove("active"));
}

function quickFillLogin(username) {
  if (username === "admin") {
    selectLoginUser("admin", "Quản Lý", "Admin quán", "⚡");
    return;
  }
  const empList = _publicEmployeesCache || [];
  const found = empList.find(e => (e.nickname || e.full_name) === username);
  const role = (found && found.role) || "Nhân viên";
  const initial = username.charAt(0).toUpperCase();
  selectLoginUser(username, username, role, initial);
}

function togglePasswordVisibility(id) {
  const input = document.getElementById(id);
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value.trim();
  const btn = document.getElementById("btn-login-submit");

  if (!username) {
    showToast("Vui lòng chạm chọn tên nhân viên của bạn ở trên", "error");
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<span>Đang đăng nhập...</span>`;

  const resp = await apiRequest("/api/auth/login", {
    method: "POST",
    body: {
      username,
      password,
    },
  });

  btn.disabled = false;
  btn.innerHTML = `<span>Vào ca làm việc</span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>`;

  if (resp && resp.success) {
    AppState.token = resp.token;
    localStorage.setItem("sober_token", resp.token);
    AppState.user = resp.user;
    AppState.role = resp.user.role || (resp.user.is_admin ? "Quản Lý" : "Pha Chế");

    showToast("Đăng nhập thành công!", "success");
    await initApp();
  } else {
    showToast(resp.message || "Tên đăng nhập hoặc mật khẩu không đúng", "error");
  }
}

function handleLogout() {
  openModal(
    "Xác nhận đăng xuất",
    `<p>Bạn có chắc chắn muốn đăng xuất khỏi tài khoản <strong>${escapeHtml(AppState.user ? (AppState.user.nickname || AppState.user.username) : "")}</strong>?</p>`,
    `
      <button class="btn btn-secondary btn-sm" onclick="closeModal()">Hủy</button>
      <button class="btn btn-danger btn-sm" onclick="confirmLogout()">Đăng xuất ngay</button>
    `
  );
}

function confirmLogout() {
  closeModal();
  localStorage.removeItem("sober_token");
  AppState.token = null;
  AppState.user = null;
  showToast("Đã đăng xuất", "info");
  showLoginScreen();
  loadPublicUsers();
}

// ── Navigation & Role Separation ─────────────────────────────────────────────
function renderNavigation() {
  const isAdmin = AppState.user && AppState.user.is_admin;
  const sidebarNav = document.getElementById("sidebar-nav-items");
  const bottomNav = document.getElementById("bottom-nav");

  if (!sidebarNav || !bottomNav) return;

  if (isAdmin) {
    // Admin Desktop Sidebar
    sidebarNav.innerHTML = `
      <li class="sidebar-nav-item" data-tab="tab-admin-dashboard" onclick="switchTab('tab-admin-dashboard')">
        ${getIcon("home")} <span>Tổng quan</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-admin-roster" onclick="switchTab('tab-admin-roster')">
        ${getIcon("calendar")} <span>Xếp lịch</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-admin-matrix" onclick="switchTab('tab-admin-matrix')">
        ${getIcon("matrix")} <span>Đăng ký lịch</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-admin-swaps" onclick="switchTab('tab-admin-swaps')">
        ${getIcon("swap")} <span>Duyệt đổi ca</span>
        <span id="sidebar-swap-badge" class="sidebar-nav-badge hidden">0</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-admin-employees" onclick="switchTab('tab-admin-employees')">
        ${getIcon("users")} <span>Nhân sự</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-admin-payroll" onclick="switchTab('tab-admin-payroll')">
        ${getIcon("dollar")} <span>Công & lương</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-admin-inventory" onclick="switchTab('tab-admin-inventory')">
        ${getIcon("box")} <span>Kho / NVL</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-admin-announcements" onclick="switchTab('tab-admin-announcements')">
        ${getIcon("megaphone")} <span>Thông báo quán</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-admin-settings" onclick="switchTab('tab-admin-settings')">
        ${getIcon("settings")} <span>Cài đặt</span>
      </li>
    `;

    // Admin Mobile Bottom Nav (5 items)
    bottomNav.innerHTML = `
      <button class="bottom-nav-item" data-tab="tab-admin-dashboard" onclick="switchTab('tab-admin-dashboard')">
        ${getIcon("home", 20)}
        <span>Tổng quan</span>
      </button>
      <button class="bottom-nav-item" data-tab="tab-admin-roster" onclick="switchTab('tab-admin-roster')">
        ${getIcon("calendar", 20)}
        <span>Lịch</span>
      </button>
      <button class="bottom-nav-item" data-tab="tab-admin-swaps" onclick="switchTab('tab-admin-swaps')">
        ${getIcon("swap", 20)}
        <span>Duyệt</span>
        <span id="bottom-swap-badge" class="bottom-nav-badge hidden">0</span>
      </button>
      <button class="bottom-nav-item" data-tab="tab-admin-employees" onclick="switchTab('tab-admin-employees')">
        ${getIcon("users", 20)}
        <span>Nhân sự</span>
      </button>
      <button class="bottom-nav-item" data-tab="tab-profile" onclick="switchTab('tab-profile')">
        ${getIcon("user", 20)}
        <span>Cá nhân</span>
      </button>
    `;
  } else {
    // Employee Desktop Sidebar
    sidebarNav.innerHTML = `
      <li class="sidebar-nav-item" data-tab="tab-emp-home" onclick="switchTab('tab-emp-home')">
        ${getIcon("home")} <span>Trang chủ</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-emp-schedule" onclick="switchTab('tab-emp-schedule')">
        ${getIcon("calendar")} <span>Lịch làm việc</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-emp-register" onclick="switchTab('tab-emp-register')">
        ${getIcon("matrix")} <span>Đăng ký lịch</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-emp-swap" onclick="switchTab('tab-emp-swap')">
        ${getIcon("swap")} <span>Đổi ca</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-emp-payroll" onclick="switchTab('tab-emp-payroll')">
        ${getIcon("dollar")} <span>Công & lương</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-notifications" onclick="switchTab('tab-notifications')">
        ${getIcon("bell")} <span>Thông báo</span>
        <span id="sidebar-notif-badge" class="sidebar-nav-badge hidden">0</span>
      </li>
      <li class="sidebar-nav-item" data-tab="tab-profile" onclick="switchTab('tab-profile')">
        ${getIcon("user")} <span>Tài khoản</span>
      </li>
    `;

    // Employee Mobile Bottom Nav (5 items)
    bottomNav.innerHTML = `
      <button class="bottom-nav-item" data-tab="tab-emp-home" onclick="switchTab('tab-emp-home')">
        ${getIcon("home", 20)}
        <span>Trang chủ</span>
      </button>
      <button class="bottom-nav-item" data-tab="tab-emp-schedule" onclick="switchTab('tab-emp-schedule')">
        ${getIcon("calendar", 20)}
        <span>Lịch</span>
      </button>
      <button class="bottom-nav-item" data-tab="tab-emp-swap" onclick="switchTab('tab-emp-swap')">
        ${getIcon("swap", 20)}
        <span>Đổi ca</span>
      </button>
      <button class="bottom-nav-item" data-tab="tab-notifications" onclick="switchTab('tab-notifications')">
        ${getIcon("bell", 20)}
        <span>Thông báo</span>
        <span id="bottom-notif-badge" class="bottom-nav-badge hidden">0</span>
      </button>
      <button class="bottom-nav-item" data-tab="tab-profile" onclick="switchTab('tab-profile')">
        ${getIcon("user", 20)}
        <span>Cá nhân</span>
      </button>
    `;
  }
}

function updateUserUI() {
  if (!AppState.user) return;
  const name = AppState.user.nickname || AppState.user.username || "Nhân viên";
  const role = AppState.user.role || (AppState.user.is_admin ? "Quản Lý" : "Pha Chế");
  const initial = name.charAt(0).toUpperCase();

  // Sidebar user info
  const sideAvatar = document.getElementById("sidebar-user-avatar");
  const sideName = document.getElementById("sidebar-user-name");
  const sideRole = document.getElementById("sidebar-user-role");
  if (sideAvatar) sideAvatar.textContent = initial;
  if (sideName) sideName.textContent = name;
  if (sideRole) sideRole.textContent = role;

  // Mobile header badge
  const mobBadge = document.getElementById("mobile-role-badge");
  if (mobBadge) mobBadge.textContent = role;

  // Profile tab info
  const profAvatar = document.getElementById("profile-avatar");
  const profName = document.getElementById("profile-name");
  const profRole = document.getElementById("profile-role");
  if (profAvatar) profAvatar.textContent = initial;
  if (profName) profName.textContent = name;
  if (profRole) profRole.textContent = role;

  // Employee Welcome
  const empWelcomeName = document.getElementById("emp-welcome-name");
  const empWelcomeRole = document.getElementById("emp-welcome-role");
  if (empWelcomeName) empWelcomeName.textContent = name;
  if (empWelcomeRole) empWelcomeRole.textContent = role;

  renderEmployeeRewardCard();
  updateBadgeCounts();
}

function updateBadgeCounts() {
  const isAdmin = AppState.user && AppState.user.is_admin;
  if (isAdmin) {
    const pendingSwaps = (AppState.swaps || []).filter(s => s.status === "pending").length;
    const sideBadge = document.getElementById("sidebar-swap-badge");
    const botBadge = document.getElementById("bottom-swap-badge");
    if (sideBadge) {
      sideBadge.textContent = pendingSwaps;
      sideBadge.classList.toggle("hidden", pendingSwaps === 0);
    }
    if (botBadge) {
      botBadge.textContent = pendingSwaps;
      botBadge.classList.toggle("hidden", pendingSwaps === 0);
    }
  } else {
    const unread = (AppState.notifications || []).filter(n => !n.is_read).length;
    const sideBadge = document.getElementById("sidebar-notif-badge");
    const botBadge = document.getElementById("bottom-notif-badge");
    const headerDot = document.getElementById("header-notif-dot");
    if (sideBadge) {
      sideBadge.textContent = unread;
      sideBadge.classList.toggle("hidden", unread === 0);
    }
    if (botBadge) {
      botBadge.textContent = unread;
      botBadge.classList.toggle("hidden", unread === 0);
    }
    if (headerDot) {
      headerDot.classList.toggle("hidden", unread === 0);
    }
  }
}

function switchTab(tabId) {
  // Hide all panels
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));

  // Show selected panel
  const panel = document.getElementById(tabId);
  if (panel) {
    panel.classList.remove("hidden");
    AppState.activeTab = tabId;
  }

  // Sync active nav item in Sidebar
  document.querySelectorAll(".sidebar-nav-item").forEach(item => {
    item.classList.toggle("active", item.getAttribute("data-tab") === tabId);
  });

  // Sync active nav item in Mobile Bottom Bar
  document.querySelectorAll(".bottom-nav-item").forEach(item => {
    item.classList.toggle("active", item.getAttribute("data-tab") === tabId);
  });

  // Scroll to top
  window.scrollTo({ top: 0, behavior: "smooth" });

  // Tab-specific lifecycle loader
  switch (tabId) {
    case "tab-emp-home":
      loadEmployeeHomeData();
      break;
    case "tab-emp-register":
      renderAvailabilityForm();
      break;
    case "tab-emp-schedule":
      renderEmployeeSchedule();
      break;
    case "tab-emp-swap":
      renderSwapWorkflow();
      break;
    case "tab-emp-payroll":
      loadEmployeePayrollData();
      break;
    case "tab-notifications":
      renderNotificationsTab();
      break;
    case "tab-admin-dashboard":
      loadAdminDashboardData();
      break;
    case "tab-admin-roster":
      loadAdminRosterData();
      break;
    case "tab-admin-matrix":
      renderAdminAvailabilityMatrix();
      break;
    case "tab-admin-swaps":
      renderAdminSwapsTab();
      break;
    case "tab-admin-employees":
      renderAdminEmployeesTab();
      break;
    case "tab-admin-payroll":
      loadAdminSalaryData();
      break;
    case "tab-admin-inventory":
      renderAdminInventoryTab();
      break;
  }
}

// ============================================================================
// EMPLOYEE MODULES
// ============================================================================

// ── 1. Employee Home ────────────────────────────────────────────────────────
async function loadEmployeeHomeData() {
  if (!AppState.user) return;
  const nick = AppState.user.nickname || AppState.user.username;

  // 0. Update reward card balance
  renderEmployeeRewardCard();

  // 1. Fetch personal salary summary
  const summaryResp = await apiRequest(`/api/personal/summary?nickname=${encodeURIComponent(nick)}`);
  if (summaryResp && summaryResp.success && summaryResp.summary) {
    AppState.personalSummary = summaryResp.summary;
    const s = summaryResp.summary;

    const salaryEl = document.getElementById("emp-hero-salary");
    const periodEl = document.getElementById("emp-hero-period");
    const hoursEl = document.getElementById("emp-stat-hours");
    const otEl = document.getElementById("emp-stat-ot");
    const daysEl = document.getElementById("emp-stat-days");

    if (salaryEl) salaryEl.textContent = formatCurrency((s.estimated_pay_k || 0) * 1000);
    if (periodEl) periodEl.textContent = s.period ? `Kỳ lương: ${s.period}` : `Tháng ${s.month}/${s.year}`;
    if (hoursEl) hoursEl.textContent = `${s.total_hours || 0}h`;
    if (otEl) otEl.textContent = `${s.overtime_hours || 0}h`;
    if (daysEl) daysEl.textContent = `${(s.recent_checkins || []).length} ca`;

    if (s.balance !== undefined && s.balance !== null) {
      if (AppState.user) AppState.user.balance = s.balance;
      const userNorm = normalizeName(nick);
      const myEmp = (AppState.employees || []).find(e => {
        return normalizeName(e.nickname || "") === userNorm || normalizeName(e.full_name || "") === userNorm;
      });
      if (myEmp) myEmp.balance = s.balance;
    }
    renderEmployeeRewardCard();
  }

  // 2. Identify next upcoming shift from current roster
  findNextUpcomingShift(nick);

  // 3. Render recent notifications snippet
  renderHomeNotificationsSnippet();
}

function findNextUpcomingShift(nick) {
  const timeEl = document.getElementById("emp-next-shift-time");
  const roleEl = document.getElementById("emp-next-shift-role");
  const statusEl = document.getElementById("emp-next-shift-status");

  if (!AppState.currentRoster || !AppState.currentRoster.shifts) {
    if (timeEl) timeEl.textContent = "Chưa có lịch tuần chính thức";
    if (roleEl) roleEl.textContent = "Vui lòng kiểm tra lại sau khi Quản lý chốt lịch";
    if (statusEl) statusEl.textContent = "Chờ xếp ca";
    return;
  }

  const shifts = AppState.currentRoster.shifts;
  const days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
  const cas = [
    { name: "Sáng", time: "07:00 – 12:00" },
    { name: "Chiều", time: "13:00 – 17:00" },
    { name: "Tối", time: "18:00 – 22:30" }
  ];

  let found = null;
  const userNorm = (nick || "").trim().toLowerCase();

  for (const d of days) {
    for (const ca of cas) {
      const slotKey = `${d}_${ca.name}`;
      const staffList = shifts[slotKey] || [];
      if (staffList.some(name => name.toLowerCase() === userNorm)) {
        found = { day: d, ca: ca.name, time: ca.time };
        break;
      }
    }
    if (found) break;
  }

  if (found) {
    const dayNames = { T2: "Thứ Hai", T3: "Thứ Ba", T4: "Thứ Tư", T5: "Thứ Năm", T6: "Thứ Sáu", T7: "Thứ Bảy", CN: "Chủ Nhật" };
    if (timeEl) timeEl.textContent = `${dayNames[found.day]} • Ca ${found.ca} (${found.time})`;
    if (roleEl) roleEl.textContent = `Vị trí: ${AppState.user.role || 'Barista'}`;
    if (statusEl) statusEl.textContent = "Đã xếp lịch";
  } else {
    if (timeEl) timeEl.textContent = "Bạn chưa có ca làm tiếp theo";
    if (roleEl) roleEl.textContent = "Đã đăng ký ca? Xem thêm tại mục Đăng ký lịch";
    if (statusEl) statusEl.textContent = "Không có ca";
  }
}

function renderHomeNotificationsSnippet() {
  const container = document.getElementById("emp-home-notifs-list");
  if (!container) return;

  const notifs = AppState.notifications || [];
  if (notifs.length === 0) {
    container.innerHTML = `<div class="empty-state" style="padding: 16px;"><p>Chưa có thông báo mới.</p></div>`;
    return;
  }

  let html = '<div style="display: flex; flex-direction: column; gap: 8px;">';
  notifs.slice(0, 3).forEach(n => {
    html += `
      <div style="padding: 10px 12px; background: ${n.is_read ? 'var(--bg-app)' : 'var(--primary-subtle)'}; border-radius: var(--radius-md); font-size: 13px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 2px;">
          <strong style="color: var(--text-main);">${escapeHtml(n.title)}</strong>
          <span style="font-size: 11px; color: var(--text-dim);">${escapeHtml(n.created_at)}</span>
        </div>
        <p style="font-size: 12px; color: var(--text-muted); margin: 0;">${escapeHtml(n.message)}</p>
      </div>
    `;
  });
  html += '</div>';
  container.innerHTML = html;
}

// ── 1.1 Quỹ Ly Thưởng Doanh Thu (Yêu Cầu & Dùng Ly) ──────────────────────────
function renderEmployeeRewardCard() {
  if (!AppState.user) return;
  const nick = AppState.user.nickname || AppState.user.username || "";
  const userNorm = normalizeName(nick);

  let balance = null;
  // 1. Kiểm tra từ personalSummary nếu đã tải
  if (AppState.personalSummary && AppState.personalSummary.balance !== undefined && AppState.personalSummary.balance !== null) {
    balance = AppState.personalSummary.balance;
  }
  // 2. Kiểm tra từ danh sách nhân viên AppState.employees
  if (balance === null && AppState.employees && AppState.employees.length > 0) {
    const myEmp = AppState.employees.find(e => {
      const n1 = normalizeName(e.nickname || "");
      const n2 = normalizeName(e.full_name || "");
      return (n1 && n1 === userNorm) || (n2 && n2 === userNorm);
    });
    if (myEmp && myEmp.balance !== undefined && myEmp.balance !== null) {
      balance = myEmp.balance;
    }
  }
  // 3. Fallback về AppState.user.balance hoặc 0
  if (balance === null) {
    balance = (AppState.user && AppState.user.balance !== undefined && AppState.user.balance !== null) ? AppState.user.balance : 0;
  }

  const countEl = document.getElementById("emp-reward-count");
  if (countEl) {
    countEl.textContent = balance;
  }
}

function showRewardRequestModal() {
  if (!AppState.user) return;
  const currentNick = AppState.user.nickname || AppState.user.username || "";
  const currentNorm = normalizeName(currentNick);

  // Inferred shift (Sáng, Chiều, Tối)
  const currentCa = (AppState.serverTime && AppState.serverTime.inferred_ca) || "Tối";

  // List active employees
  const staffList = (AppState.employees || []).filter(e => e.active !== false);

  // Collect checked-in nicknames
  const checkedInNicks = new Set((AppState.openSessions || []).map(s => normalizeName(s.nickname || s.employee_name || "")));

  let staffHtml = staffList.map(e => {
    const isMe = normalizeName(e.nickname || e.full_name) === currentNorm;
    const isCheckedIn = checkedInNicks.has(normalizeName(e.nickname || e.full_name));
    const preChecked = isMe || isCheckedIn;
    return `
      <label class="reward-staff-item ${preChecked ? 'selected' : ''}" id="staff-row-${escapeHtml(e.nickname)}" onclick="toggleRewardStaffRow(this)">
        <div style="display: flex; align-items: center; gap: 10px;">
          <input type="checkbox" name="reward_staff" value="${escapeHtml(e.nickname)}" ${preChecked ? 'checked' : ''} style="pointer-events: none;">
          <div>
            <div style="font-weight: 600; font-size: 14px; color: var(--text-main);">
              ${escapeHtml(e.full_name || e.nickname)} ${isMe ? '<span class="badge badge-primary" style="font-size: 10px; margin-left: 4px;">Bạn</span>' : ''}
            </div>
            <div style="font-size: 12px; color: var(--text-muted);">${escapeHtml(e.role || 'Pha chế')} ${isCheckedIn ? '• <span style="color:var(--success);">Đang check-in</span>' : ''}</div>
          </div>
        </div>
      </label>
    `;
  }).join('');

  const bodyHtml = `
    <div style="margin-bottom: 16px;">
      <label class="form-label" style="margin-bottom: 8px;">1. Chọn ca làm việc:</label>
      <div class="reward-shift-selector" id="reward-shift-picker">
        <div class="reward-shift-chip ${currentCa === 'Sáng' ? 'active' : ''}" onclick="selectRewardShift(this, 'Sáng')">🌅 Ca Sáng</div>
        <div class="reward-shift-chip ${currentCa === 'Chiều' ? 'active' : ''}" onclick="selectRewardShift(this, 'Chiều')">☀️ Ca Chiều</div>
        <div class="reward-shift-chip ${currentCa === 'Tối' ? 'active' : ''}" onclick="selectRewardShift(this, 'Tối')">🌙 Ca Tối</div>
      </div>
      <input type="hidden" id="selected-reward-ca" value="${escapeHtml(currentCa)}">
    </div>

    <div style="margin-bottom: 12px;">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
        <label class="form-label" style="margin-bottom: 0;">2. Chọn các bạn cùng trực ca (+1 ly):</label>
        <button type="button" class="btn btn-ghost btn-xs" onclick="quickSelectActiveOnly()">Chọn bạn check-in</button>
      </div>
      <div class="reward-staff-list" id="reward-staff-list">
        ${staffHtml}
      </div>
    </div>

    <div style="padding: 10px 12px; background: var(--bg-card-subtle); border-radius: var(--radius-md); font-size: 12px; color: var(--text-muted);">
      ℹ️ <strong>Lưu ý:</strong> Sau khi bấm gửi, yêu cầu sẽ được chuyển đến Quản lý phê duyệt (qua Telegram & WebApp) trước khi cộng vào số dư ly thưởng.
    </div>
  `;

  const actionsHtml = `
    <button type="button" class="btn btn-secondary" onclick="closeModal()">Hủy</button>
    <button type="button" class="btn btn-primary" id="btn-submit-reward-req" onclick="submitRewardRequest()">
      <span>Gửi Yêu Cầu Quản Lý</span>
    </button>
  `;

  openModal("Báo Thưởng Doanh Thu", bodyHtml, actionsHtml);
}

function selectRewardShift(chip, ca) {
  document.querySelectorAll("#reward-shift-picker .reward-shift-chip").forEach(c => c.classList.remove("active"));
  chip.classList.add("active");
  const hiddenInput = document.getElementById("selected-reward-ca");
  if (hiddenInput) hiddenInput.value = ca;
}

function toggleRewardStaffRow(row) {
  const cb = row.querySelector("input[type=checkbox]");
  if (!cb) return;
  cb.checked = !cb.checked;
  row.classList.toggle("selected", cb.checked);
}

function quickSelectActiveOnly() {
  const checkedInNicks = new Set((AppState.openSessions || []).map(s => normalizeName(s.nickname || s.employee_name || "")));
  const currentNick = AppState.user ? normalizeName(AppState.user.nickname || AppState.user.username || "") : "";

  document.querySelectorAll("#reward-staff-list .reward-staff-item").forEach(row => {
    const cb = row.querySelector("input[type=checkbox]");
    if (!cb) return;
    const nickNorm = normalizeName(cb.value);
    const shouldCheck = checkedInNicks.has(nickNorm) || nickNorm === currentNick;
    cb.checked = shouldCheck;
    row.classList.toggle("selected", shouldCheck);
  });
}

async function submitRewardRequest() {
  const caInput = document.getElementById("selected-reward-ca");
  const ca = caInput ? caInput.value : "Tối";

  const selectedBoxes = Array.from(document.querySelectorAll("#reward-staff-list input[type=checkbox]:checked"));
  const employees = selectedBoxes.map(b => b.value);

  if (employees.length === 0) {
    showToast("Vui lòng chọn ít nhất 1 nhân viên trong ca!", "warning");
    return;
  }

  const submitBtn = document.getElementById("btn-submit-reward-req");
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span>Đang gửi...</span>`;
  }

  const resp = await apiRequest("/api/rewards/request", {
    method: "POST",
    body: {
      employees: employees,
      ca: ca
    }
  });

  if (resp && resp.success) {
    closeModal();
    showToast(resp.message || "Đã gửi yêu cầu thưởng ca thành công!", "success");
    if (resp.approved && resp.employees) {
      AppState.employees = resp.employees;
      renderEmployeeRewardCard();
    }
  } else {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span>Gửi Yêu Cầu Quản Lý</span>`;
    }
    showToast((resp && resp.message) || "Lỗi khi gửi yêu cầu thưởng", "danger");
  }
}

function showUseRewardModal() {
  if (!AppState.user) return;
  const nick = AppState.user.nickname || AppState.user.username || "";
  const userNorm = normalizeName(nick);
  const myEmp = (AppState.employees || []).find(e => normalizeName(e.nickname || e.full_name) === userNorm);
  const balance = (myEmp && myEmp.balance !== undefined && myEmp.balance !== null) ? myEmp.balance : (AppState.user.balance || 0);

  if (balance <= 0) {
    const bodyHtml = `
      <div style="text-align: center; padding: 16px 8px;">
        <div style="font-size: 40px; margin-bottom: 12px;">☕</div>
        <h4 style="margin-bottom: 8px; color: var(--text-main);">Bạn chưa có ly thưởng nào</h4>
        <p style="font-size: 13px; color: var(--text-muted); line-height: 1.5; margin: 0;">
          Số dư ly thưởng hiện tại là <strong>0 ly</strong>.<br>
          Khi ca làm việc của bạn đạt doanh thu thưởng, hãy dùng nút <strong>Báo thưởng ca</strong> để được Quản lý duyệt cộng thưởng nhé!
        </p>
      </div>
    `;
    const actionsHtml = `
      <button type="button" class="btn btn-primary" onclick="closeModal()" style="width: 100%;">Đã hiểu</button>
    `;
    openModal("Quỹ ly thưởng", bodyHtml, actionsHtml);
    return;
  }

  const bodyHtml = `
    <div style="text-align: center; padding: 16px 8px;">
      <div style="font-size: 40px; margin-bottom: 12px;">🥤</div>
      <h4 style="margin-bottom: 8px; color: var(--text-main);">Dùng 1 ly thưởng tại quán?</h4>
      <p style="font-size: 14px; color: var(--text-muted); line-height: 1.5; margin-bottom: 16px;">
        Bạn hiện đang có <strong style="color: var(--primary); font-size: 16px;">${balance} ly thưởng</strong>.<br>
        Bạn có muốn dùng <strong>1 ly nước</strong> ngay bây giờ không?
      </p>
      <div style="padding: 10px 12px; background: var(--warning-bg); border: 1px solid var(--warning-border); border-radius: var(--radius-md); font-size: 12px; color: #925829; text-align: left;">
        ℹ️ Hệ thống sẽ trừ 1 ly vào quỹ cá nhân trên Google Sheets và tự động gửi thông báo đối soát vào nhóm quán.
      </div>
    </div>
  `;

  const actionsHtml = `
    <button type="button" class="btn btn-secondary" onclick="closeModal()">Để sau</button>
    <button type="button" class="btn btn-primary" id="btn-confirm-use-reward" onclick="submitUseReward('${escapeHtml(nick)}')">
      <span>Xác nhận dùng 1 ly</span>
    </button>
  `;

  openModal("Xác nhận dùng ly thưởng", bodyHtml, actionsHtml);
}

async function submitUseReward(nick) {
  const btn = document.getElementById("btn-confirm-use-reward");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span>Đang trừ...</span>`;
  }

  const resp = await apiRequest("/api/rewards/use", {
    method: "POST",
    body: { nickname: nick }
  });
  if (resp && resp.success) {
    closeModal();
    showToast(resp.message || "Đã trừ 1 ly thưởng thành công!", "success");

    // Update state
    if (resp.balance !== undefined) {
      if (AppState.user) AppState.user.balance = resp.balance;
      const userNorm = normalizeName(nick);
      const myEmp = (AppState.employees || []).find(e => normalizeName(e.nickname || e.full_name) === userNorm);
      if (myEmp) myEmp.balance = resp.balance;
    }
    if (resp.employees) {
      AppState.employees = resp.employees;
    }
    renderEmployeeRewardCard();
  } else {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<span>Xác nhận dùng 1 ly</span>`;
    }
    showToast((resp && resp.message) || "Lỗi khi trừ ly thưởng", "danger");
  }
}

// ── 2. Employee Availability Registration ────────────────────────────────────
function renderAvailabilityForm() {
  const wInfo = AppState.weekInfo;
  const labelEl = document.getElementById("reg-week-label");
  const container = document.getElementById("reg-days-container");
  if (!container) return;

  if (wInfo && labelEl) {
    labelEl.textContent = wInfo.week_label || "Tuần tới";
  }

  const days = (wInfo && wInfo.days) ? wInfo.days : [
    { code: "T2", label: "Thứ Hai", date_str: "T2" },
    { code: "T3", label: "Thứ Ba", date_str: "T3" },
    { code: "T4", label: "Thứ Tư", date_str: "T4" },
    { code: "T5", label: "Thứ Năm", date_str: "T5" },
    { code: "T6", label: "Thứ Sáu", date_str: "T6" },
    { code: "T7", label: "Thứ Bảy", date_str: "T7" },
    { code: "CN", label: "Chủ Nhật", date_str: "CN" },
  ];

  // Check if user already registered for this week
  const nick = AppState.user ? (AppState.user.nickname || AppState.user.username) : "";
  const existing = (AppState.shiftSchedules || {})[nick] || {};
  const currentSlots = existing.slots || {};

  let html = "";
  days.forEach(d => {
    const selected = currentSlots[d.code] || [];
    html += `
      <div class="reg-day-row">
        <div class="reg-day-info">
          <span class="reg-day-name">${d.label}</span>
          <span class="reg-day-date">${d.date_str}</span>
        </div>
        <div class="reg-slots-options" data-day="${d.code}">
          <div class="slot-toggle-pill ${selected.includes('Sáng') ? 'checked' : ''}" onclick="toggleSlotPill(this)" data-ca="Sáng">
            <span>🌅 Sáng</span>
            <small style="font-size: 11px; opacity: 0.85;">6:30–12h</small>
          </div>
          <div class="slot-toggle-pill ${selected.includes('Chiều') ? 'checked' : ''}" onclick="toggleSlotPill(this)" data-ca="Chiều">
            <span>☀️ Chiều</span>
            <small style="font-size: 11px; opacity: 0.85;">12h–18h</small>
          </div>
          <div class="slot-toggle-pill ${selected.includes('Tối') ? 'checked' : ''}" onclick="toggleSlotPill(this)" data-ca="Tối">
            <span>🌙 Tối</span>
            <small style="font-size: 11px; opacity: 0.85;">18h–22h30</small>
          </div>
        </div>
      </div>
    `;
  });
  container.innerHTML = html;
  updateAvailabilityCounter();
}

function toggleSlotPill(el) {
  el.classList.toggle("checked");
  updateAvailabilityCounter();
}

function updateAvailabilityCounter() {
  const count = document.querySelectorAll(".slot-toggle-pill.checked").length;
  const badge = document.getElementById("reg-selected-count-badge");
  if (badge) {
    badge.textContent = `${count} ca rảnh`;
    badge.className = count > 0 ? "badge badge-primary" : "badge badge-muted";
  }
}

function quickSelectAllShifts(mode) {
  document.querySelectorAll(".reg-slots-options").forEach(row => {
    const pills = row.querySelectorAll(".slot-toggle-pill");
    if (mode === "all") {
      pills.forEach(p => p.classList.add("checked"));
    } else if (mode === "evening") {
      pills[0].classList.remove("checked");
      pills[1].classList.remove("checked");
      pills[2].classList.add("checked");
    } else if (mode === "clear") {
      pills.forEach(p => p.classList.remove("checked"));
    }
  });
  updateAvailabilityCounter();
}

function copyLastWeekAvailability() {
  const nick = AppState.user ? (AppState.user.nickname || AppState.user.username) : "";
  const existing = (AppState.shiftSchedules || {})[nick];
  if (!existing || !existing.slots) {
    showToast("Chưa có dữ liệu tuần trước để sao chép", "info");
    return;
  }

  document.querySelectorAll(".reg-slots-options").forEach(row => {
    const day = row.getAttribute("data-day");
    const slots = existing.slots[day] || [];
    const pills = row.querySelectorAll(".slot-toggle-pill");
    pills[0].classList.toggle("checked", slots.includes("Sáng"));
    pills[1].classList.toggle("checked", slots.includes("Chiều"));
    pills[2].classList.toggle("checked", slots.includes("Tối"));
  });
  updateAvailabilityCounter();
  showToast("Đã sao chép lịch từ tuần trước!", "success");
}

async function submitAvailabilityRegistration() {
  if (!AppState.user) return;
  const nick = AppState.user.nickname || AppState.user.username;
  const role = AppState.user.role || "Pha Chế";
  const weekLabel = AppState.weekInfo ? AppState.weekInfo.week_label : "Tuần tới";

  const slots = {};
  let totalCount = 0;
  document.querySelectorAll(".reg-slots-options").forEach(row => {
    const day = row.getAttribute("data-day");
    const pills = row.querySelectorAll(".slot-toggle-pill");
    const checked = [];
    if (pills[0].classList.contains("checked")) checked.push("Sáng");
    if (pills[1].classList.contains("checked")) checked.push("Chiều");
    if (pills[2].classList.contains("checked")) checked.push("Tối");
    if (checked.length > 0) {
      slots[day] = checked;
      totalCount += checked.length;
    }
  });

  const resp = await apiRequest("/api/schedule/register", {
    method: "POST",
    body: {
      nickname: nick,
      role,
      slots,
      week_label: weekLabel,
    }
  });

  if (resp && resp.success) {
    showToast(`✅ Đã gửi lịch rảnh (${totalCount} ca) thành công!`, "success");
    if (resp.shift_schedules) {
      AppState.shiftSchedules = resp.shift_schedules;
    }
  } else {
    showToast(resp.message || "Không thể lưu lịch đăng ký", "error");
  }
}

// ── 3. Employee Schedule View ────────────────────────────────────────────────
function setScheduleViewMode(mode) {
  AppState.scheduleViewMode = mode;
  document.getElementById("btn-sch-week-view").classList.toggle("active", mode === "week");
  document.getElementById("btn-sch-month-view").classList.toggle("active", mode === "month");
  renderEmployeeSchedule();
}

function renderEmployeeSchedule() {
  const container = document.getElementById("emp-schedule-container");
  if (!container) return;

  const roster = AppState.currentRoster;
  const nick = AppState.user ? (AppState.user.nickname || AppState.user.username) : "";
  const userNorm = (nick || "").trim().toLowerCase();

  if (!roster || !roster.shifts) {
    container.innerHTML = `
      <div class="empty-state card">
        <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color: var(--text-dim);"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
        <div class="empty-title">Chưa có lịch tuần chính thức</div>
        <p class="empty-desc">Quản lý đang sắp xếp lịch. Bạn sẽ nhận được thông báo ngay khi lịch được công bố.</p>
      </div>
    `;
    return;
  }

  const days = (AppState.weekInfo && AppState.weekInfo.days) ? AppState.weekInfo.days : [
    { code: "T2", label: "Thứ Hai", date_str: "T2", full_date: "" },
    { code: "T3", label: "Thứ Ba", date_str: "T3", full_date: "" },
    { code: "T4", label: "Thứ Tư", date_str: "T4", full_date: "" },
    { code: "T5", label: "Thứ Năm", date_str: "T5", full_date: "" },
    { code: "T6", label: "Thứ Sáu", date_str: "T6", full_date: "" },
    { code: "T7", label: "Thứ Bảy", date_str: "T7", full_date: "" },
    { code: "CN", label: "Chủ Nhật", date_str: "CN", full_date: "" },
  ];

  const caTimes = {
    Sáng: "07:00 – 12:00",
    Chiều: "13:00 – 17:00",
    Tối: "18:00 – 22:30",
  };

  let html = '<div style="display: flex; flex-direction: column; gap: 12px;">';
  days.forEach(d => {
    // Find all shifts the user works on day d
    const userShiftsOnDay = [];
    ["Sáng", "Chiều", "Tối"].forEach(caName => {
      const slotKey = `${d.code}_${caName}`;
      const staff = roster.shifts[slotKey] || [];
      if (staff.some(s => s.toLowerCase() === userNorm)) {
        userShiftsOnDay.push({ ca: caName, time: caTimes[caName], slotKey, staff });
      }
    });

    html += `
      <div class="card" style="padding: 16px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
          <div>
            <strong style="font-size: 15px; color: var(--text-main);">${d.label}</strong>
            <span style="font-size: 13px; color: var(--text-dim); margin-left: 6px;">${d.date_str}</span>
          </div>
          ${userShiftsOnDay.length > 0 ? '<span class="badge badge-primary">Có ca làm</span>' : '<span class="badge badge-muted">Nghỉ</span>'}
        </div>
    `;

    if (userShiftsOnDay.length === 0) {
      html += `<p style="font-size: 13px; color: var(--text-dim); margin: 0;">Bạn không có ca làm việc trong ngày này.</p>`;
    } else {
      userShiftsOnDay.forEach(sh => {
        html += `
          <div style="background: var(--bg-card-subtle); border-radius: var(--radius-md); padding: 12px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <div>
              <div style="font-size: 14px; font-weight: 700; color: var(--primary);">Ca ${sh.ca} • ${sh.time}</div>
              <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">Cùng làm: ${sh.staff.filter(s => s.toLowerCase() !== userNorm).join(", ") || "Một mình"}</div>
            </div>
            <button class="btn btn-secondary btn-sm" onclick="startSwapFromShift('${d.code}', '${sh.ca}', '${d.full_date || d.date_str}', '${sh.time}')">
              ${getIcon("swap", 14)}
              <span>Đổi ca này</span>
            </button>
          </div>
        `;
      });
    }

    html += `</div>`;
  });
  html += '</div>';

  container.innerHTML = html;
}

function startSwapFromShift(day, ca, date, time) {
  AppState.swapWizard.myShift = { day, ca, date, time };
  switchTab("tab-emp-swap");
  goToSwapStep(2);
}

// ── 4. Employee Shift Swap Workflow ──────────────────────────────────────────
function renderSwapWorkflow() {
  goToSwapStep(AppState.swapWizard.step || 1);
}

function goToSwapStep(step) {
  AppState.swapWizard.step = step;

  // Indicators
  for (let i = 1; i <= 3; i++) {
    const el = document.getElementById(`swap-step-ind-${i}`);
    if (el) {
      el.classList.toggle("active", i === step);
      el.classList.toggle("done", i < step);
    }
  }

  // Hide all step containers
  document.getElementById("swap-step-1").classList.add("hidden");
  document.getElementById("swap-step-2").classList.add("hidden");
  document.getElementById("swap-step-3").classList.add("hidden");
  document.getElementById("swap-step-4").classList.add("hidden");

  if (step === 1) {
    document.getElementById("swap-step-1").classList.remove("hidden");
    renderSwapStep1MyShifts();
  } else if (step === 2) {
    document.getElementById("swap-step-2").classList.remove("hidden");
    renderSwapStep2Partners();
  } else if (step === 3) {
    document.getElementById("swap-step-3").classList.remove("hidden");
    renderSwapStep3Confirm();
  }
}

function showMySwapHistory() {
  document.getElementById("swap-step-1").classList.add("hidden");
  document.getElementById("swap-step-2").classList.add("hidden");
  document.getElementById("swap-step-3").classList.add("hidden");
  document.getElementById("swap-step-4").classList.remove("hidden");
  renderMySwapsList();
}

function renderSwapStep1MyShifts() {
  const container = document.getElementById("swap-my-shifts-list");
  const nextBtn = document.getElementById("btn-swap-to-step2");
  if (!container) return;

  const roster = AppState.currentRoster;
  const nick = AppState.user ? (AppState.user.nickname || AppState.user.username) : "";
  const userNorm = (nick || "").trim().toLowerCase();

  if (!roster || !roster.shifts) {
    container.innerHTML = `<p style="padding: 10px; color: var(--text-dim);">Chưa có lịch tuần chính thức để đổi ca.</p>`;
    return;
  }

  const days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
  const caTimes = { Sáng: "07:00 – 12:00", Chiều: "13:00 – 17:00", Tối: "18:00 – 22:30" };
  const dayLabels = { T2: "Thứ Hai", T3: "Thứ Ba", T4: "Thứ Tư", T5: "Thứ Năm", T6: "Thứ Sáu", T7: "Thứ Bảy", CN: "Chủ Nhật" };

  const myShifts = [];
  days.forEach(d => {
    ["Sáng", "Chiều", "Tối"].forEach(ca => {
      const slotKey = `${d}_${ca}`;
      const staff = roster.shifts[slotKey] || [];
      if (staff.some(s => s.toLowerCase() === userNorm)) {
        myShifts.push({ day: d, ca, time: caTimes[ca], dayLabel: dayLabels[d] });
      }
    });
  });

  if (myShifts.length === 0) {
    container.innerHTML = `<p style="padding: 10px; color: var(--text-dim);">Bạn chưa có ca làm nào trong lịch tuần này để đổi.</p>`;
    if (nextBtn) nextBtn.disabled = true;
    return;
  }

  let html = "";
  myShifts.forEach((sh, idx) => {
    const isSelected = AppState.swapWizard.myShift &&
      AppState.swapWizard.myShift.day === sh.day &&
      AppState.swapWizard.myShift.ca === sh.ca;

    html += `
      <div class="shift-pick-item ${isSelected ? 'selected' : ''}" onclick="selectMySwapShift('${sh.day}', '${sh.ca}', '${sh.dayLabel}', '${sh.time}')">
        <div>
          <strong style="color: var(--text-main); font-size: 15px;">${sh.dayLabel} • Ca ${sh.ca}</strong>
          <div style="font-size: 13px; color: var(--text-muted);">${sh.time}</div>
        </div>
        <div style="width: 20px; height: 20px; border-radius: 50%; border: 2px solid ${isSelected ? 'var(--primary)' : 'var(--border-strong)'}; background: ${isSelected ? 'var(--primary)' : 'transparent'};"></div>
      </div>
    `;
  });
  container.innerHTML = html;
}

function selectMySwapShift(day, ca, dayLabel, time) {
  AppState.swapWizard.myShift = { day, ca, dayLabel, time };
  document.getElementById("btn-swap-to-step2").disabled = false;
  renderSwapStep1MyShifts();
}

function renderSwapStep2Partners() {
  const container = document.getElementById("swap-partner-shifts-list");
  const nextBtn = document.getElementById("btn-swap-to-step3");
  if (!container) return;

  const roster = AppState.currentRoster;
  const myShift = AppState.swapWizard.myShift;
  const myNick = AppState.user ? (AppState.user.nickname || AppState.user.username) : "";
  const myNorm = (myNick || "").trim().toLowerCase();

  if (!roster || !myShift) {
    goToSwapStep(1);
    return;
  }

  const days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
  const caTimes = { Sáng: "07:00 – 12:00", Chiều: "13:00 – 17:00", Tối: "18:00 – 22:30" };
  const dayLabels = { T2: "Thứ Hai", T3: "Thứ Ba", T4: "Thứ Tư", T5: "Thứ Năm", T6: "Thứ Sáu", T7: "Thứ Bảy", CN: "Chủ Nhật" };

  // Find all colleagues who have a shift in the week
  // A colleague is eligible if:
  // 1. Not myself
  // 2. Colleague is not already working on myShift.day (conflict rule)
  // 3. I am not already working on Colleague's shift day (conflict rule)
  const candidateList = [];

  days.forEach(d => {
    ["Sáng", "Chiều", "Tối"].forEach(ca => {
      const slotKey = `${d}_${ca}`;
      const staffList = roster.shifts[slotKey] || [];
      staffList.forEach(colleague => {
        if (colleague.toLowerCase() === myNorm) return;

        // Check if colleague already works on myShift.day
        const colleagueWorksOnMyDay = ["Sáng", "Chiều", "Tối"].some(c => {
          return (roster.shifts[`${myShift.day}_${c}`] || []).some(s => s.toLowerCase() === colleague.toLowerCase());
        });

        // Check if I work on colleague's d
        const iWorkOnColleagueDay = ["Sáng", "Chiều", "Tối"].some(c => {
          return (roster.shifts[`${d}_${c}`] || []).some(s => s.toLowerCase() === myNorm);
        });

        const hasConflict = colleagueWorksOnMyDay || (iWorkOnColleagueDay && d !== myShift.day);

        candidateList.push({
          nickname: colleague,
          role: "Barista",
          day: d,
          dayLabel: dayLabels[d],
          ca,
          time: caTimes[ca],
          hasConflict,
          conflictReason: colleagueWorksOnMyDay ? "Trùng lịch ca của bạn" : "Bạn đã có ca ngày này",
        });
      });
    });
  });

  if (candidateList.length === 0) {
    container.innerHTML = `<div class="empty-state" style="padding: 20px;"><p>Không có ca phù hợp nào của đồng nghiệp trong tuần này để đổi.</p></div>`;
    if (nextBtn) nextBtn.disabled = true;
    return;
  }

  let html = "";
  candidateList.forEach(cand => {
    const isSelected = AppState.swapWizard.partnerShift &&
      AppState.swapWizard.partnerShift.nickname === cand.nickname &&
      AppState.swapWizard.partnerShift.day === cand.day &&
      AppState.swapWizard.partnerShift.ca === cand.ca;

    html += `
      <div class="candidate-card ${cand.hasConflict ? 'disabled' : ''} ${isSelected ? 'selected' : ''}" style="${isSelected ? 'border-color: var(--primary); background: var(--primary-subtle);' : ''}">
        <div style="display: flex; align-items: center; gap: 10px;">
          <div class="user-avatar" style="width: 34px; height: 34px; font-size: 13px;">${cand.nickname.charAt(0).toUpperCase()}</div>
          <div class="candidate-meta">
            <span class="candidate-name">${escapeHtml(cand.nickname)}</span>
            <span class="candidate-stats">${cand.dayLabel} • Ca ${cand.ca} (${cand.time})</span>
          </div>
        </div>
        <div>
          ${cand.hasConflict ?
            `<span class="badge badge-danger">${cand.conflictReason}</span>` :
            `<button class="btn btn-secondary btn-sm" onclick="selectSwapPartner('${escapeHtml(cand.nickname)}', '${cand.day}', '${cand.ca}', '${cand.dayLabel}', '${cand.time}')">
              ${isSelected ? '✓ Đã chọn' : 'Chọn đổi'}
            </button>`
          }
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

function selectSwapPartner(nickname, day, ca, dayLabel, time) {
  AppState.swapWizard.partnerShift = { nickname, day, ca, dayLabel, time };
  AppState.swapWizard.partnerNickname = nickname;
  document.getElementById("btn-swap-to-step3").disabled = false;
  renderSwapStep2Partners();
}

function renderSwapStep3Confirm() {
  const my = AppState.swapWizard.myShift;
  const partner = AppState.swapWizard.partnerShift;
  const myNick = AppState.user ? (AppState.user.nickname || AppState.user.username) : "Bạn";

  if (!my || !partner) {
    goToSwapStep(1);
    return;
  }

  document.getElementById("swap-confirm-my-name").textContent = myNick;
  document.getElementById("swap-confirm-my-shift").textContent = `${my.dayLabel || my.day} • Ca ${my.ca} (${my.time})`;

  document.getElementById("swap-confirm-partner-name").textContent = partner.nickname;
  document.getElementById("swap-confirm-partner-shift").textContent = `${partner.dayLabel || partner.day} • Ca ${partner.ca} (${partner.time})`;
}

async function submitSwapRequest() {
  const my = AppState.swapWizard.myShift;
  const partner = AppState.swapWizard.partnerShift;
  const myNick = AppState.user ? (AppState.user.nickname || AppState.user.username) : "";
  const reason = document.getElementById("swap-reason").value.trim();

  if (!my || !partner || !myNick) {
    showToast("Vui lòng hoàn thành các bước chọn ca", "error");
    return;
  }

  const weekKey = AppState.weekInfo ? AppState.weekInfo.week_key : "";

  const resp = await apiRequest("/api/swaps/create", {
    method: "POST",
    body: {
      week_key: weekKey,
      requester: myNick,
      requester_role: AppState.user.role || "Pha Chế",
      requester_shift: { day: my.day, ca: my.ca, time: my.time },
      target: partner.nickname,
      target_role: "Pha Chế",
      target_shift: { day: partner.day, ca: partner.ca, time: partner.time },
      reason,
    }
  });

  if (resp && resp.success) {
    showToast("✅ Đã gửi yêu cầu đổi ca tới Quản lý thành công!", "success");
    AppState.swapWizard.myShift = null;
    AppState.swapWizard.partnerShift = null;
    document.getElementById("swap-reason").value = "";

    // Refresh swaps list
    const swapsResp = await apiRequest(`/api/swaps?nickname=${encodeURIComponent(myNick)}`);
    if (swapsResp && swapsResp.success) {
      AppState.swaps = swapsResp.swaps;
    }
    showMySwapHistory();
  } else {
    showToast(resp.message || "Không thể gửi yêu cầu đổi ca", "error");
  }
}

function filterMySwaps(status) {
  AppState.swapWizard.activeFilter = status;
  ["all", "pending", "approved", "rejected"].forEach(st => {
    const btn = document.getElementById(`tab-swap-filter-${st}`);
    if (btn) btn.classList.toggle("active", st === status);
  });
  renderMySwapsList();
}

function renderMySwapsList() {
  const container = document.getElementById("my-swaps-list");
  if (!container) return;

  const swaps = AppState.swaps || [];
  const filter = AppState.swapWizard.activeFilter || "all";
  const filtered = filter === "all" ? swaps : swaps.filter(s => s.status === filter);

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state" style="padding: 24px;"><p>Không có yêu cầu đổi ca nào.</p></div>`;
    return;
  }

  let html = "";
  filtered.forEach(sw => {
    const statusBadges = {
      pending: '<span class="badge badge-warning">Đang chờ duyệt</span>',
      approved: '<span class="badge badge-success">Đã duyệt</span>',
      rejected: '<span class="badge badge-danger">Đã từ chối</span>',
    };
    const reqS = sw.requester_shift || {};
    const tgtS = sw.target_shift || {};

    html += `
      <div style="background: var(--bg-card-subtle); border-radius: var(--radius-md); padding: 14px; border: 1px solid var(--border-light);">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
          <span style="font-size: 12px; color: var(--text-dim);">${sw.created_at}</span>
          ${statusBadges[sw.status] || ''}
        </div>
        <div style="display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 8px; font-size: 13px;">
          <div>
            <strong>${escapeHtml(sw.requester)}</strong><br>
            <span style="color: var(--text-muted);">${reqS.day || ''} Ca ${reqS.ca || ''}</span>
          </div>
          <div style="color: var(--text-dim);">⇄</div>
          <div>
            <strong>${escapeHtml(sw.target)}</strong><br>
            <span style="color: var(--text-muted);">${tgtS.day || ''} Ca ${tgtS.ca || ''}</span>
          </div>
        </div>
        ${sw.reason ? `<div style="margin-top: 8px; font-size: 12px; color: var(--text-muted); font-style: italic;">Lý do: "${escapeHtml(sw.reason)}"</div>` : ''}
      </div>
    `;
  });

  container.innerHTML = html;
}

// ── 5. Employee Payroll Tab ──────────────────────────────────────────────────
async function loadEmployeePayrollData() {
  if (!AppState.user) return;
  const nick = AppState.user.nickname || AppState.user.username;

  const resp = await apiRequest(`/api/personal/summary?nickname=${encodeURIComponent(nick)}`);
  if (!resp || !resp.success || !resp.summary) return;

  const regularPay = Math.round((s.regular_hours || 0) * (s.rate || 0) * 1000);
  const otPay = Math.round((s.overtime_hours || 0) * (s.rate || 0) * 1.5 * 1000);
  const penalty = (s.late_count || 0) * 10000;
  const netTotal = Math.max(0, regularPay + otPay - penalty);

  document.getElementById("emp-payroll-total").textContent = formatCurrency(netTotal);
  document.getElementById("emp-payroll-rate").textContent = `Mức lương: ${s.rate || 0}k/giờ`;

  document.getElementById("emp-breakdown-regular").textContent = formatCurrency(regularPay);
  document.getElementById("emp-breakdown-ot").textContent = `+${formatCurrency(otPay)}`;
  document.getElementById("emp-breakdown-penalty").textContent = `-${formatCurrency(penalty)}`;

  // Render recent checkins
  const container = document.getElementById("emp-checkin-history-list");
  if (!container) return;

  const checkins = s.recent_checkins || [];
  if (checkins.length === 0) {
    container.innerHTML = `<p style="padding: 12px; color: var(--text-dim);">Chưa có bản ghi chấm công nào.</p>`;
    return;
  }

  let html = "";
  checkins.forEach(ci => {
    html += `
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: var(--bg-card-subtle); border-radius: var(--radius-sm); font-size: 13px;">
        <div>
          <strong>${ci.date}</strong> • ${ci.checkin_time} → ${ci.checkout_time}
          <div style="font-size: 12px; color: var(--text-dim);">${ci.note || 'Ca chính'}</div>
        </div>
        <span class="badge badge-primary">${ci.total_hours}h</span>
      </div>
    `;
  });
  container.innerHTML = html;
}

// ── 6. Common Notifications Tab ──────────────────────────────────────────────
async function renderNotificationsTab() {
  const container = document.getElementById("notifications-list");
  if (!container) return;

  const nick = AppState.user ? (AppState.user.nickname || AppState.user.username) : "";
  const resp = await apiRequest(`/api/notifications?nickname=${encodeURIComponent(nick)}`);
  if (resp && resp.success) {
    AppState.notifications = resp.notifications;
  }

  const notifs = AppState.notifications || [];
  if (notifs.length === 0) {
    container.innerHTML = `<div class="empty-state card"><p>Hộp thư rỗng.</p></div>`;
    return;
  }

  let html = "";
  notifs.forEach(n => {
    html += `
      <div class="card" style="padding: 14px; background: ${n.is_read ? 'var(--bg-card)' : 'var(--primary-subtle)'};" onclick="markNotifRead('${n.id}')">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
          <strong style="color: var(--text-main); font-size: 14px;">${escapeHtml(n.title)}</strong>
          <span style="font-size: 11px; color: var(--text-dim);">${escapeHtml(n.created_at)}</span>
        </div>
        <p style="margin: 0; font-size: 13px;">${escapeHtml(n.message)}</p>
      </div>
    `;
  });
  container.innerHTML = html;
  updateBadgeCounts();
}

async function markNotifRead(id) {
  const nick = AppState.user ? (AppState.user.nickname || AppState.user.username) : "";
  await apiRequest("/api/notifications/mark-read", {
    method: "POST",
    body: { id, nickname: nick }
  });
  renderNotificationsTab();
}

// ============================================================================
// ADMIN MODULES (QUẢN LÝ)
// ============================================================================

// ── 1. Admin Dashboard ───────────────────────────────────────────────────────
async function loadAdminDashboardData() {
  const ovResp = await apiRequest("/api/admin/overview");
  if (!ovResp || !ovResp.success) return;

  // Active staff count
  const activeStaff = ovResp.checkin_today ? ovResp.checkin_today.filter(c => !c.checkout_time || c.checkout_time === '—') : [];
  document.getElementById("kpi-active-staff").textContent = `${activeStaff.length} người`;
  const badgeEl = document.getElementById("active-staff-count-badge");
  if (badgeEl) badgeEl.textContent = `${activeStaff.length} người`;

  // Swaps pending count
  const pendingSwaps = (ovResp.leave_requests || []).filter(r => r.type === 'swap' && r.status === 'pending');
  // Also check swaps store
  const allSwapsResp = await apiRequest("/api/swaps?status=pending");
  const pendingStoreSwaps = (allSwapsResp && allSwapsResp.success) ? allSwapsResp.swaps : [];
  const totalPending = pendingStoreSwaps.length || pendingSwaps.length;

  document.getElementById("kpi-pending-swaps").textContent = totalPending;
  AppState.swaps = (allSwapsResp && allSwapsResp.success) ? allSwapsResp.swaps : [];
  updateBadgeCounts();

  // Render pending swaps preview on dashboard
  renderAdminDashSwapsList(pendingStoreSwaps);

  // Render pending rewards list
  const pendingRewards = ovResp.pending_rewards || [];
  const rewBadge = document.getElementById("admin-dash-rewards-badge");
  if (rewBadge) rewBadge.textContent = pendingRewards.length;
  renderAdminDashRewardsList(pendingRewards);

  // Render active working staff list
  renderAdminDashActiveStaff(activeStaff);

  // Check low stock materials
  const matResp = await apiRequest("/api/inventory");
  if (matResp && matResp.success && Array.isArray(matResp.materials)) {
    const lowStock = matResp.materials.filter(m => m.min_stock > 0 && m.stock <= m.min_stock);
    document.getElementById("kpi-low-stock").textContent = `${lowStock.length} món`;
  }
}

function renderAdminDashRewardsList(rewards) {
  const container = document.getElementById("admin-dash-rewards-list");
  if (!container) return;

  if (!rewards || rewards.length === 0) {
    container.innerHTML = `<div class="empty-state" style="padding: 16px;"><p>Không có yêu cầu thưởng ca nào đang chờ duyệt.</p></div>`;
    return;
  }

  let html = '<div style="display: flex; flex-direction: column; gap: 8px;">';
  rewards.forEach(r => {
    const reqId = r.id || r.request_id;
    const empsStr = (r.employees || []).join(", ");
    html += `
      <div class="reward-request-row">
        <div>
          <div class="reward-request-info-title">🎁 Ca ${escapeHtml(r.ca || '')} • +1 ly cho: <strong>${escapeHtml(empsStr)}</strong></div>
          <div class="reward-request-info-sub">Người gửi: ${escapeHtml(r.sender || 'Nhân viên')} • ${escapeHtml(r.created_at || '')}</div>
        </div>
        <div class="reward-request-actions">
          <button type="button" class="btn btn-success btn-xs" onclick="handleAdminDecideReward('${escapeHtml(reqId)}', true)">
            ✅ Duyệt
          </button>
          <button type="button" class="btn btn-danger btn-xs" onclick="handleAdminDecideReward('${escapeHtml(reqId)}', false)">
            ❌ Từ chối
          </button>
        </div>
      </div>
    `;
  });
  html += '</div>';
  container.innerHTML = html;
}

async function handleAdminDecideReward(requestId, approve) {
  const actionText = approve ? "duyệt cộng thưởng (+1 ly)" : "từ chối yêu cầu thưởng";
  if (!confirm(`Bạn có chắc chắn muốn ${actionText} này không?`)) return;

  const resp = await apiRequest("/api/admin/rewards/decide", {
    method: "POST",
    body: {
      request_id: requestId,
      approve: approve
    }
  });

  if (resp && resp.success) {
    showToast(resp.message || "Đã xử lý yêu cầu thành công!", "success");
    loadAdminDashboardData();
  } else {
    showToast((resp && resp.message) || "Lỗi khi xử lý yêu cầu", "danger");
  }
}

function renderAdminDashSwapsList(swaps) {
  const container = document.getElementById("admin-dash-swaps-list");
  if (!container) return;

  if (swaps.length === 0) {
    container.innerHTML = `<div class="empty-state" style="padding: 16px;"><p>Không có yêu cầu đổi ca nào cần duyệt.</p></div>`;
    return;
  }

  let html = '<div style="display: flex; flex-direction: column; gap: 10px;">';
  swaps.slice(0, 4).forEach(sw => {
    const reqS = sw.requester_shift || {};
    const tgtS = sw.target_shift || {};
    html += `
      <div style="background: var(--bg-card-subtle); border-radius: var(--radius-md); padding: 12px 14px; border: 1px solid var(--border-light); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
        <div>
          <div style="font-size: 14px; font-weight: 700;">${escapeHtml(sw.requester)} ⇄ ${escapeHtml(sw.target)}</div>
          <div style="font-size: 12px; color: var(--text-muted);">${reqS.day || ''} Ca ${reqS.ca || ''} đổi lấy ${tgtS.day || ''} Ca ${tgtS.ca || ''}</div>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn btn-secondary btn-sm" onclick="handleAdminSwapDecide('${sw.id}', false)">Từ chối</button>
          <button class="btn btn-primary btn-sm" onclick="handleAdminSwapDecide('${sw.id}', true)">Duyệt đổi ca</button>
        </div>
      </div>
    `;
  });
  html += '</div>';
  container.innerHTML = html;
}

function renderAdminDashActiveStaff(active) {
  const container = document.getElementById("admin-dash-active-staff");
  if (!container) return;

  if (active.length === 0) {
    container.innerHTML = `<p style="padding: 12px; color: var(--text-dim);">Hiện tại không có nhân viên nào đang trong ca.</p>`;
    return;
  }

  let html = "";
  active.forEach(st => {
    html += `
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: var(--bg-card-subtle); border-radius: var(--radius-sm); font-size: 13px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="width: 8px; height: 8px; border-radius: 50%; background: var(--success);"></span>
          <strong>${escapeHtml(st.nickname)}</strong>
        </div>
        <span style="font-size: 12px; color: var(--text-muted);">Vào ca lúc: ${st.checkin_time}</span>
      </div>
    `;
  });
  container.innerHTML = html;
}

// ── 2. Admin Schedule Planning (70/30 Grid & Contextual Drawer) ──────────────
async function loadAdminRosterData() {
  const weekInfo = AppState.weekInfo || {};
  const weekKey = weekInfo.week_key;

  const resp = await apiRequest(`/api/roster?offset=${AppState.weekOffset}`);
  if (resp && resp.success && resp.roster) {
    AppState.currentRoster = resp.roster;
    AppState.weekInfo = resp.week_info;
    if (resp.shift_schedules) {
      AppState.shiftSchedules = resp.shift_schedules;
    }

    // Header label & status
    const labelEl = document.getElementById("admin-roster-week-label");
    const rangeEl = document.getElementById("roster-calendar-range");
    const badgeEl = document.getElementById("roster-status-badge");

    if (labelEl) labelEl.textContent = resp.roster.week_label || "Tuần làm việc";
    if (rangeEl) rangeEl.textContent = resp.week_info ? `${resp.week_info.monday_date} – ${resp.week_info.sunday_date}` : "Tuần này";
    if (badgeEl) {
      const isPub = resp.roster.status === "published";
      badgeEl.className = `badge ${isPub ? 'badge-success' : 'badge-warning'}`;
      badgeEl.textContent = isPub ? "Chính thức (Published)" : "Bản nháp (Draft)";
    }

    renderDesktopRosterGrid();
    renderMobileAdminSchedule();
  }
}

function navigateRosterWeek(step) {
  AppState.weekOffset += step;
  loadAdminRosterData();
}

function renderDesktopRosterGrid() {
  const tbody = document.getElementById("desktop-roster-tbody");
  if (!tbody || !AppState.currentRoster) return;

  const roster = AppState.currentRoster;
  const shifts = roster.shifts || {};
  const targets = roster.targets || {};
  const days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
  const cas = [
    { code: "Sáng", time: "07:00-12:00", defaultNeed: 2 },
    { code: "Chiều", time: "13:00-17:00", defaultNeed: 2 },
    { code: "Tối", time: "18:00-22:30", defaultNeed: 3 },
  ];

  // Update table headers with dates
  if (AppState.weekInfo && AppState.weekInfo.days) {
    AppState.weekInfo.days.forEach(d => {
      const th = document.getElementById(`th-${d.code}`);
      if (th) th.innerHTML = `<div>${d.code}</div><div style="font-size: 11px; font-weight: normal; color: var(--text-dim);">${d.date_str}</div>`;
    });
  }

  let html = "";
  cas.forEach(ca => {
    html += `<tr>`;
    html += `
      <td style="background: var(--bg-card-subtle); padding: 10px; border-radius: var(--radius-sm); font-size: 12px; font-weight: 700; color: var(--text-main);">
        <div>Ca ${ca.code}</div>
        <div style="font-size: 10px; color: var(--text-dim); font-weight: normal;">${ca.time}</div>
      </td>
    `;

    days.forEach(d => {
      const slotKey = `${d}_${ca.code}`;
      const staffList = shifts[slotKey] || [];
      const needed = targets[slotKey] || ca.defaultNeed;
      const assigned = staffList.length;

      // Status indicator class
      let statusClass = "status-ok";
      if (assigned === 0 || assigned < needed - 1) {
        statusClass = "status-danger";
      } else if (assigned < needed) {
        statusClass = "status-warning";
      }

      const isSelected = AppState.selectedSlot && AppState.selectedSlot.slotKey === slotKey;

      html += `
        <td>
          <div class="schedule-shift-cell ${statusClass} ${isSelected ? 'selected' : ''}" onclick="selectAdminRosterSlot('${d}', '${ca.code}', '${slotKey}')">
            <div class="shift-cell-header">
              <span class="shift-ratio-badge">${assigned}/${needed} người</span>
              <button type="button" class="btn btn-icon btn-ghost btn-sm" style="width: 22px; height: 22px; min-height: 22px;" title="Xếp người">+</button>
            </div>
            <div class="shift-staff-chips">
              ${staffList.map(name => `<span class="shift-assigned-chip">${escapeHtml(name)}</span>`).join("")}
            </div>
          </div>
        </td>
      `;
    });
    html += `</tr>`;
  });

  tbody.innerHTML = html;
}

function selectAdminRosterSlot(day, ca, slotKey) {
  AppState.selectedSlot = { day, ca, slotKey };
  renderDesktopRosterGrid();
  renderContextualAssignmentDrawer();
}

function renderContextualAssignmentDrawer() {
  const drawer = document.getElementById("assignment-drawer-card");
  const titleEl = document.getElementById("drawer-slot-title");
  const subtitleEl = document.getElementById("drawer-slot-subtitle");
  const bodyEl = document.getElementById("drawer-content-body");

  if (!drawer || !AppState.selectedSlot || !AppState.currentRoster) return;

  const { day, ca, slotKey } = AppState.selectedSlot;
  const roster = AppState.currentRoster;
  const shifts = roster.shifts || {};
  const targets = roster.targets || {};
  const assignedStaff = shifts[slotKey] || [];
  const needed = targets[slotKey] || 2;

  const dayLabels = { T2: "Thứ Hai", T3: "Thứ Ba", T4: "Thứ Tư", T5: "Thứ Năm", T6: "Thứ Sáu", T7: "Thứ Bảy", CN: "Chủ Nhật" };
  const caTimes = { Sáng: "07:00 – 12:00", Chiều: "13:00 – 17:00", Tối: "18:00 – 22:30" };

  titleEl.textContent = `${dayLabels[day]} • Ca ${ca}`;
  subtitleEl.textContent = `${caTimes[ca]} | Cần: ${needed} • Đã xếp: ${assignedStaff.length}/${needed}`;

  // Candidates list logic:
  // Split into 2 tabs: 'Đã đăng ký ca này' vs 'Không đăng ký ca này'
  const employees = (AppState.bootstrapData && AppState.bootstrapData.employees) ? AppState.bootstrapData.employees : [];
  const schedules = AppState.shiftSchedules || {};

  const registeredCandidates = [];
  const unregisteredCandidates = [];

  employees.forEach(emp => {
    const nick = emp.nickname || emp.full_name;
    const reg = schedules[nick] || {};
    const regSlots = reg.slots || {};
    const daySlots = regSlots[day] || [];
    const isAssignedHere = assignedStaff.includes(nick);

    // Calculate weekly assigned shifts count for fair distribution
    let weeklyAssignedCount = 0;
    Object.values(shifts).forEach(list => {
      if (list.includes(nick)) weeklyAssignedCount++;
    });

    // Check conflict (working another ca on the same day)
    const worksOtherCaToday = ["Sáng", "Chiều", "Tối"].some(c => c !== ca && (shifts[`${day}_${c}`] || []).includes(nick));
    const targetShifts = reg.target_shifts || 5;

    const candData = {
      nickname: nick,
      role: emp.role || reg.role || "Barista",
      isAssignedHere,
      weeklyAssignedCount,
      targetShifts,
      worksOtherCaToday,
    };

    if (daySlots.includes(ca)) {
      registeredCandidates.push(candData);
    } else {
      unregisteredCandidates.push(candData);
    }
  });

  // Sort candidates by weekly assigned shifts count ascending (least shifts first for fair distribution)
  registeredCandidates.sort((a, b) => a.weeklyAssignedCount - b.weeklyAssignedCount);
  unregisteredCandidates.sort((a, b) => a.weeklyAssignedCount - b.weeklyAssignedCount);

  // Render Subtabs & Filters
  let html = `
    <div class="drawer-subtabs">
      <button class="drawer-subtab-btn ${AppState.drawerTab === 'registered' ? 'active' : ''}" onclick="setDrawerTab('registered')">
        🟢 Rảnh ca này (${registeredCandidates.length})
      </button>
      <button class="drawer-subtab-btn ${AppState.drawerTab === 'unregistered' ? 'active' : ''}" onclick="setDrawerTab('unregistered')">
        ⚪ Chưa đăng ký (${unregisteredCandidates.length})
      </button>
    </div>
  `;

  // Currently assigned staff chips with unassign button
  if (assignedStaff.length > 0) {
    html += `
      <div style="margin-bottom: 16px;">
        <span style="font-size: 12px; font-weight: 700; color: var(--text-main);">Đang trong ca (${assignedStaff.length}):</span>
        <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;">
          ${assignedStaff.map(name => `
            <span class="badge badge-primary" style="padding: 6px 10px;">
              ${escapeHtml(name)}
              <button type="button" onclick="handleUnassignStaff('${name}')" style="margin-left: 4px; color: inherit;" title="Bỏ khỏi ca">✕</button>
            </span>
          `).join("")}
        </div>
      </div>
    `;
  }

  // Active candidate list based on drawer tab
  const activeCandidates = AppState.drawerTab === "registered" ? registeredCandidates : unregisteredCandidates;

  if (activeCandidates.length === 0) {
    html += `<div class="empty-state" style="padding: 16px;"><p>Không có nhân sự nào trong mục này.</p></div>`;
  } else {
    html += `<div class="candidate-list">`;
    activeCandidates.forEach(c => {
      const shiftBadgeClass = c.weeklyAssignedCount === 0 ? 'badge-info' : (c.weeklyAssignedCount <= 3 ? 'badge-success' : 'badge-warning');

      html += `
        <div class="candidate-card ${c.worksOtherCaToday ? 'disabled' : ''}">
          <div style="display: flex; align-items: center; gap: 10px;">
            <div class="user-avatar" style="width: 32px; height: 32px; font-size: 13px;">${c.nickname.charAt(0).toUpperCase()}</div>
            <div class="candidate-meta">
              <span class="candidate-name">${escapeHtml(c.nickname)} <small style="color: var(--text-dim);">(${c.role})</small></span>
              <span class="candidate-stats" style="margin-top: 2px;">
                Đã có: <span class="badge ${shiftBadgeClass}" style="padding: 1px 6px; font-weight: 700; font-size: 11px;">${c.weeklyAssignedCount} ca</span>
              </span>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 6px;">
            ${c.worksOtherCaToday ? '<span class="badge badge-danger">Trùng ngày</span>' : ''}
            ${c.isAssignedHere ?
              `<button class="btn btn-danger btn-sm" onclick="handleUnassignStaff('${c.nickname}')">Bỏ ca</button>` :
              `<button class="btn btn-primary btn-sm" ${c.worksOtherCaToday ? 'disabled' : ''} onclick="handleAssignStaff('${c.nickname}')">+ Xếp ca</button>`
            }
          </div>
        </div>
      `;
    });
    html += `</div>`;
  }

  bodyEl.innerHTML = html;
}

function setDrawerTab(tab) {
  AppState.drawerTab = tab;
  renderContextualAssignmentDrawer();
}

async function handleAssignStaff(nickname) {
  if (!AppState.selectedSlot || !AppState.currentRoster) return;
  const { slotKey } = AppState.selectedSlot;
  const weekKey = AppState.currentRoster.week_key;

  const resp = await apiRequest("/api/admin/roster/assign", {
    method: "POST",
    body: {
      week_key: weekKey,
      day_ca: slotKey,
      nickname,
    }
  });

  if (resp && resp.success && resp.roster) {
    AppState.currentRoster = resp.roster;
    renderDesktopRosterGrid();
    renderContextualAssignmentDrawer();
    showToast(`Đã xếp ${nickname} vào ca!`, "success");
  } else {
    showToast(resp.message || "Lỗi khi xếp nhân sự", "error");
  }
}

async function handleUnassignStaff(nickname) {
  if (!AppState.selectedSlot || !AppState.currentRoster) return;
  const { slotKey } = AppState.selectedSlot;
  const weekKey = AppState.currentRoster.week_key;

  const resp = await apiRequest("/api/admin/roster/unassign", {
    method: "POST",
    body: {
      week_key: weekKey,
      day_ca: slotKey,
      nickname,
    }
  });

  if (resp && resp.success && resp.roster) {
    AppState.currentRoster = resp.roster;
    renderDesktopRosterGrid();
    renderContextualAssignmentDrawer();
    showToast(`Đã bỏ ${nickname} khỏi ca`, "info");
  } else {
    showToast(resp.message || "Lỗi khi bỏ nhân sự", "error");
  }
}

async function handleSuggestRosterDraft() {
  if (!AppState.currentRoster) return;
  const weekKey = AppState.currentRoster.week_key;

  const resp = await apiRequest("/api/admin/roster/suggest", {
    method: "POST",
    body: { week_key: weekKey }
  });

  if (resp && resp.success && resp.roster) {
    AppState.currentRoster = resp.roster;
    renderDesktopRosterGrid();
    renderContextualAssignmentDrawer();
    showToast("✅ Đã tự động chia đều ca theo lịch rảnh của nhân viên!", "success");
  } else {
    showToast(resp.message || "Không thể tạo gợi ý", "error");
  }
}

function handlePublishRosterConfirm() {
  if (!AppState.currentRoster) return;
  openModal(
    "Xác nhận chốt lịch tuần",
    `<p>Sau khi chốt, lịch sẽ trở thành <strong>chính thức</strong> và tự động gửi thông báo đến toàn bộ nhân viên có ca làm trong tuần.</p>`,
    `
      <button class="btn btn-secondary btn-sm" onclick="closeModal()">Hủy</button>
      <button class="btn btn-primary btn-sm" onclick="confirmPublishRoster()">Chốt & Phát hành ngay</button>
    `
  );
}

async function confirmPublishRoster() {
  closeModal();
  if (!AppState.currentRoster) return;
  const weekKey = AppState.currentRoster.week_key;

  const resp = await apiRequest("/api/admin/roster/publish", {
    method: "POST",
    body: { week_key: weekKey }
  });

  if (resp && resp.success && resp.roster) {
    AppState.currentRoster = resp.roster;
    renderDesktopRosterGrid();
    const badgeEl = document.getElementById("roster-status-badge");
    if (badgeEl) {
      badgeEl.className = "badge badge-success";
      badgeEl.textContent = "Chính thức (Published)";
    }
    showToast(resp.message || "Đã chốt và phát hành lịch tuần!", "success");
  } else {
    showToast(resp.message || "Không thể chốt lịch", "error");
  }
}

// ── Mobile Responsive Admin Schedule ─────────────────────────────────────────
function renderMobileAdminSchedule() {
  const dayPicker = document.getElementById("admin-mobile-day-picker");
  const shiftsList = document.getElementById("mobile-roster-shifts-list");
  if (!dayPicker || !shiftsList || !AppState.currentRoster) return;

  if (window.innerWidth >= 1024) {
    dayPicker.style.display = "none";
    shiftsList.style.display = "none";
    document.getElementById("desktop-roster-table").style.display = "table";
    return;
  }

  // Display mobile view
  dayPicker.style.display = "flex";
  shiftsList.style.display = "block";
  document.getElementById("desktop-roster-table").style.display = "none";

  const days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
  const selectedDay = AppState.adminSelectedDay || "T2";

  let dayPills = "";
  days.forEach(d => {
    dayPills += `
      <button class="mobile-day-pill ${d === selectedDay ? 'active' : ''}" onclick="selectAdminMobileDay('${d}')">
        ${d}
      </button>
    `;
  });
  dayPicker.innerHTML = dayPills;

  // Render 3 shift cards for selected day
  const roster = AppState.currentRoster;
  const shifts = roster.shifts || {};
  const targets = roster.targets || {};
  const cas = [
    { code: "Sáng", time: "07:00 – 12:00", defaultNeed: 2 },
    { code: "Chiều", time: "13:00 – 17:00", defaultNeed: 2 },
    { code: "Tối", time: "18:00 – 22:30", defaultNeed: 3 },
  ];

  let cardsHtml = "";
  cas.forEach(ca => {
    const slotKey = `${selectedDay}_${ca.code}`;
    const staffList = shifts[slotKey] || [];
    const needed = targets[slotKey] || ca.defaultNeed;

    cardsHtml += `
      <div class="mobile-shift-card" onclick="selectAdminRosterSlot('${selectedDay}', '${ca.code}', '${slotKey}')">
        <div>
          <strong style="font-size: 15px; color: var(--text-main);">Ca ${ca.code}</strong>
          <div style="font-size: 12px; color: var(--text-muted);">${ca.time}</div>
          <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px;">
            ${staffList.map(name => `<span class="badge badge-primary">${escapeHtml(name)}</span>`).join("")}
          </div>
        </div>
        <div style="text-align: right;">
          <span class="badge ${staffList.length >= needed ? 'badge-success' : 'badge-warning'}">${staffList.length}/${needed}</span>
          <div style="margin-top: 6px;">
            <button class="btn btn-secondary btn-sm">Điều phối</button>
          </div>
        </div>
      </div>
    `;
  });

  shiftsList.innerHTML = cardsHtml;
}

function selectAdminMobileDay(day) {
  AppState.adminSelectedDay = day;
  renderMobileAdminSchedule();
}

// ── 3. Admin Availability Matrix ─────────────────────────────────────────────
function renderAdminAvailabilityMatrix() {
  const tbody = document.getElementById("admin-matrix-tbody");
  if (!tbody) return;

  const employees = (AppState.bootstrapData && AppState.bootstrapData.employees) ? AppState.bootstrapData.employees : [];
  const schedules = AppState.shiftSchedules || {};
  const days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];

  if (employees.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; padding: 20px; color: var(--text-dim);">Chưa có nhân sự nào</td></tr>`;
    return;
  }

  let html = "";
  employees.forEach(emp => {
    const nick = emp.nickname || emp.full_name;
    const reg = schedules[nick] || {};
    const slots = reg.slots || {};

    html += `<tr>`;
    html += `<td style="padding: 10px 14px; font-weight: 700;">${escapeHtml(nick)}</td>`;
    html += `<td>${emp.role || 'Barista'}</td>`;

    days.forEach(d => {
      const daySlots = slots[d] || [];
      const hasMorning = daySlots.includes("Sáng");
      const hasAfternoon = daySlots.includes("Chiều");
      const hasEvening = daySlots.includes("Tối");

      html += `<td style="text-align: center; font-size: 11px;">`;
      if (hasMorning || hasAfternoon || hasEvening) {
        html += `<span style="color: var(--primary); font-weight: 700;">`;
        if (hasMorning) html += `S `;
        if (hasAfternoon) html += `C `;
        if (hasEvening) html += `T`;
        html += `</span>`;
      } else {
        html += `<span style="color: var(--text-dim);">—</span>`;
      }
      html += `</td>`;
    });

    html += `<td style="text-align: center; font-weight: 600;">${reg.target_shifts || 5} ca</td>`;
    html += `</tr>`;
  });

  tbody.innerHTML = html;
}

// ── 4. Admin Shift Swap Approvals ────────────────────────────────────────────
async function renderAdminSwapsTab() {
  const container = document.getElementById("admin-swaps-container");
  if (!container) return;

  const resp = await apiRequest("/api/swaps");
  if (resp && resp.success) {
    AppState.swaps = resp.swaps;
  }

  const swaps = AppState.swaps || [];
  if (swaps.length === 0) {
    container.innerHTML = `<div class="empty-state card"><p>Không có yêu cầu đổi ca nào trong hệ thống.</p></div>`;
    return;
  }

  let html = "";
  swaps.forEach(sw => {
    const reqS = sw.requester_shift || {};
    const tgtS = sw.target_shift || {};
    const isPending = sw.status === "pending";

    html += `
      <div class="card" style="padding: 20px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px;">
          <span style="font-size: 12px; color: var(--text-dim);">${sw.created_at}</span>
          <span class="badge ${isPending ? 'badge-warning' : (sw.status === 'approved' ? 'badge-success' : 'badge-danger')}">
            ${isPending ? 'Chờ duyệt' : (sw.status === 'approved' ? 'Đã duyệt' : 'Đã từ chối')}
          </span>
        </div>

        <div class="swap-comparison-card" style="margin-bottom: 14px; background: var(--bg-card-subtle);">
          <div class="swap-side">
            <span class="swap-side-tag">Người yêu cầu</span>
            <span class="swap-side-name">${escapeHtml(sw.requester)}</span>
            <span class="swap-side-shift">${reqS.day || ''} • Ca ${reqS.ca || ''} (${reqS.time || ''})</span>
          </div>
          <div class="swap-arrow-icon">⇄</div>
          <div class="swap-side">
            <span class="swap-side-tag">Người nhận</span>
            <span class="swap-side-name">${escapeHtml(sw.target)}</span>
            <span class="swap-side-shift">${tgtS.day || ''} • Ca ${tgtS.ca || ''} (${tgtS.time || ''})</span>
          </div>
        </div>

        ${sw.reason ? `<div style="font-size: 13px; color: var(--text-muted); margin-bottom: 14px;"><strong>Lý do:</strong> "${escapeHtml(sw.reason)}"</div>` : ''}

        ${isPending ? `
          <div style="display: flex; justify-content: flex-end; gap: 10px;">
            <button class="btn btn-secondary btn-sm" onclick="handleAdminSwapDecide('${sw.id}', false)">Từ chối</button>
            <button class="btn btn-primary btn-sm" onclick="handleAdminSwapDecide('${sw.id}', true)">Duyệt hoán đổi ca</button>
          </div>
        ` : ''}
      </div>
    `;
  });

  container.innerHTML = html;
  updateBadgeCounts();
}

async function handleAdminSwapDecide(swapId, approve) {
  const resp = await apiRequest("/api/admin/swaps/decide", {
    method: "POST",
    body: { swap_id: swapId, approve }
  });

  if (resp && resp.success) {
    showToast(resp.message || "Đã xử lý yêu cầu đổi ca!", "success");
    if (resp.roster) {
      AppState.currentRoster = resp.roster;
    }
    renderAdminSwapsTab();
  } else {
    showToast(resp.message || "Không thể xử lý yêu cầu", "error");
  }
}

// ── 5. Admin Employees Tab ───────────────────────────────────────────────────
function getRoleCssClass(role) {
  const norm = (role || "").toLowerCase();
  if (norm.includes("pha chế") || norm.includes("barista")) return "role-phache";
  if (norm.includes("phục vụ")) return "role-phucvu";
  if (norm.includes("thu ngân")) return "role-thungan";
  if (norm.includes("quản lý") || norm.includes("admin")) return "role-quanly";
  return "role-phache";
}

function renderAdminEmployeesTab() {
  const tbody = document.getElementById("admin-employees-tbody");
  if (!tbody || !AppState.bootstrapData) return;

  const employees = AppState.bootstrapData.employees || [];
  if (employees.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 24px; color: var(--text-dim);">Chưa có nhân viên nào trong danh sách.</td></tr>`;
    return;
  }

  let html = "";
  employees.forEach(emp => {
    const nick = emp.nickname || emp.full_name;
    const role = emp.role || "Pha Chế";
    const initial = (nick || "?").trim().charAt(0).toUpperCase();
    const roleClass = getRoleCssClass(role);
    const rateVal = emp.rate || 18;

    html += `
      <tr>
        <td style="padding: 12px 14px;">
          <div class="emp-name-cell">
            <div class="emp-avatar-sm">${escapeHtml(initial)}</div>
            <div style="font-weight: 700; color: var(--text-main); font-size: 14px;">${escapeHtml(nick)}</div>
          </div>
        </td>
        <td style="text-align: center;">
          <select class="inline-role-select ${roleClass}" 
                  onchange="onInlineRoleChange('${escapeHtml(nick)}', this)"
                  title="Bấm để thay đổi vị trí">
            <option value="Pha Chế" ${role === 'Pha Chế' ? 'selected' : ''}>☕ Pha Chế</option>
            <option value="Phục Vụ" ${role === 'Phục Vụ' ? 'selected' : ''}>🍽️ Phục Vụ</option>
            <option value="Thu Ngân" ${role === 'Thu Ngân' ? 'selected' : ''}>💵 Thu Ngân</option>
            <option value="Quản Lý" ${role === 'Quản Lý' ? 'selected' : ''}>👑 Quản Lý</option>
          </select>
        </td>
        <td style="text-align: center;">
          <div class="inline-rate-box" title="Bấm để sửa mức lương">
            <input type="number" 
                   class="inline-rate-input" 
                   value="${rateVal}" 
                   step="0.5" 
                   min="10" 
                   max="100" 
                   data-original="${rateVal}"
                   onfocus="this.select()"
                   onkeydown="if(event.key==='Enter') this.blur()"
                   onchange="onInlineRateChange('${escapeHtml(nick)}', this)">
            <span class="inline-rate-unit">k/h</span>
          </div>
        </td>
        <td style="text-align: center;">
          <span style="font-weight: 700; color: var(--text-main);">${emp.balance || 0}</span>
          <span style="font-size: 12px; color: var(--text-dim);"> ly</span>
        </td>
        <td style="text-align: right; padding-right: 14px; white-space: nowrap;">
          <button class="btn-icon-subtle" onclick="showRenameEmployeeModal('${escapeHtml(nick)}')" title="Đổi tên nhân viên">✏️</button>
          <button class="btn-icon-subtle btn-delete" onclick="confirmDeleteEmployee('${escapeHtml(nick)}')" title="Xóa nhân viên" style="margin-left: 4px;">🗑️</button>
        </td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

async function onInlineRoleChange(nickname, selectEl) {
  const role = selectEl.value;
  const oldRoleClass = selectEl.className;
  
  // Update class immediately for responsive visual feedback
  selectEl.className = `inline-role-select ${getRoleCssClass(role)}`;

  const resp = await apiRequest("/api/admin/employee/role", {
    method: "POST",
    body: { nickname, role }
  });

  if (resp && resp.success) {
    showToast(`✅ Đã lưu vị trí ${nickname}: ${role}!`, "success");
    if (resp.employees) {
      AppState.bootstrapData.employees = resp.employees;
    } else {
      const emp = (AppState.bootstrapData.employees || []).find(e => (e.nickname || e.full_name) === nickname);
      if (emp) emp.role = role;
    }
  } else {
    showToast(resp.message || "Lỗi cập nhật vị trí", "error");
    selectEl.className = oldRoleClass;
    if (AppState.bootstrapData && AppState.bootstrapData.employees) {
      const emp = AppState.bootstrapData.employees.find(e => (e.nickname || e.full_name) === nickname);
      if (emp) selectEl.value = emp.role || "Pha Chế";
    }
  }
}

async function onInlineRateChange(nickname, inputEl) {
  const original = parseFloat(inputEl.getAttribute("data-original") || "18");
  const newRate = parseFloat(inputEl.value);

  if (isNaN(newRate) || newRate <= 0) {
    showToast("Mức lương phải > 0 (k/giờ)", "error");
    inputEl.value = original;
    return;
  }

  if (newRate === original) {
    return;
  }

  const resp = await apiRequest("/api/admin/employee/salary-rate", {
    method: "POST",
    body: { nickname, rate: newRate }
  });

  if (resp && resp.success) {
    showToast(`✅ Đã lưu mức lương ${nickname}: ${newRate}k/h!`, "success");
    inputEl.setAttribute("data-original", newRate);
    if (resp.employees) {
      AppState.bootstrapData.employees = resp.employees;
    } else {
      const emp = (AppState.bootstrapData.employees || []).find(e => (e.nickname || e.full_name) === nickname);
      if (emp) emp.rate = newRate;
    }
  } else {
    showToast(resp.message || "Lỗi cập nhật mức lương", "error");
    inputEl.value = original;
  }
}

function showAddEmployeeModal() {
  openModal(
    "Thêm nhân viên mới",
    `
      <div class="form-group">
        <label class="form-label" for="new-emp-name">Tên / Nickname nhân viên</label>
        <input type="text" id="new-emp-name" class="form-input" placeholder="VD: Hoàng, Lan, Tuấn...">
      </div>
      <div class="form-group">
        <label class="form-label" for="new-emp-role">Vị trí làm việc (do Quản lý xếp)</label>
        <select id="new-emp-role" class="form-input">
          <option value="Pha Chế" selected>Pha Chế (Barista)</option>
          <option value="Phục Vụ">Phục Vụ</option>
          <option value="Thu Ngân">Thu Ngân</option>
          <option value="Quản Lý">Quản Lý</option>
        </select>
        <div class="form-hint">Mật khẩu đăng nhập mặc định cho nhân viên mới là: <strong>123456789</strong></div>
      </div>
    `,
    `
      <button class="btn btn-secondary btn-sm" onclick="closeModal()">Hủy</button>
      <button class="btn btn-primary btn-sm" onclick="submitAddEmployee()">Lưu nhân viên</button>
    `
  );
}

async function submitAddEmployee() {
  const name = document.getElementById("new-emp-name").value.trim();
  const roleEl = document.getElementById("new-emp-role");
  const role = roleEl ? roleEl.value.trim() : "Pha Chế";
  if (!name) {
    showToast("Vui lòng nhập tên nhân viên", "error");
    return;
  }

  const resp = await apiRequest("/api/admin/employee/add", {
    method: "POST",
    body: { nickname: name, role: role || "Pha Chế" }
  });

  if (resp && resp.success) {
    showToast(`Đã thêm nhân viên ${name} (${role})!`, "success");
    closeModal();
    if (resp.employees) {
      AppState.bootstrapData.employees = resp.employees;
      renderAdminEmployeesTab();
    }
  } else {
    showToast(resp.message || "Không thể thêm nhân viên", "error");
  }
}

function showRenameEmployeeModal(nickname) {
  openModal(
    "Đổi tên nhân viên",
    `
      <div class="form-group">
        <label class="form-label" for="rename-emp-input">Tên / Nickname mới</label>
        <input type="text" id="rename-emp-input" class="form-input" value="${escapeHtml(nickname)}" placeholder="Nhập tên mới">
        <div class="form-hint">Dữ liệu chấm công, thưởng và ca làm sẽ được cập nhật sang tên mới.</div>
      </div>
    `,
    `
      <button class="btn btn-secondary btn-sm" onclick="closeModal()">Hủy</button>
      <button class="btn btn-primary btn-sm" onclick="submitRenameEmployee('${escapeHtml(nickname)}')">Lưu tên mới</button>
    `
  );
}

async function submitRenameEmployee(oldNickname) {
  const input = document.getElementById("rename-emp-input");
  const newNickname = input ? input.value.trim() : "";
  if (!newNickname || newNickname === oldNickname) {
    closeModal();
    return;
  }

  const resp = await apiRequest("/api/admin/employee/rename", {
    method: "POST",
    body: { old_nickname: oldNickname, new_nickname: newNickname }
  });

  if (resp && resp.success) {
    showToast(`✅ Đã đổi tên ${oldNickname} → ${newNickname}!`, "success");
    closeModal();
    if (resp.employees) {
      AppState.bootstrapData.employees = resp.employees;
      renderAdminEmployeesTab();
    }
  } else {
    showToast(resp.message || "Không thể đổi tên nhân viên", "error");
  }
}

function confirmDeleteEmployee(nickname) {
  openModal(
    "Xác nhận xóa nhân viên",
    `
      <p style="margin-bottom: 12px;">Bạn có chắc chắn muốn xóa nhân viên <strong>${escapeHtml(nickname)}</strong> khỏi hệ thống quán?</p>
      <div style="font-size: 13px; color: var(--danger); background: var(--danger-bg); border: 1px solid var(--danger-border); padding: 10px; border-radius: var(--radius-sm); line-height: 1.5;">
        ⚠️ Nhân viên bị xóa sẽ không thể đăng nhập hoặc hiển thị trong danh sách chấm công và bàn giao ca.
      </div>
    `,
    `
      <button class="btn btn-secondary btn-sm" onclick="closeModal()">Hủy</button>
      <button class="btn btn-danger btn-sm" onclick="submitDeleteEmployee('${escapeHtml(nickname)}')">Xác nhận xóa</button>
    `
  );
}

async function submitDeleteEmployee(nickname) {
  closeModal();
  const resp = await apiRequest("/api/admin/employee/remove", {
    method: "POST",
    body: { nickname }
  });

  if (resp && resp.success) {
    showToast(`✅ Đã xóa nhân viên ${nickname}!`, "success");
    if (resp.employees) {
      AppState.bootstrapData.employees = resp.employees;
      renderAdminEmployeesTab();
    }
  } else {
    showToast(resp.message || "Không thể xóa nhân viên", "error");
  }
}

// ── 6. Admin Payroll Management ──────────────────────────────────────────────
async function loadAdminSalaryData() {
  const select = document.getElementById("admin-salary-month-select");
  const tbody = document.getElementById("admin-salary-tbody");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 24px; color: var(--text-dim);">Đang tải dữ liệu bảng lương...</td></tr>`;

  let url = "/api/admin/salary";
  if (select && select.value && select.value !== "current") {
    const parts = select.value.split("-");
    if (parts.length === 2) {
      url += `?year=${parts[0]}&month=${parts[1]}`;
    }
  }

  const resp = await apiRequest(url);
  if (!resp || !resp.success || !resp.salary) {
    const err = (resp && resp.message) || "Không thể tải dữ liệu bảng lương. Vui lòng kiểm tra quyền Admin.";
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 24px; color: var(--danger);">${escapeHtml(err)}</td></tr>`;
    return;
  }

  const s = resp.salary;

  // Update KPI Cards
  const kpiTotal = document.getElementById("admin-salary-kpi-total");
  const kpiHours = document.getElementById("admin-salary-kpi-hours");
  const kpiPeriod = document.getElementById("admin-salary-kpi-period");

  if (kpiTotal) kpiTotal.textContent = formatCurrency((s.total_payout || 0) * 1000);
  if (kpiHours) kpiHours.textContent = `${s.total_hours || 0}h`;
  if (kpiPeriod && s.period_start && s.period_end) {
    kpiPeriod.textContent = `${s.period_start} → ${s.period_end}`;
  }

  // Populate Month Filter Select if needed
  if (select && Array.isArray(resp.options) && resp.options.length > 0) {
    const curMonth = s.month;
    const curYear = s.year;
    if (select.options.length <= 1) {
      let optHtml = "";
      resp.options.forEach(opt => {
        const val = `${opt.year}-${opt.month}`;
        const isSelected = (opt.month === curMonth && opt.year === curYear);
        optHtml += `<option value="${val}" ${isSelected ? "selected" : ""}>Tháng ${opt.month}/${opt.year}${!opt.exists ? " ✨" : ""}</option>`;
      });
      select.innerHTML = optHtml;
    }
  }

  const items = s.items || s.rows || [];
  if (items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 24px; color: var(--text-dim);">Chưa có dữ liệu bảng lương tháng ${s.month || ''}/${s.year || ''}</td></tr>`;
    return;
  }

  let html = "";
  items.forEach(r => {
    const displayName = r.display_name || r.nickname;
    const initial = displayName.charAt(0).toUpperCase();
    const hours = r.hours !== undefined ? r.hours : (r.total_hours || 0);
    const rate = r.rate || 0;
    const bonus = r.bonus || 0;
    const advance = r.advance || 0;
    const totalAmount = (r.total !== undefined ? r.total : (r.net_salary || 0)) * 1000;

    let bonusAdvHtml = "—";
    if (bonus > 0 && advance > 0) {
      bonusAdvHtml = `<span style="color: var(--success); font-weight: 600;">+${formatCurrency(bonus * 1000)}</span><br><span style="color: var(--warning); font-weight: 600;">-${formatCurrency(advance * 1000)}</span>`;
    } else if (bonus > 0) {
      bonusAdvHtml = `<span style="color: var(--success); font-weight: 600;">+${formatCurrency(bonus * 1000)}</span>`;
    } else if (advance > 0) {
      bonusAdvHtml = `<span style="color: var(--warning); font-weight: 600;">-${formatCurrency(advance * 1000)}</span>`;
    }

    html += `
      <tr>
        <td style="padding: 10px 14px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <div class="staff-card-avatar" style="width: 28px; height: 28px; font-size: 12px;">${escapeHtml(initial)}</div>
            <div>
              <div style="font-weight: 700; color: var(--text-main); font-size: 13.5px;">${escapeHtml(displayName)}</div>
              ${displayName !== r.nickname ? `<div style="font-size: 11px; color: var(--text-dim);">${escapeHtml(r.nickname)}</div>` : ''}
            </div>
          </div>
        </td>
        <td style="text-align: center; font-weight: 600;">${hours}h</td>
        <td style="text-align: center; color: var(--text-muted);">${rate}k/h</td>
        <td style="text-align: center;">${bonusAdvHtml}</td>
        <td style="text-align: center; font-weight: 700; font-size: 14.5px; color: var(--primary);">${formatCurrency(totalAmount)}</td>
        <td style="text-align: right; padding-right: 14px;">
          <button class="btn btn-secondary btn-sm" onclick="showSalaryModifierModal('${escapeHtml(r.nickname)}')">
            <span>+ Thưởng/Ứng</span>
          </button>
        </td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function showSalaryModifierModal(nickname) {
  openModal(
    `Thưởng / Ứng lương: ${nickname}`,
    `
      <div class="form-group">
        <label class="form-label">Loại điều chỉnh</label>
        <select id="mod-type" class="form-select">
          <option value="bonus">🎁 Thưởng tiền (+)</option>
          <option value="advance">💸 Ứng lương (-)</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label" for="mod-amount">Số tiền</label>
        <input type="text" id="mod-amount" class="form-input" placeholder="VD: 50k hoặc 50000">
        <div class="form-hint">Nhập 50 = 50.000đ, hoặc 100k = 100.000đ</div>
      </div>
    `,
    `
      <button class="btn btn-secondary btn-sm" onclick="closeModal()">Hủy</button>
      <button class="btn btn-primary btn-sm" onclick="submitSalaryModifier('${nickname}')">Áp dụng</button>
    `
  );
}

async function submitSalaryModifier(nickname) {
  const type = document.getElementById("mod-type").value;
  const amount = document.getElementById("mod-amount").value.trim();
  if (!amount) {
    showToast("Vui lòng nhập số tiền", "error");
    return;
  }

  const select = document.getElementById("admin-salary-month-select");
  let month = null;
  let year = null;
  if (select && select.value && select.value !== "current") {
    const parts = select.value.split("-");
    if (parts.length === 2) {
      year = parseInt(parts[0], 10);
      month = parseInt(parts[1], 10);
    }
  }

  const resp = await apiRequest("/api/admin/salary/modifier", {
    method: "POST",
    body: { nickname, type, amount, month, year }
  });

  if (resp && resp.success) {
    showToast("Đã cập nhật bảng lương!", "success");
    closeModal();
    loadAdminSalaryData();
  } else {
    showToast(resp.message || "Lỗi cập nhật", "error");
  }
}

// ── 7. Admin Inventory Tab ───────────────────────────────────────────────────
async function renderAdminInventoryTab() {
  const tbody = document.getElementById("admin-inventory-tbody");
  if (!tbody) return;

  const resp = await apiRequest("/api/inventory");
  if (!resp || !resp.success || !Array.isArray(resp.materials)) return;

  let html = "";
  resp.materials.forEach(m => {
    const isLow = m.min_stock > 0 && m.stock <= m.min_stock;
    html += `
      <tr>
        <td style="padding: 10px 14px; font-weight: 600;">${escapeHtml(m.name)}</td>
        <td>${escapeHtml(m.group || 'Khác')}</td>
        <td style="text-align: center; font-weight: 700; color: ${isLow ? 'var(--danger)' : 'var(--text-main)'};">${m.stock} ${m.unit}</td>
        <td style="text-align: center;">${m.min_stock} ${m.unit}</td>
        <td style="text-align: center;">
          <span class="badge ${isLow ? 'badge-danger' : 'badge-success'}">${isLow ? 'Sắp hết' : 'Đủ hàng'}</span>
        </td>
        <td style="text-align: right; padding-right: 14px;">
          <button class="btn btn-secondary btn-sm" onclick="showQuickImportModal('${escapeHtml(m.name)}')">+ Nhập</button>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

function showQuickImportModal(name) {
  openModal(
    `Nhập kho: ${name}`,
    `
      <div class="form-group">
        <label class="form-label" for="quick-imp-qty">Số lượng nhập thêm</label>
        <input type="number" id="quick-imp-qty" class="form-input" min="0.1" step="0.5" placeholder="VD: 5">
      </div>
      <div class="form-group">
        <label class="form-label" for="quick-imp-note">Ghi chú</label>
        <input type="text" id="quick-imp-note" class="form-input" placeholder="VD: Nhập buổi sáng">
      </div>
    `,
    `
      <button class="btn btn-secondary btn-sm" onclick="closeModal()">Hủy</button>
      <button class="btn btn-primary btn-sm" onclick="submitQuickImport('${name}')">Xác nhận nhập kho</button>
    `
  );
}

async function submitQuickImport(name) {
  const qty = parseFloat(document.getElementById("quick-imp-qty").value);
  const note = document.getElementById("quick-imp-note").value.trim();
  if (!qty || qty <= 0) return;

  const resp = await apiRequest("/api/inventory/import", {
    method: "POST",
    body: { name, qty, note }
  });

  if (resp && resp.success) {
    showToast(`Đã nhập thêm ${qty} ${name}!`, "success");
    closeModal();
    renderAdminInventoryTab();
  } else {
    showToast(resp.message || "Lỗi nhập kho", "error");
  }
}

function showAddMaterialModal() {
  openModal(
    "Thêm nguyên vật liệu mới",
    `
      <div class="form-group">
        <label class="form-label" for="new-mat-name">Tên NVL</label>
        <input type="text" id="new-mat-name" class="form-input" placeholder="VD: Syrup Đào, Trà Lục...">
      </div>
      <div class="form-group">
        <label class="form-label" for="new-mat-unit">Đơn vị tính</label>
        <input type="text" id="new-mat-unit" class="form-input" placeholder="VD: chai, hộp, kg...">
      </div>
      <div class="form-group">
        <label class="form-label" for="new-mat-min">Tồn kho tối thiểu (Cảnh báo)</label>
        <input type="number" id="new-mat-min" class="form-input" value="2" min="0">
      </div>
    `,
    `
      <button class="btn btn-secondary btn-sm" onclick="closeModal()">Hủy</button>
      <button class="btn btn-primary btn-sm" onclick="submitAddMaterial()">Lưu NVL</button>
    `
  );
}

async function submitAddMaterial() {
  const name = document.getElementById("new-mat-name").value.trim();
  const unit = document.getElementById("new-mat-unit").value.trim();
  const minStock = parseFloat(document.getElementById("new-mat-min").value) || 0;

  if (!name || !unit) return;

  const resp = await apiRequest("/api/inventory/material/add", {
    method: "POST",
    body: { name, unit, min_stock: minStock, price: 0 }
  });

  if (resp && resp.success) {
    showToast(`Đã thêm ${name}!`, "success");
    closeModal();
    renderAdminInventoryTab();
  } else {
    showToast(resp.message || "Lỗi khi thêm", "error");
  }
}

// ── 8. Admin Announcements ───────────────────────────────────────────────────
async function submitAdminAnnouncement() {
  const msg = document.getElementById("admin-announce-msg").value.trim();
  if (!msg) {
    showToast("Vui lòng nhập nội dung thông báo", "error");
    return;
  }

  const resp = await apiRequest("/api/admin/announce", {
    method: "POST",
    body: { message: msg }
  });

  if (resp && resp.success) {
    showToast("Đã gửi thông báo vào nhóm chung!", "success");
    document.getElementById("admin-announce-msg").value = "";
  } else {
    showToast(resp.message || "Không thể gửi thông báo", "error");
  }
}

// ── 9. Password Management ───────────────────────────────────────────────────
async function submitChangePassword(target) {
  let oldPwd = "";
  let newPwd = "";

  if (target === "admin") {
    oldPwd = document.getElementById("admin-old-pass").value.trim();
    newPwd = document.getElementById("admin-new-pass").value.trim();
  } else {
    oldPwd = document.getElementById("user-old-pwd").value.trim();
    newPwd = document.getElementById("user-new-pwd").value.trim();
  }

  if (!oldPwd || !newPwd) {
    showToast("Vui lòng nhập đầy đủ mật khẩu cũ và mới", "error");
    return;
  }

  const resp = await apiRequest("/api/auth/change-password", {
    method: "POST",
    body: { old_password: oldPwd, new_password: newPwd }
  });

  if (resp && resp.success) {
    showToast("✅ Đã đổi mật khẩu thành công!", "success");
    if (target === "admin") {
      document.getElementById("admin-old-pass").value = "";
      document.getElementById("admin-new-pass").value = "";
    } else {
      document.getElementById("user-old-pwd").value = "";
      document.getElementById("user-new-pwd").value = "";
    }
  } else {
    showToast(resp.message || "Mật khẩu cũ không chính xác", "error");
  }
}

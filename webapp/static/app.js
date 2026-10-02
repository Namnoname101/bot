const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function stripAccents(str) {
  return String(str || "")
    .replace(/[đĐ]/g, "d")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function haptic(type = "light") {
  try {
    if (tg && tg.HapticFeedback) {
      if (type === "success" || type === "error" || type === "warning") {
        tg.HapticFeedback.notificationOccurred(type);
      } else {
        tg.HapticFeedback.impactOccurred(type);
      }
    }
  } catch (_) {}
}

const App = {
  state: {
    activeTab: "attendance",
    user: null,
    serverTime: null,
    employees: [],
    openSessions: [],
    materials: [],
    materialGroups: [],
    selectedInvGroup: "ALL",
    cart: {}, // { materialName: qty }
    smartExportState: null,

    // Identity (Role & Nickname)
    myNickname: localStorage.getItem("sober_my_nickname") || "",
    myRole: localStorage.getItem("sober_my_role") || "Pha Chế",

    // Practical features state
    checklists: {},
    checklistChecked: {},
    recipes: [],
    shiftSchedules: {},
    myScheduleSlots: {},
    pettyExpenses: [],
    leaveRequests: [],
    leaveType: "late",

    // Check-in selections
    checkinType: "Ca Chính",
    checkinCa: "Sáng",
    checkinEmp: localStorage.getItem("sober_my_nickname") || "",

    // Rewards & Reports selections
    rewardReqSelected: {},
    reportCa: "Sáng",
    reportSelectedEmps: {},
    endshiftCa: "Sáng",
    endshiftRole: localStorage.getItem("sober_my_role") || "Pha Chế",

    // Admin state
    adminOverview: null,
    salaryOptions: [],
    salaryData: null,
    salaryModType: "advance",
  },

  async api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    const initData = (tg && tg.initData) || new URLSearchParams(window.location.search).get("initData") || "";
    if (initData) {
      headers["X-Telegram-Init-Data"] = initData;
    }
    const adminKey = localStorage.getItem("sober_admin_key") || new URLSearchParams(window.location.search).get("admin_key") || "";
    if (adminKey) {
      headers["X-Admin-Key"] = adminKey;
    }
    const empName = this.state.myNickname || localStorage.getItem("sober_my_nickname") || "";
    if (empName) {
      headers["X-Employee-Name"] = encodeURIComponent(empName);
    }
    if (options.body && !(options.body instanceof FormData) && typeof options.body === "object") {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    const resp = await fetch(path, Object.assign({}, options, { headers }));
    const data = await resp.json().catch(() => ({ success: false, message: "Lỗi phản hồi máy chủ" }));
    if (!resp.ok || data.success === false) {
      const err = new Error(data.message || `HTTP ${resp.status}`);
      err.status = resp.status;
      err.data = data;
      throw err;
    }
    return data;
  },

  toast(msg, duration = 2800) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => el.classList.add("hidden"), duration);
  },

  openModal(title, htmlContent) {
    document.getElementById("modal-title").textContent = title;
    document.getElementById("modal-body").innerHTML = htmlContent;
    document.getElementById("modal-overlay").classList.remove("hidden");
  },

  closeModal() {
    document.getElementById("modal-overlay").classList.add("hidden");
  },

  openRoleModal() {
    const u = this.state.user || {};
    const curNick = this.state.myNickname || "";
    const curRole = this.state.myRole || "Pha Chế";
    const empOptions = [
      `<option value="">-- Chọn tên nhân viên --</option>`,
      ...this.state.employees.map(
        (e) => `<option value="${esc(e.nickname)}" ${e.nickname === curNick ? "selected" : ""}>${esc(e.nickname)}</option>`
      ),
    ].join("");

    const adminSection = u.is_admin && localStorage.getItem("sober_admin_key")
      ? `<hr style="border-color:var(--border);margin:14px 0" />
         <p class="text-xs mb-8">🛡 Bạn đang bật quyền Quản lý trên trình duyệt.</p>
         <button class="btn btn-danger btn-block" onclick="App.logoutAdminKey()">Đăng Xuất Quyền Quản Lý</button>`
      : !u.is_admin
      ? `<hr style="border-color:var(--border);margin:14px 0" />
         <label class="field-label">👑 Dành cho Quản lý (Nhập ID/PIN Quản lý)</label>
         <div class="row-gap">
           <input id="modal-admin-key-input" type="password" class="input" placeholder="Mã PIN / ID Quản lý..." />
           <button class="btn btn-secondary" onclick="App.submitAdminKey()">Mở Khóa</button>
         </div>`
      : `<p class="text-xs mt-8">👑 Đã tự động xác thực quyền Quản lý qua Telegram.</p>`;

    this.openModal(
      "👤 Chọn Nhân Viên & Vị Trí Ca Làm",
      `
      <label class="field-label">1. Tên nhân viên</label>
      <select id="modal-emp-nick" class="input mb-8">${empOptions}</select>

      <label class="field-label">2. Bộ phận làm việc hôm nay</label>
      <div class="segmented mb-12" id="modal-role-seg">
        <button type="button" class="seg-btn ${curRole === "Pha Chế" ? "active" : ""}" data-val="Pha Chế" onclick="App.selectModalRole('Pha Chế')">🍹 Pha Chế</button>
        <button type="button" class="seg-btn ${curRole === "Phục Vụ" ? "active" : ""}" data-val="Phục Vụ" onclick="App.selectModalRole('Phục Vụ')">🍽 Phục Vụ</button>
      </div>

      <button class="btn btn-primary btn-block" onclick="App.saveEmployeeIdentity()">✅ Lưu & Vào Ca Làm Việc</button>
      ${adminSection}
      `
    );
    this._tempModalRole = curRole;
  },

  selectModalRole(role) {
    this._tempModalRole = role;
    document.querySelectorAll("#modal-role-seg .seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === role);
    });
  },

  saveEmployeeIdentity() {
    const nick = (document.getElementById("modal-emp-nick")?.value || "").trim();
    const role = this._tempModalRole || "Pha Chế";
    this.state.myNickname = nick;
    this.state.myRole = role;
    localStorage.setItem("sober_my_nickname", nick);
    localStorage.setItem("sober_my_role", role);
    if (nick) {
      this.state.checkinEmp = nick;
    }
    this.setEndshiftRole(role);
    this.closeModal();
    this.renderHeader();
    this.renderAll();
    if (nick) {
      this.loadPersonalSummary(nick);
    }
    this.toast(`✅ Đã chọn: ${nick || "Nhân viên"} (${role})`);
  },

  async submitAdminKey() {
    const val = (document.getElementById("modal-admin-key-input")?.value || "").trim();
    if (!val) {
      this.toast("⚠️ Vui lòng nhập mã Quản lý");
      return;
    }
    localStorage.setItem("sober_admin_key", val);
    this.closeModal();
    await this.init();
    if (this.state.user && this.state.user.is_admin) {
      this.toast("✅ Đã mở khóa quyền Quản lý!");
    } else {
      localStorage.removeItem("sober_admin_key");
      this.toast("❌ Mã Quản lý không đúng!");
    }
  },

  async logoutAdminKey() {
    localStorage.removeItem("sober_admin_key");
    localStorage.removeItem("sober_tg_admin_logged");
    this.closeModal();
    this.state.activeTab = "attendance";
    await this.init();
    this.toast("Đã chuyển về chế độ Nhân viên");
  },

  // ==================== LOGIN & AUTH FLOW ====================

  _selectedLoginRole: "Pha Chế",
  _isExplicitLoggedOut: false,

  switchLoginTab(type) {
    haptic("light");
    document.querySelectorAll("#login-role-tabs .seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.role === type);
    });
    const empForm = document.getElementById("form-login-employee");
    const adminForm = document.getElementById("form-login-admin");
    if (type === "employee") {
      empForm?.classList.remove("hidden");
      adminForm?.classList.add("hidden");
    } else {
      empForm?.classList.add("hidden");
      adminForm?.classList.remove("hidden");
    }
  },

  setLoginRole(role) {
    haptic("light");
    this._selectedLoginRole = role;
    const barCard = document.getElementById("card-role-barista");
    const srvCard = document.getElementById("card-role-server");
    if (barCard && srvCard) {
      barCard.classList.toggle("active", role === "Pha Chế");
      srvCard.classList.toggle("active", role === "Phục Vụ");
    }
  },

  populateLoginEmployeeSelect() {
    const selectEl = document.getElementById("login-emp-select");
    if (!selectEl) return;
    const curNick = this.state.myNickname || "";
    const opts = [
      '<option value="">-- Chọn tên nhân viên của bạn --</option>',
      ...this.state.employees.map(
        (e) => `<option value="${esc(e.nickname)}" ${e.nickname === curNick ? "selected" : ""}>${esc(e.nickname)}</option>`
      ),
    ].join("");
    selectEl.innerHTML = opts;
  },

  showLoginScreen() {
    document.getElementById("screen-login")?.classList.remove("hidden");
    document.getElementById("app-header")?.classList.add("hidden");
    document.querySelector(".app-content")?.classList.add("hidden");
    document.querySelector(".bottom-nav")?.classList.add("hidden");
    document.body.classList.add("login-mode");
    this.populateLoginEmployeeSelect();

    const tgHint = document.getElementById("login-tg-auto");
    if (tgHint) {
      if (this.state.user && this.state.user.is_admin && !this._isExplicitLoggedOut) {
        tgHint.classList.remove("hidden");
        const span = tgHint.querySelector("span");
        if (span) span.textContent = `⚡ Quản lý Telegram: ${this.state.user.full_name || ""}`;
      } else {
        tgHint.classList.add("hidden");
      }
    }
  },

  showMainApp() {
    document.getElementById("screen-login")?.classList.add("hidden");
    document.getElementById("app-header")?.classList.remove("hidden");
    document.querySelector(".app-content")?.classList.remove("hidden");
    document.querySelector(".bottom-nav")?.classList.remove("hidden");
    document.body.classList.remove("login-mode");
  },

  submitEmployeeLogin() {
    haptic("success");
    const selectEl = document.getElementById("login-emp-select");
    const nick = (selectEl ? selectEl.value : "").trim();
    if (!nick) {
      haptic("error");
      this.toast("⚠️ Vui lòng chọn tên nhân viên của bạn!");
      return;
    }
    const role = this._selectedLoginRole || "Pha Chế";
    this.state.myNickname = nick;
    this.state.myRole = role;
    this.state.checkinEmp = nick;
    this._isExplicitLoggedOut = false;
    localStorage.setItem("sober_my_nickname", nick);
    localStorage.setItem("sober_my_role", role);
    localStorage.removeItem("sober_admin_key");
    localStorage.removeItem("sober_tg_admin_logged");

    this.setEndshiftRole(role);
    this.showMainApp();
    this.renderHeader();
    this.renderAll();
    this.loadPersonalSummary(nick);
    this.switchTab("attendance");
    this.toast(`🎉 Chào mừng ${nick} (${role}) vào ca làm!`);
  },

  async submitAdminLogin() {
    haptic("light");
    const input = document.getElementById("login-admin-key-input");
    const key = (input ? input.value : "").trim();
    if (!key) {
      haptic("error");
      this.toast("⚠️ Vui lòng nhập mã bảo mật Quản lý!");
      return;
    }

    localStorage.setItem("sober_admin_key", key);
    try {
      const data = await this.api("/api/bootstrap");
      if (data && data.user && data.user.is_admin) {
        haptic("success");
        this.state.user = data.user;
        this.state.serverTime = data.server_time;
        this.state.employees = data.employees || [];
        this._isExplicitLoggedOut = false;
        this.showMainApp();
        this.renderHeader();
        this.renderAll();
        this.switchTab("admin");
        this.toast("👑 Đăng nhập Quản lý thành công!");
      } else {
        localStorage.removeItem("sober_admin_key");
        haptic("error");
        this.toast("❌ Mã Quản lý không hợp lệ hoặc không có quyền!");
      }
    } catch (err) {
      localStorage.removeItem("sober_admin_key");
      haptic("error");
      this.toast("❌ Đăng nhập thất bại: " + (err.message || "Lỗi xác thực"));
    }
  },

  loginWithTelegram() {
    if (this.state.user && this.state.user.is_admin) {
      haptic("success");
      this._isExplicitLoggedOut = false;
      localStorage.setItem("sober_tg_admin_logged", "1");
      this.showMainApp();
      this.renderHeader();
      this.renderAll();
      this.switchTab("admin");
      this.toast(`👑 Đã đăng nhập Quản lý: ${this.state.user.full_name}`);
    } else {
      this.toast("Tài khoản Telegram của bạn không có quyền Quản lý.");
    }
  },

  logout() {
    haptic("light");
    localStorage.removeItem("sober_my_nickname");
    localStorage.removeItem("sober_my_role");
    localStorage.removeItem("sober_admin_key");
    localStorage.removeItem("sober_tg_admin_logged");
    this.state.myNickname = "";
    this.state.myRole = "Pha Chế";
    this._isExplicitLoggedOut = true;
    this.showLoginScreen();
    this.toast("👋 Đã đăng xuất!");
  },

  async init() {
    try {
      if (tg) {
        tg.ready();
        tg.expand();
      }
    } catch (_) {}

    document.getElementById("app-loading").classList.remove("hidden");
    document.getElementById("app-error").classList.add("hidden");

    try {
      const data = await this.api("/api/bootstrap");
      this.state.user = data.user;
      this.state.serverTime = data.server_time;
      this.state.employees = data.employees || [];
      this.state.openSessions = data.open_sessions || [];
      this.state.materials = data.materials || [];
      this.state.materialGroups = data.material_groups || [];
      this.state.checklists = data.checklists || {};
      this.state.recipes = data.recipes || [];
      this.state.shiftSchedules = data.shift_schedules || {};
      this.state.pettyExpenses = data.petty_expenses || [];
      this.state.leaveRequests = data.leave_requests || [];

      const inferredCa = (data.server_time && data.server_time.inferred_ca) || "Sáng";
      this.state.checkinCa = inferredCa;
      this.state.reportCa = inferredCa;
      this.state.endshiftCa = inferredCa;

      const lvDateEl = document.getElementById("lv-date-input");
      if (lvDateEl && !lvDateEl.value && data.server_time) {
        lvDateEl.value = data.server_time.date || "";
      }

      this.populateLoginEmployeeSelect();

      // Check whether user has logged in
      const hasNick = Boolean(this.state.myNickname);
      const isAdminKey = Boolean(localStorage.getItem("sober_admin_key"));
      const isTgAdmin = Boolean(
        localStorage.getItem("sober_tg_admin_logged") &&
        this.state.user &&
        this.state.user.is_admin &&
        !this._isExplicitLoggedOut
      );

      const isAuthenticated = (hasNick && this.state.myRole) || isAdminKey || isTgAdmin;

      document.getElementById("app-loading").classList.add("hidden");

      if (isAuthenticated) {
        this.showMainApp();
        this.renderHeader();
        this.setCheckinCa(inferredCa);
        this.setReportCa(inferredCa);
        this.setEndshiftCa(inferredCa);
        this.setEndshiftRole(this.state.myRole || "Pha Chế");
        this.renderAll();
        const defaultTab = (!hasNick && (isAdminKey || isTgAdmin)) ? "admin" : (this.state.activeTab || "attendance");
        this.switchTab(defaultTab);
      } else {
        this.showLoginScreen();
      }
    } catch (err) {
      document.getElementById("app-loading").classList.add("hidden");
      document.getElementById("app-error").classList.remove("hidden");
      document.getElementById("error-desc").textContent = err.message || "Không thể kết nối máy chủ.";
    }
  },

  async refreshAll() {
    haptic("light");
    await this.init();
    if (this.state.user && this.state.user.is_admin && this.state.activeTab === "admin") {
      await this.loadAdminOverview();
    }
    this.toast("🔄 Đã làm mới dữ liệu!");
  },

  renderHeader() {
    const u = this.state.user || {};
    const st = this.state.serverTime || {};
    const myNick = this.state.myNickname;
    const myRole = this.state.myRole || "Pha Chế";
    const roleIcon = myRole === "Phục Vụ" ? "🍽" : "🍹";

    const displayName = myNick ? `${myNick} (${myRole})` : u.full_name || "Nhân viên";
    document.getElementById("header-subtitle").textContent = `${displayName} • ${st.time || ""} (${st.date || ""})`;

    const badge = document.getElementById("role-badge");
    const adminNav = document.getElementById("nav-admin-btn");
    const superBtn = document.getElementById("subtab-btn-super");
    const addRecipeBtn = document.getElementById("btn-add-recipe");

    if (u.is_super_admin) {
      badge.textContent = "👑 Admin Gốc";
      badge.className = "badge badge-admin";
      adminNav.classList.remove("hidden");
      superBtn.classList.remove("hidden");
      if (addRecipeBtn) addRecipeBtn.classList.remove("hidden");
    } else if (u.is_admin) {
      badge.textContent = "🛡 Quản Lý";
      badge.className = "badge badge-admin";
      adminNav.classList.remove("hidden");
      superBtn.classList.add("hidden");
      if (addRecipeBtn) addRecipeBtn.classList.remove("hidden");
    } else {
      badge.textContent = myNick ? `${roleIcon} ${myNick}` : "👤 Chọn NV";
      badge.className = "badge badge-emp";
      adminNav.classList.add("hidden");
      superBtn.classList.add("hidden");
      if (addRecipeBtn) addRecipeBtn.classList.add("hidden");
    }

    // Update top Identity Bar
    const idIcon = document.getElementById("identity-icon");
    const idTitle = document.getElementById("identity-title");
    const idSub = document.getElementById("identity-sub");
    if (idTitle && idSub && idIcon) {
      if (myNick) {
        idIcon.textContent = roleIcon;
        idTitle.textContent = `${myNick} — Bộ phận ${myRole}${u.is_admin ? " (👑 Quản lý)" : ""}`;
        idSub.textContent = `Đã đồng bộ tên & checklist theo vị trí ${myRole}. Bấm để đổi nhân viên.`;
      } else if (u.is_admin) {
        idIcon.textContent = "👑";
        idTitle.textContent = "Đang ở chế độ Quản lý (Admin)";
        idSub.textContent = "Bấm vào đây nếu muốn chọn thêm tên nhân viên hoặc đăng xuất quyền Quản lý.";
      } else {
        idIcon.textContent = "👤";
        idTitle.textContent = "Chưa chọn tên nhân viên";
        idSub.textContent = "Bấm vào đây để chọn Tên & Vị trí (🍹 Pha chế / 🍽 Phục vụ / 👑 Quản lý)";
      }
    }
  },

  renderAll() {
    this.renderAttendance();
    this.renderInventoryGroups();
    this.renderInventoryList();
    this.renderRecipesList();
    this.renderRewardBalances();
    this.renderRewardRequestGrid();
    this.renderReportEmpGrid();
    this.renderPettyExpenses();
    this.renderEndshiftChecklist();
    this.populateEmployeeFeatureSelects();
    this.renderLeaveHistory();
    this.populateAdminSelects();
  },

  switchTab(tabName) {
    haptic("light");
    this.state.activeTab = tabName;
    document.querySelectorAll(".tab-panel").forEach((el) => el.classList.add("hidden"));
    const target = document.getElementById(`tab-${tabName}`);
    if (target) target.classList.remove("hidden");

    document.querySelectorAll(".bottom-nav .nav-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tabName);
    });

    if (tabName === "admin" && this.state.user && this.state.user.is_admin) {
      this.loadAdminOverview();
      this.loadAdminSalary();
      this.loadAdminInventory();
    }
  },

  switchSubtab(section, subId) {
    haptic("light");
    const container = document.getElementById(`tab-${section}`);
    if (!container) return;
    container.querySelectorAll(".subtab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.sub === subId);
    });
    container.querySelectorAll(".subtab-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.id !== `sub-${subId}`);
    });
    if (subId === "att-personal") {
      this.loadPersonalSummary();
    } else if (subId === "att-schedule") {
      this.loadMyScheduleGrid();
    }
  },

  // ==================== 1. ATTENDANCE ====================

  renderAttendance() {
    const st = this.state.serverTime || {};
    document.getElementById("shift-live-badge").textContent = `⏰ Ca hiện tại: ${st.inferred_ca || "--"} (${st.time || "--:--"})`;
    document.getElementById("shift-live-date").textContent = st.date || "";
    document.getElementById("stat-open-count").textContent = this.state.openSessions.length;
    document.getElementById("stat-emp-count").textContent = this.state.employees.length;

    const lowCount = this.state.materials.filter((m) => m.stock <= 0 || (m.min_stock > 0 && m.stock <= m.min_stock)).length;
    document.getElementById("stat-low-stock").textContent = lowCount;

    // Open sessions
    const badge = document.getElementById("open-sessions-badge");
    badge.textContent = `${this.state.openSessions.length} phiên`;
    const listEl = document.getElementById("open-sessions-list");

    if (!this.state.openSessions.length) {
      listEl.innerHTML = `<p class="empty-text">Chưa có nhân viên nào đang trong ca.</p>`;
    } else {
      listEl.innerHTML = this.state.openSessions
        .map(
          (s) => `
          <div class="session-item">
            <div class="session-info">
              <strong>👤 ${esc(s.nickname)}</strong>
              <span>${esc(s.shift_type)} (${esc(s.ca || "")}) • Vào lúc ${esc(s.checkin_time)}</span>
            </div>
            <button class="btn btn-danger btn-sm" onclick="App.submitCheckout('${esc(s.nickname)}', '${esc(s.shift_type)}')">
              📤 Check Out
            </button>
          </div>`
        )
        .join("");
    }

    this.renderCheckinEmployees();
  },

  setCheckinType(type) {
    haptic("light");
    this.state.checkinType = type;
    document.querySelectorAll("#ci-shift-type .seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === type);
    });
    const caWrapper = document.getElementById("ci-ca-wrapper");
    if (type === "Ca Gãy") {
      this.state.checkinCa = "Tối";
      caWrapper.classList.add("hidden");
    } else {
      caWrapper.classList.remove("hidden");
    }
  },

  setCheckinCa(ca) {
    this.state.checkinCa = ca;
    document.querySelectorAll("#ci-ca-select .seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === ca);
    });
  },

  renderCheckinEmployees() {
    const q = stripAccents(document.getElementById("ci-emp-search")?.value || "");
    const grid = document.getElementById("ci-emp-grid");
    const filtered = this.state.employees.filter(
      (e) => !q || stripAccents(e.nickname).includes(q) || stripAccents(e.full_name).includes(q)
    );
    if (!filtered.length) {
      grid.innerHTML = `<p class="empty-text" style="grid-column: span 2;">Không tìm thấy nhân viên.</p>`;
      return;
    }
    grid.innerHTML = filtered
      .map((e) => {
        const isSel = this.state.checkinEmp === e.nickname;
        return `
        <button type="button" class="emp-chip ${isSel ? "selected" : ""}" onclick="App.selectCheckinEmp('${esc(e.nickname)}')">
          <span>${esc(e.nickname)}</span>
          <span>${isSel ? "✅" : ""}</span>
        </button>`;
      })
      .join("");
  },

  selectCheckinEmp(nickname) {
    haptic("light");
    this.state.checkinEmp = nickname;
    localStorage.setItem("sober_my_nickname", nickname);
    this.renderCheckinEmployees();
  },

  async submitCheckin() {
    const nickname = this.state.checkinEmp;
    if (!nickname) {
      this.toast("⚠️ Vui lòng chạm chọn tên của bạn!");
      return;
    }
    const btn = document.getElementById("btn-submit-checkin");
    btn.disabled = true;
    btn.textContent = "⏳ Đang ghi nhận Check-in...";
    try {
      const res = await this.api("/api/checkin", {
        method: "POST",
        body: {
          nickname,
          shift_type: this.state.checkinType,
          ca: this.state.checkinCa,
        },
      });
      haptic("success");
      this.state.openSessions = res.open_sessions || [];
      this.renderAttendance();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "📥 Xác Nhận Check In";
    }
  },

  async submitCheckout(nickname, shiftType) {
    haptic("light");
    try {
      const res = await this.api("/api/checkout", {
        method: "POST",
        body: { nickname, shift_type: shiftType },
      });
      haptic("success");
      this.state.openSessions = res.open_sessions || [];
      this.renderAttendance();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    }
  },

  // ==================== 2. INVENTORY ====================

  renderInventoryGroups() {
    const el = document.getElementById("inv-group-pills");
    const pills = [
      { name: "ALL", label: "📦 Tất cả" },
      ...this.state.materialGroups.map((g) => ({ name: g.name, label: `${g.icon} ${g.name}` })),
    ];
    el.innerHTML = pills
      .map(
        (p) => `
      <button type="button" class="group-pill ${this.state.selectedInvGroup === p.name ? "active" : ""}"
        onclick="App.selectInvGroup('${esc(p.name)}')">
        ${esc(p.label)}
      </button>`
      )
      .join("");
  },

  selectInvGroup(grp) {
    haptic("light");
    this.state.selectedInvGroup = grp;
    this.renderInventoryGroups();
    this.renderInventoryList();
  },

  renderInventoryList() {
    const q = stripAccents(document.getElementById("inv-search-input")?.value || "");
    const grp = this.state.selectedInvGroup;
    const list = document.getElementById("inv-materials-list");

    const filtered = this.state.materials.filter((m) => {
      if (grp !== "ALL" && m.group !== grp) return false;
      if (q && !stripAccents(m.name).includes(q) && !stripAccents(m.group).includes(q)) return false;
      return true;
    });

    if (!filtered.length) {
      list.innerHTML = `<div class="card"><p class="empty-text">Không có nguyên vật liệu phù hợp.</p></div>`;
      return;
    }

    list.innerHTML = filtered
      .map((m) => {
        const qty = this.state.cart[m.name] || 0;
        const stockCls = m.stock <= 0 ? "stock-out" : m.min_stock > 0 && m.stock <= m.min_stock ? "stock-low" : "stock-ok";
        const unitStr = m.unit ? ` ${esc(m.unit)}` : "";
        return `
        <div class="material-item">
          <div class="mat-meta">
            <strong>${esc(m.name)}</strong>
            <span>${esc(m.group)} • Tồn: <b class="${stockCls}">${m.stock}${unitStr}</b></span>
          </div>
          <div class="qty-control">
            <button type="button" class="qty-btn" onclick="App.adjustCart('${esc(m.name)}', -1)">−</button>
            <input type="number" step="any" min="0" class="qty-input" value="${qty || ""}" placeholder="0"
              onchange="App.setCartQty('${esc(m.name)}', this.value)" />
            <button type="button" class="qty-btn" onclick="App.adjustCart('${esc(m.name)}', 1)">+</button>
          </div>
        </div>`;
      })
      .join("");

    this.renderCartBar();
  },

  adjustCart(name, delta) {
    haptic("light");
    const cur = parseFloat(this.state.cart[name] || 0);
    const next = Math.max(0, Math.round((cur + delta) * 100) / 100);
    if (next <= 0) delete this.state.cart[name];
    else this.state.cart[name] = next;
    this.renderInventoryList();
  },

  setCartQty(name, val) {
    const num = parseFloat(String(val).replace(",", "."));
    if (!num || num <= 0) delete this.state.cart[name];
    else this.state.cart[name] = Math.round(num * 100) / 100;
    this.renderInventoryList();
  },

  clearCart() {
    this.state.cart = {};
    this.renderInventoryList();
  },

  renderCartBar() {
    const entries = Object.entries(this.state.cart).filter(([, q]) => q > 0);
    const bar = document.getElementById("inv-cart-bar");
    if (!entries.length) {
      bar.classList.add("hidden");
      return;
    }
    bar.classList.remove("hidden");
    document.getElementById("cart-count-text").textContent = `📦 Đã chọn ${entries.length} món cần lấy`;
    document.getElementById("cart-preview-text").textContent = entries
      .slice(0, 3)
      .map(([n, q]) => `${n} (x${q})`)
      .join(", ");
  },

  async submitCartExport() {
    const items = Object.entries(this.state.cart)
      .filter(([, q]) => q > 0)
      .map(([name, qty]) => ({ name, qty }));
    if (!items.length) return;

    try {
      const actor = this.state.checkinEmp || this.state.user?.first_name || "Nhân viên";
      const res = await this.api("/api/inventory/export", {
        method: "POST",
        body: { items, actor_name: actor },
      });
      haptic("success");
      this.state.materials = res.materials || this.state.materials;
      this.state.cart = {};
      this.renderInventoryList();
      this.renderAttendance();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    }
  },

  async parseSmartInventory() {
    const text = document.getElementById("inv-smart-text").value.trim();
    if (!text) {
      this.toast("⚠️ Vui lòng nhập danh sách món cần lấy!");
      return;
    }
    try {
      const res = await this.api("/api/inventory/smart-parse", {
        method: "POST",
        body: { text },
      });
      this.state.smartExportState = {
        confirmed: res.confirmed || [],
        ambiguous: res.ambiguous || [],
        not_found: res.not_found || [],
      };
      this.renderSmartExportStep();
    } catch (err) {
      this.toast(err.message);
    }
  },

  renderSmartExportStep() {
    const box = document.getElementById("inv-smart-result");
    const st = this.state.smartExportState;
    if (!st) {
      box.classList.add("hidden");
      return;
    }
    box.classList.remove("hidden");

    if (st.ambiguous.length > 0) {
      const amb = st.ambiguous[0];
      box.innerHTML = `
        <div class="card-header"><h2>❓ Chọn đúng món cho "${esc(amb.query)}" (SL: ${amb.qty})</h2></div>
        <div class="chip-grid">
          ${amb.candidates
            .map(
              (c, idx) => `
            <button class="emp-chip" onclick="App.resolveSmartAmbiguous(${idx})">
              <span>${esc(c.name)} (Tồn: ${c.stock})</span>
            </button>`
            )
            .join("")}
        </div>
        <button class="btn btn-ghost btn-block mt-8" onclick="App.resolveSmartAmbiguous(-1)">⏭ Bỏ qua món này</button>
      `;
      return;
    }

    if (!st.confirmed.length) {
      box.innerHTML = `<p class="empty-text">❌ Không tìm thấy món nào khớp (${esc(st.not_found.join(", "))}).</p>`;
      return;
    }

    box.innerHTML = `
      <div class="card-header"><h2>📋 Xác Nhận Xuất Kho (${st.confirmed.length} món)</h2></div>
      ${st.confirmed
        .map(
          (item) => `
        <div class="list-row">
          <span><b>${esc(item.name)}</b></span>
          <span>Lấy: <b>${item.qty} ${esc(item.unit || "")}</b> (Tồn: ${item.stock})</span>
        </div>`
        )
        .join("")}
      ${st.not_found.length ? `<p class="text-xs mt-8">❓ Không khớp: ${esc(st.not_found.join(", "))}</p>` : ""}
      <button class="btn btn-primary btn-block mt-12" onclick="App.confirmSmartExport()">✅ Xác Nhận Xuất Kho Ngay</button>
    `;
  },

  resolveSmartAmbiguous(idx) {
    const st = this.state.smartExportState;
    if (!st || !st.ambiguous.length) return;
    const current = st.ambiguous.shift();
    if (idx >= 0 && current.candidates[idx]) {
      const c = current.candidates[idx];
      st.confirmed.push({
        name: c.name,
        qty: current.qty,
        stock: c.stock,
        unit: c.unit || "",
      });
    }
    this.renderSmartExportStep();
  },

  async confirmSmartExport() {
    const st = this.state.smartExportState;
    if (!st || !st.confirmed.length) return;
    try {
      const actor = this.state.checkinEmp || this.state.user?.first_name || "Nhân viên";
      const res = await this.api("/api/inventory/export", {
        method: "POST",
        body: { items: st.confirmed, actor_name: actor },
      });
      haptic("success");
      this.state.materials = res.materials || this.state.materials;
      this.state.smartExportState = null;
      document.getElementById("inv-smart-text").value = "";
      document.getElementById("inv-smart-result").classList.add("hidden");
      this.renderInventoryList();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    }
  },

  // ==================== 3. REWARDS, REVENUE & ENDSHIFT ====================

  renderRewardBalances() {
    const q = stripAccents(document.getElementById("rew-search")?.value || "");
    const el = document.getElementById("rew-balances-list");
    const sorted = [...this.state.employees]
      .filter((e) => !q || stripAccents(e.nickname).includes(q))
      .sort((a, b) => (b.balance || 0) - (a.balance || 0));

    if (!sorted.length) {
      el.innerHTML = `<p class="empty-text">Chưa có dữ liệu nhân viên.</p>`;
      return;
    }

    el.innerHTML = sorted
      .map(
        (e) => `
      <div class="reward-item">
        <div>
          <strong>${e.balance > 0 ? "🎁" : "⬜"} ${esc(e.nickname)}</strong>
          <div class="text-xs">Số dư: <b>${e.balance} ly thưởng</b></div>
        </div>
        <button class="btn ${e.balance > 0 ? "btn-primary" : "btn-ghost"} btn-sm"
          ${e.balance <= 0 ? "disabled" : ""}
          onclick="App.confirmUseReward('${esc(e.nickname)}', ${e.balance})">
          🥤 Dùng 1 ly
        </button>
      </div>`
      )
      .join("");
  },

  confirmUseReward(nickname, balance) {
    this.openModal(
      "🥤 Xác nhận dùng ly thưởng",
      `
      <p class="mb-12">Bạn chắc chắn muốn trừ <b>1 ly thưởng</b> của <b>${esc(nickname)}</b>? (Hiện còn ${balance} ly)</p>
      <div class="row-gap">
        <button class="btn btn-ghost" onclick="App.closeModal()">Hủy</button>
        <button class="btn btn-primary" onclick="App.submitUseReward('${esc(nickname)}')">✅ Dùng ngay!</button>
      </div>`
    );
  },

  async submitUseReward(nickname) {
    this.closeModal();
    try {
      const res = await this.api("/api/rewards/use", {
        method: "POST",
        body: { nickname },
      });
      haptic("success");
      this.state.employees = res.employees || this.state.employees;
      this.renderAll();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    }
  },

  renderRewardRequestGrid() {
    const grid = document.getElementById("rew-req-grid");
    grid.innerHTML = this.state.employees
      .map((e) => {
        const sel = !!this.state.rewardReqSelected[e.nickname];
        return `
        <button type="button" class="emp-chip ${sel ? "selected" : ""}" onclick="App.toggleRewardReqEmp('${esc(e.nickname)}')">
          <span>${esc(e.nickname)}</span>
          <span>${sel ? "✅" : ""}</span>
        </button>`;
      })
      .join("");
  },

  toggleRewardReqEmp(nickname) {
    haptic("light");
    this.state.rewardReqSelected[nickname] = !this.state.rewardReqSelected[nickname];
    this.renderRewardRequestGrid();
  },

  async submitRewardRequest() {
    const selected = Object.entries(this.state.rewardReqSelected)
      .filter(([, v]) => v)
      .map(([k]) => k);
    if (!selected.length) {
      this.toast("⚠️ Bạn chưa chọn nhân viên nào!");
      return;
    }
    try {
      const res = await this.api("/api/rewards/request", {
        method: "POST",
        body: { employees: selected },
      });
      haptic("success");
      this.state.rewardReqSelected = {};
      if (res.employees) this.state.employees = res.employees;
      this.renderAll();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    }
  },

  setReportCa(ca) {
    this.state.reportCa = ca;
    document.querySelectorAll("#rpt-ca-select .seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === ca);
    });
  },

  renderReportEmpGrid() {
    const grid = document.getElementById("rpt-emp-grid");
    grid.innerHTML = this.state.employees
      .map((e) => {
        const sel = !!this.state.reportSelectedEmps[e.nickname];
        return `
        <button type="button" class="emp-chip ${sel ? "selected" : ""}" onclick="App.toggleReportEmp('${esc(e.nickname)}')">
          <span>${esc(e.nickname)}</span>
          <span>${sel ? "✅" : ""}</span>
        </button>`;
      })
      .join("");
    this.updateRevenuePreview();
  },

  toggleReportEmp(nickname) {
    haptic("light");
    this.state.reportSelectedEmps[nickname] = !this.state.reportSelectedEmps[nickname];
    this.renderReportEmpGrid();
  },

  updateRevenuePreview() {
    const count = Object.values(this.state.reportSelectedEmps).filter(Boolean).length;
    const raw = (document.getElementById("rpt-revenue-input")?.value || "").trim().toUpperCase();
    const banner = document.getElementById("rpt-reward-preview");

    let amount = 0;
    if (raw) {
      let s = raw.replace(/,/g, "");
      if (s.endsWith("M")) amount = parseFloat(s.slice(0, -1)) * 1_000_000;
      else if (s.endsWith("K")) amount = parseFloat(s.slice(0, -1)) * 1_000;
      else amount = parseFloat(s.replace(/\./g, ""));
    }

    const eligible = (count === 2 && amount >= 1_200_000) || (count >= 3 && amount >= 1_500_000);
    if (eligible) {
      banner.textContent = `🎉 Đạt chỉ tiêu thưởng! Mỗi bạn (${count} NV) sẽ được +1 ly thưởng.`;
    } else {
      banner.textContent = `Đã chọn ${count} NV • Chỉ tiêu thưởng: 2 NV ≥ 1.2M | ≥3 NV ≥ 1.5M`;
    }
  },

  async submitRevenueReport() {
    const selected = Object.entries(this.state.reportSelectedEmps)
      .filter(([, v]) => v)
      .map(([k]) => k);
    const revenue = document.getElementById("rpt-revenue-input").value.trim();
    const photoInput = document.getElementById("rpt-photo-input");

    if (!selected.length) {
      this.toast("⚠️ Vui lòng chọn nhân viên trong ca!");
      return;
    }
    if (!revenue) {
      this.toast("⚠️ Vui lòng nhập doanh thu ca!");
      return;
    }

    const btn = document.getElementById("btn-submit-report");
    btn.disabled = true;
    btn.textContent = "⏳ Đang lưu báo cáo...";

    try {
      const fd = new FormData();
      fd.append("employees", JSON.stringify(selected));
      fd.append("revenue", revenue);
      fd.append("ca", this.state.reportCa);
      if (photoInput.files && photoInput.files[0]) {
        fd.append("photo", photoInput.files[0]);
      }

      const res = await this.api("/api/reports/revenue", {
        method: "POST",
        body: fd,
      });
      haptic("success");
      this.state.reportSelectedEmps = {};
      document.getElementById("rpt-revenue-input").value = "";
      photoInput.value = "";
      if (res.employees) this.state.employees = res.employees;
      this.renderAll();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "📤 Lưu Báo Cáo Doanh Thu";
    }
  },

  setEndshiftCa(ca) {
    this.state.endshiftCa = ca;
    document.querySelectorAll("#ks-ca-select .seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === ca);
    });
  },

  setEndshiftRole(role) {
    this.state.endshiftRole = role;
    document.querySelectorAll("#ks-role-select .seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === role);
    });
    this.renderEndshiftChecklist();
  },

  renderEndshiftChecklist() {
    const box = document.getElementById("ks-checklist-box");
    if (!box) return;
    const role = this.state.endshiftRole || "Pha Chế";
    const items = (this.state.checklists && this.state.checklists[role]) || [];
    const checkedMap = this.state.checklistChecked[role] || {};

    if (!items.length) {
      box.innerHTML = `<p class="empty-text">Chưa có checklist cho bộ phận ${esc(role)}.</p>`;
      return;
    }

    const doneCount = items.filter((_, i) => !!checkedMap[i]).length;
    box.innerHTML = `
      <div class="text-xs mb-8">Tiến độ Checklist <b>${esc(role)}</b>: <b>${doneCount}/${items.length}</b> mục hoàn thành</div>
      ${items
        .map((text, idx) => {
          const isChecked = !!checkedMap[idx];
          return `
          <div class="checklist-item ${isChecked ? "checked" : ""}" onclick="App.toggleChecklistItem(${idx})">
            <input type="checkbox" ${isChecked ? "checked" : ""} onclick="event.stopPropagation(); App.toggleChecklistItem(${idx})" />
            <span>${esc(text)}</span>
          </div>`;
        })
        .join("")}
    `;
  },

  toggleChecklistItem(idx) {
    haptic("light");
    const role = this.state.endshiftRole || "Pha Chế";
    if (!this.state.checklistChecked[role]) {
      this.state.checklistChecked[role] = {};
    }
    this.state.checklistChecked[role][idx] = !this.state.checklistChecked[role][idx];
    this.renderEndshiftChecklist();
  },

  previewEndshiftPhotos() {
    const files = document.getElementById("ks-photos-input").files;
    const info = document.getElementById("ks-photos-preview");
    if (!files || !files.length) {
      info.textContent = "Chưa chọn ảnh nào.";
    } else {
      info.textContent = `📷 Đã chọn ${files.length} ảnh sẵn sàng gửi.`;
    }
  },

  async submitEndshiftPhotos() {
    const input = document.getElementById("ks-photos-input");
    if (!input.files || !input.files.length) {
      this.toast("⚠️ Vui lòng chọn ít nhất 1 ảnh kết ca!");
      return;
    }

    const role = this.state.endshiftRole || "Pha Chế";
    const items = (this.state.checklists && this.state.checklists[role]) || [];
    const checkedMap = this.state.checklistChecked[role] || {};
    const doneCount = items.filter((_, i) => !!checkedMap[i]).length;

    const btn = document.getElementById("btn-submit-endshift");
    btn.disabled = true;
    btn.textContent = `⏳ Đang tải lên ${input.files.length} ảnh...`;

    try {
      const fd = new FormData();
      fd.append("ca", this.state.endshiftCa);
      fd.append("role", role);
      if (this.state.myNickname) {
        fd.append("actor_name", `${this.state.myNickname} (${this.state.myRole || role})`);
      }
      if (items.length) {
        fd.append("checklist_summary", `${doneCount}/${items.length} mục (${role})`);
      }
      Array.from(input.files).forEach((file) => fd.append("photos", file));

      const res = await this.api("/api/endshift/upload", {
        method: "POST",
        body: fd,
      });
      haptic("success");
      input.value = "";
      this.state.checklistChecked[role] = {};
      this.renderEndshiftChecklist();
      this.previewEndshiftPhotos();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "📤 Gửi Checklist & Toàn Bộ Ảnh Kết Ca";
    }
  },

  // ── Petty Cash / Counter Expenses ─────────────────────────────────────────
  async submitPettyExpense() {
    const amountEl = document.getElementById("exp-amount-input");
    const reasonEl = document.getElementById("exp-reason-input");
    const amount = (amountEl?.value || "").trim();
    const reason = (reasonEl?.value || "").trim();
    if (!amount || !reason) {
      this.toast("⚠️ Vui lòng nhập số tiền và nội dung chi vặt!");
      return;
    }
    try {
      const res = await this.api("/api/expenses/add", {
        method: "POST",
        body: {
          nickname: this.state.myNickname || "Nhân viên",
          role: this.state.myRole || "Nhân viên",
          ca: this.state.reportCa || "Sáng",
          amount,
          reason,
        },
      });
      haptic("success");
      amountEl.value = "";
      reasonEl.value = "";
      this.state.pettyExpenses = res.petty_expenses || [];
      this.renderPettyExpenses();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    }
  },

  renderPettyExpenses() {
    const el = document.getElementById("petty-expenses-list");
    if (!el) return;
    const list = this.state.pettyExpenses || [];
    if (!list.length) {
      el.innerHTML = `<p class="empty-text">Chưa có khoản chi vặt nào gần đây.</p>`;
      return;
    }
    el.innerHTML = list
      .slice(0, 8)
      .map(
        (x) => `
      <div class="list-row">
        <div>
          <strong>💸 ${Number(x.amount || 0).toLocaleString("vi-VN")}đ — ${esc(x.reason)}</strong>
          <div class="text-xs">${esc(x.date)} ${esc(x.time)} • Ca ${esc(x.ca)} • Bởi: ${esc(x.nickname)}</div>
        </div>
      </div>`
      )
      .join("");
  },

  // ── Personal Profile, Leave Requests & Weekly Shift Schedule ──────────────
  populateEmployeeFeatureSelects() {
    const curNick = this.state.myNickname || (this.state.employees[0] && this.state.employees[0].nickname) || "";
    const opts = this.state.employees
      .map((e) => `<option value="${esc(e.nickname)}" ${e.nickname === curNick ? "selected" : ""}>${esc(e.nickname)}</option>`)
      .join("");

    ["personal-emp-select", "lv-emp-select", "sch-emp-select"].forEach((id) => {
      const sel = document.getElementById(id);
      if (sel) {
        const prev = sel.value;
        sel.innerHTML = opts;
        if (curNick) sel.value = curNick;
        else if (prev) sel.value = prev;
      }
    });

    this.loadMyScheduleGrid();
  },

  async loadPersonalSummary(forceNick) {
    const sel = document.getElementById("personal-emp-select");
    const nickname = forceNick || (sel && sel.value) || this.state.myNickname;
    const box = document.getElementById("personal-summary-box");
    const ciBox = document.getElementById("personal-checkins-list");
    if (!nickname || !box) return;

    box.innerHTML = `<p class="empty-text">⏳ Đang tải hồ sơ của ${esc(nickname)}...</p>`;
    try {
      const res = await this.api(`/api/personal/summary?nickname=${encodeURIComponent(nickname)}`);
      const s = res.summary || {};
      box.innerHTML = `
        <div class="salary-summary">
          <div>
            <div class="text-xs">Kỳ lương T${s.month}/${s.year}</div>
            <strong>${esc(s.period)}</strong>
          </div>
          <div>
            <div class="text-xs">Tổng giờ công (Gồm OT)</div>
            <strong>⏱ ${s.total_hours}h (${s.regular_hours}h + ${s.overtime_hours}h OT)</strong>
          </div>
          <div>
            <div class="text-xs">Mức lương & Tạm tính</div>
            <strong style="color:#34d399;">💰 ~${Number((s.estimated_pay_k || 0) * 1000).toLocaleString("vi-VN")}đ (${s.rate}k/h)</strong>
          </div>
          <div>
            <div class="text-xs">Ly thưởng & Đi muộn</div>
            <strong>🥤 ${s.balance} ly • ⚠️ Muộn ${s.late_count} lần</strong>
          </div>
        </div>
      `;

      const checkins = s.recent_checkins || [];
      if (ciBox) {
        ciBox.innerHTML = checkins.length
          ? checkins
              .map(
                (c) => `
              <div class="list-row">
                <div>
                  <strong>📅 ${esc(c.date)} • ${esc(c.checkin_time)} → ${esc(c.checkout_time)}</strong>
                  <div class="text-xs">${esc(c.note || "Đúng giờ")}</div>
                </div>
                <span class="badge">${esc(c.total_hours)}h</span>
              </div>`
              )
              .join("")
          : `<p class="empty-text">Chưa có lịch sử chấm công.</p>`;
      }
    } catch (err) {
      box.innerHTML = `<p class="empty-text">${esc(err.message)}</p>`;
    }
  },

  setLeaveType(type) {
    this.state.leaveType = type;
    document.querySelectorAll("#lv-type-select .seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === type);
    });
  },

  async submitLeaveRequest() {
    const nickname = document.getElementById("lv-emp-select")?.value || this.state.myNickname;
    const date = (document.getElementById("lv-date-input")?.value || "").trim();
    const ca = document.getElementById("lv-ca-select")?.value || "Sáng";
    const extra = (document.getElementById("lv-extra-input")?.value || "").trim();
    const reason = (document.getElementById("lv-reason-input")?.value || "").trim();

    if (!nickname || !reason) {
      this.toast("⚠️ Vui lòng chọn tên và nhập lý do!");
      return;
    }
    try {
      const res = await this.api("/api/requests/leave", {
        method: "POST",
        body: {
          nickname,
          role: this.state.myRole || "Nhân viên",
          type: this.state.leaveType || "late",
          date,
          ca,
          extra,
          reason,
        },
      });
      haptic("success");
      document.getElementById("lv-reason-input").value = "";
      document.getElementById("lv-extra-input").value = "";
      this.state.leaveRequests = res.leave_requests || [];
      this.renderLeaveHistory();
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    }
  },

  renderLeaveHistory() {
    const el = document.getElementById("lv-history-list");
    if (!el) return;
    const list = this.state.leaveRequests || [];
    if (!list.length) {
      el.innerHTML = `<p class="empty-text">Chưa có đơn xin phép nào.</p>`;
      return;
    }
    const typeMap = { late: "⏰ Xin đi muộn", leave: "🏖 Xin nghỉ", swap: "🔄 Đổi ca" };
    const statusMap = {
      pending: `<span class="badge" style="background:rgba(245,158,11,0.2);color:#fbbf24;">⏳ Chờ duyệt</span>`,
      approved: `<span class="badge badge-admin">✅ Đã duyệt</span>`,
      rejected: `<span class="badge" style="background:rgba(239,68,68,0.2);color:#f87171;">❌ Từ chối</span>`,
    };
    el.innerHTML = list
      .slice(0, 10)
      .map(
        (r) => `
      <div class="list-row">
        <div>
          <strong>${typeMap[r.type] || "📝 Đơn"} — ${esc(r.nickname)} (${esc(r.date)} • Ca ${esc(r.ca)})</strong>
          <div class="text-xs">${esc(r.reason)} ${r.extra ? `• (${esc(r.extra)})` : ""}</div>
        </div>
        ${statusMap[r.status] || ""}
      </div>`
      )
      .join("");
  },

  loadMyScheduleGrid() {
    const nick = document.getElementById("sch-emp-select")?.value || this.state.myNickname;
    const saved = (this.state.shiftSchedules && nick && this.state.shiftSchedules[nick]) || null;
    const slots = (saved && saved.slots) || {};
    this.state.myScheduleSlots = JSON.parse(JSON.stringify(slots));
    const noteEl = document.getElementById("sch-note-input");
    if (noteEl) noteEl.value = (saved && saved.note) || "";
    this.renderScheduleGrid();
  },

  renderScheduleGrid() {
    const wrap = document.getElementById("sch-grid-container");
    if (!wrap) return;
    const days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
    const shifts = ["Sáng", "Chiều", "Tối"];
    const slots = this.state.myScheduleSlots || {};

    wrap.innerHTML = `
      <table class="schedule-table">
        <thead>
          <tr>
            <th>Ca / Thứ</th>
            ${days.map((d) => `<th>${d}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${shifts
            .map(
              (ca) => `
            <tr>
              <th>${ca}</th>
              ${days
                .map((d) => {
                  const active = Array.isArray(slots[d]) && slots[d].includes(ca);
                  return `<td>
                    <button type="button" class="sch-slot-btn ${active ? "active" : ""}" onclick="App.toggleScheduleSlot('${d}', '${ca}')">
                      ${active ? "✓" : "—"}
                    </button>
                  </td>`;
                })
                .join("")}
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
    `;
  },

  toggleScheduleSlot(day, ca) {
    haptic("light");
    if (!this.state.myScheduleSlots[day]) {
      this.state.myScheduleSlots[day] = [];
    }
    const arr = this.state.myScheduleSlots[day];
    const idx = arr.indexOf(ca);
    if (idx >= 0) arr.splice(idx, 1);
    else arr.push(ca);
    this.renderScheduleGrid();
  },

  async submitShiftSchedule() {
    const nickname = document.getElementById("sch-emp-select")?.value || this.state.myNickname;
    const note = (document.getElementById("sch-note-input")?.value || "").trim();
    if (!nickname) {
      this.toast("⚠️ Vui lòng chọn tên nhân viên!");
      return;
    }
    try {
      const res = await this.api("/api/schedule/register", {
        method: "POST",
        body: {
          nickname,
          role: this.state.myRole || "Nhân viên",
          slots: this.state.myScheduleSlots || {},
          note,
          week_label: "Tuần tới",
        },
      });
      haptic("success");
      this.state.shiftSchedules = res.shift_schedules || {};
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    }
  },

  // ── Recipe Book (Sổ tay Công thức Pha chế) ────────────────────────────────
  renderRecipesList() {
    const el = document.getElementById("recipes-list");
    if (!el) return;
    const q = stripAccents(document.getElementById("recipe-search-input")?.value || "");
    const isAdmin = !!(this.state.user && this.state.user.is_admin);
    const list = (this.state.recipes || []).filter(
      (r) => !q || stripAccents(r.name).includes(q) || stripAccents(r.group).includes(q) || stripAccents(r.ingredients).includes(q)
    );

    if (!list.length) {
      el.innerHTML = `<div class="card"><p class="empty-text">Không tìm thấy công thức phù hợp.</p></div>`;
      return;
    }

    el.innerHTML = list
      .map(
        (r) => `
      <div class="recipe-card">
        <div class="recipe-header">
          <div>
            <div class="recipe-title">🍹 ${esc(r.name)}</div>
            <div class="text-xs">${esc(r.group)} • ${esc(r.size || "Size M")}</div>
          </div>
          ${
            isAdmin
              ? `<div class="row-gap" style="flex:0;">
                  <button class="btn btn-ghost btn-sm" onclick="App.openRecipeModal('${esc(r.id)}')">✏️</button>
                  <button class="btn btn-danger btn-sm" onclick="App.submitDeleteRecipe('${esc(r.id)}')">🗑</button>
                 </div>`
              : ""
          }
        </div>
        <div class="text-xs"><b>📌 Định lượng nguyên liệu:</b></div>
        <div class="recipe-block">${esc(r.ingredients)}</div>
        ${
          r.steps
            ? `<div class="text-xs mt-8"><b>🥣 Các bước pha:</b></div>
               <div class="recipe-block">${esc(r.steps)}</div>`
            : ""
        }
      </div>`
      )
      .join("");
  },

  openRecipeModal(recipeId) {
    const existing = (this.state.recipes || []).find((x) => x.id === recipeId) || {};
    this.openModal(
      recipeId ? `✏️ Sửa Công Thức: ${existing.name}` : "➕ Thêm Công Thức Mới",
      `
      <label class="field-label">Tên món</label>
      <input id="modal-rcp-name" class="input mb-8" value="${esc(existing.name || "")}" placeholder="VD: Trà Sữa Ô Long" />
      <div class="row-gap mb-8">
        <input id="modal-rcp-group" class="input" value="${esc(existing.group || "Cà Phê")}" placeholder="Nhóm món" />
        <input id="modal-rcp-size" class="input" value="${esc(existing.size || "Size M (500ml)")}" placeholder="Size ly" />
      </div>
      <label class="field-label">Định lượng nguyên liệu (mỗi dòng 1 nguyên liệu)</label>
      <textarea id="modal-rcp-ing" class="textarea mb-8" rows="4" placeholder="Cốt trà: 120ml\nSữa đặc: 30ml...">${esc(existing.ingredients || "")}</textarea>
      <label class="field-label">Các bước thực hiện</label>
      <textarea id="modal-rcp-steps" class="textarea mb-12" rows="3" placeholder="1. Khuấy đều...\n2. Thêm đá...">${esc(existing.steps || "")}</textarea>
      <button class="btn btn-primary btn-block" onclick="App.submitSaveRecipe('${esc(existing.id || "")}')">💾 Lưu Công Thức</button>
      `
    );
  },

  async submitSaveRecipe(id) {
    const name = (document.getElementById("modal-rcp-name")?.value || "").trim();
    const group = (document.getElementById("modal-rcp-group")?.value || "").trim();
    const size = (document.getElementById("modal-rcp-size")?.value || "").trim();
    const ingredients = (document.getElementById("modal-rcp-ing")?.value || "").trim();
    const steps = (document.getElementById("modal-rcp-steps")?.value || "").trim();
    if (!name || !ingredients) {
      this.toast("⚠️ Vui lòng nhập Tên món và Định lượng!");
      return;
    }
    this.closeModal();
    try {
      const res = await this.api("/api/admin/recipes/save", {
        method: "POST",
        body: { id, name, group, size, ingredients, steps },
      });
      haptic("success");
      this.state.recipes = res.recipes || [];
      this.renderRecipesList();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  async submitDeleteRecipe(id) {
    try {
      const res = await this.api("/api/admin/recipes/delete", {
        method: "POST",
        body: { id },
      });
      haptic("success");
      this.state.recipes = res.recipes || [];
      this.renderRecipesList();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  // ==================== 4. FEEDBACK ====================

  async submitFeedback() {
    const input = document.getElementById("feedback-input");
    const message = input.value.trim();
    if (!message) {
      this.toast("⚠️ Vui lòng nhập nội dung góp ý!");
      return;
    }
    try {
      const res = await this.api("/api/feedback", {
        method: "POST",
        body: { message },
      });
      haptic("success");
      input.value = "";
      this.toast(res.message);
    } catch (err) {
      haptic("error");
      this.toast(err.message);
    }
  },

  // ==================== 5. ADMIN DASHBOARD ====================

  populateAdminSelects() {
    const empOpts = this.state.employees
      .map((e) => `<option value="${esc(e.nickname)}">${esc(e.nickname)} (${e.rate}k/h)</option>`)
      .join("");
    const modSel = document.getElementById("adm-sal-mod-emp");
    const otSel = document.getElementById("adm-ot-emp");
    if (modSel) modSel.innerHTML = empOpts;
    if (otSel) otSel.innerHTML = empOpts;

    const matOpts = this.state.materials
      .map((m) => `<option value="${esc(m.name)}">${esc(m.name)} (Tồn: ${m.stock} ${esc(m.unit || "")})</option>`)
      .join("");
    const impSel = document.getElementById("adm-inv-import-name");
    if (impSel) impSel.innerHTML = matOpts;
  },

  async loadAdminOverview() {
    try {
      const res = await this.api("/api/admin/overview");
      this.state.adminOverview = res;
      this.renderAdminOverview();
    } catch (err) {
      this.toast(err.message);
    }
  },

  renderAdminOverview() {
    const ov = this.state.adminOverview;
    if (!ov) return;

    const pendingRewards = ov.pending_rewards || [];
    const pendingLeaves = (ov.leave_requests || []).filter((x) => x.status === "pending");
    const totalPending = pendingRewards.length + pendingLeaves.length;

    // Badge on bottom nav
    const navBadge = document.getElementById("nav-admin-badge");
    if (totalPending > 0) {
      navBadge.textContent = totalPending;
      navBadge.classList.remove("hidden");
    } else {
      navBadge.classList.add("hidden");
    }

    // 0. Analytics Dashboard (Revenue by Shift & Petty Expenses)
    const anaEl = document.getElementById("adm-analytics-box");
    if (anaEl && ov.analytics) {
      const ana = ov.analytics;
      const byCa = ana.revenue_by_ca || { Sáng: 0, Chiều: 0, Tối: 0 };
      const maxCa = Math.max(1, byCa["Sáng"] || 0, byCa["Chiều"] || 0, byCa["Tối"] || 0);
      const netEst = Math.max(0, (ana.total_recent_revenue || 0) - (ana.total_petty_expenses || 0));

      anaEl.innerHTML = `
        <div class="salary-summary mb-12">
          <div>
            <div class="text-xs">Tổng DT các ca gần nhất</div>
            <strong style="color:#34d399;">💰 ${Number(ana.total_recent_revenue || 0).toLocaleString("vi-VN")}đ</strong>
          </div>
          <div>
            <div class="text-xs">Tổng chi vặt tại quầy</div>
            <strong style="color:#f87171;">💸 ${Number(ana.total_petty_expenses || 0).toLocaleString("vi-VN")}đ</strong>
          </div>
          <div>
            <div class="text-xs">Thực thu sau chi vặt</div>
            <strong style="color:#fbbf24;">✨ ${Number(netEst).toLocaleString("vi-VN")}đ</strong>
          </div>
          <div>
            <div class="text-xs">Tổng giờ OT trong kỳ</div>
            <strong>⏰ ${(ov.overtime && ov.overtime.total_hours) || 0}h</strong>
          </div>
        </div>
        ${["Sáng", "Chiều", "Tối"]
          .map((ca) => {
            const val = byCa[ca] || 0;
            const pct = Math.round((val / maxCa) * 100);
            return `
            <div class="chart-bar-row">
              <div class="chart-bar-label">
                <span>Ca ${ca}</span>
                <b>${Number(val).toLocaleString("vi-VN")}đ</b>
              </div>
              <div class="chart-bar-track">
                <div class="chart-bar-fill" style="width:${pct}%"></div>
              </div>
            </div>`;
          })
          .join("")}
      `;
    }

    // 0.1 Leave / Late / Swap Requests
    const lvEl = document.getElementById("adm-leave-requests-list");
    if (lvEl) {
      const allLeaves = ov.leave_requests || [];
      const typeMap = { late: "⏰ Xin đi muộn", leave: "🏖 Xin nghỉ", swap: "🔄 Đổi ca" };
      if (!allLeaves.length) {
        lvEl.innerHTML = `<p class="empty-text">Chưa có đơn xin đi muộn / nghỉ phép / đổi ca nào.</p>`;
      } else {
        lvEl.innerHTML = allLeaves
          .slice(0, 12)
          .map((r) => {
            const isPend = r.status === "pending";
            return `
            <div class="list-row">
              <div>
                <strong>${typeMap[r.type] || "📝 Đơn"} — ${esc(r.nickname)} (${esc(r.role || "")})</strong>
                <div class="text-xs">📅 ${esc(r.date)} • Ca ${esc(r.ca)} ${r.extra ? `• ${esc(r.extra)}` : ""}</div>
                <div class="text-xs">💬 ${esc(r.reason)}</div>
              </div>
              ${
                isPend
                  ? `<div class="row-gap" style="flex:0;">
                      <button class="btn btn-success btn-sm" onclick="App.decideLeaveRequest('${esc(r.id)}', true)">Duyệt</button>
                      <button class="btn btn-danger btn-sm" onclick="App.decideLeaveRequest('${esc(r.id)}', false)">Từ chối</button>
                     </div>`
                  : `<span class="badge">${r.status === "approved" ? "✅ Đã duyệt" : "❌ Từ chối"}</span>`
              }
            </div>`;
          })
          .join("");
      }
    }

    // 0.2 Weekly Shift Schedules Summary
    const schEl = document.getElementById("adm-schedules-list");
    if (schEl) {
      const entries = Object.values(ov.shift_schedules || {});
      if (!entries.length) {
        schEl.innerHTML = `<p class="empty-text">Chưa có nhân viên nào đăng ký lịch ca tuần tới.</p>`;
      } else {
        schEl.innerHTML = entries
          .map((e) => {
            const slotSummary = Object.entries(e.slots || {})
              .filter(([, arr]) => Array.isArray(arr) && arr.length > 0)
              .map(([d, arr]) => `<b>${esc(d)}:</b> ${esc(arr.join(", "))}`)
              .join(" | ");
            return `
            <div class="list-row">
              <div>
                <strong>👤 ${esc(e.nickname)} (${esc(e.role || "NV")})</strong>
                <div class="text-xs">${slotSummary || "Chưa chọn ca"}</div>
                ${e.note ? `<div class="text-xs">📝 ${esc(e.note)}</div>` : ""}
              </div>
              <span class="text-xs">${esc(e.updated_at || "")}</span>
            </div>`;
          })
          .join("");
      }
    }

    // 1. Pending rewards
    const pendCard = document.getElementById("adm-pending-rewards-card");
    const pendList = document.getElementById("adm-pending-rewards-list");
    if (!pendingRewards.length) {
      pendCard.classList.add("hidden");
    } else {
      pendCard.classList.remove("hidden");
      pendList.innerHTML = pendingRewards
        .map(
          (r) => `
        <div class="list-row">
          <div>
            <strong>Ca ${esc(r.ca)}: ${esc((r.employees || []).join(", "))}</strong>
            <div class="text-xs">Người gửi: ${esc(r.sender)}</div>
          </div>
          <div class="row-gap" style="flex:0;">
            <button class="btn btn-success btn-sm" onclick="App.decideReward('${esc(r.id)}', true)">✅ Duyệt</button>
            <button class="btn btn-danger btn-sm" onclick="App.decideReward('${esc(r.id)}', false)">❌ Từ chối</button>
          </div>
        </div>`
        )
        .join("");
    }

    // 2. Check-in today
    const ciEl = document.getElementById("adm-checkin-today-list");
    const ciList = ov.checkin_today || [];
    if (!ciList.length) {
      ciEl.innerHTML = `<p class="empty-text">Hôm nay chưa có lượt check-in nào.</p>`;
    } else {
      ciEl.innerHTML = ciList
        .map((r) => {
          const isOpen = !r.checkout_time;
          return `
          <div class="list-row">
            <div>
              <strong>👤 ${esc(r.nickname)} ${isOpen ? "🟡 Đang ca" : `✅ Ra (${esc(r.total_hours)}h)`}</strong>
              <div class="text-xs">📥 ${esc(r.checkin_time)} → 📤 ${esc(r.checkout_time || "—")}</div>
              <div class="text-xs">${esc(r.note)}</div>
            </div>
            ${
              isOpen
                ? `<button class="btn btn-danger btn-sm" onclick="App.submitCheckout('${esc(r.nickname)}', '')">Chốt Ra</button>`
                : ""
            }
          </div>`;
        })
        .join("");
    }

    // 3. Late stats
    const lateEl = document.getElementById("adm-late-stats-list");
    const lates = ov.late_stats || [];
    if (!lates.length) {
      lateEl.innerHTML = `<p class="empty-text">✅ Không có trường hợp đi muộn nào trong tháng ${esc(ov.month_year)}!</p>`;
    } else {
      lateEl.innerHTML = lates
        .map((l) => {
          const decided =
            l.note.toLowerCase().includes("báo trước");
          return `
          <div class="list-row">
            <div>
              <strong>👤 ${esc(l.nickname)} • ${esc(l.date)} (${esc(l.checkin_time)})</strong>
              <div class="text-xs">${esc(l.note)}</div>
            </div>
            ${
              !decided
                ? `<div class="row-gap" style="flex:0;">
                    <button class="btn btn-success btn-sm" onclick="App.markLate('${esc(l.nickname)}', '${esc(l.date)}', true)">Báo trước</button>
                    <button class="btn btn-danger btn-sm" onclick="App.markLate('${esc(l.nickname)}', '${esc(l.date)}', false)">K.Báo</button>
                   </div>`
                : ""
            }
          </div>`;
        })
        .join("");
    }

    // 4. Overtime summary
    const otEl = document.getElementById("adm-ot-summary");
    if (otEl && ov.overtime) {
      const entries = Object.entries(ov.overtime.summary || {});
      otEl.innerHTML = `
        <div class="text-xs mb-8">📅 Kỳ: ${esc(ov.overtime.period)} • Tổng: <b>${ov.overtime.total_hours}h</b></div>
        ${
          entries.length
            ? entries
                .map(([n, h]) => `<div class="list-row"><span>${esc(n)}</span><b>${h}h</b></div>`)
                .join("")
            : `<p class="empty-text">Chưa có giờ làm thêm trong kỳ này.</p>`
        }
      `;
    }

    // 5. Staff list & Recent reports
    this.renderAdminEmployees();
    this.renderAdminRecentReports(ov.recent_reports || []);

    // 6. Super admin list
    const supEl = document.getElementById("adm-super-list");
    if (supEl && ov.admin_ids) {
      supEl.innerHTML = ov.admin_ids.length
        ? ov.admin_ids.map((id) => `<div class="list-row"><span>🛡 Admin phụ ID</span><code>${id}</code></div>`).join("")
        : `<p class="empty-text">Chưa có Admin phụ nào.</p>`;
    }
  },

  async decideLeaveRequest(id, approve) {
    try {
      const res = await this.api("/api/admin/requests/leave-decide", {
        method: "POST",
        body: { id, approve },
      });
      haptic("success");
      this.state.leaveRequests = res.leave_requests || [];
      this.renderLeaveHistory();
      await this.loadAdminOverview();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  async decideReward(requestId, approve) {
    try {
      const res = await this.api("/api/admin/rewards/decide", {
        method: "POST",
        body: { request_id: requestId, approve },
      });
      haptic("success");
      this.toast(res.message);
      await this.loadAdminOverview();
    } catch (err) {
      this.toast(err.message);
    }
  },

  async markLate(nickname, dateStr, reported) {
    try {
      const res = await this.api("/api/admin/late/mark", {
        method: "POST",
        body: { nickname, date: dateStr, reported },
      });
      haptic("success");
      this.toast(res.message);
      await this.loadAdminOverview();
    } catch (err) {
      this.toast(err.message);
    }
  },

  async submitAnnouncement() {
    const el = document.getElementById("adm-announce-text");
    const message = el.value.trim();
    if (!message) {
      this.toast("⚠️ Vui lòng nhập nội dung thông báo!");
      return;
    }
    try {
      const res = await this.api("/api/admin/announce", {
        method: "POST",
        body: { message },
      });
      haptic("success");
      el.value = "";
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  // ── Salary & OT ──

  async loadAdminSalary() {
    const sel = document.getElementById("adm-salary-month-select");
    let query = "";
    if (sel && sel.value) {
      const [m, y] = sel.value.split("-");
      query = `?month=${m}&year=${y}`;
    }
    try {
      const res = await this.api(`/api/admin/salary${query}`);
      this.state.salaryOptions = res.options || [];
      this.state.salaryData = res.salary || {};
      this.renderAdminSalary();
    } catch (err) {
      this.toast(err.message);
    }
  },

  renderAdminSalary() {
    const sel = document.getElementById("adm-salary-month-select");
    const sal = this.state.salaryData || {};
    const curVal = `${sal.month}-${sal.year}`;

    if (sel && this.state.salaryOptions.length) {
      sel.innerHTML = this.state.salaryOptions
        .map((o) => {
          const v = `${o.month}-${o.year}`;
          return `<option value="${v}" ${v === curVal ? "selected" : ""}>Tháng ${o.month}/${o.year} ${o.exists ? "" : "✨"}</option>`;
        })
        .join("");
    }

    const sumEl = document.getElementById("adm-salary-summary");
    sumEl.innerHTML = `
      <div>
        <span class="text-xs">Tổng giờ làm (${esc(sal.period_start || "")} - ${esc(sal.period_end || "")})</span>
        <div><b style="font-size:16px;">⏳ ${sal.total_hours || 0} giờ</b></div>
      </div>
      <div>
        <span class="text-xs">Tổng thực nhận toàn quán</span>
        <div><b style="font-size:16px; color:#34d399;">💵 ${sal.total_payout || 0}k</b></div>
      </div>
    `;

    const listEl = document.getElementById("adm-salary-list");
    const items = sal.items || [];
    if (!items.length) {
      listEl.innerHTML = `<p class="empty-text">Chưa có dữ liệu bảng lương.</p>`;
      return;
    }

    listEl.innerHTML = items
      .map(
        (item) => `
      <div class="list-row">
        <div>
          <strong>👤 ${esc(item.display_name)}</strong>
          <div class="text-xs">⏳ ${item.hours}h × ${item.rate}k = ${item.base_pay}k</div>
          <div class="text-xs">🎁 Thưởng: +${item.bonus}k | 💸 Ứng: -${item.advance}k</div>
        </div>
        <div style="text-align:right;">
          <strong style="color:#fbbf24; font-size:15px;">${item.total}k</strong>
          <div class="text-xs">Thực nhận</div>
        </div>
      </div>`
      )
      .join("");
  },

  setSalaryModType(type) {
    this.state.salaryModType = type;
    document.querySelectorAll("#adm-sal-mod-type .seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.val === type);
    });
  },

  async submitSalaryModifier() {
    const nickname = document.getElementById("adm-sal-mod-emp").value;
    const amount = document.getElementById("adm-sal-mod-amount").value.trim();
    const sal = this.state.salaryData || {};
    if (!nickname || !amount) {
      this.toast("⚠️ Vui lòng chọn nhân viên và nhập số tiền!");
      return;
    }
    try {
      const res = await this.api("/api/admin/salary/modifier", {
        method: "POST",
        body: {
          nickname,
          type: this.state.salaryModType,
          amount,
          month: sal.month,
          year: sal.year,
        },
      });
      haptic("success");
      document.getElementById("adm-sal-mod-amount").value = "";
      this.state.salaryData = res.salary || this.state.salaryData;
      this.renderAdminSalary();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  async submitAddOvertime() {
    const nickname = document.getElementById("adm-ot-emp").value;
    const hours = document.getElementById("adm-ot-hours").value.trim();
    if (!nickname || !hours) {
      this.toast("⚠️ Vui lòng chọn nhân viên và nhập số giờ!");
      return;
    }
    try {
      const res = await this.api("/api/admin/overtime/add", {
        method: "POST",
        body: { nickname, hours },
      });
      haptic("success");
      document.getElementById("adm-ot-hours").value = "";
      if (this.state.adminOverview) {
        this.state.adminOverview.overtime = res.overtime;
        this.renderAdminOverview();
      }
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  // ── Staff & Revenue Reports ──

  renderAdminEmployees() {
    const el = document.getElementById("adm-employees-list");
    if (!el) return;
    if (!this.state.employees.length) {
      el.innerHTML = `<p class="empty-text">Chưa có nhân viên nào.</p>`;
      return;
    }
    el.innerHTML = this.state.employees
      .map(
        (e) => `
      <div class="list-row">
        <div>
          <strong>👤 ${esc(e.nickname)}</strong>
          <div class="text-xs">💵 ${e.rate}k/giờ • 🎁 ${e.balance} ly</div>
        </div>
        <div class="row-gap" style="flex:0;">
          <button class="btn btn-ghost btn-sm" onclick="App.openEditSalaryRateModal('${esc(e.nickname)}', ${e.rate})">💵 Lương</button>
          <button class="btn btn-ghost btn-sm" onclick="App.openRenameEmpModal('${esc(e.nickname)}')">✏️ Tên</button>
          <button class="btn btn-ghost btn-sm" onclick="App.openRewardHistoryModal('${esc(e.nickname)}')">📜 Thưởng</button>
          <button class="btn btn-danger btn-sm" onclick="App.confirmRemoveEmployee('${esc(e.nickname)}')">🗑</button>
        </div>
      </div>`
      )
      .join("");
  },

  async submitAddEmployee() {
    const input = document.getElementById("adm-new-emp-name");
    const nickname = input.value.trim();
    if (!nickname) {
      this.toast("⚠️ Vui lòng nhập tên nhân viên!");
      return;
    }
    try {
      const res = await this.api("/api/admin/employee/add", {
        method: "POST",
        body: { nickname },
      });
      haptic("success");
      input.value = "";
      this.state.employees = res.employees || [];
      this.renderAll();
      this.renderAdminEmployees();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  openRenameEmpModal(oldNick) {
    this.openModal(
      `✏️ Đổi tên: ${oldNick}`,
      `
      <input type="text" id="modal-new-nick" class="input mb-12" value="${esc(oldNick)}" placeholder="Nhập tên mới..." />
      <button class="btn btn-primary btn-block" onclick="App.submitRenameEmployee('${esc(oldNick)}')">💾 Lưu Tên Mới</button>`
    );
  },

  async submitRenameEmployee(oldNickname) {
    const newNickname = document.getElementById("modal-new-nick").value.trim();
    if (!newNickname) return;
    this.closeModal();
    try {
      const res = await this.api("/api/admin/employee/rename", {
        method: "POST",
        body: { old_nickname: oldNickname, new_nickname: newNickname },
      });
      haptic("success");
      this.state.employees = res.employees || [];
      this.renderAll();
      this.renderAdminEmployees();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  openEditSalaryRateModal(nickname, currentRate) {
    this.openModal(
      `💵 Mức lương/giờ: ${nickname}`,
      `
      <input type="number" step="0.5" id="modal-new-rate" class="input mb-12" value="${currentRate}" placeholder="VD: 16, 18.5..." />
      <button class="btn btn-primary btn-block" onclick="App.submitEditSalaryRate('${esc(nickname)}')">💾 Cập Nhật Mức Lương</button>`
    );
  },

  async submitEditSalaryRate(nickname) {
    const rate = document.getElementById("modal-new-rate").value.trim();
    this.closeModal();
    try {
      const res = await this.api("/api/admin/employee/salary-rate", {
        method: "POST",
        body: { nickname, rate },
      });
      haptic("success");
      this.state.employees = res.employees || [];
      this.renderAll();
      this.renderAdminEmployees();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  async openRewardHistoryModal(nickname) {
    try {
      const res = await this.api(`/api/admin/employee/reward-history?nickname=${encodeURIComponent(nickname)}`);
      const records = res.records || [];
      this.openModal(
        `🎁 Lịch sử thưởng: ${nickname}`,
        records.length
          ? records
              .map(
                (r) => `
              <div class="list-row">
                <span>📅 ${esc(r.date)} — Ca ${esc(r.ca)}</span>
                <span class="text-xs">${esc(r.revenue ? Number(r.revenue).toLocaleString() + "đ" : "")}</span>
              </div>`
              )
              .join("")
          : `<p class="empty-text">Chưa có lịch sử báo cáo thưởng.</p>`
      );
    } catch (err) {
      this.toast(err.message);
    }
  },

  confirmRemoveEmployee(nickname) {
    this.openModal(
      "⚠️ Xác nhận xóa nhân viên",
      `
      <p class="mb-12">Bạn có chắc chắn muốn xóa <b>${esc(nickname)}</b> khỏi hệ thống?</p>
      <div class="row-gap">
        <button class="btn btn-ghost" onclick="App.closeModal()">Hủy</button>
        <button class="btn btn-danger" onclick="App.submitRemoveEmployee('${esc(nickname)}')">✅ Xóa</button>
      </div>`
    );
  },

  async submitRemoveEmployee(nickname) {
    this.closeModal();
    try {
      const res = await this.api("/api/admin/employee/remove", {
        method: "POST",
        body: { nickname },
      });
      haptic("success");
      this.state.employees = res.employees || [];
      this.renderAll();
      this.renderAdminEmployees();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  renderAdminRecentReports(reports) {
    const el = document.getElementById("adm-recent-reports-list");
    if (!el) return;
    if (!reports.length) {
      el.innerHTML = `<p class="empty-text">Chưa có báo cáo doanh thu nào.</p>`;
      return;
    }
    this._cachedRecentReports = reports;
    el.innerHTML = reports
      .map(
        (r, idx) => `
      <div class="list-row">
        <div>
          <strong>📅 ${esc(r.date)} — Ca ${esc(r.ca)}</strong>
          <div class="text-xs">👥 ${esc((r.employees || []).join(", "))}</div>
          <div class="text-xs">💰 Doanh thu: <b>${r.revenue ? Number(r.revenue).toLocaleString() + "đ" : "(chưa có)"}</b></div>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="App.openEditRevenueModal(${idx})">✏️ Sửa DT</button>
      </div>`
      )
      .join("");
  },

  openEditRevenueModal(idx) {
    const r = (this._cachedRecentReports || [])[idx];
    if (!r) return;
    this.openModal(
      `✏️ Sửa Doanh Thu (${r.date} Ca ${r.ca})`,
      `
      <p class="text-xs mb-8">Nhân viên: ${esc((r.employees || []).join(", "))}</p>
      <input type="text" id="modal-new-rev" class="input mb-12" value="${esc(r.revenue || "")}" placeholder="VD: 1500k, 2M..." />
      <button class="btn btn-primary btn-block" onclick="App.submitEditRevenue(${idx})">💾 Cập Nhật Doanh Thu</button>`
    );
  },

  async submitEditRevenue(idx) {
    const session = (this._cachedRecentReports || [])[idx];
    const newRevenue = document.getElementById("modal-new-rev").value.trim();
    this.closeModal();
    try {
      const res = await this.api("/api/admin/report/update-revenue", {
        method: "POST",
        body: { session, new_revenue: newRevenue },
      });
      haptic("success");
      this.renderAdminRecentReports(res.recent_reports || []);
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  // ── Admin Inventory ──

  async loadAdminInventory() {
    try {
      const res = await this.api("/api/inventory");
      this.state.materials = res.materials || [];
      this.populateAdminSelects();

      const alertsEl = document.getElementById("adm-inv-alerts-list");
      const alerts = [...(res.zero_stock || []), ...(res.low_stock || [])];
      const seen = new Set();
      const uniqueAlerts = alerts.filter((m) => {
        if (seen.has(m.name)) return false;
        seen.add(m.name);
        return true;
      });

      alertsEl.innerHTML = this.state.materials
        .map((m) => {
          const isAlert = m.stock <= 0 || (m.min_stock > 0 && m.stock <= m.min_stock);
          return `
          <div class="list-row">
            <div>
              <strong>${isAlert ? "🔴" : "✅"} ${esc(m.name)}</strong>
              <div class="text-xs">${esc(m.group)} • Tồn: <b>${m.stock} ${esc(m.unit || "")}</b> (Min: ${m.min_stock})</div>
            </div>
            <div class="row-gap" style="flex:0;">
              <button class="btn btn-ghost btn-sm" onclick="App.openEditMaterialModal('${esc(m.name)}')">✏️</button>
              <button class="btn btn-danger btn-sm" onclick="App.submitDeleteMaterial('${esc(m.name)}')">🗑</button>
            </div>
          </div>`;
        })
        .join("");

      const histEl = document.getElementById("adm-inv-history-list");
      const hist = res.history || [];
      histEl.innerHTML = hist.length
        ? hist
            .map(
              (h) => `
          <div class="list-row">
            <div>
              <strong>${h.type === "Nhập" ? "📥 +" : "📤 -"}${h.qty} ${esc(h.name)}</strong>
              <div class="text-xs">${esc(h.date)} • Bởi: ${esc(h.user)}</div>
            </div>
          </div>`
            )
            .join("")
        : `<p class="empty-text">Chưa có lịch sử xuất/nhập kho.</p>`;
    } catch (err) {
      this.toast(err.message);
    }
  },

  async submitImportStock() {
    const name = document.getElementById("adm-inv-import-name").value;
    const qty = document.getElementById("adm-inv-import-qty").value.trim();
    const note = document.getElementById("adm-inv-import-note").value.trim();
    if (!name || !qty) {
      this.toast("⚠️ Vui lòng chọn món và nhập số lượng!");
      return;
    }
    try {
      const res = await this.api("/api/inventory/import", {
        method: "POST",
        body: { name, qty, note },
      });
      haptic("success");
      document.getElementById("adm-inv-import-qty").value = "";
      document.getElementById("adm-inv-import-note").value = "";
      this.state.materials = res.materials || [];
      this.renderAll();
      await this.loadAdminInventory();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  async submitAddMaterial() {
    const name = document.getElementById("adm-mat-name").value.trim();
    const unit = document.getElementById("adm-mat-unit").value.trim();
    const min_stock = document.getElementById("adm-mat-min").value.trim() || "0";
    const price = document.getElementById("adm-mat-price").value.trim() || "0";
    const group = document.getElementById("adm-mat-group").value.trim() || "Khác";
    if (!name || !unit) {
      this.toast("⚠️ Vui lòng nhập Tên NVL và Đơn vị!");
      return;
    }
    try {
      const res = await this.api("/api/inventory/material/add", {
        method: "POST",
        body: { name, unit, min_stock, price, group },
      });
      haptic("success");
      document.getElementById("adm-mat-name").value = "";
      document.getElementById("adm-mat-unit").value = "";
      this.state.materials = res.materials || [];
      this.renderAll();
      await this.loadAdminInventory();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  openEditMaterialModal(name) {
    const m = this.state.materials.find((x) => x.name === name);
    if (!m) return;
    this.openModal(
      `✏️ Sửa NVL: ${m.name}`,
      `
      <label class="field-label">Đơn vị</label>
      <input type="text" id="modal-mat-unit" class="input" value="${esc(m.unit)}" />
      <label class="field-label">Tồn tối thiểu</label>
      <input type="number" step="any" id="modal-mat-min" class="input" value="${m.min_stock}" />
      <label class="field-label">Giá nhập</label>
      <input type="number" step="any" id="modal-mat-price" class="input mb-12" value="${m.price}" />
      <button class="btn btn-primary btn-block" onclick="App.submitUpdateMaterial('${esc(m.name)}')">💾 Lưu Thay Đổi</button>`
    );
  },

  async submitUpdateMaterial(name) {
    const unit = document.getElementById("modal-mat-unit").value.trim();
    const min_stock = document.getElementById("modal-mat-min").value.trim();
    const price = document.getElementById("modal-mat-price").value.trim();
    this.closeModal();
    try {
      const res = await this.api("/api/inventory/material/update", {
        method: "POST",
        body: { name, unit, min_stock, price },
      });
      haptic("success");
      this.state.materials = res.materials || [];
      this.renderAll();
      await this.loadAdminInventory();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  async submitDeleteMaterial(name) {
    try {
      const res = await this.api("/api/inventory/material/delete", {
        method: "POST",
        body: { name },
      });
      haptic("success");
      this.state.materials = res.materials || [];
      this.renderAll();
      await this.loadAdminInventory();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },

  async submitGrantAdmin() {
    const input = document.getElementById("adm-grant-id-input");
    const telegram_id = input.value.trim();
    if (!telegram_id) {
      this.toast("⚠️ Vui lòng nhập Telegram ID!");
      return;
    }
    try {
      const res = await this.api("/api/admin/grant-admin", {
        method: "POST",
        body: { telegram_id },
      });
      haptic("success");
      input.value = "";
      await this.loadAdminOverview();
      this.toast(res.message);
    } catch (err) {
      this.toast(err.message);
    }
  },
};

window.addEventListener("DOMContentLoaded", () => App.init());

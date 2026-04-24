/** Zepp PC Manager — Frontend */

const API = "/api";
let devices = [];
let currentAuthMac = null;
let currentNotifyMac = null;
let currentDndMac = null;
let currentGoalMac = null;

// ── Utilities ────────────────────────────────────────────────────────

function escHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
}

function safeAttr(str) {
    return (str || "").replace(/'/g, "\\'");
}

async function api(path, opts = {}) {
    const res = await fetch(API + path, {
        headers: { "Content-Type": "application/json", ...opts.headers },
        ...opts,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
}

function toast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add("hidden"), 3000);
}

function setLoading(btnId, textId, loading, text) {
    const btn = document.getElementById(btnId);
    const span = document.getElementById(textId);
    if (!btn) return;
    btn.disabled = loading;
    if (!span) return;
    if (loading) {
        span.innerHTML = `<span class="spinner inline-block mr-1"></span>${text}`;
    } else {
        span.textContent = text;
    }
}

// ── Tab switching ─────────────────────────────────────────────────────

function switchTab(tab) {
    const tabs = ["zepp", "manual"];
    tabs.forEach(t => {
        const btn = document.getElementById(`tab-${t}`);
        const panel = document.getElementById(`panel-${t}`);
        if (t === tab) {
            btn.className = btn.className.replace("tab-inactive", "tab-active");
            panel.classList.remove("hidden");
        } else {
            btn.className = btn.className.replace("tab-active", "tab-inactive");
            panel.classList.add("hidden");
        }
    });
}

// ── Zepp Cloud Login ──────────────────────────────────────────────────

async function submitZeppLogin() {
    const email = document.getElementById("zeppEmail").value.trim();
    const password = document.getElementById("zeppPassword").value;
    const region = document.getElementById("zeppRegion").value;

    const errEl = document.getElementById("zeppError");
    errEl.classList.add("hidden");

    if (!email || !password) {
        errEl.textContent = "请填写邮箱和密码";
        errEl.classList.remove("hidden");
        return;
    }

    setLoading("zeppLoginBtn", "zeppLoginBtnText", true, "登录中...");

    try {
        const res = await api("/zepp-login", {
            method: "POST",
            body: JSON.stringify({ email, password, region }),
        });

        document.getElementById("zeppPassword").value = "";
        const names = res.devices.map(d => d.name).join("、");
        toast(`已导入 ${res.count} 台设备：${names}。如手表在附近，点设备卡片上的"连接"即可完成认证。`);
        await loadDevices();
    } catch (e) {
        errEl.textContent = e.message;
        errEl.classList.remove("hidden");
    }

    setLoading("zeppLoginBtn", "zeppLoginBtnText", false, "登录并导入设备");
}

// ── Device Loading & Rendering ────────────────────────────────────────

async function loadDevices() {
    try {
        devices = await api("/devices");
        renderDevices();
    } catch (e) {
        console.error("Failed to load devices:", e);
    }
}

function renderDevices() {
    const container = document.getElementById("deviceList");
    const emptyState = document.getElementById("emptyState");

    if (devices.length === 0) {
        container.innerHTML = "";
        emptyState.classList.remove("hidden");
        return;
    }

    emptyState.classList.add("hidden");
    container.innerHTML = devices.map(d => renderDeviceCard(d)).join("");
}

function batteryColor(level) {
    if (level === null || level === undefined) return "text-gray-400";
    if (level > 50) return "text-green-600";
    if (level > 20) return "text-yellow-600";
    return "text-red-600";
}

function renderDeviceCard(d) {
    const mac = d.mac;
    const isAuthed = d.authenticated;
    const isConnected = d.connected;
    const battery = d.battery;

    const statusBadge = isAuthed
        ? `<span class="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full">已认证</span>`
        : isConnected
            ? `<span class="px-2 py-0.5 bg-yellow-100 text-yellow-700 text-xs rounded-full">已连接</span>`
            : `<span class="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full">未连接</span>`;

    const dataGrid = isAuthed ? `
        <div class="grid grid-cols-4 gap-3 mb-4">
            <div class="bg-blue-50 rounded-lg p-3 text-center">
                <div class="text-lg font-bold ${batteryColor(battery)}" id="battery-${escHtml(mac)}">
                    ${battery !== null && battery !== undefined ? battery + "%" : "--"}
                </div>
                <div class="text-xs text-gray-400 mt-0.5">电量</div>
            </div>
            <div class="bg-orange-50 rounded-lg p-3 text-center">
                <div class="text-lg font-bold text-orange-600" id="steps-${escHtml(mac)}">--</div>
                <div class="text-xs text-gray-400 mt-0.5">步数</div>
            </div>
            <div class="bg-red-50 rounded-lg p-3 text-center">
                <div class="text-lg font-bold text-red-600" id="hr-${escHtml(mac)}">--</div>
                <div class="text-xs text-gray-400 mt-0.5">心率</div>
            </div>
            <div class="bg-purple-50 rounded-lg p-3 text-center">
                <div class="text-lg font-bold text-purple-600" id="spo2-${escHtml(mac)}">--</div>
                <div class="text-xs text-gray-400 mt-0.5">血氧 %</div>
            </div>
        </div>` : "";

    const actions = isAuthed ? `
        <div class="flex flex-wrap gap-2">
            <button id="syncBtn-${escHtml(mac)}" onclick="syncDevice('${safeAttr(mac)}')"
                    class="bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
                同步数据
            </button>
            <button onclick="findDevice('${safeAttr(mac)}')"
                    class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs px-3 py-1.5 rounded-lg transition-colors">
                查找设备
            </button>
            <button onclick="syncTime('${safeAttr(mac)}')"
                    class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs px-3 py-1.5 rounded-lg transition-colors">
                同步时间
            </button>
            <button onclick="openNotifyModal('${safeAttr(mac)}')"
                    class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs px-3 py-1.5 rounded-lg transition-colors">
                推送通知
            </button>
            <button onclick="openDndModal('${safeAttr(mac)}')"
                    class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs px-3 py-1.5 rounded-lg transition-colors">
                免打扰
            </button>
            <button onclick="openGoalModal('${safeAttr(mac)}')"
                    class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs px-3 py-1.5 rounded-lg transition-colors">
                每日目标
            </button>
            <button onclick="disconnectDevice('${safeAttr(mac)}')"
                    class="bg-gray-100 hover:bg-gray-200 text-gray-600 text-xs px-3 py-1.5 rounded-lg transition-colors ml-auto">
                断开
            </button>
            <button onclick="removeDevice('${safeAttr(mac)}')"
                    class="bg-red-50 hover:bg-red-100 text-red-600 text-xs px-3 py-1.5 rounded-lg transition-colors">
                移除
            </button>
        </div>` : `
        <div class="flex flex-wrap gap-2">
            ${!isConnected ? `
            <button onclick="${d.saved_key ? `connectAndAuth('${safeAttr(mac)}')` : `connectDevice('${safeAttr(mac)}')`}"
                    class="bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
                ${d.saved_key ? "连接并认证" : "连接"}
            </button>` : ""}
            ${isConnected ? `
            <button onclick="openAuthModal('${safeAttr(mac)}')"
                    class="bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
                输入 Auth Key 认证
            </button>` : ""}
            <button onclick="removeDevice('${safeAttr(mac)}')"
                    class="bg-red-50 hover:bg-red-100 text-red-600 text-xs px-3 py-1.5 rounded-lg transition-colors ml-auto">
                移除
            </button>
        </div>`;

    return `
        <div id="device-${escHtml(mac)}" class="bg-white rounded-xl border border-gray-200 p-5 card-hover fade-in">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-3">
                    <div class="w-9 h-9 rounded-full ${isAuthed ? "bg-green-100" : "bg-gray-100"} flex items-center justify-center text-base">⌚</div>
                    <div>
                        <div class="font-semibold text-gray-800 text-sm">${escHtml(d.name || mac)}</div>
                        <div class="text-xs text-gray-400 font-mono">${escHtml(mac)}</div>
                    </div>
                </div>
                ${statusBadge}
            </div>
            ${d.model || d.firmware ? `
            <div class="flex gap-3 text-xs text-gray-400 mb-3 flex-wrap">
                ${d.model ? `<span>型号: <span class="text-gray-600">${escHtml(d.model)}</span></span>` : ""}
                ${d.firmware ? `<span>固件: <span class="text-gray-600">${escHtml(d.firmware)}</span></span>` : ""}
            </div>` : ""}
            ${d.error ? `<div class="mb-3 p-2 bg-red-50 text-red-500 text-xs rounded-lg">${escHtml(d.error)}</div>` : ""}
            ${dataGrid}
            ${actions}
        </div>`;
}

function updateDeviceCard(mac, data) {
    const get = id => document.getElementById(`${id}-${mac}`);
    const batteryEl = get("battery");
    const stepsEl = get("steps");
    const hrEl = get("hr");
    const spo2El = get("spo2");

    if (batteryEl && data.battery != null) {
        batteryEl.textContent = data.battery + "%";
        batteryEl.className = `text-lg font-bold ${batteryColor(data.battery)}`;
    }
    if (stepsEl && data.steps != null) stepsEl.textContent = data.steps.toLocaleString();
    if (hrEl && data.heart_rate != null) hrEl.textContent = data.heart_rate;
    if (spo2El && data.spo2 != null) spo2El.textContent = data.spo2;
}

// ── Device Actions ────────────────────────────────────────────────────

async function addDevice() {
    const mac = document.getElementById("newMac").value.trim();
    if (!mac) { toast("请输入 MAC 地址"); return; }
    if (!/^[0-9A-Fa-f:]{12,17}$/.test(mac.replace(/-/g, ""))) {
        toast("MAC 地址格式不正确");
        return;
    }

    setLoading("addBtn", "addBtnText", true, "添加中...");
    try {
        await api(`/devices/${mac}`, { method: "POST" });
        document.getElementById("newMac").value = "";
        toast("设备已添加，请连接并认证");
        await loadDevices();
    } catch (e) {
        toast("添加失败：" + e.message);
    }
    setLoading("addBtn", "addBtnText", false, "添加");
}

async function addFromScan(mac) {
    document.getElementById("newMac").value = mac;
    closeScanModal();
    switchTab("manual");
    await addDevice();
}

async function connectDevice(mac) {
    try {
        await api(`/devices/${mac}/connect`, { method: "POST" });
        toast("连接成功");
    } catch (e) {
        toast("连接失败：" + e.message);
    }
    await loadDevices();
}

async function connectAndAuth(mac) {
    toast("正在连接并认证...");
    try {
        await api(`/devices/${mac}/auth`, {
            method: "POST",
            body: JSON.stringify({ auth_key: "" }),
        });
        toast("认证成功");
    } catch (e) {
        toast("连接认证失败：" + e.message);
    }
    await loadDevices();
}

async function disconnectDevice(mac) {
    try {
        await api(`/devices/${mac}/disconnect`, { method: "POST" });
        toast("已断开连接");
    } catch (e) {
        toast("断开失败：" + e.message);
    }
    await loadDevices();
}

async function removeDevice(mac) {
    if (!confirm("确定移除此设备？")) return;
    try {
        await api(`/devices/${mac}`, { method: "DELETE" });
        toast("设备已移除");
    } catch (e) {
        toast("移除失败：" + e.message);
    }
    await loadDevices();
}

async function syncDevice(mac) {
    setLoading(`syncBtn-${mac}`, `syncBtn-${mac}`, true, "同步中...");
    const syncBtn = document.getElementById(`syncBtn-${mac}`);
    if (syncBtn) {
        syncBtn.disabled = true;
        syncBtn.innerHTML = `<span class="spinner inline-block mr-1"></span>同步中...`;
    }
    try {
        const data = await api(`/devices/${mac}/sync`);
        updateDeviceCard(mac, data);
        toast("同步完成");
    } catch (e) {
        toast("同步失败：" + e.message);
    }
    if (syncBtn) {
        syncBtn.disabled = false;
        syncBtn.innerHTML = "同步数据";
    }
}

async function findDevice(mac) {
    try {
        await api(`/devices/${mac}/find`, { method: "POST" });
        toast("手表正在震动...");
    } catch (e) {
        toast("操作失败：" + e.message);
    }
}

async function syncTime(mac) {
    try {
        await api(`/devices/${mac}/sync_time`, { method: "POST" });
        toast("时间同步完成");
    } catch (e) {
        toast("同步失败：" + e.message);
    }
}

// ── Auth Modal ────────────────────────────────────────────────────────

function openAuthModal(mac) {
    currentAuthMac = mac;
    document.getElementById("authKey").value = "";
    document.getElementById("authError").classList.add("hidden");
    document.getElementById("authModal").classList.remove("hidden");
    document.getElementById("authKey").focus();
}

function closeAuthModal() {
    currentAuthMac = null;
    document.getElementById("authModal").classList.add("hidden");
}

async function submitAuth() {
    const key = document.getElementById("authKey").value.trim();
    const errEl = document.getElementById("authError");
    errEl.classList.add("hidden");

    if (!key || !/^[0-9a-fA-F]{32}$/.test(key)) {
        errEl.textContent = "Auth Key 必须是 32 位十六进制字符";
        errEl.classList.remove("hidden");
        return;
    }

    setLoading("authBtn", "authBtnText", true, "认证中...");
    try {
        await api(`/devices/${currentAuthMac}/auth`, {
            method: "POST",
            body: JSON.stringify({ auth_key: key }),
        });
        closeAuthModal();
        toast("认证成功");
        await loadDevices();
    } catch (e) {
        errEl.textContent = e.message;
        errEl.classList.remove("hidden");
    }
    setLoading("authBtn", "authBtnText", false, "认证");
}

// ── Scan Modal ────────────────────────────────────────────────────────

async function openScanModal() {
    document.getElementById("scanModal").classList.remove("hidden");
    document.getElementById("scanModalContent").classList.remove("hidden");
    document.getElementById("scanModalResults").classList.add("hidden");

    try {
        const resp = await api("/scan");
        const results = resp.devices || [];
        const container = document.getElementById("scanModalResults");

        if (results.length === 0) {
            container.innerHTML = `<p class="text-sm text-gray-400 text-center py-4">未发现任何蓝牙设备<br><span class="text-xs">请确保手表蓝牙已开启且在附近</span></p>`;
        } else {
            const amazfitDevices = results.filter(d => d.is_amazfit);
            const otherDevices   = results.filter(d => !d.is_amazfit);

            let html = "";
            if (amazfitDevices.length > 0) {
                html += `<p class="text-xs text-gray-400 font-medium px-1 mb-1">识别到的 Amazfit/Zepp 设备</p>`;
                html += amazfitDevices.map(d => _scanDeviceRow(d, true)).join("");
            }
            if (otherDevices.length > 0) {
                html += `<p class="text-xs text-gray-400 font-medium px-1 mt-3 mb-1">其他蓝牙设备（${otherDevices.length} 个，可手动选择）</p>`;
                html += otherDevices.map(d => _scanDeviceRow(d, false)).join("");
            }
            container.innerHTML = html;
        }
        container.classList.remove("hidden");
        document.getElementById("scanModalContent").classList.add("hidden");
    } catch (e) {
        document.getElementById("scanModalContent").innerHTML = `
            <p class="text-sm text-red-500 text-center py-4">扫描失败：${escHtml(e.message)}</p>
            <p class="text-xs text-gray-400 text-center">请确保蓝牙适配器已开启</p>`;
    }
}

function _scanDeviceRow(d, highlight) {
    const rssiStr = d.rssi ? ` · ${d.rssi} dBm` : "";
    const bg = highlight ? "bg-blue-50 hover:bg-blue-100" : "bg-gray-50 hover:bg-gray-100";
    return `
        <div class="flex items-center justify-between p-3 ${bg} rounded-lg cursor-pointer transition-colors mb-1"
             onclick="addFromScan('${safeAttr(d.mac)}')">
            <div>
                <div class="text-sm font-medium text-gray-800">${escHtml(d.name || d.mac)}</div>
                <div class="text-xs text-gray-400 font-mono">${escHtml(d.mac)}${rssiStr}</div>
            </div>
            <span class="text-xs ${highlight ? "text-blue-600" : "text-gray-400"} font-medium">选择</span>
        </div>`;
}

function closeScanModal() {
    document.getElementById("scanModal").classList.add("hidden");
}

// ── Notification Modal ────────────────────────────────────────────────

function openNotifyModal(mac) {
    currentNotifyMac = mac;
    document.getElementById("notifyTitle").value = "";
    document.getElementById("notifyMessage").value = "";
    document.getElementById("notifyModal").classList.remove("hidden");
    document.getElementById("notifyMessage").focus();
}

function closeNotifyModal() {
    currentNotifyMac = null;
    document.getElementById("notifyModal").classList.add("hidden");
}

async function submitNotification() {
    const title = document.getElementById("notifyTitle").value.trim();
    const message = document.getElementById("notifyMessage").value.trim();
    if (!message) { toast("请输入通知内容"); return; }

    setLoading("notifyBtn", "notifyBtnText", true, "发送中...");
    try {
        await api(`/devices/${currentNotifyMac}/notification`, {
            method: "POST",
            body: JSON.stringify({ title, message }),
        });
        closeNotifyModal();
        toast("通知已发送");
    } catch (e) {
        toast("发送失败：" + e.message);
    }
    setLoading("notifyBtn", "notifyBtnText", false, "发送");
}

// ── DND Modal ─────────────────────────────────────────────────────────

function openDndModal(mac) {
    currentDndMac = mac;
    document.getElementById("dndModal").classList.remove("hidden");
}

function closeDndModal() {
    currentDndMac = null;
    document.getElementById("dndModal").classList.add("hidden");
}

async function submitDnd() {
    const enabled = document.getElementById("dndEnabled").checked;
    const [sh, sm] = document.getElementById("dndStart").value.split(":").map(Number);
    const [eh, em] = document.getElementById("dndEnd").value.split(":").map(Number);

    setLoading("dndBtn", "dndBtnText", true, "保存中...");
    try {
        await api(`/devices/${currentDndMac}/dnd`, {
            method: "POST",
            body: JSON.stringify({ enabled, start_h: sh, start_m: sm, end_h: eh, end_m: em }),
        });
        closeDndModal();
        toast("免打扰设置已保存");
    } catch (e) {
        toast("设置失败：" + e.message);
    }
    setLoading("dndBtn", "dndBtnText", false, "保存");
}

// ── Goal Modal ────────────────────────────────────────────────────────

function openGoalModal(mac) {
    currentGoalMac = mac;
    document.getElementById("goalModal").classList.remove("hidden");
}

function closeGoalModal() {
    currentGoalMac = null;
    document.getElementById("goalModal").classList.add("hidden");
}

async function submitGoal() {
    const steps = parseInt(document.getElementById("goalSteps").value);
    const calories = parseInt(document.getElementById("goalCalories").value);
    const active_min = parseInt(document.getElementById("goalActiveMin").value);

    setLoading("goalBtn", "goalBtnText", true, "保存中...");
    try {
        await api(`/devices/${currentGoalMac}/goal`, {
            method: "POST",
            body: JSON.stringify({ steps, calories, active_min }),
        });
        closeGoalModal();
        toast("每日目标已保存");
    } catch (e) {
        toast("设置失败：" + e.message);
    }
    setLoading("goalBtn", "goalBtnText", false, "保存");
}

// ── Keyboard shortcuts ────────────────────────────────────────────────

document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    closeAuthModal();
    closeScanModal();
    closeNotifyModal();
    closeDndModal();
    closeGoalModal();
});

document.getElementById("authKey").addEventListener("keydown", e => { if (e.key === "Enter") submitAuth(); });
document.getElementById("newMac").addEventListener("keydown", e => { if (e.key === "Enter") addDevice(); });
document.getElementById("zeppPassword").addEventListener("keydown", e => { if (e.key === "Enter") submitZeppLogin(); });

// ── Init ──────────────────────────────────────────────────────────────
loadDevices();

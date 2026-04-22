/** Zepp PC Manager — Frontend application logic */

const API = "/api";
let currentAuthMac = null;
let devices = [];

// ── Helpers ──────────────────────────────────────────────────────────

function escHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
}

// ── API helper ───────────────────────────────────────────────────────
async function api(path, opts = {}) {
    const res = await fetch(API + path, {
        headers: { "Content-Type": "application/json", ...opts.headers },
        ...opts,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
}

async function loadDevices() {
    try {
        devices = await api("/devices");
        renderDevices();
    } catch (e) {
        console.error("Failed to load devices:", e);
    }
}

// ── Device Actions ───────────────────────────────────────────────────

async function addDevice() {
    const mac = document.getElementById("newMac").value.trim();
    if (!mac) { toast("请输入 MAC 地址"); return; }
    if (!/^[0-9A-Fa-f:]{12,17}$/.test(mac.replace(/[-]/g, ""))) {
        toast("MAC 地址格式不正确");
        return;
    }

    const btn = document.getElementById("addBtn");
    const btnText = document.getElementById("addBtnText");
    btn.disabled = true;
    btnText.innerHTML = '<span class="spinner inline-block mr-1"></span>连接中...';

    try {
        await api(`/devices/${mac}`, { method: "POST" });
        // Try to connect
        try {
            await api(`/devices/${mac}/connect`, { method: "POST" });
            toast("已连接，请先认证");
        } catch (e) {
            toast("设备已添加，但连接失败：" + e.message);
        }
    } catch (e) {
        toast("添加失败：" + e.message);
    }

    document.getElementById("newMac").value = "";
    btn.disabled = false;
    btnText.textContent = "连接";
    await loadDevices();
}

async function addFromScan(mac) {
    document.getElementById("newMac").value = mac;
    closeScanModal();
    await addDevice();
}

async function connectDevice(mac) {
    try {
        await api(`/devices/${mac}/connect`, { method: "POST" });
        toast("已连接");
    } catch (e) {
        toast("连接失败：" + e.message);
    }
    await loadDevices();
}

async function disconnectDevice(mac) {
    try {
        await api(`/devices/${mac}/disconnect`, { method: "POST" });
        toast("已断开");
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

// ── Scanning ─────────────────────────────────────────────────────────

async function openScanModal() {
    document.getElementById("scanModal").classList.remove("hidden");
    document.getElementById("scanModalContent").classList.remove("hidden");
    document.getElementById("scanModalResults").classList.add("hidden");

    try {
        const resp = await api("/scan");
        const results = resp.devices || [];
        const container = document.getElementById("scanModalResults");

        if (results.length === 0) {
            container.innerHTML = '<p class="text-sm text-gray-500 text-center py-4">未发现 Amazfit 设备</p>';
        } else {
            container.innerHTML = results.map(d => `
                <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg cursor-pointer hover:bg-blue-50"
                     onclick="addFromScan('${d.mac.replace(/'/g, "\\'")}')">
                    <div>
                        <div class="text-sm font-medium text-gray-800">${escHtml(d.name)}</div>
                        <div class="text-xs text-gray-400 font-mono">${escHtml(d.mac)}</div>
                    </div>
                    <span class="text-xs text-blue-600">选择</span>
                </div>
            `).join("");
        }
        container.classList.remove("hidden");
        document.getElementById("scanModalContent").classList.add("hidden");
    } catch (e) {
        document.getElementById("scanModalContent").innerHTML = `
            <p class="text-sm text-red-500 text-center py-4">扫描失败：${escHtml(e.message)}</p>
            <p class="text-xs text-gray-400 text-center">请确保蓝牙已开启</p>
        `;
    }
}

function closeScanModal() {
    document.getElementById("scanModal").classList.add("hidden");
}

// ── Authentication ───────────────────────────────────────────────────

function openAuthModal(mac) {
    currentAuthMac = mac;
    document.getElementById("authModal").classList.remove("hidden");
    document.getElementById("authKey").value = "";
    document.getElementById("authError").classList.add("hidden");
    document.getElementById("authKey").focus();
}

function closeAuthModal() {
    currentAuthMac = null;
    document.getElementById("authModal").classList.add("hidden");
}

function showAuthHelp() {
    document.getElementById("authHelpModal").classList.remove("hidden");
}

function closeAuthHelpModal() {
    document.getElementById("authHelpModal").classList.add("hidden");
}

async function submitAuth() {
    const key = document.getElementById("authKey").value.trim();
    if (!key) { toast("请输入 Auth Key"); return; }
    if (!/^[0-9a-fA-F]{32}$/.test(key)) {
        showAuthError("Auth Key 必须是 32 位十六进制字符");
        return;
    }

    const btn = document.getElementById("authBtn");
    const btnText = document.getElementById("authBtnText");
    btn.disabled = true;
    btnText.innerHTML = '<span class="spinner inline-block mr-1"></span>认证中...';

    try {
        await api(`/devices/${currentAuthMac}/auth`, {
            method: "POST",
            body: JSON.stringify({ auth_key: key }),
        });
        closeAuthModal();
        toast("认证成功");
        await loadDevices();
    } catch (e) {
        showAuthError(e.message);
    }

    btn.disabled = false;
    btnText.textContent = "认证";
}

function showAuthError(msg) {
    const el = document.getElementById("authError");
    el.textContent = msg;
    el.classList.remove("hidden");
}

// ── Data Actions ─────────────────────────────────────────────────────

async function syncDevice(mac) {
    const syncBtn = document.getElementById(`syncBtn-${mac}`);
    if (syncBtn) {
        syncBtn.disabled = true;
        syncBtn.innerHTML = '<span class="spinner inline-block mr-1"></span>同步中...';
    }

    try {
        const data = await api(`/devices/${mac}/sync`);
        toast("同步完成");
        updateDeviceCard(mac, data);
    } catch (e) {
        toast("同步失败：" + e.message);
    }

    if (syncBtn) {
        syncBtn.disabled = false;
        syncBtn.innerHTML = "同步数据";
    }
    await loadDevices();
}

async function findDevice(mac) {
    try {
        await api(`/devices/${mac}/find`, { method: "POST" });
        toast("手表正在震动");
    } catch (e) {
        toast("操作失败：" + e.message);
    }
}

async function syncTime(mac) {
    try {
        await api(`/devices/${mac}/sync_time`, { method: "POST" });
        toast("时间同步完成");
    } catch (e) {
        toast("时间同步失败：" + e.message);
    }
}

// ── UI Rendering ─────────────────────────────────────────────────────

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

function renderDeviceCard(d) {
    const isConnected = d.connected;
    const isAuthed = d.authenticated;
    const batteryLevel = d.battery ?? null;
    const batteryIcon = batteryLevel !== null
        ? (batteryLevel > 50 ? "🔋" : batteryLevel > 20 ? "🪫" : "🔴")
        : "--";
    const batteryColor = batteryLevel !== null
        ? (batteryLevel > 50 ? "text-green-600" : batteryLevel > 20 ? "text-yellow-600" : "text-red-600")
        : "text-gray-400";

    return `
        <div id="device-${escHtml(d.mac)}" class="bg-white rounded-xl border border-gray-200 p-6 mb-4 card-hover fade-in">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-full flex items-center justify-center text-lg ${isAuthed ? 'bg-green-100' : 'bg-gray-100'}">
                        ⌚
                    </div>
                    <div>
                        <h3 class="font-semibold text-gray-800">${escHtml(d.name || d.mac)}</h3>
                        <p class="text-xs text-gray-400 font-mono">${escHtml(d.mac)}</p>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    ${isAuthed
                        ? `<span class="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full">已认证</span>`
                        : `<span class="px-2 py-0.5 ${isConnected ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-500'} text-xs rounded-full">${isConnected ? '已连接' : '未连接'}</span>`
                    }
                </div>
            </div>

            ${d.model || d.firmware ? `
            <div class="flex gap-4 mb-4 text-xs text-gray-500 flex-wrap">
                ${d.model ? `<span>型号: <span class="text-gray-700">${escHtml(d.model)}</span></span>` : ""}
                ${d.firmware ? `<span>固件: <span class="text-gray-700">${escHtml(d.firmware)}</span></span>` : ""}
                ${d.saved_key ? `<span class="text-green-600">🔑 Key 已保存</span>` : ""}
            </div>
            ` : ""}

            ${d.error ? `<div class="mb-4 p-2 bg-red-50 text-red-600 text-xs rounded-lg">${escHtml(d.error)}</div>` : ""}

            ${isAuthed ? `
            <!-- Data Dashboard -->
            <div class="grid grid-cols-4 gap-4 mb-4">
                <div class="bg-blue-50 rounded-lg p-4 text-center">
                    <div class="text-xl font-bold ${batteryColor}" id="battery-${escHtml(d.mac)}">${batteryLevel !== null ? batteryLevel + "%" : "--"}</div>
                    <div class="text-xs text-blue-400 mt-1">电量 ${batteryIcon}</div>
                </div>
                <div class="bg-orange-50 rounded-lg p-4 text-center">
                    <div class="text-xl font-bold text-orange-700" id="steps-${escHtml(d.mac)}">--</div>
                    <div class="text-xs text-orange-400 mt-1">步数</div>
                </div>
                <div class="bg-red-50 rounded-lg p-4 text-center">
                    <div class="text-xl font-bold text-red-700" id="hr-${escHtml(d.mac)}">--</div>
                    <div class="text-xs text-red-400 mt-1">心率 BPM</div>
                </div>
                <div class="bg-purple-50 rounded-lg p-4 text-center">
                    <div class="text-xl font-bold text-purple-700" id="spo2-${escHtml(d.mac)}">--</div>
                    <div class="text-xs text-purple-400 mt-1">血氧 %</div>
                </div>
            </div>

            <!-- Action Buttons -->
            <div class="flex gap-2">
                <button id="syncBtn-${escHtml(d.mac)}" onclick="syncDevice('${escHtml(d.mac).replace(/'/g, "\\\\'")}')" class="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors">
                    同步数据
                </button>
                <button onclick="findDevice('${escHtml(d.mac).replace(/'/g, "\\\\'")}')" class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors">
                    查找设备
                </button>
                <button onclick="syncTime('${escHtml(d.mac).replace(/'/g, "\\\\'")}')" class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors">
                    同步时间
                </button>
                <button onclick="disconnectDevice('${escHtml(d.mac).replace(/'/g, "\\\\'")}')" class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors">
                    断开
                </button>
                <button onclick="removeDevice('${escHtml(d.mac).replace(/'/g, "\\\\'")}')" class="bg-red-50 hover:bg-red-100 text-red-600 text-sm font-medium px-4 py-2 rounded-lg transition-colors">
                    移除
                </button>
            </div>
            ` : `
            <!-- Not Authed -->
            <div class="flex gap-2">
                <button onclick="openAuthModal('${escHtml(d.mac).replace(/'/g, "\\\\'")}')" class="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors">
                    输入 Auth Key 认证
                </button>
                ${!isConnected ? `
                <button onclick="connectDevice('${escHtml(d.mac).replace(/'/g, "\\\\'")}')" class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors">
                    连接
                </button>
                ` : ""}
                <button onclick="removeDevice('${escHtml(d.mac).replace(/'/g, "\\\\'")}')" class="bg-red-50 hover:bg-red-100 text-red-600 text-sm font-medium px-4 py-2 rounded-lg transition-colors">
                    移除
                </button>
            </div>
            `}
        </div>
    `;
}

function updateDeviceCard(mac, data) {
    const batteryEl = document.getElementById(`battery-${mac}`);
    const stepsEl = document.getElementById(`steps-${mac}`);
    const hrEl = document.getElementById(`hr-${mac}`);
    const spo2El = document.getElementById(`spo2-${mac}`);

    if (batteryEl && data.battery !== null) {
        batteryEl.textContent = data.battery + "%";
        batteryEl.className = "text-xl font-bold " + (data.battery > 50 ? "text-green-600" : data.battery > 20 ? "text-yellow-600" : "text-red-600");
    }
    if (stepsEl && data.steps !== null) stepsEl.textContent = data.steps;
    if (hrEl && data.heart_rate !== null) hrEl.textContent = data.heart_rate;
    if (spo2El && data.spo2 !== null) spo2El.textContent = data.spo2;
}

// ── Toast ────────────────────────────────────────────────────────────

function toast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add("hidden"), 3000);
}

// ── Keyboard shortcuts ───────────────────────────────────────────────

document.getElementById("authKey").addEventListener("keydown", e => { if (e.key === "Enter") submitAuth(); });
document.getElementById("newMac").addEventListener("keydown", e => { if (e.key === "Enter") addDevice(); });

// Close modals on Escape
document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
        closeAuthModal();
        closeAuthHelpModal();
        closeScanModal();
        document.getElementById("helpModal").classList.add("hidden");
    }
});

// ── Init ─────────────────────────────────────────────────────────────
loadDevices();

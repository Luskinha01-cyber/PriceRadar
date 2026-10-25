/**
 * app.js — PriceRadar Frontend Controller (Pure Vanilla JS)
 * =========================================================
 * - Exclusivamente Dark Mode
 * - Sincronização bidirecional entre Sliders (range) e Inputs numéricos
 * - Renderização de cards de alta precisão com ícones SVG vetoriais
 */

let appState = {
    products: [],
    settings: {},
    stats: { total_products: 0, deals_count: 0, total_savings: 0 },
    currentFilter: "all",
    previewedData: null,
    lastAlertEmail: null
};

let priceChartInstance = null;

// =====================================================================
// 1. INICIALIZAÇÃO, MICROANIMAÇÕES E SINCRONIZAÇÃO DE INPUTS
// =====================================================================

document.addEventListener("DOMContentLoaded", () => {
    initBidirectionalInputs();
    initRippleEffects();
    initRevealObserver();
    initCardSpotlight();
    initScrollSpy();
    loadState();
    setInterval(loadState, 45000);
});

/**
 * Sincronização bidirecional obrigatória entre <input type="range"> e <input type="number">
 */
function bindRangeAndNumber(rangeId, numberId, onUpdate = null) {
    const rangeEl = document.getElementById(rangeId);
    const numberEl = document.getElementById(numberId);
    if (!rangeEl || !numberEl) return;

    rangeEl.addEventListener("input", () => {
        numberEl.value = rangeEl.value;
        if (onUpdate) onUpdate(Number(rangeEl.value));
    });

    numberEl.addEventListener("input", () => {
        const val = Number(numberEl.value);
        if (!Number.isNaN(val) && val > 0) {
            if (val > Number(rangeEl.max)) {
                rangeEl.max = Math.ceil(val * 1.25);
            }
            rangeEl.value = val;
            if (onUpdate) onUpdate(val);
        }
    });
}

function initBidirectionalInputs() {
    bindRangeAndNumber("inputTargetSlider", "inputTargetPrice", updateTargetDeltaBadge);
    bindRangeAndNumber("editTargetSlider", "editTargetPrice");
    bindRangeAndNumber("cfgIntervalSlider", "cfgCheckInterval");
}

function syncSliderBounds(referencePrice = null) {
    const base =
        referencePrice ||
        Number(document.getElementById("inputCurrentPrice").value) ||
        (appState.previewedData && appState.previewedData.price);

    const slider = document.getElementById("inputTargetSlider");
    if (!slider || !base || base <= 0) return;

    slider.min = Math.max(1, Math.floor(base * 0.3));
    slider.max = Math.ceil(base * 1.1);
    updateTargetDeltaBadge(Number(document.getElementById("inputTargetPrice").value));
}

function updateTargetDeltaBadge(targetVal) {
    const badge = document.getElementById("targetDeltaPreview");
    if (!badge) return;

    const base =
        Number(document.getElementById("inputCurrentPrice").value) ||
        (appState.previewedData && appState.previewedData.price);

    if (!targetVal || targetVal <= 0) {
        badge.textContent = "Defina o valor";
        return;
    }

    if (base && base > 0) {
        const diffPct = Math.round(((base - targetVal) / base) * 100);
        if (diffPct > 0) {
            badge.textContent = `-${diffPct}% vs. cotação`;
        } else {
            badge.textContent = formatBRL(targetVal);
        }
    } else {
        badge.textContent = formatBRL(targetVal);
    }
}

/**
 * Feedback tátil (.fx-ripple) capturando coordenadas do ponteiro
 */
function initRippleEffects() {
    document.addEventListener("pointerdown", (event) => {
        const target = event.target.closest(".fx-ripple");
        if (!target || target.disabled) return;

        const rect = target.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const wave = document.createElement("span");
        wave.className = "ripple-wave";
        wave.style.width = `${size}px`;
        wave.style.height = `${size}px`;
        wave.style.left = `${event.clientX - rect.left - size / 2}px`;
        wave.style.top = `${event.clientY - rect.top - size / 2}px`;

        target.appendChild(wave);
        setTimeout(() => wave.remove(), 520);
    });
}

function formatBRL(value) {
    const num = Number(value) || 0;
    return num.toLocaleString("pt-BR", {
        style: "currency",
        currency: "BRL"
    });
}

function formatTimestamp(dateStr) {
    if (!dateStr) return "AGORA";
    const parts = dateStr.split(" ");
    if (parts.length < 2) return dateStr;
    const [, mm, dd] = parts[0].split("-");
    const time = parts[1].slice(0, 5);
    return `${dd}/${mm} · ${time}`;
}

// =====================================================================
// 2. CARREGAMENTO DE ESTADO E RENDERIZAÇÃO
// =====================================================================

async function loadState() {
    try {
        const response = await fetch("/api/state");
        const data = await response.json();

        appState.products = data.products || [];
        appState.settings = data.settings || {};
        appState.stats = data.stats || { total_products: 0, deals_count: 0, total_savings: 0 };

        renderKPIs();
        renderProducts();
    } catch (err) {
        console.error("Erro ao sincronizar estado:", err);
    }
}

function renderKPIs() {
    const { products, settings, stats } = appState;

    animateValue(document.getElementById("kpiTotalProducts"), stats.total_products, v => Math.round(v));
    animateValue(document.getElementById("kpiDealsCount"), stats.deals_count, v => Math.round(v));
    animateValue(document.getElementById("kpiTotalSavings"), stats.total_savings, v => formatBRL(v));

    const emailModeEl = document.getElementById("kpiEmailMode");
    const activeRecipient = settings.default_recipient || settings.smtp_email;
    if (activeRecipient) {
        emailModeEl.textContent = activeRecipient;
        emailModeEl.classList.add("text-emerald");
    } else {
        emailModeEl.textContent = "Aguardando E-mail";
        emailModeEl.classList.remove("text-emerald");
    }

    const monitorDot = document.getElementById("monitorDot");
    const monitorText = document.getElementById("monitorStatusText");
    if (settings.auto_check_enabled) {
        monitorDot.classList.add("active");
        monitorText.textContent = `ATIVO · ${settings.check_interval_minutes || 30}M`;
    } else {
        monitorDot.classList.remove("active");
        monitorText.textContent = "PAUSADO";
    }

    const dealsCount = products.filter(p => p.current_price <= p.target_price).length;
    const waitingCount = products.length - dealsCount;
    document.getElementById("countAll").textContent = products.length;
    document.getElementById("countDeals").textContent = dealsCount;
    document.getElementById("countWaiting").textContent = waitingCount;
    renderTicker();
}

function renderProducts() {
    const grid = document.getElementById("productsGrid");
    const searchQuery = (document.getElementById("searchInput").value || "").toLowerCase().trim();

    const filtered = appState.products.filter(prod => {
        const isDeal = prod.current_price <= prod.target_price;
        if (appState.currentFilter === "deals" && !isDeal) return false;
        if (appState.currentFilter === "waiting" && isDeal) return false;

        if (searchQuery) {
            const matchTitle = (prod.title || "").toLowerCase().includes(searchQuery);
            const matchStore = (prod.store_name || "").toLowerCase().includes(searchQuery);
            return matchTitle || matchStore;
        }
        return true;
    });

    if (filtered.length === 0) {
        grid.innerHTML = `
            <div class="empty-box">
                <h3>Nenhum item corresponde ao filtro atual</h3>
                <p>Adicione uma URL do Mercado Livre no painel superior ou restaure a base de demonstração.</p>
                <button type="button" class="btn btn-secondary fx-ripple" onclick="seedDemoProducts()">
                    Restaurar exemplos
                </button>
            </div>
        `;
        return;
    }

    grid.innerHTML = filtered.map(prod => buildProductCardHTML(prod)).join("");

    // Entrada escalonada apenas na primeira renderização (evita "piscar" nos refreshes)
    const cards = grid.querySelectorAll(".product-card");
    cards.forEach((card, i) => {
        card.style.setProperty("--stagger-i", i);
        if (!appState.hasRendered) {
            card.classList.add("fx-reveal");
            revealObserver.observe(card);
        }
    });
    appState.hasRendered = true;
}

function buildProductCardHTML(prod) {
    const isDeal = prod.current_price <= prod.target_price;
    const referencePrice = Math.max(prod.initial_price || prod.current_price, prod.highest_price || prod.current_price);
    const diffFromHigh = referencePrice - prod.current_price;
    const discountPct = referencePrice > 0 ? Math.round((diffFromHigh / referencePrice) * 100) : 0;

    let goalProgress = 100;
    if (!isDeal && prod.current_price > 0) {
        goalProgress = Math.min(96, Math.max(10, Math.round((prod.target_price / prod.current_price) * 100)));
    }

    const diffToTarget = prod.current_price - prod.target_price;
    const deltaLabel = isDeal
        ? `Abaixo do alvo (${formatBRL(Math.abs(diffToTarget))})`
        : `Distância para o alvo: ${formatBRL(diffToTarget)}`;

    const historyCount = (prod.history || []).length;

    return `
        <article class="product-card ${isDeal ? "is-deal" : ""}" id="product-card-${prod.id}">
            <div>
                <div class="card-meta-bar">
                    <span class="domain-label mono-text">${escapeHTML(prod.store_name || "Mercado Livre")}</span>
                    <span class="state-pill mono-text ${isDeal ? "deal" : "waiting"}">
                        ${isDeal ? "ALVO ATINGIDO" : "EM OBSERVAÇÃO"}
                    </span>
                </div>

                <div class="product-identity">
                    <div class="thumb-frame">
                        <img
                            src="${escapeHTML(prod.image_url)}"
                            alt="${escapeHTML(prod.title)}"
                            onerror="this.src='https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=400&q=80'"
                        />
                    </div>
                    <div class="product-title-wrap">
                        <a href="${escapeHTML(prod.url)}" target="_blank" rel="noopener noreferrer" class="product-link">
                            ${escapeHTML(prod.title)}
                        </a>
                        <div class="product-timestamp mono-text">
                            COLETA: ${formatTimestamp(prod.last_checked)} · ${historyCount} AMOSTRA(S) ${discountPct > 0 ? `· -${discountPct}%` : ""}
                        </div>
                    </div>
                </div>
            </div>

            ${buildSparklineHTML(prod, isDeal)}

            <div class="quote-matrix">
                <div class="quote-cell">
                    <span class="quote-label">ATUAL</span>
                    <span class="quote-val current mono-text ${isDeal ? "is-deal" : ""}">
                        ${formatBRL(prod.current_price)}
                    </span>
                </div>
                <div class="quote-cell">
                    <span class="quote-label">ALVO</span>
                    <span class="quote-val mono-text">
                        ${formatBRL(prod.target_price)}
                    </span>
                </div>
                <div class="quote-cell">
                    <span class="quote-label">MÁXIMO</span>
                    <span class="quote-val mono-text ${diffFromHigh > 0 ? "strike" : ""}">
                        ${formatBRL(referencePrice)}
                    </span>
                </div>
            </div>

            <div class="target-meter">
                <div class="target-meter-head">
                    <span>Proximidade do gatilho</span>
                    <span class="mono-text">${deltaLabel}</span>
                </div>
                <div class="target-track">
                    <div class="target-fill ${isDeal ? "deal" : ""}" style="width: ${goalProgress}%;"></div>
                </div>
            </div>

            <div class="card-footer-bar">
                <div class="action-group">
                    <button type="button" class="card-btn fx-ripple" onclick="openHistoryModal(${prod.id})" title="Série histórica">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
                        </svg>
                        <span>Série (${historyCount})</span>
                    </button>
                    <button type="button" class="card-btn fx-ripple" id="btn-check-${prod.id}" onclick="checkSingleProduct(${prod.id})" title="Coletar cotação agora">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                            <path d="M3 3v5h5"/>
                        </svg>
                        <span>Coletar</span>
                    </button>
                    <button type="button" class="card-btn card-btn-emerald fx-ripple" onclick="simulatePriceDrop(${prod.id})" title="Simular queda abaixo do alvo">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/>
                            <polyline points="17 18 23 18 23 12"/>
                        </svg>
                        <span>Simular Queda</span>
                    </button>
                </div>

                <div class="action-group">
                    <button type="button" class="card-btn fx-ripple" onclick="openEditTargetModal(${prod.id})" title="Editar preço alvo">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M12 20h9"/>
                            <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>
                        </svg>
                    </button>
                    <button type="button" class="card-btn card-btn-danger fx-ripple" onclick="deleteProduct(${prod.id})" title="Remover item">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 6h18"/>
                            <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/>
                            <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
                        </svg>
                    </button>
                </div>
            </div>
        </article>
    `;
}

// =====================================================================
// 3. INGESTÃO DE URL E EXTRAÇÃO DE COTAÇÃO
// =====================================================================

function toggleManualFields(forceOpen = null) {
    const container = document.getElementById("manualFieldsContainer");
    const toggleText = document.getElementById("toggleManualText");
    const shouldShow = forceOpen !== null ? forceOpen : container.classList.contains("hidden");

    if (shouldShow) {
        container.classList.remove("hidden");
        toggleText.textContent = "Ocultar campos manuais";
    } else {
        container.classList.add("hidden");
        toggleText.textContent = "Entrada manual";
    }
}

async function previewFromUrl() {
    const urlInput = document.getElementById("inputUrl");
    const btn = document.getElementById("btnPreviewUrl");
    const url = urlInput.value.trim();

    if (!url) {
        showToast("URL obrigatória", "Insira o endereço completo do anúncio para extrair a cotação.", "error");
        urlInput.focus();
        return;
    }

    btn.disabled = true;
    btn.innerHTML = "<span>Extraindo...</span>";

    try {
        const res = await fetch("/api/scrape-preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url })
        });
        const data = await res.json();

        if (data.success && data.price) {
            appState.previewedData = data;
            document.getElementById("previewImg").src = data.image_url;
            document.getElementById("previewStore").textContent = data.store_name;
            document.getElementById("previewTitle").textContent = data.title;
            document.getElementById("previewPrice").textContent = formatBRL(data.price);
            document.getElementById("scrapePreviewCard").classList.remove("hidden");

            document.getElementById("inputTitle").value = data.title;
            document.getElementById("inputCurrentPrice").value = data.price;

            const suggestedTarget = Number((data.price * 0.90).toFixed(2));
            syncSliderBounds(data.price);
            document.getElementById("inputTargetPrice").value = suggestedTarget;
            document.getElementById("inputTargetSlider").value = suggestedTarget;
            updateTargetDeltaBadge(suggestedTarget);

            showToast("Cotação extraída", `Valor atual identificado: ${formatBRL(data.price)}`, "success");
        } else {
            toggleManualFields(true);
            if (data.title) {
                document.getElementById("inputTitle").value = data.title;
            }
            showToast("Leitura parcial", data.error || "Informe a cotação inicial manualmente.", "info");
        }
    } catch (err) {
        toggleManualFields(true);
        showToast("Falha na leitura", "Preencha os campos manuais para cadastrar o item.", "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"/>
                <path d="m21 21-4.3-4.3"/>
            </svg>
            <span>Extrair Cotação</span>
        `;
    }
}

function applyQuickDiscount(discountFraction) {
    const basePrice =
        Number(document.getElementById("inputCurrentPrice").value) ||
        (appState.previewedData && appState.previewedData.price);

    if (!basePrice) return;
    const target = Number((basePrice * (1 - discountFraction)).toFixed(2));
    syncSliderBounds(basePrice);
    document.getElementById("inputTargetPrice").value = target;
    document.getElementById("inputTargetSlider").value = target;
    updateTargetDeltaBadge(target);
}

async function handleAddProduct(event) {
    event.preventDefault();

    const btn = document.getElementById("btnSubmitProduct");
    const payload = {
        url: document.getElementById("inputUrl").value.trim(),
        target_price: document.getElementById("inputTargetPrice").value,
        notify_email: document.getElementById("inputNotifyEmail").value.trim(),
        title: document.getElementById("inputTitle").value.trim(),
        current_price: document.getElementById("inputCurrentPrice").value,
        image_url: appState.previewedData ? appState.previewedData.image_url : ""
    };

    btn.disabled = true;
    btn.innerHTML = "<span>Processando...</span>";

    try {
        const res = await fetch("/api/products", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (!res.ok || !data.success) {
            if (data.need_manual_price) {
                toggleManualFields(true);
                if (data.title) document.getElementById("inputTitle").value = data.title;
                document.getElementById("inputCurrentPrice").focus();
            }
            showToast("Atenção", data.error || "Verifique os parâmetros informados.", "error");
            return;
        }

        document.getElementById("addProductForm").reset();
        document.getElementById("scrapePreviewCard").classList.add("hidden");
        document.getElementById("targetDeltaPreview").textContent = "Defina o valor";
        appState.previewedData = null;

        await loadState();
        showToast("Monitoramento iniciado", data.message, "success");

        if (data.alert) {
            handleAlertNotification(data.alert);
        }
    } catch (err) {
        showToast("Erro", "Falha ao registrar o produto no banco local.", "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="5" x2="12" y2="19"/>
                <line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            <span>Adicionar ao Radar</span>
        `;
    }
}

// =====================================================================
// 4. COLETA DE COTAÇÃO, SIMULAÇÃO DE QUEDA E ALERTAS
// =====================================================================

async function checkSingleProduct(productId) {
    const btn = document.getElementById(`btn-check-${productId}`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = "<span>Lendo...</span>";
    }

    try {
        const res = await fetch(`/api/products/${productId}/check`, { method: "POST" });
        const data = await res.json();

        await loadState();
        showToast("Sincronização concluída", data.note || "Cotação atualizada.", "success");

        if (data.alert) {
            handleAlertNotification(data.alert);
        }
    } catch (err) {
        showToast("Erro", "Falha ao consultar a página do produto.", "error");
    }
}

async function simulatePriceDrop(productId) {
    try {
        const res = await fetch(`/api/products/${productId}/simulate-drop`, { method: "POST" });
        const data = await res.json();

        if (data.success) {
            await loadState();
            showToast(
                "Gatilho de preço acionado",
                `Nova cotação: ${formatBRL(data.product.current_price)} (abaixo do alvo definido)`,
                "success"
            );

            if (data.alert) {
                handleAlertNotification(data.alert, true);
            }
        }
    } catch (err) {
        showToast("Erro", "Falha ao executar simulação de queda.", "error");
    }
}

async function checkAllProducts() {
    const btn = document.getElementById("btnCheckAll");
    btn.disabled = true;
    btn.innerHTML = "<span>Sincronizando...</span>";

    try {
        const res = await fetch("/api/check-all", { method: "POST" });
        const data = await res.json();

        await loadState();
        showToast("Lote verificado", data.message, "success");

        if (data.last_alert) {
            handleAlertNotification(data.last_alert);
        }
    } catch (err) {
        showToast("Erro", "Falha ao sincronizar lote de produtos.", "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
                <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                <path d="M16 16h5v5" />
            </svg>
            <span>Sincronizar</span>
        `;
    }
}

function handleAlertNotification(alertObj, autoOpenModal = false) {
    appState.lastAlertEmail = alertObj;

    showToast(
        alertObj.sent ? "Notificação SMTP enviada" : "Payload de alerta gerado",
        alertObj.message,
        "success",
        true
    );

    if (autoOpenModal) {
        openEmailPreviewModal(alertObj);
    }
}

function openEmailPreviewModal(alertObj = null) {
    const targetAlert = alertObj || appState.lastAlertEmail;
    if (!targetAlert) return;

    document.getElementById("emailPreviewStatusBadge").textContent = targetAlert.sent
        ? "DISPARO SMTP AUTENTICADO"
        : "SIMULAÇÃO LOCAL · RENDER HTML";
    document.getElementById("emailPreviewSubject").textContent = targetAlert.subject || "Notificação de Preço";
    document.getElementById("emailPreviewMeta").textContent =
        `DESTINO: ${targetAlert.recipient} · ${targetAlert.message}`;

    const iframe = document.getElementById("emailPreviewFrame");
    iframe.srcdoc = targetAlert.html_preview || "<p>Sem conteúdo HTML</p>";

    document.getElementById("emailPreviewModal").classList.remove("hidden");
}

// =====================================================================
// 5. SÉRIE HISTÓRICA E GRÁFICO (Chart.js)
// =====================================================================

function openHistoryModal(productId) {
    const prod = appState.products.find(p => p.id === productId);
    if (!prod) return;

    document.getElementById("historyModalTitle").textContent = prod.title;

    const summaryEl = document.getElementById("historySummaryBar");
    summaryEl.innerHTML = `
        <div class="history-stat-cell">
            <span>INICIAL</span>
            <strong>${formatBRL(prod.initial_price)}</strong>
        </div>
        <div class="history-stat-cell">
            <span>MÁXIMO</span>
            <strong>${formatBRL(prod.highest_price)}</strong>
        </div>
        <div class="history-stat-cell">
            <span>MÍNIMO</span>
            <strong class="text-emerald">${formatBRL(prod.lowest_price)}</strong>
        </div>
        <div class="history-stat-cell">
            <span>ALVO DEFINIDO</span>
            <strong>${formatBRL(prod.target_price)}</strong>
        </div>
    `;

    const history = prod.history || [];
    const labels = history.map(h => formatTimestamp(h.checked_at));
    const prices = history.map(h => h.price);
    const targetLine = history.map(() => prod.target_price);

    const tbody = document.getElementById("historyTableBody");
    tbody.innerHTML = [...history].reverse().map(item => {
        const isBelow = item.price <= prod.target_price;
        return `
            <tr>
                <td class="mono-text">${formatTimestamp(item.checked_at)}</td>
                <td class="mono-text"><strong>${formatBRL(item.price)}</strong></td>
                <td>
                    <span class="state-pill mono-text ${isBelow ? "deal" : "waiting"}">
                        ${isBelow ? "ABAIXO DO ALVO" : "ACIMA DO ALVO"}
                    </span>
                </td>
            </tr>
        `;
    }).join("");

    const ctx = document.getElementById("priceHistoryChart").getContext("2d");
    if (priceChartInstance) {
        priceChartInstance.destroy();
    }

    priceChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [
                {
                    label: "Cotação (R$)",
                    data: prices,
                    borderColor: "#10b981",
                    backgroundColor: "rgba(16, 185, 129, 0.08)",
                    borderWidth: 2,
                    pointRadius: 3.5,
                    pointBackgroundColor: "#10b981",
                    tension: 0.25,
                    fill: true
                },
                {
                    label: "Alvo (R$)",
                    data: targetLine,
                    borderColor: "#a1a1aa",
                    borderWidth: 1.5,
                    borderDash: [5, 5],
                    pointRadius: 0,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: "#a1a1aa",
                        font: { family: "JetBrains Mono", size: 11 }
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: "#71717a", font: { family: "JetBrains Mono", size: 10 } },
                    grid: { color: "rgba(255, 255, 255, 0.04)" }
                },
                y: {
                    ticks: {
                        color: "#71717a",
                        font: { family: "JetBrains Mono", size: 10 },
                        callback: val => "R$ " + val
                    },
                    grid: { color: "rgba(255, 255, 255, 0.04)" }
                }
            }
        }
    });

    document.getElementById("historyModal").classList.remove("hidden");
}

// =====================================================================
// 6. EDIÇÃO DE GATILHO, EXCLUSÃO E CONFIGURAÇÕES SMTP
// =====================================================================

function openEditTargetModal(productId) {
    const prod = appState.products.find(p => p.id === productId);
    if (!prod) return;

    document.getElementById("editProductId").value = prod.id;
    document.getElementById("editProductTitle").textContent = prod.title;
    document.getElementById("editTargetPrice").value = prod.target_price;
    document.getElementById("editNotifyEmail").value = prod.notify_email || "";

    const slider = document.getElementById("editTargetSlider");
    if (slider) {
        const base = Math.max(prod.current_price, prod.target_price);
        slider.min = Math.max(1, Math.floor(base * 0.25));
        slider.max = Math.ceil(base * 1.3);
        slider.value = prod.target_price;
    }

    document.getElementById("editTargetModal").classList.remove("hidden");
}

async function handleSaveTarget(event) {
    event.preventDefault();
    const productId = document.getElementById("editProductId").value;
    const target_price = document.getElementById("editTargetPrice").value;
    const notify_email = document.getElementById("editNotifyEmail").value.trim();

    try {
        const res = await fetch(`/api/products/${productId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target_price, notify_email })
        });
        const data = await res.json();

        if (data.success) {
            closeModal("editTargetModal");
            await loadState();
            showToast("Parâmetro salvo", "Preço alvo atualizado com sucesso.", "success");
        }
    } catch (err) {
        showToast("Erro", "Não foi possível atualizar o preço alvo.", "error");
    }
}

async function deleteProduct(productId) {
    try {
        await fetch(`/api/products/${productId}`, { method: "DELETE" });
        await loadState();
        showToast("Item removido", "O produto foi excluído do radar.", "info");
    } catch (err) {
        showToast("Erro", "Não foi possível remover o item.", "error");
    }
}

async function seedDemoProducts() {
    try {
        const res = await fetch("/api/seed-demo", { method: "POST" });
        const data = await res.json();
        await loadState();
        showToast("Base restaurada", data.message, "success");
    } catch (err) {
        showToast("Erro", "Falha ao restaurar itens de demonstração.", "error");
    }
}

function openSettingsModal() {
    const s = appState.settings || {};
    document.getElementById("cfgSmtpEmail").value = s.smtp_email || "";
    document.getElementById("cfgSmtpPassword").value = "";
    document.getElementById("cfgSmtpPassword").placeholder = s.has_password
        ? "•••••••••••••••• (Token configurado)"
        : "xxxx xxxx xxxx xxxx";
    document.getElementById("cfgDefaultRecipient").value = s.default_recipient || "";
    document.getElementById("cfgSmtpHost").value = s.smtp_host || "smtp.gmail.com";
    document.getElementById("cfgSmtpPort").value = s.smtp_port || 587;

    const intervalVal = s.check_interval_minutes || 30;
    document.getElementById("cfgCheckInterval").value = intervalVal;
    document.getElementById("cfgIntervalSlider").value = intervalVal;
    document.getElementById("cfgAutoCheck").checked = Boolean(s.auto_check_enabled ?? true);

    document.getElementById("settingsModal").classList.remove("hidden");
}

async function handleSaveSettings(event) {
    event.preventDefault();
    const payload = {
        smtp_email: document.getElementById("cfgSmtpEmail").value.trim(),
        smtp_password: document.getElementById("cfgSmtpPassword").value.trim(),
        default_recipient: document.getElementById("cfgDefaultRecipient").value.trim(),
        smtp_host: document.getElementById("cfgSmtpHost").value.trim(),
        smtp_port: document.getElementById("cfgSmtpPort").value,
        check_interval_minutes: document.getElementById("cfgCheckInterval").value,
        auto_check_enabled: document.getElementById("cfgAutoCheck").checked
    };

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            closeModal("settingsModal");
            await loadState();
            showToast("Parâmetros atualizados", data.message, "success");
        }
    } catch (err) {
        showToast("Erro", "Falha ao salvar parâmetros.", "error");
    }
}

async function triggerTestEmail() {
    const typedRecipientEl = document.getElementById("cfgDefaultRecipient");
    const recipient = typedRecipientEl ? typedRecipientEl.value.trim() : "";

    try {
        const res = await fetch("/api/test-email", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ recipient })
        });
        const data = await res.json();
        await loadState();
        if (data.alert) {
            handleAlertNotification(data.alert, true);
        }
    } catch (err) {
        showToast("Erro", "Falha ao executar teste de envio.", "error");
    }
}

// =====================================================================
// 7. FILTROS, MODAIS E NOTIFICAÇÕES
// =====================================================================

function setFilter(filterName) {
    appState.currentFilter = filterName;
    document.querySelectorAll(".seg-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.filter === filterName);
    });
    renderProducts();
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.add("hidden");
}

function closeModalOnBackdrop(event, modalId) {
    if (event.target.id === modalId) {
        closeModal(modalId);
    }
}

function showToast(title, message, type = "info", includeEmailPreviewBtn = false) {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast-item ${type}`;

    toast.innerHTML = `
        <div class="toast-head">${escapeHTML(title)}</div>
        <div class="toast-body">${escapeHTML(message)}</div>
        ${includeEmailPreviewBtn ? `<button type="button" class="inline-action-link" style="margin-top:4px; color:#10b981;" onclick="openEmailPreviewModal()">Inspecionar e-mail HTML &rarr;</button>` : ""}
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.remove();
    }, 6000);
}

function escapeHTML(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// =====================================================================
// 8. V2 — MICROINTERAÇÕES, SPARKLINES E TICKER
// =====================================================================

let revealObserver = null;

/**
 * Revela elementos .fx-reveal ao entrarem na viewport (IntersectionObserver).
 * Depois da animação, remove a classe para não interferir no tilt/hover.
 */
function initRevealObserver() {
    revealObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const el = entry.target;
            el.classList.add("is-visible");
            revealObserver.unobserve(el);
            setTimeout(() => el.classList.remove("fx-reveal", "is-visible"), 1100);
        });
    }, { threshold: 0.12 });

    document.querySelectorAll(".fx-reveal").forEach(el => revealObserver.observe(el));
}

/**
 * Spotlight que segue o cursor + tilt 3D sutil nos cards (delegação de eventos).
 */
function initCardSpotlight() {
    const grid = document.getElementById("productsGrid");
    if (!grid) return;

    grid.addEventListener("pointermove", (event) => {
        if (event.pointerType === "touch") return;
        const card = event.target.closest(".product-card");
        if (!card) return;

        const rect = card.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        card.style.setProperty("--mx", `${x}px`);
        card.style.setProperty("--my", `${y}px`);

        const rotY = ((x / rect.width) - 0.5) * 5;
        const rotX = ((y / rect.height) - 0.5) * -5;
        card.style.transform = `perspective(800px) rotateX(${rotX}deg) rotateY(${rotY}deg)`;
    });

    grid.addEventListener("pointerout", (event) => {
        const card = event.target.closest(".product-card");
        if (card && !card.contains(event.relatedTarget)) {
            card.style.transform = "";
        }
    });
}

/**
 * Destaca no menu a seção atualmente visível.
 */
function initScrollSpy() {
    const links = document.querySelectorAll(".nav-link");
    const sections = ["sec-overview", "sec-ingest", "sec-catalog"]
        .map(id => document.getElementById(id))
        .filter(Boolean);

    const spy = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            links.forEach(link => {
                link.classList.toggle("active", link.getAttribute("href") === `#${entry.target.id}`);
            });
        });
    }, { rootMargin: "-40% 0px -50% 0px" });

    sections.forEach(section => spy.observe(section));
}

/**
 * Anima um número do valor anterior até o novo (count-up com easing).
 */
function animateValue(el, target, formatter) {
    if (!el) return;
    const from = Number(el.dataset.val ?? 0);
    const to = Number(target) || 0;
    el.dataset.val = to;

    if (from === to) {
        el.textContent = formatter(to);
        return;
    }

    const duration = 800;
    const start = performance.now();
    const step = (now) => {
        const progress = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = formatter(from + (to - from) * eased);
        if (progress < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}

/**
 * Gera o mini-gráfico SVG (sparkline) com a tendência desde a primeira coleta.
 */
function buildSparklineHTML(prod, isDeal) {
    const prices = (prod.history || []).map(h => h.price);
    if (prices.length < 2) {
        return `
            <div class="spark-row">
                <svg class="spark-svg" viewBox="0 0 120 38" preserveAspectRatio="none" aria-hidden="true">
                    <line x1="0" y1="19" x2="120" y2="19" stroke="rgba(255,255,255,0.14)" stroke-dasharray="3 4" />
                </svg>
                <div class="spark-trend flat"><strong>--</strong><span>aguardando</span></div>
            </div>`;
    }

    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min || 1;
    const w = 120, h = 38, pad = 4;
    const points = prices.map((p, i) => {
        const x = (i / (prices.length - 1)) * w;
        const y = pad + (1 - (p - min) / range) * (h - pad * 2);
        return [x, y];
    });
    const path = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const [lx, ly] = points[points.length - 1];

    const first = prices[0];
    const last = prices[prices.length - 1];
    const pct = first > 0 ? ((last - first) / first) * 100 : 0;
    const dir = pct < -0.05 ? "down" : pct > 0.05 ? "up" : "flat";
    const sign = pct > 0 ? "+" : "";

    return `
        <div class="spark-row">
            <svg class="spark-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
                <polyline class="spark-line ${isDeal ? "deal" : ""}" points="${path}" vector-effect="non-scaling-stroke" />
                <circle class="spark-dot ${isDeal ? "deal" : ""}" cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="2.6" />
            </svg>
            <div class="spark-trend ${dir}">
                <strong>${sign}${pct.toFixed(1)}%</strong>
                <span>desde a 1ª coleta</span>
            </div>
        </div>`;
}

/**
 * Preenche a faixa de cotações rolante (conteúdo duplicado para loop contínuo).
 */
function renderTicker() {
    const track = document.getElementById("tickerTrack");
    if (!track) return;

    const items = appState.products.map(prod => {
        const hist = prod.history || [];
        const prev = hist.length > 1 ? hist[hist.length - 2].price : prod.current_price;
        const diff = prod.current_price - prev;
        const dir = diff < 0 ? "down" : diff > 0 ? "up" : "flat";
        const arrow = diff < 0 ? "▼" : diff > 0 ? "▲" : "–";
        const pct = prev > 0 ? Math.abs((diff / prev) * 100).toFixed(1) : "0.0";
        const shortTitle = (prod.title || "").split(" ").slice(0, 4).join(" ");
        return `
            <span class="ticker-item">
                <span>${escapeHTML(shortTitle)}</span>
                <strong>${formatBRL(prod.current_price)}</strong>
                <span class="ticker-delta ${dir}">${arrow} ${pct}%</span>
            </span>`;
    }).join("");

    if (!items) {
        track.innerHTML = "";
        return;
    }
    track.innerHTML = items + items;
}

/* ==========================================================================
   Fault Diagnosis Papers — Application Logic
   State-driven vanilla JS, no framework dependencies.
   ========================================================================== */

(function () {
    "use strict";

    // -----------------------------------------------------------------------
    // Constants
    // -----------------------------------------------------------------------
    const CATEGORY_META = {
        deep_learning: { name: "基于深度学习的方法", icon: "🤖" },
        transfer_learning: { name: "迁移学习与域适应", icon: "🔄" },
        federated_learning: { name: "联邦学习与隐私保护", icon: "🔗" },
        explainable_ai: { name: "可解释性", icon: "🧠" },
        application_deployment: { name: "应用与部署", icon: "🏭" },
    };

    const BATCH_SIZE = 30;
    const STALE_THRESHOLD_DAYS = 30;
    const DEBOUNCE_MS = 250;

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------
    const state = {
        papers: [],
        categories: [],
        meta: null,

        // Filters
        searchQuery: "",
        activeCategory: "all",
        sortBy: "citations",

        // Pagination
        visibleCount: BATCH_SIZE,

        // UI states
        isLoading: true,
        hasError: false,
        errorMessage: "",
    };

    // -----------------------------------------------------------------------
    // DOM References (cached after DOMContentLoaded)
    // -----------------------------------------------------------------------
    let dom = {};

    function cacheDom() {
        dom = {
            // Header
            updateTime: document.getElementById("update-time"),
            totalCount: document.getElementById("total-count"),
            // Stale warning
            staleWarning: document.getElementById("stale-warning"),
            staleDays: document.getElementById("stale-days"),
            staleDismiss: document.getElementById("stale-dismiss"),
            // Search
            searchInput: document.getElementById("search-input"),
            searchClear: document.getElementById("search-clear"),
            // Category pills
            categoryPills: document.getElementById("category-pills"),
            // Sort
            sortSelect: document.getElementById("sort-select"),
            // Result count
            resultCount: document.getElementById("result-count"),
            // Content areas
            loadingState: document.getElementById("loading-state"),
            errorState: document.getElementById("error-state"),
            errorMsg: document.getElementById("error-msg"),
            emptyState: document.getElementById("empty-state"),
            paperGrid: document.getElementById("paper-grid"),
            // Load more
            loadMoreWrapper: document.getElementById("load-more-wrapper"),
            loadMoreBtn: document.getElementById("load-more-btn"),
            loadMoreRemaining: document.getElementById("load-more-remaining"),
            // Buttons
            retryBtn: document.getElementById("retry-btn"),
            clearFiltersBtn: document.getElementById("clear-filters-btn"),
        };
    }

    // -----------------------------------------------------------------------
    // Utility Functions
    // -----------------------------------------------------------------------

    function debounce(fn, delay) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    function formatDate(isoString) {
        if (!isoString) return "--";
        try {
            const d = new Date(isoString);
            return d.toLocaleDateString("zh-CN", {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
            });
        } catch {
            return isoString;
        }
    }

    function daysSince(isoString) {
        if (!isoString) return Infinity;
        try {
            const then = new Date(isoString);
            const now = new Date();
            return Math.floor((now - then) / (1000 * 60 * 60 * 24));
        } catch {
            return Infinity;
        }
    }

    function formatAuthors(authors) {
        if (!authors || authors.length === 0) return "Unknown";
        if (authors.length <= 3) return authors.join(", ");
        return authors.slice(0, 3).join(", ") + " et al.";
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    // -----------------------------------------------------------------------
    // Data Loading
    // -----------------------------------------------------------------------

    async function loadPapers() {
        state.isLoading = true;
        state.hasError = false;
        render();

        // Safety fallback: force hide loading after 10 seconds
        var loadTimeout = setTimeout(function () {
            if (state.isLoading) {
                console.warn("Loading timeout triggered — forcing error state");
                state.isLoading = false;
                state.hasError = true;
                state.errorMessage = "数据加载超时，请检查网络连接后刷新页面。";
                render();
            }
        }, 10000);

        try {
            var resp = await fetch("data/papers.json");
            if (!resp.ok) {
                throw new Error("HTTP " + resp.status + ": " + resp.statusText);
            }
            var data = await resp.json();

            state.papers = data.papers || [];
            state.categories = data.categories || [];
            state.meta = data.meta || null;
            state.isLoading = false;
            clearTimeout(loadTimeout);

            // Each step wrapped individually so one failure doesn't block others
            try { restoreStateFromHash(); } catch (e) { console.error(e); }
            try { applyFilters(); } catch (e) { console.error(e); }
            try { render(); } catch (e) { console.error(e); }
            try { saveStateToHash(); } catch (e) { console.error(e); }
            try { checkStaleness(); } catch (e) { console.error(e); }
        } catch (err) {
            console.error("Failed to load papers:", err);
            clearTimeout(loadTimeout);
            state.isLoading = false;
            state.hasError = true;
            state.errorMessage = err.message || "网络请求失败，请检查网络连接后重试。";
            try { render(); } catch (e) { console.error(e); }
        }
    }

    // -----------------------------------------------------------------------
    // Filtering & Sorting
    // -----------------------------------------------------------------------

    function applyFilters() {
        let result = [...state.papers];

        // 1. Category filter
        if (state.activeCategory !== "all") {
            result = result.filter((p) => p.category === state.activeCategory);
        }

        // 2. Search query (AND logic over whitespace-separated terms)
        if (state.searchQuery.trim().length > 0) {
            const terms = state.searchQuery.trim().toLowerCase().split(/\s+/);
            result = result.filter((p) => {
                const searchable = [
                    p.title || "",
                    p.abstract || "",
                    (p.authors || []).join(" "),
                    p.venue || "",
                    (CATEGORY_META[p.category] || {}).name || "",
                ]
                    .join(" ")
                    .toLowerCase();
                return terms.every((term) => searchable.includes(term));
            });
        }

        state._filteredPapers = result;
        applySortAndLimit();
    }

    function applySortAndLimit() {
        const sorted = [...(state._filteredPapers || [])];

        switch (state.sortBy) {
            case "citations":
                sorted.sort((a, b) => (b.citationCount || 0) - (a.citationCount || 0));
                break;
            case "year-desc":
                sorted.sort((a, b) => (b.year || 0) - (a.year || 0));
                break;
            case "year-asc":
                sorted.sort((a, b) => (a.year || 0) - (b.year || 0));
                break;
            case "title":
                sorted.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
                break;
            default:
                sorted.sort((a, b) => (b.citationCount || 0) - (a.citationCount || 0));
        }

        state._sortedPapers = sorted;
        state._displayedPapers = sorted.slice(0, state.visibleCount);
    }

    // -----------------------------------------------------------------------
    // Render
    // -----------------------------------------------------------------------

    function render() {
        renderHeader();
        renderSearch();
        renderCategoryPills();
        renderSortSelect();
        renderResultCount();
        renderContent();
        renderLoadMore();
        updateCategoryPillCounts();
    }

    function renderHeader() {
        if (state.meta) {
            dom.updateTime.innerHTML =
                '<span class="meta-badge__icon">🕐</span> ' + formatDate(state.meta.lastUpdated);
            dom.totalCount.innerHTML =
                '<span class="meta-badge__icon">📄</span> ' + state.meta.totalPapers + " 篇论文";
        }
    }

    function renderSearch() {
        dom.searchClear.hidden = state.searchQuery.length === 0;
    }

    function renderCategoryPills() {
        const pills = dom.categoryPills.querySelectorAll(".category-pill");
        pills.forEach((pill) => {
            const cat = pill.dataset.category;
            if (cat === state.activeCategory) {
                pill.classList.add("active");
                pill.setAttribute("aria-selected", "true");
            } else {
                pill.classList.remove("active");
                pill.setAttribute("aria-selected", "false");
            }
        });
    }

    function updateCategoryPillCounts() {
        if (!state.meta || !state.meta.categoryStats) return;

        const allCount = state.papers.length;
        setPillCount("all", allCount);

        for (const [catId, count] of Object.entries(state.meta.categoryStats)) {
            setPillCount(catId, count);
        }
    }

    function setPillCount(catId, count) {
        const el = document.getElementById("pill-count-" + catId);
        if (el) {
            el.textContent = `(${count})`;
        }
    }

    function renderSortSelect() {
        dom.sortSelect.value = state.sortBy;
    }

    function renderResultCount() {
        const total = (state._filteredPapers || []).length;
        const shown = (state._displayedPapers || []).length;
        dom.resultCount.textContent = `显示 ${shown} / ${total} 篇论文`;
    }

    function renderContent() {
        // Hide all state containers first
        dom.loadingState.hidden = true;
        dom.errorState.hidden = true;
        dom.emptyState.hidden = true;
        dom.paperGrid.innerHTML = "";

        if (state.isLoading) {
            dom.loadingState.hidden = false;
            return;
        }

        if (state.hasError) {
            dom.errorState.hidden = false;
            dom.errorMsg.textContent = state.errorMessage;
            return;
        }

        const displayed = state._displayedPapers || [];
        if (displayed.length === 0) {
            dom.emptyState.hidden = false;
            return;
        }

        // Build paper cards using DocumentFragment
        const fragment = document.createDocumentFragment();
        displayed.forEach((paper) => {
            fragment.appendChild(createPaperCard(paper));
        });
        dom.paperGrid.appendChild(fragment);
    }

    function renderLoadMore() {
        const total = (state._filteredPapers || []).length;
        const shown = (state._displayedPapers || []).length;
        const remaining = total - shown;

        if (remaining > 0) {
            dom.loadMoreWrapper.hidden = false;
            dom.loadMoreRemaining.textContent = remaining;
        } else {
            dom.loadMoreWrapper.hidden = true;
        }
    }

    // -----------------------------------------------------------------------
    // Paper Card Factory
    // -----------------------------------------------------------------------

    function createPaperCard(paper) {
        const card = document.createElement("article");
        card.className = "paper-card";
        card.dataset.category = paper.category;
        card.dataset.year = paper.year;

        // Title
        const title = document.createElement("h2");
        title.className = "paper-card__title";
        const link = document.createElement("a");
        link.href = paper.url || "#";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = paper.title || "Untitled";
        title.appendChild(link);
        card.appendChild(title);

        // Authors
        const authors = document.createElement("p");
        authors.className = "paper-card__authors";
        const authorStr = formatAuthors(paper.authors);
        authors.textContent = authorStr;
        if (paper.authors && paper.authors.length > 3) {
            const more = document.createElement("span");
            more.className = "paper-card__authors-more";
            more.textContent = ` (共 ${paper.authors.length} 位作者)`;
            more.title = paper.authors.join("; ");
            authors.appendChild(more);
        }
        card.appendChild(authors);

        // Meta row: venue + year
        const meta = document.createElement("div");
        meta.className = "paper-card__meta";

        if (paper.venue) {
            const venueSpan = document.createElement("span");
            venueSpan.className = "paper-card__venue";
            venueSpan.textContent = paper.venue;
            meta.appendChild(venueSpan);
        }

        if (paper.year) {
            if (paper.venue) {
                const sep = document.createElement("span");
                sep.className = "paper-card__meta-sep";
                sep.textContent = "·";
                meta.appendChild(sep);
            }
            const yearSpan = document.createElement("span");
            yearSpan.textContent = String(paper.year);
            meta.appendChild(yearSpan);
        }

        // Source tag
        if (paper.source) {
            const sep = document.createElement("span");
            sep.className = "paper-card__meta-sep";
            sep.textContent = "·";
            meta.appendChild(sep);
            const srcTag = document.createElement("span");
            srcTag.className = "paper-card__source-tag";
            srcTag.textContent = paper.source === "semantic_scholar" ? "S2" : "arXiv";
            meta.appendChild(srcTag);
        }

        card.appendChild(meta);

        // Abstract with expand toggle
        if (paper.abstract) {
            const abstract = document.createElement("p");
            abstract.className = "paper-card__abstract";
            abstract.textContent = paper.abstract;
            card.appendChild(abstract);

            // Only show toggle if abstract is long enough
            if (paper.abstract.length > 200) {
                const toggle = document.createElement("button");
                toggle.className = "paper-card__abstract-toggle";
                toggle.textContent = "展开摘要 ▼";
                toggle.addEventListener("click", () => {
                    const isExpanded = abstract.classList.toggle("expanded");
                    toggle.textContent = isExpanded ? "收起摘要 ▲" : "展开摘要 ▼";
                });
                card.appendChild(toggle);
            }
        }

        // Footer
        const footer = document.createElement("div");
        footer.className = "paper-card__footer";

        // Badges (citations + category + year)
        const badges = document.createElement("div");
        badges.className = "paper-card__badges";

        // Citation count
        const citations = document.createElement("span");
        citations.className = "paper-card__citations";
        citations.textContent = `📊 引用 ${paper.citationCount || 0}`;
        citations.title = `引用次数: ${paper.citationCount || 0}`;
        badges.appendChild(citations);

        // Category tag
        const catMeta = CATEGORY_META[paper.category];
        if (catMeta) {
            const catTag = document.createElement("span");
            catTag.className = "paper-card__category-tag";
            catTag.textContent = catMeta.icon + " " + catMeta.name;
            badges.appendChild(catTag);
        }

        footer.appendChild(badges);

        // External link button
        if (paper.url) {
            const extLink = document.createElement("a");
            extLink.className = "paper-card__external-link";
            extLink.href = paper.url;
            extLink.target = "_blank";
            extLink.rel = "noopener noreferrer";
            extLink.textContent = "📄 查看论文";
            footer.appendChild(extLink);
        }

        card.appendChild(footer);
        return card;
    }

    // -----------------------------------------------------------------------
    // Staleness Check
    // -----------------------------------------------------------------------

    function checkStaleness() {
        if (!state.meta || !state.meta.lastUpdated) return;

        const days = daysSince(state.meta.lastUpdated);
        if (days > STALE_THRESHOLD_DAYS) {
            dom.staleWarning.hidden = false;
            dom.staleDays.textContent = days;
        } else {
            dom.staleWarning.hidden = true;
        }
    }

    // -----------------------------------------------------------------------
    // URL Hash State
    // -----------------------------------------------------------------------

    function saveStateToHash() {
        const params = new URLSearchParams();
        if (state.activeCategory !== "all") params.set("cat", state.activeCategory);
        if (state.searchQuery) params.set("q", state.searchQuery);
        if (state.sortBy !== "citations") params.set("sort", state.sortBy);
        const hash = params.toString();
        history.replaceState(null, "", hash ? "#" + hash : window.location.pathname);
    }

    function restoreStateFromHash() {
        const hash = window.location.hash.slice(1);
        if (!hash) return;
        const params = new URLSearchParams(hash);
        if (params.has("cat")) {
            const cat = params.get("cat");
            if (cat === "all" || CATEGORY_META[cat]) {
                state.activeCategory = cat;
            }
        }
        if (params.has("q")) {
            state.searchQuery = params.get("q") || "";
        }
        if (params.has("sort")) {
            const sort = params.get("sort");
            if (["citations", "year-desc", "year-asc", "title"].includes(sort)) {
                state.sortBy = sort;
            }
        }
        // Sync search input
        if (dom.searchInput) {
            dom.searchInput.value = state.searchQuery;
        }
    }

    // -----------------------------------------------------------------------
    // Event Handlers
    // -----------------------------------------------------------------------

    function setupEvents() {
        // Each listener guarded independently — one broken element won't kill others

        // Search input (debounced)
        if (dom.searchInput) {
            dom.searchInput.addEventListener(
                "input",
                debounce(function () {
                    state.searchQuery = this.value.trim();
                    state.visibleCount = BATCH_SIZE;
                    try { applyFilters(); } catch (e) { console.error(e); }
                    try { render(); } catch (e) { console.error(e); }
                    try { saveStateToHash(); } catch (e) { console.error(e); }
                }, DEBOUNCE_MS)
            );
        }

        // Search clear
        if (dom.searchClear) {
            dom.searchClear.addEventListener("click", function () {
                dom.searchInput.value = "";
                state.searchQuery = "";
                state.visibleCount = BATCH_SIZE;
                try { applyFilters(); } catch (e) { console.error(e); }
                try { render(); } catch (e) { console.error(e); }
                try { saveStateToHash(); } catch (e) { console.error(e); }
                if (dom.searchInput) dom.searchInput.focus();
            });
        }

        // Category pills (event delegation)
        if (dom.categoryPills) {
            dom.categoryPills.addEventListener("click", function (e) {
                // closest() polyfill for older browsers
                var el = e.target;
                while (el && el !== dom.categoryPills) {
                    if (el.classList && el.classList.contains("category-pill")) break;
                    el = el.parentElement;
                }
                if (!el || el === dom.categoryPills) return;

                var cat = el.dataset.category;
                state.activeCategory = cat;
                state.visibleCount = BATCH_SIZE;
                try { applyFilters(); } catch (err) { console.error(err); }
                try { render(); } catch (err) { console.error(err); }
                try { saveStateToHash(); } catch (err) { console.error(err); }

                try {
                    el.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
                } catch (_) { /* ignore scroll errors */ }
            });
        }

        // Sort select
        if (dom.sortSelect) {
            dom.sortSelect.addEventListener("change", function () {
                state.sortBy = this.value;
                state.visibleCount = BATCH_SIZE;
                try { applySortAndLimit(); } catch (err) { console.error(err); }
                try { render(); } catch (err) { console.error(err); }
                try { saveStateToHash(); } catch (err) { console.error(err); }
            });
        }

        // Load more
        if (dom.loadMoreBtn) {
            dom.loadMoreBtn.addEventListener("click", function () {
                state.visibleCount += BATCH_SIZE;
                try { applySortAndLimit(); } catch (err) { console.error(err); }
                try { render(); } catch (err) { console.error(err); }
            });
        }

        // Retry button
        if (dom.retryBtn) {
            dom.retryBtn.addEventListener("click", function () {
                loadPapers();
            });
        }

        // Clear filters button
        if (dom.clearFiltersBtn) {
            dom.clearFiltersBtn.addEventListener("click", function () {
                state.searchQuery = "";
                state.activeCategory = "all";
                state.sortBy = "citations";
                state.visibleCount = BATCH_SIZE;
                if (dom.searchInput) dom.searchInput.value = "";
                try { applyFilters(); } catch (err) { console.error(err); }
                try { render(); } catch (err) { console.error(err); }
                try { saveStateToHash(); } catch (err) { console.error(err); }
            });
        }

        // Stale warning dismiss
        if (dom.staleDismiss) {
            dom.staleDismiss.addEventListener("click", function () {
                dom.staleWarning.hidden = true;
            });
        }

        // Browser back/forward
        window.addEventListener("hashchange", function () {
            try { restoreStateFromHash(); } catch (err) { console.error(err); }
            if (dom.searchInput) dom.searchInput.value = state.searchQuery;
            try { applyFilters(); } catch (err) { console.error(err); }
            try { render(); } catch (err) { console.error(err); }
        });
    }

    // -----------------------------------------------------------------------
    // Initialize
    // -----------------------------------------------------------------------

    function init() {
        cacheDom();
        setupEvents();
        loadPapers();
    }

    // Start when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();

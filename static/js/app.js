// Client-side enhancements: instant button feedback, AJAX toggles, and the
// human-friendly schedule builder. No framework — kept deliberately simple.

document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initAlerts();
    initFormLoadingStates();
    initAjaxToggles();
    initScheduleBuilder();
    initRewritePreview();
    initPasswordToggles();
});

// Adds a show/hide eye icon to every password field wrapped in a
// .password-field container, so people can verify what they typed instead
// of guessing blind — especially useful for pasted or complex passwords.
function initPasswordToggles() {
    document.querySelectorAll(".password-toggle-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const wrapper = btn.closest(".password-field");
            const input = wrapper ? wrapper.querySelector("input") : null;
            if (!input) return;
            const showing = input.type === "text";
            input.type = showing ? "password" : "text";
            btn.classList.toggle("showing", !showing);
        });
    });
}

// Day/night theme, persisted in localStorage. Applied as early as possible
// (before other init) so there's no flash of the wrong theme.
function initTheme() {
    const saved = localStorage.getItem("relay-theme") || "dark";
    applyTheme(saved);

    document.querySelectorAll("[data-theme-btn]").forEach((btn) => {
        btn.addEventListener("click", () => {
            applyTheme(btn.getAttribute("data-theme-btn"));
        });
    });
}

function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("relay-theme", theme);
    document.querySelectorAll("[data-theme-btn]").forEach((btn) => {
        btn.classList.toggle("active", btn.getAttribute("data-theme-btn") === theme);
    });
}

// Auto-dismiss alert banners.
function initAlerts() {
    document.querySelectorAll(".alert").forEach((el) => {
        setTimeout(() => {
            el.style.transition = "opacity 0.4s";
            el.style.opacity = "0";
            setTimeout(() => el.remove(), 400);
        }, 4000);
    });
}

// Give every submit button instant visual feedback (spinner + disabled)
// the moment a form is submitted, so the UI never feels unresponsive even
// while the server round-trip is in flight.
function initFormLoadingStates() {
    document.querySelectorAll("form").forEach((form) => {
        form.addEventListener("submit", () => {
            const btn = form.querySelector('button[type="submit"], .btn-primary');
            if (!btn) return;
            if (!btn.querySelector(".btn-text-default")) {
                btn.innerHTML =
                    '<span class="btn-text-default">' + btn.textContent.trim() + "</span><span class=\"spinner\"></span>";
            }
            btn.classList.add("is-loading");
            btn.setAttribute("disabled", "disabled");
        });
    });
}

// Elements with [data-ajax-toggle="/some/url"] flip instantly via fetch
// instead of a full page reload/redirect, so pausing a schedule or
// disabling a source feels immediate.
function initAjaxToggles() {
    document.querySelectorAll("[data-ajax-toggle]").forEach((input) => {
        input.addEventListener("change", async () => {
            const url = input.getAttribute("data-ajax-toggle");
            const row = input.closest("[data-toggle-row]");
            const statusText = row ? row.querySelector(".toggle-status-text") : null;
            const optimistic = input.checked;
            if (statusText) statusText.textContent = optimistic ? "On" : "Off";

            try {
                const res = await fetch(url, {
                    method: "POST",
                    headers: { "X-Requested-With": "fetch" },
                });
                if (!res.ok) throw new Error("Request failed");
                const data = await res.json();
                const isActive = "is_active" in data ? data.is_active : optimistic;
                input.checked = isActive;
                if (statusText) statusText.textContent = isActive ? "On" : "Off";
            } catch (err) {
                // Revert on failure so the UI never lies about server state.
                input.checked = !optimistic;
                if (statusText) statusText.textContent = !optimistic ? "On" : "Off";
                console.error("Toggle failed:", err);
            }
        });
    });
}

// ---------------- Schedule builder ----------------
// Translates a plain-language frequency choice into a cron expression,
// so most users never have to think about cron syntax at all.
const FREQ_PRESETS = [
    { key: "15m", label: "Every 15 min", cron: () => "*/15 * * * *" },
    { key: "30m", label: "Every 30 min", cron: () => "*/30 * * * *" },
    { key: "1h", label: "Every hour", cron: () => "0 * * * *" },
    { key: "3h", label: "Every 3 hours", cron: () => "0 */3 * * *" },
    { key: "6h", label: "Every 6 hours", cron: () => "0 */6 * * *" },
    { key: "daily", label: "Once a day", cron: (time) => {
        const [h, m] = (time || "09:00").split(":");
        return `${parseInt(m, 10)} ${parseInt(h, 10)} * * *`;
    } },
];

function initScheduleBuilder() {
    const wrapper = document.querySelector("[data-schedule-builder]");
    if (!wrapper) return;

    const cronInput = wrapper.querySelector('input[name="cron_expression"]');
    const chipContainer = wrapper.querySelector(".freq-grid");
    const dailyTime = wrapper.querySelector('input[name="daily_time"]');
    const preview = wrapper.querySelector(".cron-preview code");
    const advancedToggle = wrapper.querySelector(".advanced-toggle");
    const advancedBox = wrapper.querySelector(".advanced-cron");

    let selectedKey = "30m";

    function applyPreset(key) {
        selectedKey = key;
        chipContainer.querySelectorAll(".freq-chip").forEach((chip) => {
            chip.classList.toggle("selected", chip.dataset.freq === key);
        });
        const preset = FREQ_PRESETS.find((p) => p.key === key);
        if (!preset) return;
        if (dailyTime) dailyTime.style.display = key === "daily" ? "block" : "none";
        const cron = preset.cron(dailyTime ? dailyTime.value : null);
        cronInput.value = cron;
        if (preview) preview.textContent = cron;
    }

    chipContainer.querySelectorAll(".freq-chip").forEach((chip) => {
        chip.addEventListener("click", () => applyPreset(chip.dataset.freq));
    });

    if (dailyTime) {
        dailyTime.addEventListener("change", () => {
            if (selectedKey === "daily") applyPreset("daily");
        });
    }

    if (advancedToggle) {
        advancedToggle.addEventListener("click", () => {
            advancedBox.classList.toggle("open");
            advancedToggle.textContent = advancedBox.classList.contains("open")
                ? "Hide custom cron expression"
                : "Need a custom schedule? Enter a cron expression";
        });
    }

    cronInput.addEventListener("input", () => {
        if (preview) preview.textContent = cronInput.value;
        chipContainer.querySelectorAll(".freq-chip").forEach((chip) => chip.classList.remove("selected"));
    });

    applyPreset(selectedKey);
}

// ---------------- Rewrite preview ----------------
// Lets an admin see, before turning a source live, what Gemini will
// actually produce given the current persona/keywords/language settings.
function initRewritePreview() {
    const btn = document.querySelector("[data-preview-rewrite]");
    if (!btn) return;

    btn.addEventListener("click", async (e) => {
        e.preventDefault();
        const form = btn.closest("form");
        const box = document.querySelector(".preview-box");
        const originalEl = box.querySelector(".preview-original");
        const rewrittenEl = box.querySelector(".preview-rewritten");

        btn.classList.add("is-loading");
        btn.setAttribute("disabled", "disabled");
        box.classList.add("visible");
        originalEl.textContent = "Fetching a live sample…";
        rewrittenEl.textContent = "";

        const formData = new FormData(form);

        try {
            const res = await fetch("/sources/preview-rewrite", {
                method: "POST",
                body: formData,
                headers: { "X-Requested-With": "fetch" },
            });
            const data = await res.json();
            if (data && data.error) {
                originalEl.textContent = data.error;
                rewrittenEl.textContent = "";
            } else if (data && data.original_preview) {
                originalEl.textContent = data.original_preview + "…";
                rewrittenEl.textContent = data.rewritten || "";
            } else {
                originalEl.textContent = "Unexpected response from the server. Check the terminal log for details.";
                rewrittenEl.textContent = "";
            }
        } catch (err) {
            originalEl.textContent = "Something went wrong fetching the preview. Check your Gemini API key and try again.";
        } finally {
            btn.classList.remove("is-loading");
            btn.removeAttribute("disabled");
        }
    });
}

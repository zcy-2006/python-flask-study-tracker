document.addEventListener("DOMContentLoaded", function () {
    const root = document.documentElement;
    const toggle = document.getElementById("theme-toggle");

    function updateToggle() {
        if (!toggle) return;
        const isDark = root.getAttribute("data-bs-theme") === "dark";
        toggle.textContent = isDark ? "☀️" : "🌙";
        toggle.setAttribute("aria-pressed", String(isDark));
    }

    if (toggle) {
        updateToggle();
        toggle.addEventListener("click", function () {
            const nextTheme = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
            root.setAttribute("data-bs-theme", nextTheme);
            try {
                localStorage.setItem("study-theme", nextTheme);
            } catch (error) {
                // Theme still applies when local storage is unavailable.
            }
            updateToggle();
        });
    }

    document.addEventListener("submit", function (event) {
        const message = event.target.dataset.confirm;
        if (message && !window.confirm(message)) {
            event.preventDefault();
        }
    });

    document.querySelectorAll(".alert-dismissible").forEach(function (alert) {
        window.setTimeout(function () {
            const instance = window.bootstrap && window.bootstrap.Alert.getOrCreateInstance(alert);
            if (instance) instance.close();
        }, 5000);
    });

    document.addEventListener("keydown", function (event) {
        const target = event.target;
        const typing = target && (
            target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.tagName === "SELECT" ||
            target.isContentEditable
        );

        if (!typing && event.key === "/") {
            const search = document.getElementById("q");
            if (search) {
                event.preventDefault();
                search.focus();
                search.select();
            }
        }

        if (!typing && event.key.toLowerCase() === "n") {
            const newLink = document.querySelector('a[href$="/records/new"]');
            if (newLink) {
                event.preventDefault();
                window.location.href = newLink.href;
            }
        }

        if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && target && target.form) {
            event.preventDefault();
            target.form.requestSubmit();
        }
    });
});

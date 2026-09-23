(function () {
    try {
        const saved = localStorage.getItem("study-theme");
        const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        document.documentElement.setAttribute("data-bs-theme", saved || (prefersDark ? "dark" : "light"));
    } catch (error) {
        document.documentElement.setAttribute("data-bs-theme", "light");
    }
})();

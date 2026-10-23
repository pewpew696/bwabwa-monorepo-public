(function () {
  var STORAGE_KEY = "bwabwa-theme";
  var root = document.documentElement;

  function readStoredTheme() {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch (error) {
      return null;
    }
  }

  function storeTheme(theme) {
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch (error) {
      return;
    }
  }

  root.setAttribute("data-theme", readStoredTheme() === "light" ? "light" : "dark");

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) {
      return;
    }
    var nextTheme = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", nextTheme);
    storeTheme(nextTheme);
  });
})();

// webapp/static/toast.js — toast ringan + auto-clear untuk htmx swap.
(function () {
  var TOAST_ROOT_ID = "toast-root";
  var TOAST_LIFETIME_MS = 5000;
  var timerId = null;

  function clearToast() {
    var root = document.getElementById(TOAST_ROOT_ID);
    if (root) root.innerHTML = "";
  }

  function showToast(message) {
    var root = document.getElementById(TOAST_ROOT_ID);
    if (!root) return;
    root.innerHTML = '<div class="toast">' + message + '</div>';
    window.clearTimeout(timerId);
    timerId = window.setTimeout(clearToast, TOAST_LIFETIME_MS);
  }

  window.rishuuToast = showToast;

  document.addEventListener("htmx:afterSwap", function (event) {
    var toastRoot = document.getElementById(TOAST_ROOT_ID);
    if (!toastRoot || event.detail.target !== toastRoot) return;
    window.clearTimeout(timerId);
    timerId = window.setTimeout(clearToast, TOAST_LIFETIME_MS);
  });
})();

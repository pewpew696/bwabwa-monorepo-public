(function () {
  var MODAL_ROOT_ID = "modal-root";

  function clearModal() {
    var modalRoot = document.getElementById(MODAL_ROOT_ID);
    if (modalRoot) {
      modalRoot.innerHTML = "";
    }
  }

  function isSafePath(path) {
    return typeof path === "string" && path.charAt(0) === "/" && path.charAt(1) !== "/";
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-modal-close]")) {
      clearModal();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      clearModal();
    }
  });

  document.addEventListener("auth-upgraded", function (event) {
    var form = event.target;
    var retryUrl = form && form.dataset ? form.dataset.retryUrl : "";
    var retryTarget = form && form.dataset ? form.dataset.retryTarget : "";
    clearModal();
    if (isSafePath(retryUrl) && retryTarget && document.getElementById(retryTarget)) {
      window.htmx.ajax("GET", retryUrl, { target: "#" + retryTarget, swap: "innerHTML" });
      return;
    }
    window.location.reload();
  });
})();

// Unit 15: kalau icon item gagal load, hapus img → text fallback kelihatan.
(function () {
  document.addEventListener(
    "error",
    function (e) {
      var t = e.target;
      if (t && t.classList && t.classList.contains("item-tok-img")) {
        t.remove();
      }
    },
    true
  );
})();

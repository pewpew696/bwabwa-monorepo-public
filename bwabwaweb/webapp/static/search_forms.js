// search_forms.js — handle submit form pencarian (player & MU).
// Form diarahkan ke URL /intel/player/<nama> atau /intel/mu/<nama>.
document.addEventListener("DOMContentLoaded", function () {
    var playerForm = document.getElementById("player-search");
    if (playerForm) {
        playerForm.addEventListener("submit", function (e) {
            e.preventDefault();
            var name = this.q.value.trim();
            if (!name) return;
            window.location.href = "/intel/player/" + encodeURIComponent(name);
        });
    }

    var muForm = document.getElementById("mu-search");
    if (muForm) {
        muForm.addEventListener("submit", function (e) {
            e.preventDefault();
            var name = this.q.value.trim();
            if (!name) return;
            window.location.href = "/intel/mu/" + encodeURIComponent(name);
        });
    }
});

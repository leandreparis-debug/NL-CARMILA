// Confort facultatif : la page fonctionne entièrement sans JavaScript.
// Affiche le champ « Autre enseigne » seulement quand « Autre… » est choisi.
(function () {
  "use strict";
  document.querySelectorAll("select.brand-select").forEach(function (select) {
    var field = document.getElementById(select.dataset.other);
    if (!field) { return; }
    var update = function () { field.hidden = select.value !== "autre"; };
    select.addEventListener("change", update);
    update();
  });
})();

"use strict";
/* O tema, escolhido antes da primeira pintura.
 *
 * Precisa ser um arquivo servido, e não um <script> dentro do HTML: o
 * servidor manda `script-src 'self'`, e script embutido é bloqueado. O
 * cabeçalho existe de propósito — um POST aqui emite nota fiscal —, então
 * quem se adapta é a tela.
 *
 * Deixar isto para o app.js, que carrega no fim do corpo, faria a tela
 * piscar branca por um quadro em quem usa o escuro. */
(function () {
  try {
    var guardado = localStorage.getItem("tema");
    document.documentElement.dataset.tema = guardado === "claro" ? "claro" : "escuro";
  } catch (e) {
    document.documentElement.dataset.tema = "escuro";
  }
})();

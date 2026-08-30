"use strict";
/* ==================================================================== *
 * Central de Notas — a tela.
 *
 * O motor fiscal é o Python que serve esta página. Ele é quem fala GWT-RPC
 * com o portal de São Bernardo, monta o corpo da requisição e sabe o que é
 * NBS, indicador de operação e classificação tributária.
 *
 * Aqui não há regra fiscal nenhuma. Esta camada desenha e pergunta. Duas
 * implementações da mesma regra divergem, e quando divergem a nota sai
 * errada — já aconteceu neste sistema com a razão social e com a descrição.
 * ==================================================================== */

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

/* ------------------------------------------------------------------ *
 * Conversa com o motor
 * ------------------------------------------------------------------ */

async function motor(rota, opcoes = {}) {
  let resposta;
  try {
    resposta = await fetch(rota, {
      ...opcoes,
      headers: { "Content-Type": "application/json", ...(opcoes.headers || {}) },
      cache: "no-store",
    });
  } catch (falha) {
    // fetch só rejeita quando não houve resposta: motor fechado, porta
    // trocada. Vale separar de um erro que o motor devolveu.
    const erro = new Error("O motor fiscal não respondeu.");
    erro.status = 0;
    throw erro;
  }
  const bruto = await resposta.text();
  let corpo = {};
  if (bruto) {
    try { corpo = JSON.parse(bruto); }
    catch { corpo = { error: bruto.slice(0, 240) }; }
  }
  if (!resposta.ok) {
    const erro = new Error(corpo.error || `o motor respondeu ${resposta.status}`);
    erro.status = resposta.status;
    erro.campo = corpo.field;
    erro.pendente = corpo.pending;
    throw erro;
  }
  return corpo;
}

/* ------------------------------------------------------------------ *
 * Formatação. Não valida nada — quem valida é o motor.
 * ------------------------------------------------------------------ */

const MOEDA = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

function paraNumero(valor) {
  if (typeof valor === "number") return Number.isFinite(valor) ? valor : 0;
  const texto = String(valor ?? "").trim();
  if (!texto) return 0;
  // "1.234,56" tem ponto de milhar e vírgula decimal. Trocar a vírgula por
  // ponto sem tirar o milhar antes transforma 1.234,56 em 1.234.56, e o
  // parse devolve 1,23 — mil reais a menos na soma.
  const brasileiro = /,\d{1,2}$/.test(texto);
  const limpo = brasileiro
    ? texto.replace(/\./g, "").replace(",", ".")
    : texto.replace(/,/g, "");
  const numero = Number.parseFloat(limpo.replace(/[^\d.-]/g, ""));
  return Number.isFinite(numero) ? numero : 0;
}

const dinheiro = (v) => MOEDA.format(paraNumero(v));
const exibir = (v) => estado.mascarado ? "R$ •••" : dinheiro(v);

function documento(bruto) {
  const d = String(bruto ?? "").replace(/\D/g, "");
  if (d.length === 14) return d.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
  if (d.length === 11) return d.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, "$1.$2.$3-$4");
  return String(bruto ?? "");
}

const dataBr = (iso) => {
  const t = String(iso ?? "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(t) ? t.split("-").reverse().join("/") : t;
};

function quando(iso) {
  const t = String(iso ?? "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(t)) return "";
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
  const dias = Math.round((hoje - new Date(t + "T00:00:00")) / 86400000);
  if (dias <= 0) return "hoje";
  if (dias === 1) return "ontem";
  if (dias < 30) return `há ${dias} dias`;
  if (dias < 60) return "há 1 mês";
  return `há ${Math.floor(dias / 30)} meses`;
}

/* ------------------------------------------------------------------ *
 * Leitura de uma nota
 * ------------------------------------------------------------------ */

const SITUACOES = {
  submitted: { rotulo: "Emitida",  classe: "ok",   tom: "var(--ok)" },
  draft:     { rotulo: "Rascunho", classe: "off",  tom: "var(--off)" },
  failed:    { rotulo: "Recusada", classe: "bad",  tom: "var(--bad)" },
};

/** Cor estável por prestador: a mesma empresa recebe sempre a mesma faixa. */
const TINTAS = ["#7c5cff", "#22d3ee", "#f472b6", "#34d399", "#fbbf24", "#a78bfa"];
function tintaDoPrestador(nome) {
  let soma = 0;
  for (const letra of nome) soma = (soma * 31 + letra.charCodeAt(0)) >>> 0;
  return TINTAS[soma % TINTAS.length];
}

/**
 * Quem emitiu a nota.
 *
 * Nota gravada antes de o programa registrar isso não tem o dado, e não há
 * de onde tirá-lo. Ela diz "não registrado" — que é a verdade — em vez de
 * ser atribuída a alguma empresa por chute.
 */
function prestadorDe(nota) {
  const p = (nota.payload || {}).prestador || {};
  const nome = String(p.razao_social || "").trim();
  if (nome) return nome;
  const ccm = String(p.inscricao || "").trim();
  return ccm ? `CCM ${ccm}` : "— não registrado";
}

const inscricaoDe = (nota) => String(((nota.payload || {}).prestador || {}).inscricao || "");
const servicoDe = (nota) => (nota.payload || {}).servico || {};
const tomadorDe = (nota) => (nota.payload || {}).tomador || {};
const valorDe = (nota) => paraNumero(servicoDe(nota).valor);
const numeroDe = (nota) => String((nota.nota || {}).numero || "");

function textoBuscavel(nota) {
  const s = servicoDe(nota), t = tomadorDe(nota);
  return [
    prestadorDe(nota), t.nome, t.documento, documento(t.documento),
    s.descricao, s.codigo,
    // O valor entra cru E formatado: quem procura digita 5600, e o formatado
    // é "5.600,00" — o ponto de milhar impede a busca por dígitos seguidos.
    s.valor, dinheiro(s.valor),
    numeroDe(nota), dataBr(nota.created_at),
    (SITUACOES[nota.status] || {}).rotulo,
  ].filter(Boolean).join(" ").toLowerCase();
}

/* ------------------------------------------------------------------ *
 * Estado
 * ------------------------------------------------------------------ */

const estado = {
  tela: "painel",
  notas: [],
  saude: null,
  configuracao: null,
  situacao: "todas",
  prestador: "todos",
  de: "",
  ate: "",
  busca: "",
  ordem: { col: "data", dir: "desc" },
  selecao: new Set(),
  mascarado: false,
  enviando: null,
  faixaFechada: false,
};

/* Empresa, período e busca — a situação entra depois, senão os contadores
   mudariam de número ao clicar num deles. */
function baseFiltrada() {
  const termo = estado.busca.trim().toLowerCase();
  return estado.notas.filter((nota) => {
    if (estado.prestador !== "todos" && prestadorDe(nota) !== estado.prestador) return false;
    const dia = String(nota.created_at || "").slice(0, 10);
    if (estado.de && dia < estado.de) return false;
    if (estado.ate && dia > estado.ate) return false;
    if (!termo) return true;
    const alvo = textoBuscavel(nota);
    return termo.split(/\s+/).every((parte) => alvo.includes(parte));
  });
}

function visiveis() {
  const base = baseFiltrada();
  const lista = estado.situacao === "todas"
    ? base : base.filter((n) => n.status === estado.situacao);
  const { col, dir } = estado.ordem;
  const peso = dir === "asc" ? 1 : -1;
  const chave = {
    status: (n) => (SITUACOES[n.status] || {}).rotulo || "",
    numero: (n) => numeroDe(n).padStart(12, "0"),
    prestador: prestadorDe,
    tomador: (n) => tomadorDe(n).nome || documento(tomadorDe(n).documento),
    servico: (n) => servicoDe(n).descricao || "",
    valor: valorDe,
    data: (n) => String(n.created_at || ""),
  }[col];
  return [...lista].sort((a, b) => {
    const x = chave(a), y = chave(b);
    return x > y ? peso : x < y ? -peso : 0;
  });
}

/* ------------------------------------------------------------------ *
 * Avisos flutuantes
 * ------------------------------------------------------------------ */

function avisar(titulo, texto = "", tom = "info") {
  const cores = { info: "var(--accent)", ok: "var(--ok)", alerta: "var(--wait)", erro: "var(--bad)" };
  const caixa = document.createElement("div");
  caixa.className = "aviso";
  caixa.style.setProperty("--tone", cores[tom] || cores.info);
  caixa.innerHTML = `<div><b></b>${texto ? "<span></span>" : ""}</div><button class="x" aria-label="Fechar">×</button>`;
  caixa.querySelector("b").textContent = titulo;
  if (texto) caixa.querySelector("span").textContent = texto;

  const sair = () => {
    caixa.classList.add("saindo");
    setTimeout(() => caixa.remove(), 200);
  };
  caixa.querySelector(".x").addEventListener("click", sair);
  caixa.addEventListener("click", sair);
  $("#avisos").appendChild(caixa);
  setTimeout(sair, tom === "erro" ? 9000 : 4500);
}

/* ------------------------------------------------------------------ *
 * Modal
 * ------------------------------------------------------------------ */

function abrirModal(titulo, pares) {
  const fundo = document.createElement("div");
  fundo.className = "fundo-modal";
  fundo.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="${titulo}">
      <header><h2></h2><button class="x" aria-label="Fechar">×</button></header>
      <div class="corpo"><dl></dl></div>
    </div>`;
  fundo.querySelector("h2").textContent = titulo;
  const lista = fundo.querySelector("dl");
  for (const [rotulo, valor] of pares) {
    const dt = document.createElement("dt");
    dt.textContent = rotulo;
    const dd = document.createElement("dd");
    dd.textContent = valor === "" || valor == null ? "—" : String(valor);
    lista.append(dt, dd);
  }
  const fechar = () => fundo.remove();
  fundo.querySelector(".x").addEventListener("click", fechar);
  fundo.addEventListener("click", (e) => { if (e.target === fundo) fechar(); });
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape") { fechar(); document.removeEventListener("keydown", esc); }
  });
  $("#modal-raiz").appendChild(fundo);
}

/* ------------------------------------------------------------------ *
 * Ícones
 * ------------------------------------------------------------------ */

const ICONE = {
  pdf:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/><path d="M9 17h6"/></svg>`,
  info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg>`,
  send: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m4 12 16-8-6 16-2.5-6z"/></svg>`,
  seta: `<span class="seta"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m8 9 4-4 4 4"/><path d="m16 15-4 4-4-4"/></svg></span>`,
};

/* ------------------------------------------------------------------ *
 * Contadores
 * ------------------------------------------------------------------ */

const GRUPOS = [
  { chave: "todas",     rotulo: "Todas",     tom: "accent" },
  { chave: "submitted", rotulo: "Emitidas",  tom: "ok" },
  { chave: "draft",     rotulo: "Rascunhos", tom: "off" },
  { chave: "failed",    rotulo: "Recusadas", tom: "bad" },
];

function pintarContadores() {
  const base = baseFiltrada();
  $("#contadores").innerHTML = GRUPOS.map((g) => {
    const lista = g.chave === "todas" ? base : base.filter((n) => n.status === g.chave);
    const soma = lista.reduce((t, n) => t + valorDe(n), 0);
    return `<button class="counter" type="button" data-grupo="${g.chave}" data-tom="${g.tom}"
              aria-pressed="${estado.situacao === g.chave}">
              <span class="k">${g.rotulo}</span>
              <span class="n mono">${lista.length}</span>
              <span class="v mono">${exibir(soma)}</span>
            </button>`;
  }).join("");

  const recusadas = base.filter((n) => n.status === "failed").length;
  const faixa = $("#faixa-falhas");
  if (recusadas && !estado.faixaFechada) {
    $("#faixa-falhas-txt").textContent = recusadas === 1
      ? "1 nota foi recusada pelo portal."
      : `${recusadas} notas foram recusadas pelo portal.`;
    faixa.classList.remove("oculto");
  } else {
    faixa.classList.add("oculto");
  }
}

/* ------------------------------------------------------------------ *
 * Cabeçalho ordenável
 * ------------------------------------------------------------------ */

const TITULOS = {
  status: "Situação", numero: "Nº", prestador: "Prestador",
  tomador: "Tomador", servico: "Serviço", valor: "Valor", data: "Emissão",
};

function pintarCabecalho() {
  $$("th[data-col]").forEach((th) => {
    const col = th.dataset.col;
    const ativo = estado.ordem.col === col;
    th.innerHTML = `<button type="button" ${ativo ? `data-dir="${estado.ordem.dir}"` : ""}>${TITULOS[col]} ${ICONE.seta}</button>`;
    th.querySelector("button").addEventListener("click", () => {
      if (estado.ordem.col === col) estado.ordem.dir = estado.ordem.dir === "asc" ? "desc" : "asc";
      else estado.ordem = { col, dir: "asc" };
      pintarCabecalho();
      pintarTabela();
    });
  });
}

/* ------------------------------------------------------------------ *
 * Tabela
 * ------------------------------------------------------------------ */

function pintarTabela() {
  const lista = visiveis();
  const corpo = $("#corpo");
  const filtrando = lista.length !== estado.notas.length;

  if (!lista.length) {
    corpo.innerHTML = `<tr><td colspan="9"><div class="vazio">
      <b>${filtrando ? "Nenhuma nota com esses filtros" : "Nenhuma nota ainda"}</b>
      ${filtrando
        ? "Tente outro prestador, outro período, ou limpe a busca."
        : "As notas que você emitir aparecem aqui, com número, situação e PDF."}
    </div></td></tr>`;
  } else {
    corpo.innerHTML = lista.map((nota) => {
      const sit = SITUACOES[nota.status] || SITUACOES.draft;
      const quem = prestadorDe(nota);
      const anonimo = quem.startsWith("—");
      const numero = numeroDe(nota);
      const temPdf = nota.status === "submitted" && numero;
      const podeEnviar = nota.status !== "submitted";
      const emCurso = estado.enviando === nota.id;
      const t = tomadorDe(nota), s = servicoDe(nota);
      return `
      <tr data-id="${nota.id}" data-sel="${estado.selecao.has(nota.id) ? 1 : 0}">
        <td><input class="chk" type="checkbox" data-id="${nota.id}" ${estado.selecao.has(nota.id) ? "checked" : ""} aria-label="Selecionar"></td>
        <td><span class="pill ${emCurso ? "wait" : sit.classe}"><span class="bola"></span>${emCurso ? "Enviando…" : sit.rotulo}</span></td>
        <td class="mono">${numero || '<span class="risco">—</span>'}</td>
        <td>
          <span class="prest ${anonimo ? "anonimo" : ""}">
            <span class="tag"></span>
            <span>
              <span class="quem"></span>
              ${inscricaoDe(nota) ? `<span class="ccm mono">CCM ${inscricaoDe(nota)}</span>` : ""}
            </span>
          </span>
        </td>
        <td class="tomador"><b></b><span class="mono" data-doc></span></td>
        <td><span class="servico"></span></td>
        <td class="fim mono">${exibir(s.valor)}</td>
        <td class="fim quando"><b class="mono">${dataBr(nota.created_at)}</b><span>${quando(nota.created_at)}</span></td>
        <td>
          <span class="acts">
            <button class="act pdf" type="button" data-acao="pdf" data-id="${nota.id}" title="${temPdf ? "Abrir em PDF" : "Só depois de emitida"}" ${temPdf ? "" : "disabled"}>${ICONE.pdf}</button>
            <button class="act" type="button" data-acao="detalhes" data-id="${nota.id}" title="Detalhes">${ICONE.info}</button>
            <button class="act" type="button" data-acao="enviar" data-id="${nota.id}" title="${podeEnviar ? "Enviar ao portal" : "Já enviada"}" ${podeEnviar ? "" : "disabled"}>${ICONE.send}</button>
          </span>
        </td>
      </tr>`;
    }).join("");

    // Nome do prestador, tomador e serviço entram como TEXTO, não como HTML:
    // vêm do portal e de quem digitou, e um "&" ou "<" na razão social não
    // pode virar marcação no meio da tabela.
    lista.forEach((nota, i) => {
      const tr = corpo.children[i];
      const quem = prestadorDe(nota);
      tr.querySelector(".prest .quem").textContent = quem;
      const faixa = tr.querySelector(".prest .tag");
      faixa.style.setProperty("--c", quem.startsWith("—") ? "var(--off)" : tintaDoPrestador(quem));
      // Sem razão social, o documento sobe para a linha de cima e a de baixo
      // fica vazia — repetir o mesmo CNPJ duas vezes só ocupa espaço.
      const t = tomadorDe(nota);
      const doc = documento(t.documento);
      tr.querySelector(".tomador b").textContent = t.nome || doc || "Sem tomador";
      tr.querySelector(".tomador [data-doc]").textContent = t.nome ? doc : "";
      const desc = String(servicoDe(nota).descricao || "—").replace(/\s+/g, " ");
      const alvo = tr.querySelector(".servico");
      alvo.textContent = desc;
      alvo.title = desc;
    });
  }

  const soma = lista.reduce((t, n) => t + valorDe(n), 0);
  $("#contagem").textContent = filtrando
    ? `${lista.length} de ${estado.notas.length} nota(s)`
    : `${estado.notas.length} nota(s)`;
  $("#soma").textContent = exibir(soma);
  $("#chk-todos").checked = lista.length > 0 && lista.every((n) => estado.selecao.has(n.id));
  pintarSelecao();
}

function pintarSelecao() {
  const n = estado.selecao.size;
  $("#selbar").classList.toggle("oculto", n === 0);
  if (!n) return;
  $("#sel-quem").innerHTML = `<b>${n}</b> nota${n > 1 ? "s" : ""} selecionada${n > 1 ? "s" : ""}`;
  const so = n === 1 ? notaPorId([...estado.selecao][0]) : null;
  $("#btn-pdf").disabled = !(so && so.status === "submitted" && numeroDe(so));
  $("#btn-detalhes").disabled = n !== 1;
  $("#btn-enviar").disabled = !(so && so.status !== "submitted");
}

const notaPorId = (id) => estado.notas.find((n) => n.id === id);

/* ------------------------------------------------------------------ *
 * Ações
 * ------------------------------------------------------------------ */

async function abrirPdf(id) {
  const nota = notaPorId(id);
  if (!nota) return;
  try {
    const { url } = await motor(`/documents/${encodeURIComponent(id)}/pdf-url`);
    // Aberto numa aba: o navegador atravessa proxy e certificado do Windows,
    // que é onde o download automático do programa costuma esbarrar.
    window.open(url, "_blank", "noopener");
    avisar("Abrindo no portal", `Nota nº ${numeroDe(nota)}.`, "ok");
  } catch (erro) {
    avisar(
      erro.pendente ? "Ainda não há o que abrir" : "Não consegui abrir",
      erro.pendente
        ? "Só depois de o portal aceitar a nota ela ganha número e código de verificação."
        : erro.message,
      "alerta",
    );
  }
}

function verDetalhes(id) {
  const nota = notaPorId(id);
  if (!nota) return;
  const s = servicoDe(nota), t = tomadorDe(nota), n = nota.nota || {};
  abrirModal(`Nota ${numeroDe(nota) ? "nº " + numeroDe(nota) : "(rascunho)"}`, [
    ["Situação", (SITUACOES[nota.status] || {}).rotulo || nota.status],
    ["Prestador", prestadorDe(nota)],
    ["Tomador", t.nome || "—"],
    ["Documento", documento(t.documento)],
    ["Serviço", s.codigo || "—"],
    ["Descrição", s.descricao || "—"],
    ["Valor", dinheiro(s.valor)],
    ["Alíquota", s.aliquota ? `${s.aliquota}%` : "—"],
    ["ISS", s.iss ? dinheiro(s.iss) : "—"],
    ["NBS", s.nbs || "—"],
    ["Indicador da operação", s.indicador_operacao || "—"],
    ["Classificação tributária", s.classificacao_tributaria || "—"],
    ["Situação tributária", s.situacao_tributaria || "—"],
    ["Competência", (nota.payload || {}).competencia || "—"],
    ["Código de verificação", n.codigo_verificacao || "—"],
    ["Criada em", dataBr(nota.created_at)],
  ]);
}

async function enviarAoPortal(id) {
  const nota = notaPorId(id);
  if (!nota) return;
  const numero = numeroDe(nota);
  if (nota.status === "submitted") {
    avisar("Já foi emitida", `Nota nº ${numero}. Não se emite duas vezes.`, "alerta");
    return;
  }
  // Confirmação explícita: depois daqui a nota existe no portal, e não há
  // desfazer. O aviso muda de texto conforme a transmissão esteja ligada.
  const transmitindo = estado.saude && estado.saude.live_mode;
  const pergunta = transmitindo
    ? `Emitir esta nota de ${dinheiro(servicoDe(nota).valor)} no portal?\n\nA transmissão está ATIVA: a nota vai existir de verdade, e não há como desfazer.`
    : `Preparar esta nota de ${dinheiro(servicoDe(nota).valor)}?\n\nO modo seguro está ligado: ela será montada e validada, mas NÃO será enviada.`;
  if (!window.confirm(pergunta)) return;

  estado.enviando = id;
  pintarTabela();
  try {
    const saida = await motor(`/documents/${encodeURIComponent(id)}/submit`, { method: "POST" });
    if (saida.transmitted) {
      avisar("Nota emitida", saida.message || "O portal aceitou.", "ok");
    } else {
      avisar("Não foi transmitida", saida.message || "Modo seguro: nada foi enviado.", "alerta");
    }
  } catch (erro) {
    avisar(
      erro.status === 409 ? "Nota já enviada" : "O portal recusou",
      erro.message + (erro.campo ? ` (campo: ${erro.campo})` : ""),
      "erro",
    );
  } finally {
    estado.enviando = null;
    await carregarNotas();
  }
}

/* ------------------------------------------------------------------ *
 * Painel
 * ------------------------------------------------------------------ */

function pintarPainel() {
  const notas = estado.notas;
  const emitidas = notas.filter((n) => n.status === "submitted");
  const cartoes = [
    { k: "Rascunhos", n: notas.filter((x) => x.status === "draft").length, d: "aguardando revisão", tom: "off" },
    { k: "Emitidas", n: emitidas.length, d: "no portal", tom: "ok" },
    { k: "Recusadas", n: notas.filter((x) => x.status === "failed").length, d: "precisam de atenção", tom: "bad" },
    { k: "Faturado", n: exibir(emitidas.reduce((t, x) => t + valorDe(x), 0)), d: "somando as emitidas", tom: "accent", compacto: true },
  ];
  $("#painel-cartoes").innerHTML = cartoes.map((c) => `
    <div class="cartao" data-tom="${c.tom}">
      <span class="k">${c.k}</span>
      <span class="n mono${c.compacto ? " compacto" : ""}">${c.n}</span>
      <span class="d">${c.d}</span>
    </div>`).join("");

  const recentes = [...notas]
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
    .slice(0, 6);
  const ul = $("#recentes");
  ul.innerHTML = recentes.length
    ? recentes.map((nota) => {
        const sit = SITUACOES[nota.status] || SITUACOES.draft;
        return `<li>
          <span class="txt"><b></b><span></span></span>
          <span class="mono">${exibir(servicoDe(nota).valor)}</span>
          <span class="pill ${sit.classe}"><span class="bola"></span>${sit.rotulo}${numeroDe(nota) ? " · nº " + numeroDe(nota) : ""}</span>
        </li>`;
      }).join("")
    : `<li class="linha-centro">Nenhuma nota ainda.</li>`;
  recentes.forEach((nota, i) => {
    const li = ul.children[i];
    li.querySelector("b").textContent = tomadorDe(nota).nome || documento(tomadorDe(nota).documento) || "Sem tomador";
    li.querySelector(".txt span").textContent =
      `${prestadorDe(nota)} · ${String(servicoDe(nota).descricao || "—").replace(/\s+/g, " ")}`;
  });
}

/* ------------------------------------------------------------------ *
 * Empresas
 * ------------------------------------------------------------------ */

function pintarEmpresas() {
  const porEmpresa = new Map();
  for (const nota of estado.notas) {
    const quem = prestadorDe(nota);
    const atual = porEmpresa.get(quem) || { notas: 0, emitidas: 0, total: 0, ccm: inscricaoDe(nota) };
    atual.notas += 1;
    if (nota.status === "submitted") { atual.emitidas += 1; atual.total += valorDe(nota); }
    porEmpresa.set(quem, atual);
  }
  const linhas = [...porEmpresa.entries()].sort((a, b) => b[1].notas - a[1].notas);
  $("#empresas-cartoes").innerHTML = linhas.length
    ? linhas.map(([quem, d]) => {
        const anonimo = quem.startsWith("—");
        return `<div class="cartao" ${anonimo ? 'data-tom="off"' : ""} data-empresa>
          <span class="k">${d.ccm ? "CCM " + d.ccm : "sem inscrição"}</span>
          <span class="n nome-empresa" data-nome></span>
          <span class="d">${d.notas} nota(s) · ${d.emitidas} emitida(s)</span>
          <span class="d mono total-empresa">${exibir(d.total)}</span>
        </div>`;
      }).join("")
    : `<p class="sem-nada">Nenhuma nota ainda.</p>`;
  linhas.forEach(([quem, dados], i) => {
    const cartao = $("#empresas-cartoes").children[i];
    if (!cartao || !cartao.hasAttribute("data-empresa")) return;
    cartao.querySelector("[data-nome]").textContent = quem;
    // Cor calculada entra por CSSOM: o CSP cuida de marcação, não de script
    // já autorizado, então isto passa onde style="..." não passaria.
    if (!quem.startsWith("—")) {
      cartao.style.setProperty("--tone", tintaDoPrestador(quem));
      cartao.style.borderLeft = "3px solid var(--tone)";
    }
  });
}

/* ------------------------------------------------------------------ *
 * Filtro de prestador
 * ------------------------------------------------------------------ */

function pintarFiltroPrestador() {
  const nomes = [...new Set(estado.notas.map(prestadorDe))].sort();
  const caixa = $("#f-prestador");
  const antes = estado.prestador;
  caixa.innerHTML = `<option value="todos">Todos</option>` +
    nomes.map((n) => `<option value="${n.replace(/"/g, "&quot;")}"></option>`).join("");
  nomes.forEach((n, i) => { caixa.options[i + 1].textContent = n; });
  caixa.value = nomes.includes(antes) ? antes : "todos";
  estado.prestador = caixa.value;
}

/* ------------------------------------------------------------------ *
 * Telas
 * ------------------------------------------------------------------ */

const TELAS = {
  painel: { titulo: "Painel", sub: "Visão geral da emissão de notas." },
  notas: { titulo: "Notas fiscais de serviço", sub: "Rascunhos, emissões e recusas." },
  empresas: { titulo: "Empresas", sub: "Quem emitiu, e quanto." },
};

function mostrar(tela) {
  estado.tela = tela;
  $("#titulo").textContent = TELAS[tela].titulo;
  $("#subtitulo").textContent = TELAS[tela].sub;
  for (const nome of Object.keys(TELAS)) {
    $(`#tela-${nome}`).classList.toggle("oculto", nome !== tela);
  }
  $$(".rail-item").forEach((b) => {
    if (b.dataset.tela === tela) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  pintarTudo();
}

function pintarTudo() {
  if (estado.tela === "painel") pintarPainel();
  if (estado.tela === "empresas") pintarEmpresas();
  if (estado.tela === "notas") { pintarContadores(); pintarTabela(); }
}

/* ------------------------------------------------------------------ *
 * Carga
 * ------------------------------------------------------------------ */

async function carregarNotas() {
  try {
    const { documents } = await motor("/documents");
    estado.notas = documents || [];
    // Seleção de nota que sumiu não pode sobreviver à recarga.
    estado.selecao = new Set([...estado.selecao].filter((id) => notaPorId(id)));
    pintarFiltroPrestador();
    pintarTudo();
  } catch (erro) {
    avisar("Não consegui ler as notas", erro.message, "erro");
  }
}

async function carregarSaude() {
  const caixa = $("#conexao");
  try {
    estado.saude = await motor("/health");
    caixa.classList.remove("fora");
    $("#conexao-txt").textContent = "conectado";
    const vivo = estado.saude.live_mode;
    $("#selo-modo").innerHTML =
      `<span class="pill ${vivo ? "wait" : "off"}"><span class="bola"></span>${vivo ? "Transmissão ativa" : "Modo seguro"}</span>`;
  } catch {
    estado.saude = null;
    caixa.classList.add("fora");
    $("#conexao-txt").textContent = "desligado";
    $("#selo-modo").innerHTML = "";
  }
}

async function carregarConfiguracao() {
  try {
    estado.configuracao = await motor("/config");
    const faltando = (estado.configuracao.pending || []);
    if (faltando.length) {
      avisar("Falta para conseguir emitir", faltando.join(" · "), "alerta");
    }
  } catch { /* o aviso de motor fora já foi dado pela saúde */ }
}

/* ------------------------------------------------------------------ *
 * Eventos
 * ------------------------------------------------------------------ */

$$(".rail-item").forEach((b) => b.addEventListener("click", () => mostrar(b.dataset.tela)));

$("#btn-tema").addEventListener("click", () => {
  const novo = document.documentElement.dataset.tema === "claro" ? "escuro" : "claro";
  document.documentElement.dataset.tema = novo;
  try { localStorage.setItem("tema", novo); } catch { /* sem armazenamento */ }
  pintarTudo();   // o gráfico é SVG desenhado com as cores do tema
});

$("#btn-recarregar").addEventListener("click", async () => {
  await Promise.all([carregarSaude(), carregarNotas()]);
  avisar("Atualizado", "", "ok");
});

$("#contadores").addEventListener("click", (e) => {
  const alvo = e.target.closest("[data-grupo]");
  if (!alvo) return;
  estado.situacao = estado.situacao === alvo.dataset.grupo ? "todas" : alvo.dataset.grupo;
  pintarContadores();
  pintarTabela();
});

let atrasoBusca;
$("#busca").addEventListener("input", (e) => {
  // Redesenhar a tabela a cada tecla trava a digitação com muitas notas.
  clearTimeout(atrasoBusca);
  const texto = e.target.value;
  atrasoBusca = setTimeout(() => {
    estado.busca = texto;
    pintarContadores();
    pintarTabela();
  }, 160);
});

$("#f-prestador").addEventListener("change", (e) => {
  estado.prestador = e.target.value;
  estado.selecao.clear();
  pintarContadores();
  pintarTabela();
});

["de", "ate"].forEach((campo) => {
  $(`#f-${campo}`).addEventListener("change", (e) => {
    estado[campo] = e.target.value;
    pintarContadores();
    pintarTabela();
  });
});

$("#btn-olho").addEventListener("click", (e) => {
  estado.mascarado = !estado.mascarado;
  e.currentTarget.setAttribute("aria-pressed", String(estado.mascarado));
  pintarTudo();
});

$("#chk-todos").addEventListener("change", (e) => {
  if (e.target.checked) visiveis().forEach((n) => estado.selecao.add(n.id));
  else estado.selecao.clear();
  pintarTabela();
});

$("#corpo").addEventListener("click", (e) => {
  const acao = e.target.closest("[data-acao]");
  if (acao) {
    e.stopPropagation();
    if (acao.dataset.acao === "pdf") abrirPdf(acao.dataset.id);
    if (acao.dataset.acao === "detalhes") verDetalhes(acao.dataset.id);
    if (acao.dataset.acao === "enviar") enviarAoPortal(acao.dataset.id);
    return;
  }
  const caixa = e.target.closest(".chk");
  const linha = e.target.closest("tr[data-id]");
  if (!linha) return;
  const id = linha.dataset.id;
  if (caixa) {
    caixa.checked ? estado.selecao.add(id) : estado.selecao.delete(id);
  } else {
    estado.selecao.has(id) ? estado.selecao.delete(id) : estado.selecao.add(id);
  }
  pintarTabela();
});

$("#corpo").addEventListener("dblclick", (e) => {
  const linha = e.target.closest("tr[data-id]");
  if (linha) verDetalhes(linha.dataset.id);
});

$("#btn-limpar-sel").addEventListener("click", () => { estado.selecao.clear(); pintarTabela(); });
$("#btn-pdf").addEventListener("click", () => abrirPdf([...estado.selecao][0]));
$("#btn-detalhes").addEventListener("click", () => verDetalhes([...estado.selecao][0]));
$("#btn-enviar").addEventListener("click", () => enviarAoPortal([...estado.selecao][0]));
$("#faixa-falhas-x").addEventListener("click", () => {
  estado.faixaFechada = true;
  $("#faixa-falhas").classList.add("oculto");
});
$("#faixa-falhas").addEventListener("click", (e) => {
  if (e.target.closest(".fechar")) return;
  estado.situacao = "failed";
  pintarContadores();
  pintarTabela();
});

/* ------------------------------------------------------------------ *
 * Início
 * ------------------------------------------------------------------ */

(async function iniciar() {
  pintarCabecalho();
  mostrar("painel");
  await carregarSaude();
  await carregarNotas();
  await carregarConfiguracao();
  // O motor pode ser fechado com a página aberta; a bolinha precisa contar.
  setInterval(carregarSaude, 30000);
})();

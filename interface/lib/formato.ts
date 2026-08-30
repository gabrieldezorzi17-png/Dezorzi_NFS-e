/**
 * Formatação de dinheiro, documento e data.
 *
 * Estas funções não validam nada — quem valida é o motor, em `validation.py`,
 * e é ele que decide se uma nota pode sair. Aqui é só apresentação. Duplicar
 * regra fiscal em TypeScript é como as duas metades de um sistema começam a
 * discordar sobre o que é um CNPJ válido.
 */

const MOEDA = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});

const NUMERO = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * Aceita o que o motor devolve: número, "1.234,56" ou "1234.56".
 *
 * A ordem importa. "1.234,56" tem ponto de milhar e vírgula decimal; se a
 * vírgula for trocada por ponto sem tirar o milhar antes, 1.234,56 vira
 * 1.234.56 e o parse devolve 1,23 — a nota sairia com mil reais a menos.
 */
export function paraNumero(valor: unknown): number {
  if (typeof valor === "number") return Number.isFinite(valor) ? valor : 0;
  if (typeof valor !== "string") return 0;
  const limpo = valor.trim();
  if (!limpo) return 0;
  const brasileiro = /,\d{1,2}$/.test(limpo);
  const normalizado = brasileiro
    ? limpo.replace(/\./g, "").replace(",", ".")
    : limpo.replace(/,/g, "");
  const numero = Number.parseFloat(normalizado.replace(/[^\d.-]/g, ""));
  return Number.isFinite(numero) ? numero : 0;
}

export function dinheiro(valor: unknown): string {
  return MOEDA.format(paraNumero(valor));
}

export function numero(valor: unknown): string {
  return NUMERO.format(paraNumero(valor));
}

export function porcentagem(valor: unknown): string {
  return `${NUMERO.format(paraNumero(valor))}%`;
}

/** 11222333000181 -> 11.222.333/0001-81; 12345678909 -> 123.456.789-09. */
export function documento(bruto: unknown): string {
  const digitos = String(bruto ?? "").replace(/\D/g, "");
  if (digitos.length === 14) {
    return digitos.replace(
      /^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/,
      "$1.$2.$3/$4-$5",
    );
  }
  if (digitos.length === 11) {
    return digitos.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, "$1.$2.$3-$4");
  }
  return String(bruto ?? "");
}

export function cep(bruto: unknown): string {
  const digitos = String(bruto ?? "").replace(/\D/g, "").slice(0, 8);
  return digitos.length === 8
    ? digitos.replace(/^(\d{5})(\d{3})$/, "$1-$2")
    : digitos;
}

/** "2026-08-29T17:23:04" -> "29/08/2026". */
export function data(bruto: unknown): string {
  const texto = String(bruto ?? "");
  const iso = texto.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return texto.slice(0, 10);
  const [ano, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${ano}`;
}

/** "há 2 dias", para a coluna de data não obrigar a fazer conta de cabeça. */
export function quando(bruto: unknown): string {
  const texto = String(bruto ?? "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(texto)) return "";
  const alvo = new Date(`${texto}T00:00:00`);
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const dias = Math.round((hoje.getTime() - alvo.getTime()) / 86_400_000);
  if (dias <= 0) return "hoje";
  if (dias === 1) return "ontem";
  if (dias < 30) return `há ${dias} dias`;
  if (dias < 60) return "há 1 mês";
  return `há ${Math.floor(dias / 30)} meses`;
}

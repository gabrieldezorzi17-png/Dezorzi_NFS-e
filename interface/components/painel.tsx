"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useMemo } from "react";

import { api, type Documento } from "@/lib/api";
import { cn } from "@/lib/cn";
import { dinheiro, paraNumero } from "@/lib/formato";
import { CASCATA, ITEM, MOLA_LONGA, TELA } from "@/lib/motion";
import { CartaoHolofote } from "./cartao-holofote";
import { NumeroAnimado } from "./numero-animado";
import { PilulaStatus } from "./pilula-status";

/* ------------------------------------------------------------------ *
 * Contas
 * ------------------------------------------------------------------ */

interface Resumo {
  rascunhos: number;
  emitidas: number;
  falhas: number;
  faturado: number;
}

function resumir(notas: Documento[]): Resumo {
  return notas.reduce<Resumo>(
    (acumulado, nota) => {
      if (nota.status === "draft") acumulado.rascunhos += 1;
      if (nota.status === "failed") acumulado.falhas += 1;
      if (nota.status === "submitted") {
        acumulado.emitidas += 1;
        // Só o que foi de fato emitido conta como faturado. Somar rascunho
        // daria um número maior e errado justo no cartão que se olha primeiro.
        acumulado.faturado += paraNumero(nota.payload?.servico?.valor);
      }
      return acumulado;
    },
    { rascunhos: 0, emitidas: 0, falhas: 0, faturado: 0 },
  );
}

interface Dia {
  dia: string;
  rotulo: string;
  quantidade: number;
  valor: number;
}

/** Os últimos N dias, inclusive os sem nota — senão o gráfico mente sobre o ritmo. */
function porDia(notas: Documento[], dias = 14): Dia[] {
  const contagem = new Map<string, { quantidade: number; valor: number }>();
  for (const nota of notas) {
    if (nota.status !== "submitted") continue;
    const dia = String(nota.created_at ?? "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dia)) continue;
    const atual = contagem.get(dia) ?? { quantidade: 0, valor: 0 };
    atual.quantidade += 1;
    atual.valor += paraNumero(nota.payload?.servico?.valor);
    contagem.set(dia, atual);
  }

  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const serie: Dia[] = [];
  for (let recuo = dias - 1; recuo >= 0; recuo -= 1) {
    const data = new Date(hoje);
    data.setDate(hoje.getDate() - recuo);
    const chave = data.toISOString().slice(0, 10);
    const achado = contagem.get(chave) ?? { quantidade: 0, valor: 0 };
    serie.push({
      dia: chave,
      rotulo: `${String(data.getDate()).padStart(2, "0")}/${String(data.getMonth() + 1).padStart(2, "0")}`,
      ...achado,
    });
  }
  return serie;
}

/* ------------------------------------------------------------------ *
 * Gráfico
 * ------------------------------------------------------------------ */

/**
 * Área com a linha se desenhando.
 *
 * SVG à mão, sem biblioteca de gráfico: são duas curvas e um preenchimento.
 * Uma dependência de 60 kB para isto seria peso que a janela carrega em toda
 * abertura, para desenhar catorze pontos.
 */
function GraficoDeEmissao({ serie }: { serie: Dia[] }) {
  const largura = 720;
  const altura = 180;
  const folga = { topo: 16, base: 26, lado: 8 };

  const { linha, area, pontos, teto } = useMemo(() => {
    const teto = Math.max(1, ...serie.map((d) => d.quantidade));
    const util = {
      largura: largura - folga.lado * 2,
      altura: altura - folga.topo - folga.base,
    };
    const passo = serie.length > 1 ? util.largura / (serie.length - 1) : 0;

    const pontos = serie.map((dia, indice) => ({
      ...dia,
      x: folga.lado + indice * passo,
      y: folga.topo + util.altura - (dia.quantidade / teto) * util.altura,
    }));

    // Curva suave por Catmull-Rom convertida em Bézier: com poucos pontos, a
    // linha reta fica angulosa e a curva "spline" pronta exagera os picos.
    const suave = pontos
      .map((ponto, indice, todos) => {
        if (indice === 0) return `M ${ponto.x} ${ponto.y}`;
        const anterior = todos[indice - 1];
        const meio = (anterior.x + ponto.x) / 2;
        return `C ${meio} ${anterior.y}, ${meio} ${ponto.y}, ${ponto.x} ${ponto.y}`;
      })
      .join(" ");

    const base = folga.topo + util.altura;
    const area = pontos.length
      ? `${suave} L ${pontos[pontos.length - 1].x} ${base} L ${pontos[0].x} ${base} Z`
      : "";

    return { linha: suave, area, pontos, teto };
  }, [serie]);

  return (
    <svg
      viewBox={`0 0 ${largura} ${altura}`}
      className="h-44 w-full"
      role="img"
      aria-label={`Notas emitidas por dia nos últimos ${serie.length} dias. Pico de ${teto}.`}
    >
      <defs>
        <linearGradient id="preenchimento" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgb(var(--primaria))" stopOpacity="0.28" />
          <stop offset="100%" stopColor="rgb(var(--primaria))" stopOpacity="0" />
        </linearGradient>
      </defs>

      {[0.5, 1].map((fracao) => (
        <line
          key={fracao}
          x1={folga.lado}
          x2={largura - folga.lado}
          y1={folga.topo + (altura - folga.topo - folga.base) * (1 - fracao)}
          y2={folga.topo + (altura - folga.topo - folga.base) * (1 - fracao)}
          stroke="rgb(var(--borda))"
          strokeDasharray="3 5"
        />
      ))}

      <motion.path
        d={area}
        fill="url(#preenchimento)"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.25 }}
      />
      <motion.path
        d={linha}
        fill="none"
        stroke="rgb(var(--primaria))"
        strokeWidth={2.5}
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
      />

      {pontos.map((ponto) => (
        <g key={ponto.dia}>
          {ponto.quantidade > 0 && (
            <motion.circle
              cx={ponto.x}
              cy={ponto.y}
              r={3.5}
              fill="rgb(var(--fundo))"
              stroke="rgb(var(--primaria))"
              strokeWidth={2}
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ ...MOLA_LONGA, delay: 0.5 }}
            />
          )}
          <title>{`${ponto.rotulo}: ${ponto.quantidade} nota(s) · ${dinheiro(ponto.valor)}`}</title>
        </g>
      ))}

      {pontos.map((ponto, indice) =>
        // Um rótulo a cada três, senão catorze datas viram um borrão.
        indice % 3 === 0 || indice === pontos.length - 1 ? (
          <text
            key={`r-${ponto.dia}`}
            x={ponto.x}
            y={altura - 8}
            textAnchor="middle"
            className="fill-[rgb(var(--tinta-3))] text-[10px]"
          >
            {ponto.rotulo}
          </text>
        ) : null,
      )}
    </svg>
  );
}

/* ------------------------------------------------------------------ *
 * Painel
 * ------------------------------------------------------------------ */

interface Props {
  aoEmitir: () => void;
  aoVerNotas: () => void;
}

export function Painel({ aoEmitir, aoVerNotas }: Props) {
  const notas = useQuery({ queryKey: ["notas"], queryFn: api.listarNotas });
  const saude = useQuery({
    queryKey: ["saude"],
    queryFn: api.saude,
    refetchInterval: 30_000,
  });
  const configuracao = useQuery({
    queryKey: ["configuracao"],
    queryFn: api.configuracao,
  });

  const lista = notas.data ?? [];
  const resumo = useMemo(() => resumir(lista), [lista]);
  const serie = useMemo(() => porDia(lista), [lista]);
  const transmitindo = saude.data?.live_mode ?? false;
  const pendencias = configuracao.data?.pending ?? [];

  const indicadores = [
    {
      titulo: "Rascunhos",
      valor: resumo.rascunhos,
      detalhe: "aguardando revisão",
      faixa: "rgb(var(--primaria))",
      formato: "inteiro" as const,
    },
    {
      titulo: "Emitidas",
      valor: resumo.emitidas,
      detalhe: "no portal",
      faixa: "rgb(var(--sucesso))",
      formato: "inteiro" as const,
    },
    {
      titulo: "Falhas",
      valor: resumo.falhas,
      detalhe: "precisam de atenção",
      faixa: "rgb(var(--falha))",
      formato: "inteiro" as const,
    },
    {
      titulo: "Faturado",
      valor: resumo.faturado,
      detalhe: "somando as emitidas",
      faixa: "rgb(var(--primaria))",
      formato: "moeda" as const,
    },
  ];

  return (
    <motion.section
      variants={TELA}
      initial="entrada"
      animate="ativa"
      exit="saida"
      className="space-y-5"
    >
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Painel</h1>
          <p className="text-sm text-[rgb(var(--tinta-3))]">
            Visão geral da emissão de notas.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <PilulaStatus
            tom={transmitindo ? "ativo" : "seguro"}
            detalhe={
              transmitindo
                ? "Apertar Emitir manda a nota ao portal de verdade."
                : "As notas são montadas e validadas, mas não são enviadas."
            }
          />
          <BotaoPrincipal onClick={aoEmitir}>Emitir NFS-e</BotaoPrincipal>
        </div>
      </header>

      {pendencias.length > 0 && (
        <motion.div
          variants={ITEM}
          initial="entrada"
          animate="ativa"
          className="rounded-card border-l-4 border-l-[rgb(var(--alerta-tinta))] bg-[rgb(var(--alerta-fundo))] px-4 py-3"
        >
          <p className="text-sm font-semibold text-[rgb(var(--alerta-tinta))]">
            Falta para conseguir emitir:
          </p>
          <ul className="mt-1 space-y-0.5 text-xs text-[rgb(var(--alerta-tinta))]">
            {pendencias.map((item) => (
              <li key={item}>• {item}</li>
            ))}
          </ul>
        </motion.div>
      )}

      <motion.div
        variants={CASCATA}
        initial="entrada"
        animate="ativa"
        className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
      >
        {indicadores.map((indicador) => (
          <motion.div key={indicador.titulo} variants={ITEM}>
            <CartaoHolofote faixa={indicador.faixa} className="h-full p-5 pl-6">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-[rgb(var(--tinta-3))]">
                {indicador.titulo}
              </p>
              <NumeroAnimado
                valor={indicador.valor}
                formato={indicador.formato}
                className="mt-2 block text-3xl font-semibold tabular-nums tracking-tight"
              />
              <p className="mt-1 text-xs text-[rgb(var(--tinta-3))]">
                {indicador.detalhe}
              </p>
            </CartaoHolofote>
          </motion.div>
        ))}
      </motion.div>

      <motion.div variants={ITEM} initial="entrada" animate="ativa">
        <CartaoHolofote estatico className="p-5">
          <div className="mb-2 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">Emissão nos últimos 14 dias</h2>
            <span className="text-xs text-[rgb(var(--tinta-3))]">
              {serie.reduce((soma, dia) => soma + dia.quantidade, 0)} nota(s)
            </span>
          </div>
          {notas.isLoading ? (
            <div className="h-44 animate-pulse rounded-lg bg-[rgb(var(--superficie-alta))]" />
          ) : (
            <GraficoDeEmissao serie={serie} />
          )}
        </CartaoHolofote>
      </motion.div>

      <motion.div variants={ITEM} initial="entrada" animate="ativa">
        <CartaoHolofote estatico className="p-5">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">Notas recentes</h2>
            <button
              type="button"
              onClick={aoVerNotas}
              className="text-xs font-medium text-[rgb(var(--primaria))] hover:underline"
            >
              Ver todas
            </button>
          </div>
          <ul className="divide-y divide-[rgb(var(--borda))]">
            {lista.slice(0, 5).map((nota) => (
              <li
                key={nota.id}
                className="flex items-center justify-between gap-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {nota.payload?.tomador?.nome || "Sem tomador"}
                  </p>
                  <p className="truncate text-xs text-[rgb(var(--tinta-3))]">
                    {nota.payload?.servico?.descricao || "—"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <span className="text-sm tabular-nums">
                    {dinheiro(nota.payload?.servico?.valor)}
                  </span>
                  <PilulaStatus
                    tom={nota.status}
                    texto={
                      nota.status === "submitted" && nota.nota?.numero
                        ? `Emitida · nº ${nota.nota.numero}`
                        : undefined
                    }
                    detalhe={nota.status === "failed" ? nota.erro : undefined}
                  />
                </div>
              </li>
            ))}
            {lista.length === 0 && !notas.isLoading && (
              <li className="py-8 text-center text-sm text-[rgb(var(--tinta-3))]">
                Nenhuma nota ainda.
              </li>
            )}
          </ul>
        </CartaoHolofote>
      </motion.div>
    </motion.section>
  );
}

/** Botão de ação principal, com borda que acende e resposta ao toque. */
export function BotaoPrincipal({
  children,
  className,
  ...resto
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <motion.button
      whileTap={{ scale: 0.97 }}
      whileHover={{ scale: 1.015 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className={cn(
        "borda-viva relative overflow-hidden rounded-lg px-4 py-2.5",
        "bg-[rgb(var(--primaria))] text-sm font-semibold text-white",
        "shadow-[0_6px_20px_-8px_rgb(var(--primaria)/0.85)]",
        "transition-colors hover:bg-[rgb(var(--primaria-forte))]",
        "disabled:cursor-not-allowed disabled:opacity-55 disabled:shadow-none",
        className,
      )}
      {...(resto as React.ComponentProps<typeof motion.button>)}
    >
      {children}
    </motion.button>
  );
}

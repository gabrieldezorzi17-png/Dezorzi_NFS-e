"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowDown, ArrowUp, Search, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { api, ErroDoMotor, type Documento } from "@/lib/api";
import { cn } from "@/lib/cn";
import { data, dinheiro, documento as formatarDoc, quando } from "@/lib/formato";
import { LINHA, TELA, TOQUE } from "@/lib/motion";
import { BotaoPrincipal } from "./painel";
import { CartaoHolofote } from "./cartao-holofote";
import { PilulaStatus } from "./pilula-status";

const ALTURA_LINHA = 56;
const ALTURA_JANELA = 520;

/** Tudo por que uma nota pode ser procurada, numa linha só. */
function textoBuscavel(nota: Documento): string {
  const tomador = nota.payload?.tomador ?? {};
  const servico = nota.payload?.servico ?? {};
  return [
    tomador.nome,
    tomador.documento,
    formatarDoc(tomador.documento),
    servico.descricao,
    servico.codigo,
    servico.valor,
    nota.nota?.numero,
    data(nota.created_at),
    { draft: "rascunho", submitted: "emitida", failed: "falhou" }[nota.status],
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

const coluna = createColumnHelper<Documento>();

interface Props {
  aoEmitir: () => void;
  aoAbrirDetalhes: (nota: Documento) => void;
}

export function TabelaNotas({ aoEmitir, aoAbrirDetalhes }: Props) {
  const cliente = useQueryClient();
  const [procurado, setProcurado] = useState("");
  const [ordem, setOrdem] = useState<SortingState>([
    { id: "created_at", desc: true },
  ]);
  const [selecionada, setSelecionada] = useState<string | null>(null);

  const notas = useQuery({ queryKey: ["notas"], queryFn: api.listarNotas });
  const [enviando, setEnviando] = useState<string | null>(null);

  /**
   * Envio, com a tela respondendo antes do portal.
   *
   * A linha vira "Processando" no instante do clique — a emissão leva
   * segundos, e uma tela parada nesse intervalo faz a pessoa clicar de novo.
   *
   * O otimismo para AQUI, na pílula. O status da nota no cache não é
   * adiantado de propósito: escrever "Emitida" antes de o portal confirmar
   * seria a tela afirmando um fato fiscal que ainda não aconteceu. Quem diz
   * se foi transmitida é o motor, e `onSettled` vai buscar a resposta dele.
   */
  const envio = useMutation({
    mutationFn: (id: string) => api.enviar(id),
    onMutate: (id) => {
      setEnviando(id);
    },
    onSettled: () => {
      setEnviando(null);
      cliente.invalidateQueries({ queryKey: ["notas"] });
    },
  });

  const colunas = useMemo(
    () => [
      coluna.accessor((nota) => nota.payload?.tomador?.nome ?? "", {
        id: "cliente",
        header: "Cliente",
        cell: (info) => {
          const nota = info.row.original;
          const doc = nota.payload?.tomador?.documento;
          return (
            <div className="min-w-0">
              <p className="truncate font-medium">
                {info.getValue() || formatarDoc(doc) || "Sem tomador"}
              </p>
              {info.getValue() && doc ? (
                <p className="truncate text-xs text-[rgb(var(--tinta-3))]">
                  {formatarDoc(doc)}
                </p>
              ) : null}
            </div>
          );
        },
      }),
      coluna.accessor((nota) => nota.payload?.servico?.descricao ?? "", {
        id: "servico",
        header: "Serviço",
        cell: (info) => (
          // A descrição pode ter várias linhas; aqui ela é resumo, e as
          // quebras aparecem em Detalhes e na nota impressa.
          <p className="truncate text-[rgb(var(--tinta-2))]">
            {String(info.getValue()).replace(/\s+/g, " ") || "—"}
          </p>
        ),
      }),
      coluna.accessor((nota) => nota.payload?.servico?.valor ?? 0, {
        id: "valor",
        header: "Valor",
        cell: (info) => (
          <span className="block text-right tabular-nums">
            {dinheiro(info.getValue())}
          </span>
        ),
      }),
      coluna.accessor("status", {
        id: "status",
        header: "Status",
        cell: (info) => {
          const nota = info.row.original;
          const emCurso = enviando === nota.id;
          return (
            <PilulaStatus
              tom={emCurso ? "processando" : nota.status}
              texto={
                !emCurso && nota.status === "submitted" && nota.nota?.numero
                  ? `Emitida · nº ${nota.nota.numero}`
                  : undefined
              }
              detalhe={
                nota.status === "failed"
                  ? nota.erro || "O portal recusou esta nota. Abra os detalhes."
                  : undefined
              }
            />
          );
        },
      }),
      coluna.accessor("created_at", {
        id: "created_at",
        header: "Criada em",
        cell: (info) => (
          <div className="text-right">
            <p className="tabular-nums">{data(info.getValue())}</p>
            <p className="text-xs text-[rgb(var(--tinta-3))]">
              {quando(info.getValue())}
            </p>
          </div>
        ),
      }),
    ],
    [enviando],
  );

  const tabela = useReactTable({
    data: notas.data ?? [],
    columns: colunas,
    state: { sorting: ordem, globalFilter: procurado },
    onSortingChange: setOrdem,
    onGlobalFilterChange: setProcurado,
    globalFilterFn: (linha, _coluna, filtro) => {
      const termo = String(filtro ?? "").trim().toLowerCase();
      if (!termo) return true;
      const alvo = textoBuscavel(linha.original);
      // Cada palavra em qualquer lugar: "mundial 250" acha a nota da Mundial
      // de R$ 250,00 sem depender da ordem em que foi digitada.
      return termo.split(/\s+/).every((parte) => alvo.includes(parte));
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const linhas = tabela.getRowModel().rows;
  const rolagem = useRef<HTMLDivElement>(null);

  /**
   * Virtualização.
   *
   * Só as linhas visíveis existem no DOM. Com noventa notas isso não muda
   * nada; com dez mil é a diferença entre abrir e travar — e o arquivo de
   * notas só cresce.
   *
   * Nota sobre animação: a `layout` do Framer Motion não convive com isto,
   * porque o virtualizador é quem controla o `transform` de cada linha. As
   * duas brigariam pela mesma propriedade. Por isso a entrada e a saída são
   * animadas por opacidade e deslocamento, não por `layout`.
   */
  const virtual = useVirtualizer({
    count: linhas.length,
    getScrollElement: () => rolagem.current,
    estimateSize: () => ALTURA_LINHA,
    overscan: 8,
  });

  const notaSelecionada = linhas.find((l) => l.original.id === selecionada)?.original;

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
          <h1 className="text-2xl font-semibold tracking-tight">Minhas notas</h1>
          <p className="text-sm text-[rgb(var(--tinta-3))]">
            Rascunhos, emissões e falhas.
          </p>
        </div>
        <BotaoPrincipal onClick={aoEmitir}>Emitir NFS-e</BotaoPrincipal>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <div
          className={cn(
            "vidro flex items-center gap-2 rounded-lg px-3 py-2",
            "focus-within:ring-2 focus-within:ring-[rgb(var(--primaria)/0.45)]",
          )}
        >
          <Search className="size-4 shrink-0 text-[rgb(var(--tinta-3))]" />
          <input
            value={procurado}
            onChange={(evento) => setProcurado(evento.target.value)}
            onKeyDown={(evento) => evento.key === "Escape" && setProcurado("")}
            placeholder="Buscar por cliente, CNPJ, nº, valor…"
            aria-label="Buscar notas"
            className="w-64 bg-transparent text-sm outline-none placeholder:text-[rgb(var(--tinta-3))]"
          />
          {procurado && (
            <button
              type="button"
              onClick={() => setProcurado("")}
              aria-label="Limpar busca"
              className="text-[rgb(var(--tinta-3))] hover:text-[rgb(var(--tinta))]"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>

        <span className="text-xs text-[rgb(var(--tinta-3))]">
          {procurado.trim()
            ? `${linhas.length} de ${notas.data?.length ?? 0}`
            : `${notas.data?.length ?? 0} nota(s)`}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <BotaoSecundario
            disabled={!notaSelecionada}
            onClick={() => notaSelecionada && aoAbrirDetalhes(notaSelecionada)}
          >
            Detalhes
          </BotaoSecundario>
          <BotaoPrincipal
            disabled={
              !notaSelecionada ||
              notaSelecionada.status === "submitted" ||
              envio.isPending
            }
            onClick={() => notaSelecionada && envio.mutate(notaSelecionada.id)}
          >
            {envio.isPending ? "Enviando ao portal…" : "Enviar ao portal"}
          </BotaoPrincipal>
        </div>
      </div>

      {envio.isError && (
        <AvisoDeErro erro={envio.error} aoFechar={() => envio.reset()} />
      )}

      <CartaoHolofote estatico className="overflow-hidden p-0">
        {/* Cabeçalho fora da área que rola: some junto com as linhas, se ficar dentro. */}
        <div className="border-b border-[rgb(var(--borda))] bg-[rgb(var(--superficie-alta))]">
          {tabela.getHeaderGroups().map((grupo) => (
            <div key={grupo.id} className="flex items-center px-4">
              {grupo.headers.map((cabecalho) => (
                <button
                  key={cabecalho.id}
                  type="button"
                  onClick={cabecalho.column.getToggleSortingHandler()}
                  className={cn(
                    "flex items-center gap-1 py-3 text-[11px] font-semibold uppercase tracking-wider",
                    "text-[rgb(var(--tinta-3))] transition-colors hover:text-[rgb(var(--tinta-2))]",
                    LARGURA[cabecalho.column.id],
                    (cabecalho.column.id === "valor" ||
                      cabecalho.column.id === "created_at") &&
                      "justify-end",
                  )}
                >
                  {flexRender(
                    cabecalho.column.columnDef.header,
                    cabecalho.getContext(),
                  )}
                  {cabecalho.column.getIsSorted() === "asc" && (
                    <ArrowUp className="size-3" />
                  )}
                  {cabecalho.column.getIsSorted() === "desc" && (
                    <ArrowDown className="size-3" />
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>

        <div
          ref={rolagem}
          style={{ height: ALTURA_JANELA }}
          className="overflow-auto"
        >
          {linhas.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
              <p className="text-sm font-medium text-[rgb(var(--tinta-2))]">
                {procurado.trim()
                  ? "Nenhuma nota com esse texto"
                  : "Nenhuma nota ainda"}
              </p>
              <p className="max-w-sm text-xs text-[rgb(var(--tinta-3))]">
                {procurado.trim()
                  ? "Procure por cliente, CNPJ, número da nota, valor ou data."
                  : "As notas que você emitir aparecem aqui, com número, status e PDF."}
              </p>
            </div>
          ) : (
            <div
              style={{ height: virtual.getTotalSize() }}
              className="relative w-full"
            >
              <AnimatePresence initial={false}>
                {virtual.getVirtualItems().map((item) => {
                  const linha = linhas[item.index];
                  const nota = linha.original;
                  const marcada = selecionada === nota.id;
                  return (
                    <motion.div
                      key={nota.id}
                      variants={LINHA}
                      initial="entrada"
                      animate="ativa"
                      exit="saida"
                      onClick={() => setSelecionada(marcada ? null : nota.id)}
                      onDoubleClick={() => aoAbrirDetalhes(nota)}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        width: "100%",
                        height: item.size,
                        transform: `translateY(${item.start}px)`,
                      }}
                      className={cn(
                        "flex cursor-pointer items-center px-4",
                        "border-b border-[rgb(var(--borda))] transition-colors",
                        item.index % 2 === 1 && "bg-[rgb(var(--superficie-alta)/0.45)]",
                        "hover:bg-[rgb(var(--primaria)/0.06)]",
                        marcada &&
                          "bg-[rgb(var(--primaria)/0.10)] ring-1 ring-inset ring-[rgb(var(--primaria)/0.35)]",
                      )}
                    >
                      {linha.getVisibleCells().map((celula) => (
                        <div
                          key={celula.id}
                          className={cn(
                            "min-w-0 text-sm",
                            LARGURA[celula.column.id],
                          )}
                        >
                          {flexRender(
                            celula.column.columnDef.cell,
                            celula.getContext(),
                          )}
                        </div>
                      ))}
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            </div>
          )}
        </div>
      </CartaoHolofote>
    </motion.section>
  );
}

/** Larguras por coluna. Fora do JSX para cabeçalho e célula não divergirem. */
const LARGURA: Record<string, string> = {
  cliente: "flex-[2] pr-3",
  servico: "flex-[2.4] pr-3",
  valor: "w-28 shrink-0 pr-3 text-right",
  status: "w-44 shrink-0 pr-3",
  created_at: "w-28 shrink-0 text-right",
};

function BotaoSecundario({
  className,
  ...resto
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <motion.button
      whileTap={TOQUE}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className={cn(
        "rounded-lg border border-[rgb(var(--borda-forte))] px-3.5 py-2.5",
        "bg-[rgb(var(--superficie))] text-sm font-medium",
        "transition-colors hover:bg-[rgb(var(--superficie-alta))]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...(resto as React.ComponentProps<typeof motion.button>)}
    />
  );
}

function AvisoDeErro({ erro, aoFechar }: { erro: unknown; aoFechar: () => void }) {
  const doMotor = erro instanceof ErroDoMotor ? erro : null;
  const mensagem =
    doMotor?.message ?? (erro instanceof Error ? erro.message : String(erro));
  const dica = doMotor?.portalIndisponivel
    ? "O portal não respondeu. Isso não é problema do preenchimento — tente de novo em instantes."
    : doMotor?.jaEnviada
      ? "Esta nota já foi emitida. Não se emite duas vezes."
      : doMotor?.corrigivel
        ? "Corrija o campo apontado e envie de novo."
        : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-start gap-3 rounded-card border-l-4 border-l-[rgb(var(--falha))] bg-[rgb(var(--falha-fundo))] px-4 py-3"
    >
      <div className="flex-1">
        <p className="text-sm font-semibold text-[rgb(var(--falha-tinta))]">
          {mensagem}
        </p>
        {dica && (
          <p className="mt-0.5 text-xs text-[rgb(var(--falha-tinta))]">{dica}</p>
        )}
      </div>
      <button
        type="button"
        onClick={aoFechar}
        aria-label="Fechar aviso"
        className="text-[rgb(var(--falha-tinta))]"
      >
        <X className="size-4" />
      </button>
    </motion.div>
  );
}

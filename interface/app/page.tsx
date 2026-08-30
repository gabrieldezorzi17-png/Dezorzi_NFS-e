"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  FileText,
  LayoutGrid,
  Moon,
  Plus,
  Settings,
  Sun,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api, type Documento } from "@/lib/api";
import { cn } from "@/lib/cn";
import { MOLA, TOQUE } from "@/lib/motion";
import { FormularioEmissao } from "@/components/formulario-emissao";
import { Painel } from "@/components/painel";
import { PilulaStatus } from "@/components/pilula-status";
import { TabelaNotas } from "@/components/tabela-notas";

type Tela = "painel" | "emitir" | "notas" | "config";

const NAVEGACAO = [
  { chave: "painel" as const, texto: "Painel", Icone: LayoutGrid },
  { chave: "emitir" as const, texto: "Emitir NFS-e", Icone: Plus },
  { chave: "notas" as const, texto: "Minhas notas", Icone: FileText },
  { chave: "config" as const, texto: "Configurações", Icone: Settings },
];

export default function Aplicativo() {
  const [tela, setTela] = useState<Tela>("painel");
  const [tema, setTema] = useState<"claro" | "escuro">("escuro");
  const [detalhe, setDetalhe] = useState<Documento | null>(null);

  const saude = useQuery({
    queryKey: ["saude"],
    queryFn: api.saude,
    refetchInterval: 30_000,
  });

  // O tema escolhido sobrevive a fechar a janela. `localStorage` é lido só no
  // cliente: no servidor ele não existe, e ler lá quebraria a hidratação.
  useEffect(() => {
    const guardado = window.localStorage.getItem("tema");
    if (guardado === "claro" || guardado === "escuro") setTema(guardado);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", tema === "escuro");
    window.localStorage.setItem("tema", tema);
  }, [tema]);

  const transmitindo = saude.data?.live_mode ?? false;
  const motorFora = saude.isError;

  return (
    <div className="flex min-h-screen">
      {/* ---------------------------------------------------------------- */}
      {/* Barra lateral                                                     */}
      {/* ---------------------------------------------------------------- */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-56 flex-col border-r border-[rgb(var(--borda))] bg-[rgb(var(--superficie))] md:flex">
        <div className="px-5 py-5">
          <div className="flex items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-[rgb(var(--primaria))] text-xs font-bold text-white">
              NF
            </span>
            <span className="text-sm font-semibold">NFS-e</span>
          </div>
          <p className="mt-1 text-[11px] text-[rgb(var(--tinta-3))]">
            Controle fiscal · v2
          </p>
        </div>

        <nav className="flex-1 space-y-0.5 px-2">
          {NAVEGACAO.map(({ chave, texto, Icone }) => {
            const ativo = tela === chave;
            return (
              <motion.button
                key={chave}
                whileTap={TOQUE}
                onClick={() => setTela(chave)}
                className={cn(
                  "relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm",
                  "transition-colors",
                  ativo
                    ? "font-medium text-[rgb(var(--primaria))]"
                    : "text-[rgb(var(--tinta-2))] hover:bg-[rgb(var(--superficie-alta))]",
                )}
              >
                {ativo && (
                  // `layoutId` faz o realce DESLIZAR de um item ao outro em
                  // vez de piscar no lugar novo — um só elemento, movido.
                  <motion.span
                    layoutId="realce-nav"
                    transition={MOLA}
                    className="absolute inset-0 rounded-lg bg-[rgb(var(--primaria)/0.10)] ring-1 ring-inset ring-[rgb(var(--primaria)/0.28)]"
                  />
                )}
                <Icone className="relative size-4 shrink-0" />
                <span className="relative">{texto}</span>
              </motion.button>
            );
          })}
        </nav>

        <div className="space-y-3 px-4 py-4">
          <PilulaStatus
            tom={motorFora ? "failed" : transmitindo ? "ativo" : "seguro"}
            texto={motorFora ? "Motor desligado" : undefined}
            detalhe={
              motorFora
                ? "A interface não achou o motor fiscal em 127.0.0.1. Abra-o nesta máquina."
                : transmitindo
                  ? "Apertar Emitir manda a nota ao portal de verdade."
                  : "As notas são montadas e validadas, mas não são enviadas."
            }
          />

          <div className="flex rounded-lg bg-[rgb(var(--superficie-alta))] p-1">
            {(["claro", "escuro"] as const).map((opcao) => (
              <button
                key={opcao}
                type="button"
                onClick={() => setTema(opcao)}
                className={cn(
                  "relative flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 text-[11px] font-medium capitalize",
                  tema === opcao
                    ? "text-[rgb(var(--tinta))]"
                    : "text-[rgb(var(--tinta-3))]",
                )}
              >
                {tema === opcao && (
                  <motion.span
                    layoutId="realce-tema"
                    transition={MOLA}
                    className="absolute inset-0 rounded-md bg-[rgb(var(--superficie))] shadow-sm"
                  />
                )}
                {opcao === "claro" ? (
                  <Sun className="relative size-3" />
                ) : (
                  <Moon className="relative size-3" />
                )}
                <span className="relative">{opcao}</span>
              </button>
            ))}
          </div>

          <p className="text-[10px] text-[rgb(var(--tinta-3))]">Dezorzi®</p>
        </div>
      </aside>

      {/* ---------------------------------------------------------------- */}
      {/* Conteúdo                                                          */}
      {/* ---------------------------------------------------------------- */}
      <main className="flex-1 px-4 py-6 md:pl-[240px] md:pr-6">
        <div className="mx-auto max-w-5xl">
          {/* `mode="wait"` para a tela que sai terminar antes de a nova
              entrar; as duas ao mesmo tempo empilham e a página salta. */}
          <AnimatePresence mode="wait">
            {tela === "painel" && (
              <Painel
                key="painel"
                aoEmitir={() => setTela("emitir")}
                aoVerNotas={() => setTela("notas")}
              />
            )}
            {tela === "notas" && (
              <TabelaNotas
                key="notas"
                aoEmitir={() => setTela("emitir")}
                aoAbrirDetalhes={setDetalhe}
              />
            )}
            {tela === "emitir" && (
              <FormularioEmissao key="emitir" aoSalvar={() => setTela("notas")} />
            )}
            {tela === "config" && (
              <motion.section
                key="config"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                transition={MOLA}
              >
                <h1 className="text-2xl font-semibold tracking-tight">
                  Configurações
                </h1>
                <p className="mt-1 text-sm text-[rgb(var(--tinta-3))]">
                  Empresa, alíquotas e modo de transmissão continuam no motor —
                  são decisões fiscais, e o lugar delas é junto de quem emite.
                </p>
              </motion.section>
            )}
          </AnimatePresence>
        </div>
      </main>

      {/* Detalhes da nota, em painel lateral. */}
      <AnimatePresence>
        {detalhe && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDetalhe(null)}
              className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
            />
            <motion.aside
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={MOLA}
              className="vidro fixed inset-y-0 right-0 z-50 w-full max-w-md overflow-auto p-6"
            >
              <button
                type="button"
                onClick={() => setDetalhe(null)}
                className="mb-4 text-xs text-[rgb(var(--tinta-3))] hover:underline"
              >
                Fechar
              </button>
              <h2 className="text-lg font-semibold">
                {detalhe.payload?.tomador?.nome || "Sem tomador"}
              </h2>
              <PilulaStatus tom={detalhe.status} className="mt-2" />
              <pre className="mt-4 whitespace-pre-wrap break-words rounded-lg bg-[rgb(var(--superficie-alta))] p-3 font-mono text-[11px] leading-relaxed">
                {JSON.stringify(detalhe.payload, null, 2)}
              </pre>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { motion, useReducedMotion } from "framer-motion";

import { cn } from "@/lib/cn";
import { MOLA_CURTA } from "@/lib/motion";
import type { StatusNota } from "@/lib/api";

type Tom = StatusNota | "processando" | "seguro" | "ativo";

const APARENCIA: Record<Tom, { texto: string; classe: string }> = {
  draft: {
    texto: "Rascunho",
    classe:
      "bg-[rgb(var(--neutro-fundo))] text-[rgb(var(--neutro-tinta))] ring-[rgb(var(--borda-forte))]",
  },
  submitted: {
    texto: "Emitida",
    classe:
      "bg-[rgb(var(--sucesso-fundo))] text-[rgb(var(--sucesso-tinta))] ring-[rgb(var(--sucesso)/0.35)]",
  },
  failed: {
    texto: "Falhou",
    classe:
      "bg-[rgb(var(--falha-fundo))] text-[rgb(var(--falha-tinta))] ring-[rgb(var(--falha)/0.45)]",
  },
  processando: {
    texto: "Processando",
    classe:
      "bg-[rgb(var(--primaria-fraca))] text-[rgb(var(--primaria))] ring-[rgb(var(--primaria)/0.35)]",
  },
  seguro: {
    texto: "Modo seguro",
    classe:
      "bg-[rgb(var(--neutro-fundo))] text-[rgb(var(--neutro-tinta))] ring-[rgb(var(--borda-forte))]",
  },
  ativo: {
    texto: "Transmissão ativa",
    classe:
      "bg-[rgb(var(--alerta-fundo))] text-[rgb(var(--alerta-tinta))] ring-[rgb(var(--alerta-tinta)/0.35)]",
  },
};

/** Pulso verde: nota que chegou ao portal. */
function Pulso() {
  const semMovimento = useReducedMotion();
  return (
    <span className="relative flex size-2">
      {!semMovimento && (
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-[rgb(var(--sucesso))] opacity-60" />
      )}
      <span className="relative inline-flex size-2 rounded-full bg-[rgb(var(--sucesso))]" />
    </span>
  );
}

/** Giro contínuo: o motor está falando com o portal agora. */
function Giro() {
  const semMovimento = useReducedMotion();
  return (
    <motion.span
      aria-hidden
      animate={semMovimento ? undefined : { rotate: 360 }}
      transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
      className="inline-block size-3 rounded-full border-2 border-current border-t-transparent opacity-90"
    />
  );
}

interface Props {
  tom: Tom;
  /** Sobrescreve o texto padrão — para "Emitida · nº 99", por exemplo. */
  texto?: string;
  /** Explicação que aparece ao pousar o mouse. Usado sobretudo na falha. */
  detalhe?: string;
  className?: string;
}

/**
 * Selo de status.
 *
 * A cor sozinha não basta: quem não distingue vermelho de verde ficaria sem a
 * informação. Por isso cada tom carrega também texto e forma — ponto que
 * pulsa, círculo que gira, nada.
 */
export function PilulaStatus({ tom, texto, detalhe, className }: Props) {
  const aparencia = APARENCIA[tom] ?? APARENCIA.draft;

  const selo = (
    <motion.span
      layout
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={MOLA_CURTA}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1",
        "text-[11px] font-semibold leading-none ring-1 ring-inset",
        aparencia.classe,
        detalhe && "cursor-help",
        className,
      )}
    >
      {tom === "submitted" && <Pulso />}
      {tom === "processando" && <Giro />}
      {tom === "failed" && (
        <span aria-hidden className="text-sm leading-none">
          !
        </span>
      )}
      {texto ?? aparencia.texto}
    </motion.span>
  );

  if (!detalhe) return selo;

  return (
    <Tooltip.Root delayDuration={120}>
      <Tooltip.Trigger asChild>{selo}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="top"
          sideOffset={6}
          collisionPadding={12}
          className={cn(
            "vidro z-50 max-w-xs rounded-lg px-3 py-2 text-xs leading-relaxed",
            "text-[rgb(var(--tinta-2))] shadow-lg",
            // A transição é escrita à mão: as classes `animate-in` vêm do
            // plugin `tailwindcss-animate`, que não está instalado — sem ele
            // são classes que não existem, e a dica apareceria seca.
            "origin-[var(--radix-tooltip-content-transform-origin)]",
            "transition-[opacity,transform] duration-150 ease-out",
            "data-[state=closed]:scale-95 data-[state=closed]:opacity-0",
            "data-[state=delayed-open]:scale-100 data-[state=delayed-open]:opacity-100",
          )}
        >
          {detalhe}
          <Tooltip.Arrow className="fill-[rgb(var(--superficie))]" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

/** O provedor precisa envolver a árvore uma vez, no layout. */
export const ProvedorDeDicas = Tooltip.Provider;

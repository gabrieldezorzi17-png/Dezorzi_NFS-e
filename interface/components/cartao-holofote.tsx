"use client";

import { motion, useReducedMotion, type HTMLMotionProps } from "framer-motion";
import { useCallback, useRef } from "react";

import { cn } from "@/lib/cn";
import { ELEVAR, MOLA } from "@/lib/motion";

interface Props extends HTMLMotionProps<"div"> {
  /** Barra colorida na lateral esquerda — a leitura de status num relance. */
  faixa?: string;
  /** Desliga a elevação para painéis grandes, onde ela parece tremor. */
  estatico?: boolean;
}

/**
 * Cartão de vidro com holofote que segue o cursor.
 *
 * A posição do cursor viaja por variável CSS, escrita direto no nó. Guardar
 * isso em estado React redesenharia o componente a cada pixel de movimento do
 * mouse — sessenta vezes por segundo, por cartão. A variável muda no DOM e o
 * compositor resolve, sem passar pelo React.
 */
export function CartaoHolofote({
  faixa,
  estatico,
  className,
  children,
  ...resto
}: Props) {
  const no = useRef<HTMLDivElement>(null);
  const semMovimento = useReducedMotion();

  const seguirCursor = useCallback((evento: React.MouseEvent<HTMLDivElement>) => {
    const alvo = no.current;
    if (!alvo) return;
    const caixa = alvo.getBoundingClientRect();
    alvo.style.setProperty("--cursor-x", `${evento.clientX - caixa.left}px`);
    alvo.style.setProperty("--cursor-y", `${evento.clientY - caixa.top}px`);
  }, []);

  return (
    <motion.div
      ref={no}
      onMouseMove={seguirCursor}
      whileHover={estatico || semMovimento ? undefined : ELEVAR}
      transition={MOLA}
      className={cn(
        "vidro holofote relative overflow-hidden rounded-card",
        "shadow-[0_1px_2px_rgb(0_0_0/0.04),0_8px_24px_-12px_rgb(0_0_0/0.18)]",
        className,
      )}
      {...resto}
    >
      {faixa ? (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 w-1 rounded-l-[--radius-card]"
          style={{ backgroundColor: faixa }}
        />
      ) : null}
      {children}
    </motion.div>
  );
}

"use client";

import { useMotionValue, useSpring, useReducedMotion } from "framer-motion";
import { useEffect, useRef } from "react";

import { dinheiro, numero as formatarNumero } from "@/lib/formato";

interface Props {
  valor: number;
  /** Como escrever o número a cada quadro. */
  formato?: "moeda" | "numero" | "inteiro";
  className?: string;
}

/**
 * Número que caminha até o novo valor em vez de saltar.
 *
 * Serve para o resumo de imposto do formulário: digitar o valor do serviço
 * recalcula ISS na hora, e o número deslizando deixa claro *que recalculou*.
 * Um salto seco passa despercebido — sobretudo quando muda pouco.
 *
 * O texto é escrito direto no nó, sem estado React: são sessenta quadros por
 * segundo, e cada um redesenharia o formulário inteiro.
 */
export function NumeroAnimado({ valor, formato = "moeda", className }: Props) {
  const no = useRef<HTMLSpanElement>(null);
  const semMovimento = useReducedMotion();
  const cru = useMotionValue(valor);
  const suave = useSpring(cru, { stiffness: 140, damping: 24, mass: 0.6 });

  useEffect(() => {
    if (semMovimento) {
      cru.jump(valor);
      return;
    }
    cru.set(valor);
  }, [valor, cru, semMovimento]);

  useEffect(() => {
    const escrever = (atual: number) => {
      if (!no.current) return;
      no.current.textContent =
        formato === "moeda"
          ? dinheiro(atual)
          : formato === "inteiro"
            ? String(Math.round(atual))
            : formatarNumero(atual);
    };
    escrever(suave.get());
    return suave.on("change", escrever);
  }, [suave, formato]);

  return (
    <span
      ref={no}
      className={className}
      // Leitor de tela anuncia o valor final, não a contagem.
      aria-label={formato === "moeda" ? dinheiro(valor) : String(valor)}
    >
      {formato === "moeda" ? dinheiro(valor) : String(valor)}
    </span>
  );
}

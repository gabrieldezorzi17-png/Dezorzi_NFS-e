/**
 * A física do movimento, num lugar só.
 *
 * Duração fixa faz tudo parecer igual e um pouco morto. Mola dá peso: o que é
 * grande demora um pouco mais a assentar, o que é pequeno responde na hora —
 * sem ninguém escolher milissegundo nenhum.
 */
import type { Transition, Variants } from "framer-motion";

/** A mola padrão da casa. */
export const MOLA: Transition = {
  type: "spring",
  stiffness: 300,
  damping: 30,
};

/** Para o que precisa assentar rápido: contadores, pílulas, ícones. */
export const MOLA_CURTA: Transition = {
  type: "spring",
  stiffness: 420,
  damping: 34,
};

/** Para painéis inteiros, que ficam pesados com mola muito dura. */
export const MOLA_LONGA: Transition = {
  type: "spring",
  stiffness: 180,
  damping: 26,
};

/** Troca de tela. Entra subindo, sai subindo — o movimento tem direção. */
export const TELA: Variants = {
  entrada: { opacity: 0, y: 12 },
  ativa: { opacity: 1, y: 0, transition: MOLA },
  saida: { opacity: 0, y: -12, transition: { duration: 0.16 } },
};

/**
 * Lista que aparece em cascata.
 *
 * `staggerChildren` pequeno de propósito: acima de ~40ms por item, uma
 * fileira de quatro cartões vira uma espera perceptível toda vez que a tela
 * abre — e essa tela abre o dia inteiro.
 */
export const CASCATA: Variants = {
  ativa: { transition: { staggerChildren: 0.045, delayChildren: 0.02 } },
};

export const ITEM: Variants = {
  entrada: { opacity: 0, y: 10 },
  ativa: { opacity: 1, y: 0, transition: MOLA },
};

/** Linha de tabela que entra ou sai por filtro. */
export const LINHA: Variants = {
  entrada: { opacity: 0, y: -6 },
  ativa: { opacity: 1, y: 0, transition: MOLA_CURTA },
  saida: { opacity: 0, transition: { duration: 0.12 } },
};

/** O toque: some no clique, volta no soltar. */
export const TOQUE = { scale: 0.97 } as const;

/** A elevação no hover. 1.5% é pouco de propósito — a 5% já parece brinquedo. */
export const ELEVAR = { scale: 1.015 } as const;

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Junta classes deixando a última vencer quando duas mexem na mesma coisa.
 *
 * Sem isto, `cn("px-4", props.className)` com `px-6` vindo de fora produz as
 * duas classes e quem ganha depende da ordem no CSS gerado — que não é a
 * ordem em que foram escritas.
 */
export function cn(...entradas: ClassValue[]): string {
  return twMerge(clsx(entradas));
}

import type { NextConfig } from "next";

/**
 * A janela do Tauri carrega arquivos estáticos do disco, não um servidor
 * Node. Por isso `output: "export"`: o build vira HTML e JS soltos, que o
 * webview abre direto.
 *
 * Consequência a não esquecer: nada de rota de API do Next, nada de
 * renderização no servidor. Quem responde é o motor Python — e é onde a
 * regra fiscal deve morar de qualquer forma.
 */
const configuracao: NextConfig = {
  output: "export",
  reactStrictMode: true,
  images: { unoptimized: true },
  // O motor local não é o mesmo host da interface durante o `next dev`;
  // em produção dentro do Tauri, os dois convivem em 127.0.0.1.
  env: {
    NEXT_PUBLIC_MOTOR_URL:
      process.env.NEXT_PUBLIC_MOTOR_URL ?? "http://127.0.0.1:8080",
  },
};

export default configuracao;

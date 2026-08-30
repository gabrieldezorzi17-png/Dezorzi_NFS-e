"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LazyMotion, domAnimation } from "framer-motion";
import { useState } from "react";

import { ProvedorDeDicas } from "@/components/pilula-status";

export function Provedores({ children }: { children: React.ReactNode }) {
  // Criado dentro de estado, não no módulo: um cliente por montagem. No
  // módulo, ele seria compartilhado entre requisições no servidor — e os
  // dados de uma sessão apareceriam na de outra.
  const [cliente] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Os dados vêm de um motor local: recarregar é barato, mas ficar
            // recarregando a cada foco de janela pisca a tela à toa.
            staleTime: 10_000,
            refetchOnWindowFocus: false,
            retry: (tentativas, erro) => {
              // Erro do motor com status não se resolve tentando de novo:
              // 404 continua 404, 422 continua 422. Só falha de conexão vale
              // uma segunda chance.
              const status = (erro as { status?: number })?.status;
              if (typeof status === "number" && status > 0) return false;
              return tentativas < 2;
            },
          },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={cliente}>
      {/* `LazyMotion` com `domAnimation` carrega só o necessário: corta uns
          20 kB do pacote de animação, que numa janela desktop é tempo de
          abertura. */}
      <LazyMotion features={domAnimation} strict={false}>
        <ProvedorDeDicas delayDuration={120} skipDelayDuration={300}>
          {children}
        </ProvedorDeDicas>
      </LazyMotion>
    </QueryClientProvider>
  );
}

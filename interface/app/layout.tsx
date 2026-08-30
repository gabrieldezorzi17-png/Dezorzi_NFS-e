import type { Metadata, Viewport } from "next";

import "./globals.css";
import { Provedores } from "./provedores";

export const metadata: Metadata = {
  title: "Dezorzi · NFS-e",
  description: "Emissão de NFS-e para São Bernardo do Campo.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
    { media: "(prefers-color-scheme: dark)", color: "#090d16" },
  ],
};

export default function RaizDoLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <head>
        {/*
          O tema é escolhido ANTES da primeira pintura.
          Deixar para o React aplicar depois faz a tela piscar branca por um
          quadro em quem usa o tema escuro — e é a primeira coisa que se vê
          toda vez que o programa abre.
        */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("tema");if(t==="claro"){document.documentElement.classList.remove("dark")}else{document.documentElement.classList.add("dark")}}catch(e){document.documentElement.classList.add("dark")}})();`,
          }}
        />
      </head>
      <body className="antialiased">
        <Provedores>{children}</Provedores>
      </body>
    </html>
  );
}

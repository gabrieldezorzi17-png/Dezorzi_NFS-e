# Interface web do emissor de NFS-e

Next.js + Tailwind v4 + Framer Motion + TanStack, para rodar dentro de uma
janela Tauri. Fala com o motor Python que já existe.

---

## O desenho

```
┌───────────────────────────┐        ┌──────────────────────────────┐
│  Janela Tauri (WebView2)  │  HTTP  │  Motor Python (server.py)    │
│  Next.js estático         │ ─────▶ │  GWT-RPC, sessão, validação  │
│  — desenha e pergunta     │ ◀───── │  NBS, alíquotas, rascunhos   │
└───────────────────────────┘  JSON  └──────────────┬───────────────┘
                                                    │ HTTPS
                                                    ▼
                                        portal de São Bernardo
```

**A regra fiscal não sobe para o TypeScript.** Montar o corpo GWT-RPC,
sincronizar a permutação do portal, decidir o que é NBS válido para um código
de serviço — tudo isso continua em Python, testado, com 352 testes. A
interface desenha e pergunta.

Isso não é preguiça de portar: é que duas implementações da mesma regra
divergem, e quando divergem a nota sai errada. Já aconteceu neste sistema com
a razão social (notas 74, 85 e 86) e com a descrição (nota 99).

**A senha do portal nunca passa por aqui.** Quem a pede é a tela de entrada do
motor, e ela vive só na memória daquele processo.

---

## Rodar

Nada disto está instalado nesta máquina hoje. É o custo de entrada:

| O quê | Para quê | Tamanho |
|---|---|---|
| Node.js LTS | build do Next | ~60 MB |
| Rust + cargo | compilar o Tauri | ~1,5 GB |
| VS Build Tools (C++) | o Tauri linka com MSVC | ~5–7 GB |
| WebView2 | ✅ já está aqui (151.0.4129) | — |

```bash
npm install
npm run motor     # sobe o Python em 127.0.0.1:8080
npm run dev       # sobe a interface em 3000
```

Para a janela desktop (depois de instalar Rust e Build Tools):

```bash
npm run tauri init
npm run app
```

---

## O que falta no motor

O formulário precisa de cinco rotas que **ainda não existem** em `server.py`.
Todas já existem como código Python — só não estão publicadas em HTTP:

| Rota | De onde vem |
|---|---|
| `GET /servicos` | `services.disponiveis()` |
| `GET /servicos/{codigo}/nbs` | `reforma.nbs_do_servico()` |
| `GET /nbs/{codigo}/tributacao` | `reforma.opcoes_do_nbs()` |
| `GET /cep/{cep}` | `cep.consultar()` |
| `GET /tomador/{documento}` | `tomador.consultar()` |

Enquanto não existirem, os campos correspondentes avisam que a lista não veio
— em vez de mostrar uma lista vazia como se não houvesse opção. O contrato de
cada uma está tipado no fim de `lib/api.ts`.

---

## Sobre "atualizar sem baixar executável"

O pedido era: alterar o código no servidor e o cliente já abrir a versão nova.

Isso vale para **esta camada** — a interface é HTML e JS, e o Tauri pode
carregá-la de uma URL remota em vez do disco. Mas repare no que muda de fato
neste sistema: a permutação do portal (que mudou três vezes num único dia), as
tabelas NBS, as alíquotas, as regras de obra. Nada disso está aqui. Está no
motor, na máquina de quem emite.

Então há duas formas honestas:

1. **Motor local, interface remota.** A janela busca a interface do servidor;
   o Python continua na máquina. A senha não sai dali. Mas atualizar a regra
   fiscal continua exigindo atualizar o motor — que é o que muda com
   frequência. O ganho é menor do que parece.

2. **Tudo no servidor.** Aí sim uma atualização basta. Em troca, a senha do
   portal e os cookies de sessão passam a viver num servidor, e emitir nota
   passa a depender da internet do servidor estar de pé. É uma decisão de
   responsabilidade fiscal, não de arquitetura.

Há um caminho intermediário que costuma resolver o problema real: manter o
executável e ligar o **atualizador do Tauri**, que troca a versão sozinho na
abertura. Não é "zero download" — é download que ninguém precisa fazer à mão.

---

## Arquivos

```
app/
  globals.css          tokens dos dois temas, vidro, holofote, borda viva
  layout.tsx           tema aplicado antes da primeira pintura
  page.tsx             casca: barra lateral + troca de tela animada
  provedores.tsx       TanStack Query, LazyMotion, dicas flutuantes
components/
  painel.tsx           KPIs, gráfico SVG animado, notas recentes
  tabela-notas.tsx     TanStack Table + virtualização + busca
  formulario-emissao.tsx  formulário guiado, cascata NBS, resumo vivo
  cartao-holofote.tsx  cartão de vidro com luz que segue o cursor
  pilula-status.tsx    selos vivos (pulso, giro, dica)
  numero-animado.tsx   número que caminha até o valor novo
lib/
  api.ts               cliente tipado do motor
  formato.ts           moeda, documento, data
  motion.ts            as molas, num lugar só
  cn.ts                junção de classes
```

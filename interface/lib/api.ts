/**
 * Cliente do motor fiscal.
 *
 * O motor é o Python que já existe (`server.py`): ele fala GWT-RPC com o
 * portal de São Bernardo, monta o corpo da requisição, guarda os rascunhos e
 * sabe o que é NBS, indicador de operação e classificação tributária.
 *
 * Esta interface NÃO reimplementa nada disso. Ela desenha e pergunta. A senha
 * do portal nunca passa por aqui: quem a digita é a tela de entrada do motor,
 * e ela vive só na memória do processo local.
 *
 * O motor escuta em 127.0.0.1 e confere `Origin` antes de aceitar POST —
 * porque um POST aqui emite nota fiscal, e qualquer página aberta no navegador
 * consegue disparar um. Por isso as escritas precisam sair da mesma origem.
 */

export const MOTOR =
  process.env.NEXT_PUBLIC_MOTOR_URL ?? "http://127.0.0.1:8080";

/* ------------------------------------------------------------------ *
 * Formatos que o motor devolve
 * ------------------------------------------------------------------ */

export type StatusNota = "draft" | "submitted" | "failed";

export interface Tomador {
  nome?: string;
  documento?: string;
  email?: string;
  endereco?: string;
  numero?: string;
  complemento?: string;
  bairro?: string;
  cep?: string;
  uf?: string;
  municipio?: string;
}

export interface Servico {
  codigo?: string;
  descricao?: string;
  valor?: string | number;
  aliquota?: string | number;
  /** Reforma tributária: os quatro campos IBS/CBS. */
  nbs?: string;
  indicador_operacao?: string;
  situacao_tributaria?: string;
  classificacao_tributaria?: string;
  local_prestacao?: string;
  municipio_prestacao?: string;
  uf_prestacao?: string;
  codigo_obra?: string;
}

export interface Payload {
  tomador?: Tomador;
  servico?: Servico;
  [chave: string]: unknown;
}

export interface NotaEmitida {
  numero?: string | number;
  codigo_verificacao?: string;
  link?: string;
}

export interface Documento {
  id: string;
  status: StatusNota;
  created_at: string;
  payload: Payload;
  nota?: NotaEmitida;
  erro?: string;
}

export interface Saude {
  status: string;
  /** `true` = transmite de verdade. É a informação mais perigosa da tela. */
  live_mode: boolean;
}

export interface Configuracao {
  /** O que ainda falta para conseguir emitir. Vazio = pronto. */
  pending: string[];
  [chave: string]: unknown;
}

export interface ResultadoEnvio {
  id: string;
  status: StatusNota;
  transmitted: boolean;
  message: string;
  preview?: unknown;
  result?: { nota?: NotaEmitida; [chave: string]: unknown };
}

/* ------------------------------------------------------------------ *
 * Erros
 * ------------------------------------------------------------------ */

/**
 * Falha vinda do motor, já traduzida.
 *
 * O motor devolve status HTTP com significado fiscal, e a tela precisa
 * distinguir os casos: 422 é campo errado (dá para corrigir e reenviar),
 * 409 é nota já enviada (não se emite de novo), 502 é o portal fora do ar
 * (não é culpa do preenchimento).
 */
export class ErroDoMotor extends Error {
  constructor(
    readonly status: number,
    mensagem: string,
    readonly campo?: string,
    readonly jaEnviada?: boolean,
  ) {
    super(mensagem);
    this.name = "ErroDoMotor";
  }

  /** O usuário consegue resolver corrigindo o formulário? */
  get corrigivel(): boolean {
    return this.status === 422;
  }

  get portalIndisponivel(): boolean {
    return this.status === 502 || this.status === 0;
  }
}

async function pedir<T>(
  rota: string,
  opcoes: RequestInit = {},
): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(`${MOTOR}${rota}`, {
      ...opcoes,
      headers: {
        "Content-Type": "application/json",
        ...(opcoes.headers ?? {}),
      },
      // O motor não usa cookie; mandar credencial só ampliaria a superfície.
      credentials: "omit",
      cache: "no-store",
    });
  } catch {
    // fetch só rejeita quando não houve resposta: motor desligado, porta
    // trocada, rede derrubada. Vale a pena separar de um 500.
    throw new ErroDoMotor(
      0,
      "O motor fiscal não respondeu. Ele está aberto nesta máquina?",
    );
  }

  const bruto = await resposta.text();
  let corpo: Record<string, unknown> = {};
  if (bruto) {
    try {
      corpo = JSON.parse(bruto) as Record<string, unknown>;
    } catch {
      // Resposta que não é JSON só acontece quando algo bem estranho
      // aconteceu; o texto cru ajuda mais que "erro de parsing".
      throw new ErroDoMotor(resposta.status, bruto.slice(0, 300));
    }
  }

  if (!resposta.ok) {
    throw new ErroDoMotor(
      resposta.status,
      String(corpo.error ?? `o motor respondeu ${resposta.status}`),
      corpo.field as string | undefined,
      Boolean(corpo.already_submitted),
    );
  }
  return corpo as T;
}

/* ------------------------------------------------------------------ *
 * Rotas que o motor já atende
 * ------------------------------------------------------------------ */

export const api = {
  saude: () => pedir<Saude>("/health"),

  configuracao: () => pedir<Configuracao>("/config"),

  listarNotas: async (): Promise<Documento[]> => {
    const { documents } = await pedir<{ documents: Documento[] }>("/documents");
    return documents ?? [];
  },

  buscarNota: (id: string) => pedir<Documento>(`/documents/${id}`),

  criarRascunho: (payload: Payload) =>
    pedir<Documento>("/documents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /** Monta o corpo e mostra o que seria enviado, sem enviar. */
  previa: (id: string) =>
    pedir<{ id: string; preview: unknown }>(`/documents/${id}/preview`, {
      method: "POST",
    }),

  /**
   * Envia ao portal. Em modo seguro o motor monta, valida e devolve
   * `transmitted: false` — a nota NÃO foi emitida, e a tela precisa dizer
   * isso com todas as letras.
   */
  enviar: (id: string) =>
    pedir<ResultadoEnvio>(`/documents/${id}/submit`, { method: "POST" }),
};

/* ------------------------------------------------------------------ *
 * Rotas que o motor ainda NÃO atende
 * ------------------------------------------------------------------ *
 * O formulário precisa destas cinco. Elas existem em Python — `services.py`,
 * `reforma.py`, `cep.py`, `tomador.py`, `municipios.py` —, só não estão
 * publicadas em HTTP. Enquanto não estiverem, o formulário funciona com o
 * que já foi carregado e avisa que a lista não veio, em vez de fingir.
 *
 *   GET  /servicos                      -> {servicos: [{codigo, nome}]}
 *   GET  /servicos/{codigo}/nbs         -> {nbs: [{codigo, descricao}]}
 *   GET  /nbs/{codigo}/tributacao       -> {indicador_operacao, classificacao_tributaria}
 *   GET  /cep/{cep}                     -> {logradouro, bairro, municipio, uf}
 *   GET  /tomador/{documento}           -> Tomador
 */

export interface OpcaoServico {
  codigo: string;
  nome: string;
}

export interface OpcaoNbs {
  codigo: string;
  descricao: string;
}

export interface Tributacao {
  indicador_operacao?: string;
  classificacao_tributaria?: string;
}

/** Situação tributária padrão. Não vem da planilha de correlação: é fixa. */
export const CST_PADRAO = "000";

export const catalogo = {
  servicos: () =>
    pedir<{ servicos: OpcaoServico[] }>("/servicos").then((r) => r.servicos ?? []),

  nbsDoServico: (codigo: string) =>
    pedir<{ nbs: OpcaoNbs[] }>(
      `/servicos/${encodeURIComponent(codigo)}/nbs`,
    ).then((r) => r.nbs ?? []),

  tributacaoDoNbs: (codigo: string) =>
    pedir<Tributacao>(`/nbs/${encodeURIComponent(codigo)}/tributacao`),

  cep: (cep: string) =>
    pedir<Partial<Tomador> & { logradouro?: string }>(
      `/cep/${cep.replace(/\D/g, "")}`,
    ),

  tomador: (documento: string) =>
    pedir<Tomador>(`/tomador/${documento.replace(/\D/g, "")}`),
};

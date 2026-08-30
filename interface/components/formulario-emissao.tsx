"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Loader2, Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import {
  api,
  catalogo,
  CST_PADRAO,
  ErroDoMotor,
  type Payload,
  type Servico,
  type Tomador,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { cep as formatarCep, documento as formatarDoc, paraNumero } from "@/lib/formato";
import { CASCATA, ITEM, MOLA, TELA } from "@/lib/motion";
import { BotaoPrincipal } from "./painel";
import { CartaoHolofote } from "./cartao-holofote";
import { NumeroAnimado } from "./numero-animado";
import { PilulaStatus } from "./pilula-status";

/* ------------------------------------------------------------------ *
 * Peças do formulário
 * ------------------------------------------------------------------ */

function Secao({
  numero,
  titulo,
  descricao,
  children,
}: {
  numero: number;
  titulo: string;
  descricao?: string;
  children: React.ReactNode;
}) {
  return (
    <motion.div variants={ITEM}>
      <CartaoHolofote estatico className="p-5">
        <div className="mb-4 flex items-start gap-3">
          <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-[rgb(var(--primaria-fraca))] text-[11px] font-bold text-[rgb(var(--primaria))]">
            {numero}
          </span>
          <div>
            <h2 className="text-sm font-semibold">{titulo}</h2>
            {descricao && (
              <p className="text-xs text-[rgb(var(--tinta-3))]">{descricao}</p>
            )}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">{children}</div>
      </CartaoHolofote>
    </motion.div>
  );
}

interface CampoProps {
  rotulo: string;
  valor: string;
  aoMudar: (valor: string) => void;
  /** Mostra o giro dentro do próprio campo enquanto a consulta corre. */
  carregando?: boolean;
  /** Recado abaixo do campo: o que a consulta achou, ou o que faltou. */
  recado?: string;
  tomDoRecado?: "erro" | "ok" | "neutro";
  aoBuscar?: () => void;
  larguraCheia?: boolean;
  multilinha?: boolean;
  [resto: string]: unknown;
}

/**
 * Campo com consulta embutida.
 *
 * O giro fica DENTRO do campo, não ao lado: é ali que o olho está enquanto se
 * digita, e um indicador em outro canto da tela passa despercebido.
 */
function Campo({
  rotulo,
  valor,
  aoMudar,
  carregando,
  recado,
  tomDoRecado = "neutro",
  aoBuscar,
  larguraCheia,
  multilinha,
  ...resto
}: CampoProps) {
  const cor =
    tomDoRecado === "erro"
      ? "text-[rgb(var(--falha-tinta))]"
      : tomDoRecado === "ok"
        ? "text-[rgb(var(--sucesso-tinta))]"
        : "text-[rgb(var(--tinta-3))]";

  return (
    <div className={cn("space-y-1.5", larguraCheia && "sm:col-span-2")}>
      <label className="block text-[11px] font-semibold uppercase tracking-wider text-[rgb(var(--tinta-2))]">
        {rotulo}
      </label>
      <div
        className={cn(
          "flex items-center gap-2 rounded-lg border border-[rgb(var(--borda-forte))]",
          "bg-[rgb(var(--superficie))] px-3 transition-shadow",
          "focus-within:border-[rgb(var(--primaria))]",
          "focus-within:ring-2 focus-within:ring-[rgb(var(--primaria)/0.25)]",
          multilinha ? "py-2" : "py-0",
        )}
      >
        {multilinha ? (
          <textarea
            value={valor}
            onChange={(evento) => aoMudar(evento.target.value)}
            rows={4}
            className="w-full resize-y bg-transparent text-sm outline-none"
            {...(resto as React.TextareaHTMLAttributes<HTMLTextAreaElement>)}
          />
        ) : (
          <input
            value={valor}
            onChange={(evento) => aoMudar(evento.target.value)}
            className="w-full bg-transparent py-2.5 text-sm outline-none"
            {...(resto as React.InputHTMLAttributes<HTMLInputElement>)}
          />
        )}

        <AnimatePresence>
          {carregando && (
            <motion.span
              initial={{ opacity: 0, scale: 0.7 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.7 }}
              transition={MOLA}
            >
              <Loader2 className="size-4 animate-spin text-[rgb(var(--primaria))]" />
            </motion.span>
          )}
        </AnimatePresence>

        {aoBuscar && !carregando && (
          <button
            type="button"
            onClick={aoBuscar}
            aria-label={`Consultar ${rotulo}`}
            className="shrink-0 rounded p-1 text-[rgb(var(--tinta-3))] hover:text-[rgb(var(--primaria))]"
          >
            <Search className="size-4" />
          </button>
        )}
      </div>
      <AnimatePresence mode="wait">
        {recado && (
          <motion.p
            key={recado}
            initial={{ opacity: 0, y: -3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className={cn("text-xs", cor)}
          >
            {recado}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}

function Escolha({
  rotulo,
  valor,
  aoMudar,
  opcoes,
  vazio,
  carregando,
  recado,
  larguraCheia,
  desabilitado,
}: {
  rotulo: string;
  valor: string;
  aoMudar: (valor: string) => void;
  opcoes: { valor: string; texto: string }[];
  vazio: string;
  carregando?: boolean;
  recado?: string;
  larguraCheia?: boolean;
  desabilitado?: boolean;
}) {
  return (
    <div className={cn("space-y-1.5", larguraCheia && "sm:col-span-2")}>
      <label className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[rgb(var(--tinta-2))]">
        {rotulo}
        {carregando && (
          <Loader2 className="size-3 animate-spin text-[rgb(var(--primaria))]" />
        )}
      </label>
      <select
        value={valor}
        disabled={desabilitado || carregando}
        onChange={(evento) => aoMudar(evento.target.value)}
        className={cn(
          "w-full rounded-lg border border-[rgb(var(--borda-forte))] bg-[rgb(var(--superficie))]",
          "px-3 py-2.5 text-sm outline-none transition-shadow",
          "focus:border-[rgb(var(--primaria))] focus:ring-2 focus:ring-[rgb(var(--primaria)/0.25)]",
          "disabled:cursor-not-allowed disabled:opacity-60",
        )}
      >
        <option value="">{vazio}</option>
        {opcoes.map((opcao) => (
          <option key={opcao.valor} value={opcao.valor}>
            {opcao.texto}
          </option>
        ))}
      </select>
      {recado && <p className="text-xs text-[rgb(var(--tinta-3))]">{recado}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Formulário
 * ------------------------------------------------------------------ */

const VAZIO: { tomador: Tomador; servico: Servico } = {
  tomador: {},
  servico: { situacao_tributaria: CST_PADRAO },
};

interface Props {
  aoSalvar: (id: string) => void;
}

export function FormularioEmissao({ aoSalvar }: Props) {
  const cliente = useQueryClient();
  const [tomador, setTomador] = useState<Tomador>(VAZIO.tomador);
  const [servico, setServico] = useState<Servico>(VAZIO.servico);
  const [recados, setRecados] = useState<Record<string, string>>({});

  const saude = useQuery({ queryKey: ["saude"], queryFn: api.saude });
  const transmitindo = saude.data?.live_mode ?? false;

  const servicos = useQuery({
    queryKey: ["servicos"],
    queryFn: catalogo.servicos,
    retry: false,
  });

  /**
   * A cascata da reforma tributária.
   *
   * Escolher o código de serviço carrega os NBS daquele código; escolher o
   * NBS preenche indicador de operação e classificação tributária conforme a
   * planilha de correlação. A situação tributária (CST-IBS/CBS) não está na
   * planilha: é sempre 000.
   *
   * Estas listas moram no motor — `reforma.py` e `config/nbs_por_item.json`.
   * Adivinhar um código aqui seria emitir nota com tributação errada.
   */
  const listaNbs = useQuery({
    queryKey: ["nbs", servico.codigo],
    queryFn: () => catalogo.nbsDoServico(servico.codigo!),
    enabled: Boolean(servico.codigo),
    retry: false,
  });

  const tributacao = useQuery({
    queryKey: ["tributacao", servico.nbs],
    queryFn: () => catalogo.tributacaoDoNbs(servico.nbs!),
    enabled: Boolean(servico.nbs),
    retry: false,
  });

  // O resultado da consulta preenche os dois campos; eles continuam
  // editáveis, porque quem conhece o caso concreto é quem está emitindo.
  const indop =
    servico.indicador_operacao ?? tributacao.data?.indicador_operacao ?? "";
  const classe =
    servico.classificacao_tributaria ??
    tributacao.data?.classificacao_tributaria ??
    "";

  /* --- consultas de CNPJ e CEP --- */

  const buscaTomador = useMutation({
    mutationFn: (doc: string) => catalogo.tomador(doc),
    onSuccess: (achado) => {
      setTomador((atual) => ({ ...atual, ...achado }));
      setRecados((r) => ({ ...r, documento: achado.nome ? "Encontrado no portal." : "" }));
    },
    onError: (erro) =>
      setRecados((r) => ({
        ...r,
        documento:
          erro instanceof ErroDoMotor && erro.status === 404
            ? "Não achei este documento. Preencha à mão."
            : "Não consegui consultar agora. Preencha à mão.",
      })),
  });

  const buscaCep = useMutation({
    mutationFn: (valor: string) => catalogo.cep(valor),
    onSuccess: (achado) => {
      setTomador((atual) => ({
        ...atual,
        endereco: achado.logradouro ?? atual.endereco,
        bairro: achado.bairro ?? atual.bairro,
        municipio: achado.municipio ?? atual.municipio,
        uf: achado.uf ?? atual.uf,
      }));
      setRecados((r) => ({ ...r, cep: "Endereço preenchido." }));
    },
    onError: () =>
      setRecados((r) => ({ ...r, cep: "CEP não encontrado. Preencha à mão." })),
  });

  /* --- resumo em tempo real --- */

  const resumo = useMemo(() => {
    const valor = paraNumero(servico.valor);
    const aliquota = paraNumero(servico.aliquota);
    const iss = (valor * aliquota) / 100;
    return { valor, aliquota, iss, liquido: valor - iss };
  }, [servico.valor, servico.aliquota]);

  /* --- o que ainda falta --- */

  const faltando = useMemo(() => {
    const falta: string[] = [];
    if (!servico.codigo) falta.push("código de serviço");
    if (!servico.descricao?.trim()) falta.push("descrição");
    if (resumo.valor <= 0) falta.push("valor");
    if (!servico.nbs) falta.push("código NBS");
    if (!indop) falta.push("indicador da operação");
    if (!classe) falta.push("classificação tributária");
    return falta;
  }, [servico, resumo.valor, indop, classe]);

  const salvar = useMutation({
    mutationFn: () => {
      const payload: Payload = {
        tomador,
        servico: {
          ...servico,
          indicador_operacao: indop,
          classificacao_tributaria: classe,
          situacao_tributaria: servico.situacao_tributaria || CST_PADRAO,
        },
      };
      return api.criarRascunho(payload);
    },
    onSuccess: (documento) => {
      cliente.invalidateQueries({ queryKey: ["notas"] });
      aoSalvar(documento.id);
    },
  });

  const mudarServico = useCallback(
    (campo: keyof Servico, valor: string) =>
      setServico((atual) => ({ ...atual, [campo]: valor })),
    [],
  );

  return (
    <motion.section
      variants={TELA}
      initial="entrada"
      animate="ativa"
      exit="saida"
      className="space-y-5 pb-28"
    >
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Emitir NFS-e</h1>
          <p className="text-sm text-[rgb(var(--tinta-3))]">
            O rascunho é salvo primeiro; o envio ao portal é o passo seguinte.
          </p>
        </div>
        <PilulaStatus
          tom={transmitindo ? "ativo" : "seguro"}
          detalhe={
            transmitindo
              ? "O envio deste rascunho vai gerar nota fiscal de verdade."
              : "As notas são montadas e validadas, mas não são enviadas."
          }
        />
      </header>

      <motion.div
        variants={CASCATA}
        initial="entrada"
        animate="ativa"
        className="space-y-4"
      >
        <Secao
          numero={1}
          titulo="Tomador"
          descricao="Deixe em branco para emitir sem tomador."
        >
          <Campo
            rotulo="CNPJ ou CPF"
            valor={formatarDoc(tomador.documento ?? "")}
            aoMudar={(valor) =>
              setTomador((atual) => ({
                ...atual,
                documento: valor.replace(/\D/g, "").slice(0, 14),
              }))
            }
            carregando={buscaTomador.isPending}
            recado={recados.documento}
            tomDoRecado={recados.documento?.startsWith("Encontrado") ? "ok" : "erro"}
            aoBuscar={() =>
              tomador.documento && buscaTomador.mutate(tomador.documento)
            }
            onBlur={() => {
              const doc = (tomador.documento ?? "").replace(/\D/g, "");
              if (doc.length === 11 || doc.length === 14) buscaTomador.mutate(doc);
            }}
            inputMode="numeric"
            placeholder="00.000.000/0000-00"
          />
          <Campo
            rotulo="Razão social"
            valor={tomador.nome ?? ""}
            aoMudar={(valor) => setTomador((a) => ({ ...a, nome: valor }))}
            placeholder="Nome que sai na nota"
          />
          <Campo
            rotulo="CEP"
            valor={formatarCep(tomador.cep ?? "")}
            aoMudar={(valor) =>
              setTomador((a) => ({ ...a, cep: valor.replace(/\D/g, "").slice(0, 8) }))
            }
            carregando={buscaCep.isPending}
            recado={recados.cep}
            tomDoRecado={recados.cep?.startsWith("Endereço") ? "ok" : "erro"}
            aoBuscar={() => tomador.cep && buscaCep.mutate(tomador.cep)}
            onBlur={() => {
              const valor = (tomador.cep ?? "").replace(/\D/g, "");
              if (valor.length === 8) buscaCep.mutate(valor);
            }}
            inputMode="numeric"
            placeholder="00000-000"
          />
          <Campo
            rotulo="Endereço"
            valor={tomador.endereco ?? ""}
            aoMudar={(valor) => setTomador((a) => ({ ...a, endereco: valor }))}
          />
        </Secao>

        <Secao numero={2} titulo="Serviço">
          <Escolha
            rotulo="Código do serviço"
            valor={servico.codigo ?? ""}
            aoMudar={(valor) =>
              // Trocar o serviço invalida a escolha de NBS: os códigos válidos
              // são outros. Manter o anterior mandaria tributação de um serviço
              // dentro da nota de outro.
              setServico((atual) => ({
                ...atual,
                codigo: valor,
                nbs: undefined,
                indicador_operacao: undefined,
                classificacao_tributaria: undefined,
              }))
            }
            opcoes={(servicos.data ?? []).map((item) => ({
              valor: item.codigo,
              texto: `${item.codigo} — ${item.nome}`,
            }))}
            vazio={servicos.isError ? "(a lista não veio do motor)" : "Escolha…"}
            carregando={servicos.isLoading}
            larguraCheia
          />
          <Campo
            rotulo="Descrição"
            valor={servico.descricao ?? ""}
            aoMudar={(valor) => mudarServico("descricao", valor)}
            multilinha
            larguraCheia
            placeholder={"As quebras de linha e o espaçamento saem na nota\ncomo foram digitados."}
          />
        </Secao>

        <Secao
          numero={3}
          titulo="Reforma tributária (IBS/CBS)"
          descricao="Escolher o NBS preenche o resto conforme a planilha de correlação."
        >
          <Escolha
            rotulo="Código NBS"
            valor={servico.nbs ?? ""}
            aoMudar={(valor) =>
              setServico((atual) => ({
                ...atual,
                nbs: valor,
                indicador_operacao: undefined,
                classificacao_tributaria: undefined,
              }))
            }
            opcoes={(listaNbs.data ?? []).map((item) => ({
              valor: item.codigo,
              texto: `${item.codigo} — ${item.descricao}`,
            }))}
            vazio={
              !servico.codigo
                ? "Escolha antes o código do serviço"
                : listaNbs.isError
                  ? "(a lista não veio do motor)"
                  : "Escolha…"
            }
            carregando={listaNbs.isFetching}
            desabilitado={!servico.codigo}
            larguraCheia
          />
          <Campo
            rotulo="Indicador da operação"
            valor={indop}
            aoMudar={(valor) => mudarServico("indicador_operacao", valor)}
            carregando={tributacao.isFetching}
            recado={
              tributacao.data?.indicador_operacao && !servico.indicador_operacao
                ? "Preenchido pela planilha."
                : undefined
            }
            tomDoRecado="ok"
          />
          <Campo
            rotulo="Classificação tributária"
            valor={classe}
            aoMudar={(valor) => mudarServico("classificacao_tributaria", valor)}
            carregando={tributacao.isFetching}
            recado={
              tributacao.data?.classificacao_tributaria &&
              !servico.classificacao_tributaria
                ? "Preenchida pela planilha."
                : undefined
            }
            tomDoRecado="ok"
          />
          <Campo
            rotulo="Situação tributária (CST)"
            valor={servico.situacao_tributaria ?? CST_PADRAO}
            aoMudar={(valor) => mudarServico("situacao_tributaria", valor)}
            recado="Padrão 000 — não vem da planilha."
          />
        </Secao>

        <Secao numero={4} titulo="Valores">
          <Campo
            rotulo="Valor do serviço"
            valor={String(servico.valor ?? "")}
            aoMudar={(valor) => mudarServico("valor", valor)}
            inputMode="decimal"
            placeholder="0,00"
          />
          <Campo
            rotulo="Alíquota (%)"
            valor={String(servico.aliquota ?? "")}
            aoMudar={(valor) => mudarServico("aliquota", valor)}
            inputMode="decimal"
            placeholder="2,00"
          />
        </Secao>

        <Secao
          numero={5}
          titulo="Local da prestação"
          descricao="Preencha só quando o serviço foi prestado fora do município."
        >
          <Campo
            rotulo="Município"
            valor={servico.municipio_prestacao ?? ""}
            aoMudar={(valor) => mudarServico("municipio_prestacao", valor)}
          />
          <Campo
            rotulo="UF"
            valor={servico.uf_prestacao ?? ""}
            aoMudar={(valor) => mudarServico("uf_prestacao", valor.toUpperCase().slice(0, 2))}
          />
        </Secao>
      </motion.div>

      {/* Resumo colado no rodapé: os números recalculam enquanto se digita, e
          ficam à vista sem precisar rolar de volta. */}
      <motion.div
        initial={{ y: 40, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={MOLA}
        className="fixed inset-x-0 bottom-0 z-30 px-4 pb-4 md:pl-[240px]"
      >
        <div className="vidro mx-auto flex max-w-5xl flex-wrap items-center gap-x-8 gap-y-3 rounded-card px-5 py-3.5 shadow-lg">
          <Linha titulo="Serviço" valor={resumo.valor} />
          <Linha
            titulo={`ISS (${resumo.aliquota.toFixed(2).replace(".", ",")}%)`}
            valor={resumo.iss}
            discreto
          />
          <Linha titulo="Líquido" valor={resumo.liquido} destaque />

          <div className="ml-auto flex items-center gap-3">
            <AnimatePresence mode="wait">
              {faltando.length > 0 ? (
                <motion.span
                  key="falta"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="max-w-xs text-xs text-[rgb(var(--alerta-tinta))]"
                >
                  Falta: {faltando.join(", ")}
                </motion.span>
              ) : (
                <motion.span
                  key="pronto"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  <PilulaStatus tom="submitted" texto="Pronto para salvar" />
                </motion.span>
              )}
            </AnimatePresence>
            <BotaoPrincipal
              disabled={faltando.length > 0 || salvar.isPending}
              onClick={() => salvar.mutate()}
            >
              {salvar.isPending ? "Salvando…" : "Salvar rascunho"}
            </BotaoPrincipal>
          </div>
        </div>

        <AnimatePresence>
          {salvar.isError && (
            <motion.p
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mx-auto mt-2 max-w-5xl rounded-lg bg-[rgb(var(--falha-fundo))] px-4 py-2 text-xs text-[rgb(var(--falha-tinta))]"
            >
              {salvar.error instanceof ErroDoMotor
                ? `${salvar.error.message}${salvar.error.campo ? ` (campo: ${salvar.error.campo})` : ""}`
                : String(salvar.error)}
            </motion.p>
          )}
        </AnimatePresence>
      </motion.div>
    </motion.section>
  );
}

function Linha({
  titulo,
  valor,
  destaque,
  discreto,
}: {
  titulo: string;
  valor: number;
  destaque?: boolean;
  discreto?: boolean;
}) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-[rgb(var(--tinta-3))]">
        {titulo}
      </p>
      <NumeroAnimado
        valor={valor}
        className={cn(
          "block tabular-nums",
          destaque
            ? "text-lg font-semibold text-[rgb(var(--primaria))]"
            : discreto
              ? "text-sm text-[rgb(var(--tinta-2))]"
              : "text-sm font-medium",
        )}
      />
    </div>
  );
}

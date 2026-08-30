"""Os quatro códigos da reforma tributária que a nota passou a exigir.

Em 24/08/2026 a prefeitura republicou o portal e a tela de emissão ganhou
quatro campos **obrigatórios** — o próprio programa deles valida assim:

    'Código do indicador de operação;'
    'Código da situação tributária IBS/CBS;'
    'Classificação tributária;'

Uma nota enviada sem eles não é recusada com mensagem: o servidor lança
exceção e responde HTTP 500 "The call failed on the server", sem dizer por quê.
Foi o que derrubou a emissão.

As listas vêm do próprio portal, e **não exigem login** — são tabelas
nacionais, iguais para todas as empresas. Ficam guardadas em disco porque a de
NBS tem 675 itens e não muda de um dia para o outro.

LEITURA DA RESPOSTA
-------------------
Cada item é um objeto com cinco posições no fluxo, e a ordem dos campos muda
conforme o tipo — NbsVO e CodSituacaoTributariaVO põem o identificador antes,
IndicadorDeOperacaoVO põe a descrição. Em vez de decorar quatro layouts, a
leitura pega as duas strings de cada grupo e distingue pelo formato: código é
só dígito e ponto; o resto é descrição. Vale para os quatro.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import date, timedelta

import paths

BASE = "https://nfse.isssbc.com.br/nfseweb/"
INTERFACE = "br.com.eicon.nfseweb.client.service.ControllerService"
ARQUIVO = paths.CONFIG_DIR / "reforma_codigos.json"
VALIDADE = timedelta(days=30)     # tabela nacional; não muda toda semana

CAMPOS = {
    "nbs": "buscarNbs",
    "indicador_operacao": "buscarIndicadoresDeOperacao",
    "situacao_tributaria": "buscarCodSituacoesTributarias",
    "classificacao_tributaria": "buscarClassificacoesTributarias",
}
CODIGO = re.compile(r"^[\d.]+$")

# A planilha de correlação não traz a situação tributária. O padrão é a
# tributação integral — o caso comum da prestação de serviço — e continua
# trocável na tela, entre as 18 que o portal aceita.
CST_PADRAO = "000"


class ReformaIndisponivel(RuntimeError):
    """Não deu para obter as tabelas da reforma."""


def _buscar(metodo: str) -> str:
    import nfse_client
    import portal

    portal.sincronizar()
    corpo = (f"7|0|4|{BASE}|{portal.politica_em_uso()}|{INTERFACE}|{metodo}|1|2|3|4|0|")
    pedido = urllib.request.Request(
        BASE + "nfse", data=corpo.encode("utf-8"),
        headers={
            "Content-Type": "text/x-gwt-rpc; charset=UTF-8",
            "X-GWT-Module-Base": BASE,
            "X-GWT-Permutation": portal.em_uso(),
            "Origin": "https://nfse.isssbc.com.br",
            "Referer": "https://nfse.isssbc.com.br/",
        },
    )
    with urllib.request.urlopen(pedido, timeout=120,
                                context=nfse_client.ssl_context()) as resposta:
        return resposta.read().decode("utf-8", errors="replace")


def ler_lista(texto: str) -> list[dict[str, str]]:
    """Extrai os pares código/descrição de uma resposta de lista do portal."""
    import nfse_client

    if not texto.startswith("//OK"):
        raise ReformaIndisponivel("o portal não respondeu //OK à consulta das tabelas")
    tabela = nfse_client.gwt_strings(texto)
    miolo = texto[texto.index("[") + 1: texto.rindex("[")].rstrip(", ")
    fluxo = [t.strip() for t in miolo.split(",") if t.strip()]

    def conteudo(token: str) -> str | None:
        """O texto que o token aponta, ou None se não for conteúdo."""
        try:
            posicao = int(token)
        except ValueError:
            return None           # é um long do GWT, não referência de string
        if not 1 <= posicao <= len(tabela):
            return None
        valor = tabela[posicao - 1]
        if "/" in valor and "." in valor.split("/")[0]:
            return None           # nome de classe
        return valor

    grupos = [fluxo[i:i + 5] for i in range(0, len(fluxo) - 4, 5)]

    # Qual das cinco posições guarda o código? A ordem dos campos muda conforme
    # o tipo, então em vez de decorar quatro layouts descobre-se pelo conjunto.
    #
    # O sinal decisivo é a unicidade: **código não se repete, descrição sim** —
    # 24 indicadores de operação compartilham 6 descrições. Só "ter cara de
    # código" não bastaria: há descrições puramente numéricas, e aí as duas
    # posições empatariam. Em caso de empate, vale a mais curta: código é curto,
    # descrição é frase.
    distintos: list[set[str]] = [set() for _ in range(5)]
    comprimentos: list[list[int]] = [[] for _ in range(5)]
    for grupo in grupos:
        for i, token in enumerate(grupo):
            texto = conteudo(token)
            if texto is not None and CODIGO.match(texto):
                distintos[i].add(texto)
                comprimentos[i].append(len(texto))
    if not any(distintos):
        return []

    def peso(i: int) -> tuple[int, float]:
        medio = sum(comprimentos[i]) / len(comprimentos[i]) if comprimentos[i] else 0.0
        return len(distintos[i]), -medio

    coluna_codigo = max(range(5), key=peso)

    itens: list[dict[str, str]] = []
    for grupo in grupos:
        codigo = conteudo(grupo[coluna_codigo])
        if not codigo:
            continue
        descricao = next((c for i, c in enumerate(map(conteudo, grupo))
                          if c and i != coluna_codigo), "")
        itens.append({"codigo": codigo, "descricao": descricao})
    return itens


def _guardado() -> dict:
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def tabelas(*, atualizar: bool = False, rede: bool = True) -> dict[str, list[dict[str, str]]]:
    """As quatro tabelas, do disco ou do portal.

    ``rede=False`` devolve só o que está em disco, sem consultar o portal. É o
    que a tela usa ao abrir: a consulta de NBS traz 675 itens, e feita na
    thread da interface o programa congelaria a cada vez que a tela de emissão
    fosse aberta. A atualização acontece em segundo plano.
    """
    guardado = _guardado()
    if not atualizar and guardado.get("campos"):
        try:
            lido = date.fromisoformat(guardado.get("lido_em", ""))
        except ValueError:
            lido = None
        if lido and date.today() - lido < VALIDADE:
            return guardado["campos"]
    if not rede:
        return guardado.get("campos") or {}

    campos = {}
    for chave, metodo in CAMPOS.items():
        try:
            campos[chave] = ler_lista(_buscar(metodo))
        except Exception:
            guardadas = (guardado.get("campos") or {}).get(chave)
            if not guardadas:
                raise
            campos[chave] = guardadas        # sem rede, vale o que já se tinha
    try:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO.write_text(json.dumps({"lido_em": date.today().isoformat(),
                                       "campos": campos}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    except OSError:
        pass
    return campos


def opcoes(campo: str, *, atualizar: bool = False, rede: bool = True) -> list[dict[str, str]]:
    return tabelas(atualizar=atualizar, rede=rede).get(campo, [])


def em_disco() -> bool:
    """Já há tabelas guardadas? Sem elas a tela precisa buscar antes de servir."""
    return bool(_guardado().get("campos"))


def para_o_corpo(codigo_nbs: str) -> str:
    """O NBS como vai na requisição: só os dígitos.

    Na tela e nas tabelas ele aparece como ``1.0401.23.00``; no corpo da nota
    viaja como o inteiro ``104012300``. Descoberto comparando uma emissão feita
    pelo navegador com a que o programa monta.
    """
    return re.sub(r"\D", "", str(codigo_nbs or ""))


# --------------------------------------------------------------------------- #
# NBS por item da lista de serviços
# --------------------------------------------------------------------------- #
# São 675 códigos NBS. Escolher entre eles sem filtro é convite a errar: a
# tabela de correlação amarra cada item da LC 116 aos NBS que lhe cabem, e o
# item é o começo do próprio código de serviço — "7.02/103141/1291" é o item
# 07.02. Assim a lista cai de 675 para algumas dezenas, todas pertinentes.
CORRELACAO = paths.CONFIG_DIR / "nbs_por_item.json"


def item_do_servico(codigo_servico: str) -> str:
    """O item da LC 116 dentro do código de serviço do portal.

    ``7.02/103141/1291`` -> ``07.02``. O zero à esquerda é o formato da tabela
    de correlação; o portal escreve sem ele.
    """
    inicio = str(codigo_servico or "").split("/")[0].strip()
    partes = inicio.split(".")
    if len(partes) != 2 or not all(p.isdigit() for p in partes):
        return ""
    return f"{int(partes[0]):02d}.{partes[1]}"


def _correlacao() -> dict:
    try:
        return json.loads(CORRELACAO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def nbs_do_servico(codigo_servico: str) -> list[dict]:
    """Os NBS que cabem neste serviço, já filtrados pelo que o portal aceita.

    Cada um traz junto os indicadores de operação e as classificações
    tributárias possíveis — a planilha amarra os três, e é isso que permite
    preencher sozinho quando só há uma alternativa.

    Sem correlação para o item, devolve a lista inteira do portal: melhor
    oferecer 675 opções do que esconder a única certa.
    """
    grupo = _correlacao().get(item_do_servico(codigo_servico))
    aceitos = {p["codigo"]: p for p in opcoes("nbs", rede=False)}
    if not grupo:
        return [dict(p, indop=[], classificacao=[]) for p in aceitos.values()]
    escolhidos = []
    for codigo, dados in grupo["nbs"].items():
        if codigo not in aceitos:
            continue      # a planilha envelheceu; o portal manda
        escolhidos.append({"codigo": codigo,
                           "descricao": dados.get("descricao") or aceitos[codigo]["descricao"],
                           "indop": dados.get("indop") or [],
                           "classificacao": dados.get("classificacao") or []})
    return escolhidos or [dict(p, indop=[], classificacao=[]) for p in aceitos.values()]


def opcoes_do_nbs(codigo_servico: str, codigo_nbs: str) -> dict[str, list[dict]]:
    """Indicadores e classificações possíveis para este NBS neste serviço.

    Listas vazias querem dizer "a planilha não diz" — e aí a escolha é do
    usuário, entre tudo que o portal aceita. Num campo que vira tributo, não
    inventar é parte do trabalho.
    """
    for nbs in nbs_do_servico(codigo_servico):
        if nbs["codigo"] == codigo_nbs:
            return {"indop": nbs["indop"], "classificacao": nbs["classificacao"]}
    return {"indop": [], "classificacao": []}


def descricao_do_item(codigo_servico: str) -> str:
    grupo = _correlacao().get(item_do_servico(codigo_servico))
    return (grupo or {}).get("descricao", "")

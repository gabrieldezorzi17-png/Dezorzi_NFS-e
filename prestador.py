"""Dados do prestador (a empresa logada) para montar o corpo da nota.

Por que isto existe
-------------------
O corpo GWT-RPC capturado traz o prestador embutido — inscrição, razão social,
endereço, contato. Sem tratar isso, cada empresa precisaria de uma captura
própria. Aqui os campos do prestador são **substituídos** pelos da empresa
logada, e uma captura passa a servir a todas.

Por que os dados não vêm 100% automáticos
-----------------------------------------
O portal devolve tudo em ``getSession``, mas numa tabela de strings de objeto
Java desduplicada: dá para reconhecer com certeza o que tem formato próprio
(e-mail, CEP, UF, telefone, CNPJ), e **não** dá para saber com certeza qual
string é a razão social e qual é o bairro. Chutar isso significa emitir nota
fiscal com o nome errado.

Então: ``sugerir()`` extrai o que consegue e marca o resto; quem confirma é o
usuário, uma vez por empresa, em ``config/empresas.json``. Depois disso a
emissão é automática para aquela empresa.
"""
from __future__ import annotations

import re
from typing import Any

import config
import nfse_client
import session

CAMPOS = (
    "inscricao", "razao_social", "nome_fantasia", "email", "telefone",
    "logradouro", "numero", "bairro", "cep", "uf",
)

CORPO_SESSAO = (
    "7|0|4|https://nfse.isssbc.com.br/nfseweb/|{{env:NFSE_GWT_POLICY}}|"
    "br.com.eicon.nfseweb.client.service.ControllerService|getSession|1|2|3|4|0|"
)


def _resposta_sessao() -> str:
    portal = session.get_session()
    if not portal.usable:
        raise nfse_client.NfseError(
            "configure o login automático para ler os dados da empresa no portal"
        )
    resposta = portal.consultar({
        "method": "POST",
        "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
        "headers": {
            "Accept": "*/*",
            "Content-Type": "text/x-gwt-rpc; charset=UTF-8",
            "Origin": "https://nfse.isssbc.com.br",
            "Referer": "https://nfse.isssbc.com.br/",
            "X-GWT-Module-Base": "https://nfse.isssbc.com.br/nfseweb/",
            "X-GWT-Permutation": "{{env:NFSE_GWT_PERMUTATION}}",
        },
        "escape": "raw",
        "body": CORPO_SESSAO,
    })
    aceita, mensagens = nfse_client.avaliar_resposta(resposta)
    if not aceita:
        raise nfse_client.NfseError("; ".join(mensagens) or "o portal recusou getSession")
    return resposta


def _consultar_sessao() -> list[str]:
    """Só os textos, sem os marcadores de tipo — leitura por vizinhança."""
    return [t for t in nfse_client.gwt_strings(_resposta_sessao())
            if not t.startswith(("br.", "java.", "[B/"))]


def tabela_bruta() -> list[str]:
    """O ``getSession`` campo a campo, com os vazios visíveis.

    Mostra o fluxo, não a tabela de strings: é justamente o campo vazio que
    explica um valor lido na casa errada, e ele não aparece na tabela.
    """
    fluxo = nfse_client.gwt_fluxo(_resposta_sessao())
    return [valor if valor is not None else "—  (vazio)" for valor in fluxo]


TIPOS_LOGRADOURO = {"RUA", "AVENIDA", "AV", "PRACA", "PRAÇA", "TRAVESSA", "ALAMEDA",
                    "ESTRADA", "RODOVIA", "PASSAGEM", "PASS", "VIELA", "LARGO"}

# Número de rua: até cinco dígitos, com letra opcional (1301, 75, 12A), ou
# "S/N". O limite de cinco evita confundir com CEP, que vem em 5+3 dígitos.
_NUMERO = re.compile(r"\d{1,5}[A-Za-z]?|S/?N", re.IGNORECASE)


def parece_numero(texto: str) -> bool:
    """O texto tem cara de número de endereço?"""
    return bool(_NUMERO.fullmatch(str(texto).strip()))


def conferir(dados: dict[str, str]) -> list[str]:
    """Problemas nos dados lidos do portal que impedem uma emissão segura.

    Existe porque o portal não valida esses campos: recebendo texto onde espera
    número, ele estoura com "Erro ao processar retorno do servidor na emissão da
    NFS-e. Consulte se a nota foi emitida" — e a partir daí ninguém sabe se
    saiu nota. Conferir aqui troca essa ambiguidade por uma recusa que diz qual
    campo está errado.
    """
    problemas = []
    # Campos que o portal exige preenchidos. Como toda posição do prestador
    # passa a ser sobrescrita, um campo não lido vira campo vazio na nota — daí
    # a conferência ter de cobrir o endereço inteiro, não só o número.
    obrigatorios = {
        "inscricao": "inscrição municipal",
        "razao_social": "razão social",
        "logradouro": "logradouro",
        "bairro": "bairro",
        "uf": "UF",
    }
    for campo, nome in obrigatorios.items():
        if not str(dados.get(campo, "")).strip():
            problemas.append(f"{nome} não foi lida da sessão")
    numero = str(dados.get("numero", "")).strip()
    if not numero:
        problemas.append("número do endereço não foi lido da sessão")
    elif not parece_numero(numero):
        problemas.append(
            f"número do endereço saiu como {numero!r}, que não é um número — "
            f"provavelmente o complemento do cadastro entrou no lugar"
        )
    cep = re.sub(r"\D", "", str(dados.get("cep", "")))
    if cep and len(cep) != 8:
        problemas.append(f"CEP incompleto: {dados.get('cep')!r}")
    return problemas


def extrair(tabela: list[str], ccm: str) -> dict[str, str]:
    """Lê os dados do prestador na resposta de ``getSession``.

    As regras foram conferidas em duas empresas reais com estruturas
    diferentes — uma com e-mail cadastrado e outra sem, o que desloca todas as
    posições. Por isso nada aqui usa índice fixo: cada campo é reconhecido por
    formato ou pela vizinhança.
    """
    ccm = str(ccm).strip()
    dados: dict[str, str] = {"inscricao": ccm}

    for indice, texto in enumerate(tabela):
        # A razão social vem logo depois da inscrição — vale nas duas amostras.
        if texto == ccm and indice + 1 < len(tabela) and "razao_social" not in dados:
            seguinte = tabela[indice + 1]
            if seguinte and not seguinte.isdigit():
                dados["razao_social"] = seguinte
        if "@" in texto and "email" not in dados:
            dados["email"] = texto
        elif texto in _UFS and "uf" not in dados:
            dados["uf"] = texto
        elif re.fullmatch(r"\d{10,11}", texto) and texto != ccm and "telefone" not in dados:
            dados["telefone"] = texto
        # Endereço: tipo de logradouro, bairro e logradouro saem em sequência.
        elif texto.upper() in TIPOS_LOGRADOURO and indice + 2 < len(tabela):
            if "bairro" not in dados:
                dados["bairro"] = tabela[indice + 1]
                dados["logradouro"] = tabela[indice + 2]
        elif texto == "Comercial" and indice + 1 < len(tabela) and "numero" not in dados:
            # O número do endereço vem depois de "Comercial" — mas quando a
            # empresa tem complemento cadastrado, o complemento entra na frente.
            # Foi assim que "PRIMEBUSINESS CENTER SL.47" saiu como número de
            # rua e o portal respondeu com erro genérico em vez de recusar.
            for adiante in tabela[indice + 1: indice + 3]:
                if parece_numero(adiante):
                    dados["numero"] = adiante
                    break
                dados.setdefault("complemento", adiante)

    for anterior, seguinte in zip(tabela, tabela[1:]):
        if re.fullmatch(r"\d{5}", anterior) and re.fullmatch(r"\d{3}", seguinte):
            dados["cep"] = anterior + seguinte
            break

    # Sem o fluxo não dá para separar fantasia de razão social — ver extrair_do_fluxo.
    dados.setdefault("nome_fantasia", dados.get("razao_social", ""))
    return {campo: valor for campo, valor in dados.items() if valor}


def extrair_do_fluxo(resposta: str, ccm: str) -> dict[str, str]:
    """Lê o prestador pela posição dos campos no objeto, não pela vizinhança.

    A tabela de strings do GWT só guarda o que tem valor: um campo vazio some
    dela e empurra todos os seguintes uma casa para trás. Era o que fazia o
    **nome fantasia ser lido como razão social** em empresa que tem os dois — e
    a nota saía com o nome errado, sem nada acusar.

    No fluxo (``nfse_client.gwt_fluxo``) campo vazio ocupa lugar, então as
    posições relativas valem para qualquer empresa. Layout confirmado na
    resposta real do portal:

    ``… | inscrição | nome fantasia | razão social | …``

    e, no endereço, ``… | "Comercial" | ø | número | …``.
    """
    fluxo = nfse_client.gwt_fluxo(resposta)
    ccm = str(ccm).strip()
    if not fluxo or ccm not in fluxo:
        return {}

    dados: dict[str, str] = {"inscricao": ccm}
    posicao = fluxo.index(ccm)
    fantasia = fluxo[posicao + 1] if posicao + 1 < len(fluxo) else None
    razao = fluxo[posicao + 2] if posicao + 2 < len(fluxo) else None
    # Toda empresa tem razão social; fantasia é opcional. Se o slot da razão
    # veio vazio, o cadastro tem só um nome e ele está no slot da fantasia.
    if razao:
        dados["razao_social"] = razao
        dados["nome_fantasia"] = fantasia or razao
    elif fantasia:
        dados["razao_social"] = fantasia
        dados["nome_fantasia"] = fantasia

    # CEP sai em duas partes coladas (09792 + 370). Voltando dali, os dois
    # campos preenchidos anteriores são logradouro e bairro, nessa ordem.
    for indice in range(len(fluxo) - 1):
        atual, seguinte = fluxo[indice], fluxo[indice + 1]
        if atual and seguinte and re.fullmatch(r"\d{5}", atual) and re.fullmatch(r"\d{3}", seguinte):
            dados["cep"] = atual + seguinte
            anteriores = [v for v in fluxo[:indice] if v]
            if len(anteriores) >= 2:
                dados["logradouro"] = anteriores[-1]
                dados["bairro"] = anteriores[-2]
            break

    if "Comercial" in fluxo:
        # Layout confirmado em duas empresas com preenchimentos opostos:
        #   … | "Comercial" | complemento | número | …
        # 346186 tem complemento vazio e número 1301; 254765 tem complemento
        # "PRIMEBUSINESS CENTER SL.47" e número 27. Ler "o seguinte a Comercial"
        # acertava só a primeira, e mandava o complemento como número na outra.
        endereco = fluxo.index("Comercial")
        complemento = fluxo[endereco + 1] if endereco + 1 < len(fluxo) else None
        numero = fluxo[endereco + 2] if endereco + 2 < len(fluxo) else None
        if complemento:
            dados["complemento"] = complemento
        if numero and parece_numero(numero):
            dados["numero"] = numero
        else:
            # Layout inesperado: procura adiante em vez de mandar o que estiver
            # ali. O que não parecer número não vai para o campo número.
            for passo in range(1, 8):
                adiante = fluxo[endereco + passo] if endereco + passo < len(fluxo) else None
                if adiante and parece_numero(adiante):
                    dados["numero"] = adiante
                    break

    for valor in fluxo:
        if not valor:
            continue
        if "@" in valor and "email" not in dados:
            dados["email"] = valor
        elif valor in _UFS and "uf" not in dados:
            dados["uf"] = valor
        elif re.fullmatch(r"\d{14}", valor) and "cnpj" not in dados:
            dados["cnpj"] = valor
        elif re.fullmatch(r"\d{10,11}", valor) and valor != ccm and "telefone" not in dados:
            dados["telefone"] = valor

    return {campo: valor for campo, valor in dados.items() if valor}


def ler(resposta: str, ccm: str) -> dict[str, str]:
    """Lê o prestador pelo fluxo; completa com a leitura antiga o que faltar.

    As duas convivem de propósito: o fluxo acerta os campos cuja posição foi
    confirmada, e a leitura por vizinhança ainda cobre casos que o fluxo não
    reconhece. O que o fluxo achou tem precedência — ele é o que distingue
    fantasia de razão social.
    """
    por_vizinhanca = extrair(
        [t for t in nfse_client.gwt_strings(resposta)
         if not t.startswith(("br.", "java.", "[B/"))],
        ccm,
    )
    por_fluxo = extrair_do_fluxo(resposta, ccm)
    return {**por_vizinhanca, **por_fluxo}


_cache: dict[str, dict[str, str]] = {}


def do_portal(ccm: str = "", *, recarregar: bool = False) -> dict[str, str]:
    """Dados do prestador logado, direto do portal.

    Guardados em memória por empresa: trocar de login 15 vezes numa sessão de
    trabalho não deve virar 15 idas à rede na hora de emitir.
    """
    ccm = (ccm or config.empresa_ativa()).strip()
    if not recarregar and ccm in _cache:
        return _cache[ccm]
    dados = ler(_resposta_sessao(), ccm)
    _cache[ccm] = dados
    return dados


def esquecer(ccm: str = "") -> None:
    """Descarta o que foi lido — usado ao trocar de empresa."""
    if ccm:
        _cache.pop(str(ccm).strip(), None)
    else:
        _cache.clear()


def sugerir(ccm: str = "") -> tuple[dict[str, str], list[str]]:
    """Extração do portal mais a lista do que não veio."""
    ccm = (ccm or config.empresa_ativa()).strip()
    achado = ler(_resposta_sessao(), ccm)
    return achado, [campo for campo in CAMPOS if campo not in achado]


_UFS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}


def cadastrado(ccm: str = "") -> dict[str, str]:
    """Dados confirmados da empresa, em config/empresas.json."""
    ccm = (ccm or config.empresa_ativa()).strip()
    info = config.empresas().get(ccm) or {}
    dados = info.get("prestador") if isinstance(info, dict) else None
    if not isinstance(dados, dict):
        return {}
    return {str(k): str(v) for k, v in dados.items() if str(v).strip()}


def completo(ccm: str = "") -> bool:
    dados = cadastrado(ccm)
    return all(campo in dados for campo in CAMPOS)


def faltando(ccm: str = "") -> list[str]:
    dados = cadastrado(ccm)
    return [campo for campo in CAMPOS if campo not in dados]


def aplicar(corpo: str, posicoes: dict[str, Any], ccm: str = "",
            dados: dict[str, str] | None = None) -> str:
    """Troca no corpo as posições do prestador pelos dados da empresa logada.

    ``posicoes`` vem do modelo: ``{"32": "inscricao", "34": "razao_social", …}``
    — a posição na tabela de strings e o campo que ela guarda.
    """
    dados = dados if dados is not None else cadastrado(ccm)
    if not dados or not posicoes:
        return corpo

    partes = corpo.split("|")
    if len(partes) < 4 or not partes[2].isdigit():
        return corpo
    total = int(partes[2])
    tabela = partes[3:3 + total]

    for posicao, campo in posicoes.items():
        try:
            indice = int(posicao) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= indice < len(tabela):
            continue
        # Toda posição do prestador é sobrescrita, mesmo sem valor. Deixar a do
        # modelo seria pôr o dado da empresa da captura na nota de outra: o
        # e-mail pessoal de quem fez a captura viajou assim numa nota alheia,
        # porque a empresa logada não tinha e-mail e o campo simplesmente não
        # era tocado.
        tabela[indice] = nfse_client.escape_gwt(dados.get(str(campo)) or "")
    return "|".join(partes[:3] + tabela + partes[3 + total:])

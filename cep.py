"""Endereço a partir do CEP, para cadastrar tomador que o portal não conhece.

O portal responde vazio para CNPJ fora do cadastro dele, e aí o endereço todo é
digitado à mão. Digitar logradouro, bairro e cidade a cada cliente novo é onde
erro entra numa nota fiscal — por isso o CEP preenche o resto.

A consulta é a do **próprio portal** (``buscaEndereco``), e não um serviço de
CEP externo. Duas vantagens concretas: nada sai do portal, e o endereço vem no
formato que o portal aceita — inclusive o código IBGE do município, que a nota
precisa e que um serviço genérico entregaria noutro formato.

O código vem como ``long`` do GWT: ``LrB`` = 47809, que com a UF 35 forma
``3547809`` (Santo André).

Para desligar, ``NFSE_CEP=off`` no .env — o campo continua digitável.
"""
from __future__ import annotations

import os
import re

CORPO = (
    "7|0|6|https://nfse.isssbc.com.br/nfseweb/|{{env:NFSE_GWT_POLICY}}|"
    "br.com.eicon.nfseweb.client.service.ControllerService|buscaEndereco|"
    "java.lang.String/2004016611|{cep}|1|2|3|4|1|5|6|"
)
CABECALHOS = {
    "Accept": "*/*",
    "Content-Type": "text/x-gwt-rpc; charset=UTF-8",
    "Origin": "https://nfse.isssbc.com.br",
    "Referer": "https://nfse.isssbc.com.br/",
    "X-GWT-Module-Base": "https://nfse.isssbc.com.br/nfseweb/",
    "X-GWT-Permutation": "{{env:NFSE_GWT_PERMUTATION}}",
}


class CepError(RuntimeError):
    """Não deu para descobrir o endereço deste CEP."""


def ligado() -> bool:
    return os.getenv("NFSE_CEP", "on").strip().lower() not in ("off", "0", "false", "nao", "não")


def limpar(valor: str) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def buscar(valor: str) -> dict[str, str]:
    """Endereço do CEP: logradouro, bairro, cidade, UF e código IBGE.

    A leitura é por vizinhança dentro da resposta, ancorada nos marcadores de
    classe. Conferida em dois CEPs de municípios diferentes.
    """
    import nfse_client
    import session

    cep = limpar(valor)
    if len(cep) != 8:
        raise CepError("o CEP precisa ter 8 dígitos")
    if not ligado():
        raise CepError("consulta de CEP desligada (NFSE_CEP=off)")

    resposta = session.get_session().consultar({
        "method": "POST",
        "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
        "headers": CABECALHOS,
        "escape": "raw",
        "body": CORPO.format(cep=f"{cep[:5]}-{cep[5:]}"),
    })
    return ler_resposta(resposta, cep)


def ler_resposta(resposta: str, cep: str) -> dict[str, str]:
    """Extrai o endereço da resposta de ``buscaEndereco``."""
    import nfse_client

    tokens, tabela = nfse_client.gwt_tokens(resposta)
    if not tabela:
        raise CepError(f"CEP {cep} não encontrado")

    def texto(indice: int) -> str:
        if not 0 <= indice < len(tokens):
            return ""
        try:
            posicao = int(tokens[indice])
        except ValueError:
            return ""
        if not 1 <= posicao <= len(tabela):
            return ""
        valor = str(tabela[posicao - 1])
        estrutural = ("/" in valor and "." in valor.split("/")[0]) or valor.startswith("rO0AB")
        return "" if estrutural else valor

    def classe(indice: int, nome: str) -> bool:
        if not 0 <= indice < len(tokens):
            return False
        try:
            posicao = int(tokens[indice])
        except ValueError:
            return False
        return 1 <= posicao <= len(tabela) and nome in tabela[posicao - 1]

    # Tipo de logradouro e nome ficam separados; a nota usa os dois juntos.
    # O tipo vem quatro campos depois da classe TbTpLogradouro (marcador, Short
    # e o código); pegá-lo "três antes do bairro" falhava nos CEPs que têm
    # observação de faixa ("- DE 612 A 1510 - LADO PAR").
    tipo = nome_via = bairro = ""
    for indice in range(len(tokens)):
        if classe(indice, "TbTpLogradouro"):
            tipo = texto(indice + 4)
            break
    for indice in range(len(tokens)):
        if classe(indice, "TbCepPK"):
            anteriores = [texto(k) for k in range(indice) if texto(k)]
            if len(anteriores) >= 2:
                bairro, nome_via = anteriores[-2], anteriores[-1]
            break

    cidade = uf = ""
    municipio = ""
    for indice in range(len(tokens)):
        if classe(indice, "TbMunicipioIbgePK"):
            # O código vem como long do GWT, depois do marcador «Long». Um
            # token puramente numérico ali é referência à tabela, não o código:
            # foi o que fez Santo André virar 3503453.
            for adiante in range(indice + 1, min(indice + 5, len(tokens))):
                candidato = tokens[adiante]
                if candidato.isdigit() or candidato in ("0", ""):
                    continue
                try:
                    municipio = str(nfse_client.long_gwt_para_int(candidato))
                except Exception:
                    continue
                else:
                    break
        if classe(indice, "TbUfIbge"):
            seguintes = [texto(k) for k in range(indice, len(tokens)) if texto(k)]
            for candidato in seguintes:
                if len(candidato) == 2 and candidato.isalpha():
                    uf = candidato.upper()
                    break
    valores = [texto(k) for k in range(len(tokens)) if texto(k)]
    if uf and uf in valores:
        posterior = valores[valores.index(uf) + 1:]
        cidade = posterior[0] if posterior else ""

    if not (bairro or nome_via):
        raise CepError(f"CEP {cep} não encontrado")

    codigo_ibge = ""
    if uf and municipio:
        from municipios import ufs

        try:
            uf_codigo = next(u["codigo"] for u in ufs() if u["sigla"] == uf)
        except Exception:
            uf_codigo = ""
        if uf_codigo:
            codigo_ibge = f"{uf_codigo}{int(municipio):05d}"

    return {
        "cep": cep,
        "logradouro": f"{tipo} {nome_via}".strip() if tipo else nome_via,
        "complemento": "",
        "bairro": bairro,
        "cidade": cidade,
        "uf": uf,
        "municipio": codigo_ibge,
    }

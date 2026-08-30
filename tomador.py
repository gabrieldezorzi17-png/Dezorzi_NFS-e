"""Dados do tomador, consultados no portal a cada emissão.

Por que isto existe
-------------------
O corpo capturado traz o tomador embutido: endereço, e-mail, razão social e —
o mais importante — o **id interno dele no portal**. Sem substituir isso, cada
cliente exigiria uma captura própria, e emitir para outro tomador mandaria os
dados do cliente errado.

O portal responde tudo em ``buscaTomadorCnpj``. As regras de leitura abaixo
foram conferidas em duas consultas reais de tomadores diferentes, cuja
estrutura veio idêntica.
"""
from __future__ import annotations

import re
from typing import Any

import nfse_client
import session

CAMPOS = ("documento", "razao_social", "email", "logradouro", "numero",
          "complemento", "bairro", "cep", "id")

TIPOS_LOGRADOURO = ("RUA", "AVENIDA", "AV", "PRACA", "PRAÇA", "TRAVESSA", "ALAMEDA",
                    "ESTRADA", "RODOVIA", "PASSAGEM", "PASS", "VIELA", "LARGO")


class NaoEncontrado(RuntimeError):
    """O portal não conhece este documento no cadastro de tomadores."""


def _corpo(documento: str) -> str:
    return (
        "7|0|7|https://nfse.isssbc.com.br/nfseweb/|{{env:NFSE_GWT_POLICY}}|"
        "br.com.eicon.nfseweb.client.service.ControllerService|buscaTomadorCnpj|"
        f"java.lang.String/2004016611|I|{documento}|1|2|3|4|2|5|6|7|1|"
    )


def extrair(tabela: list[str], documento: str) -> dict[str, str]:
    """Lê os dados do tomador na resposta do portal.

    Nada aqui depende de índice absoluto: o documento consultado serve de
    âncora e os demais campos são achados por formato ou vizinhança.
    """
    documento = re.sub(r"\D", "", str(documento))
    dados: dict[str, str] = {"documento": documento}

    for indice, texto in enumerate(tabela):
        if "@" in texto and "email" not in dados:
            dados["email"] = texto
        elif texto == documento and indice + 1 < len(tabela):
            dados["complemento"] = tabela[indice + 1]
        elif texto.upper().startswith(TIPOS_LOGRADOURO) and "logradouro" not in dados:
            dados["logradouro"] = texto
            # O id interno vem imediatamente antes do logradouro; o número,
            # logo depois. Confirmado nas duas consultas.
            if indice > 0:
                dados["id"] = tabela[indice - 1]
            if indice + 1 < len(tabela):
                dados["numero"] = tabela[indice + 1]
        elif texto.startswith("Pessoa ") and indice > 0 and "razao_social" not in dados:
            dados["razao_social"] = tabela[indice - 1]

    for anterior, seguinte in zip(tabela, tabela[1:]):
        if re.fullmatch(r"\d{5}", anterior) and re.fullmatch(r"\d{3}", seguinte):
            dados["cep"] = anterior + seguinte
            break

    if tabela and "bairro" not in dados:
        dados["bairro"] = tabela[0]
    return {campo: valor for campo, valor in dados.items() if valor}


_cache: dict[str, dict[str, str]] = {}


def consultar(documento: str, *, recarregar: bool = False) -> dict[str, str]:
    """Busca o tomador no portal. O resultado fica em memória por documento."""
    documento = re.sub(r"\D", "", str(documento))
    if not recarregar and documento in _cache:
        return _cache[documento]

    portal = session.get_session()
    if not portal.usable:
        raise nfse_client.NfseError(
            "configure o login automático para consultar o tomador no portal"
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
        "body": _corpo(documento),
    })
    aceita, mensagens = nfse_client.avaliar_resposta(resposta)
    if not aceita:
        raise nfse_client.NfseError("; ".join(mensagens) or "o portal recusou a consulta")

    tabela = [t for t in nfse_client.gwt_strings(resposta) if not t.startswith(("br.", "java."))]
    if documento not in tabela:
        raise NaoEncontrado(
            f"o portal não encontrou o tomador {documento}. Cadastre-o no portal "
            f"uma vez; depois disso a emissão por aqui funciona."
        )
    dados = extrair(tabela, documento)
    _cache[documento] = dados
    return dados


def esquecer(documento: str = "") -> None:
    if documento:
        _cache.pop(re.sub(r"\D", "", documento), None)
    else:
        _cache.clear()


MANUAIS = ("razao_social", "logradouro", "numero", "complemento",
           "bairro", "cep", "email", "municipio")
OBRIGATORIOS_MANUAIS = ("razao_social", "logradouro", "numero", "bairro", "cep")


def manual(informado: dict[str, Any]) -> dict[str, str]:
    """Dados do tomador digitados à mão, quando o portal não o conhece.

    O portal responde vazio para CNPJ fora do cadastro dele — sem razão social,
    sem endereço e **sem id interno**. O id fica em branco de propósito: não há
    o que reaproveitar, e inventar um apontaria a nota para outro cliente.

    Só devolve algo se os campos essenciais estiverem preenchidos. Um bloco de
    tomador pela metade viraria nota com endereço incompleto.
    """
    dados = {"documento": re.sub(r"\D", "", str(informado.get("documento", ""))), "id": ""}
    for campo in MANUAIS:
        valor = str(informado.get(campo, "")).strip()
        if valor:
            dados[campo] = valor
    if any(campo not in dados for campo in OBRIGATORIOS_MANUAIS):
        return {}
    return dados


def falta_para_manual(informado: dict[str, Any]) -> list[str]:
    """Campos que ainda impedem montar o tomador à mão."""
    rotulos = {
        "razao_social": "razão social", "logradouro": "logradouro",
        "numero": "número", "bairro": "bairro", "cep": "CEP",
    }
    return [rotulos[campo] for campo in OBRIGATORIOS_MANUAIS
            if not str(informado.get(campo, "")).strip()]


def aplicar(corpo: str, posicoes: dict[str, Any], dados: dict[str, str]) -> str:
    """Troca no corpo as posições do tomador pelos dados consultados."""
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
        # Toda posição do tomador é sobrescrita, mesmo sem valor. Manter a do
        # modelo mandaria dado do cliente da captura — e no caso do **id
        # interno** isso apontaria a nota para outro tomador, que é o pior
        # desfecho possível. Tomador digitado à mão não tem id: vai vazio.
        tabela[indice] = nfse_client.escape_gwt(dados.get(str(campo)) or "")
    return "|".join(partes[:3] + tabela + partes[3 + total:])

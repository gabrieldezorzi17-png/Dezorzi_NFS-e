"""Estados e municípios do IBGE, lidos do próprio portal.

Servem ao campo **local da prestação**: quando o serviço é prestado fora de São
Bernardo, a nota precisa do código IBGE do município onde ele aconteceu.

A lista vem do portal (``listaUF`` e ``listaMunicipio``) em vez de um arquivo
embutido — assim ela acompanha o que o portal aceita, que é o que importa na
hora de emitir. Fica em cache no disco porque são 645 municípios só em São
Paulo e a lista praticamente não muda.

Formato das respostas, conferido contra códigos conhecidos:

* ``EstadoVO``    → ``tipo | nome | código | sigla``  (SP = 35, AC = 12)
* ``MunicipioVO`` → ``tipo | nome | código``          (São Bernardo = 48708)

O código IBGE completo é a UF seguida do município com cinco dígitos:
``35`` + ``48708`` = ``3548708``.
"""
from __future__ import annotations

import json
from typing import Any

import nfse_client
import paths
import session

CACHE_UFS = paths.CONFIG_DIR / "ufs.json"
CORPO_UFS = (
    "7|0|4|https://nfse.isssbc.com.br/nfseweb/|{{env:NFSE_GWT_POLICY}}|"
    "br.com.eicon.nfseweb.client.service.ControllerService|listaUF|1|2|3|4|0|"
)
CORPO_MUNICIPIOS = (
    "7|0|5|https://nfse.isssbc.com.br/nfseweb/|{{env:NFSE_GWT_POLICY}}|"
    "br.com.eicon.nfseweb.client.service.ControllerService|listaMunicipio|I|1|2|3|4|1|5|{uf}|"
)
CABECALHOS = {
    "Accept": "*/*",
    "Content-Type": "text/x-gwt-rpc; charset=UTF-8",
    "Origin": "https://nfse.isssbc.com.br",
    "Referer": "https://nfse.isssbc.com.br/",
    "X-GWT-Module-Base": "https://nfse.isssbc.com.br/nfseweb/",
    "X-GWT-Permutation": "{{env:NFSE_GWT_PERMUTATION}}",
}


def _consultar(corpo: str) -> str:
    return session.get_session().consultar({
        "method": "POST",
        "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
        "headers": CABECALHOS,
        "escape": "raw",
        "body": corpo,
    })


def _registros(resposta: str, tipo: str, campos: int) -> list[list[str]]:
    """Fatia a resposta em registros, a partir do marcador de tipo.

    Os códigos numéricos **não** são resolvidos contra a tabela de strings: o
    código de SP é 35 e existe uma string na posição 35, então resolver
    transformaria o código do estado no nome de outro. Aqui o token cru é
    devolvido e quem chama decide o que ele significa.
    """
    tokens, tabela = nfse_client.gwt_tokens(resposta)

    def texto(token: str) -> str | None:
        try:
            posicao = int(token)
        except ValueError:
            return None
        return tabela[posicao - 1] if 1 <= posicao <= len(tabela) else None

    registros = []
    for indice, token in enumerate(tokens):
        if texto(token) != tipo:
            continue
        pedaco = tokens[indice + 1: indice + 1 + campos]
        if len(pedaco) == campos:
            registros.append(pedaco)
    return registros


def ufs(*, atualizar: bool = False) -> list[dict[str, str]]:
    """Estados, com código IBGE e sigla."""
    if not atualizar and CACHE_UFS.exists():
        try:
            dados = json.loads(CACHE_UFS.read_text(encoding="utf-8"))
            if isinstance(dados, list) and dados:
                return dados
        except (OSError, json.JSONDecodeError):
            pass

    resposta = _consultar(CORPO_UFS)
    tokens, tabela = nfse_client.gwt_tokens(resposta)

    def texto(token: str) -> str:
        try:
            posicao = int(token)
        except ValueError:
            return ""
        return tabela[posicao - 1] if 1 <= posicao <= len(tabela) else ""

    encontrados: list[dict[str, str]] = []
    for nome_tk, codigo_tk, sigla_tk in _registros(resposta, _TIPO_UF, 3):
        nome, sigla = texto(nome_tk), texto(sigla_tk)
        if nome and len(sigla) == 2 and codigo_tk.isdigit():
            encontrados.append({"codigo": codigo_tk, "sigla": sigla, "nome": nome})
    encontrados.sort(key=lambda uf: uf["sigla"])
    if encontrados:
        CACHE_UFS.parent.mkdir(parents=True, exist_ok=True)
        CACHE_UFS.write_text(json.dumps(encontrados, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return encontrados


def municipios(uf_codigo: str, *, atualizar: bool = False) -> list[dict[str, str]]:
    """Municípios de um estado, com o código IBGE completo (7 dígitos)."""
    uf_codigo = str(uf_codigo).strip()
    if not uf_codigo.isdigit():
        raise nfse_client.NfseError(f"código de UF inválido: {uf_codigo!r}")
    cache = paths.CONFIG_DIR / f"municipios_{uf_codigo}.json"
    if not atualizar and cache.exists():
        try:
            dados = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(dados, list) and dados:
                return dados
        except (OSError, json.JSONDecodeError):
            pass

    resposta = _consultar(CORPO_MUNICIPIOS.format(uf=uf_codigo))
    _, tabela = nfse_client.gwt_tokens(resposta)

    def texto(token: str) -> str:
        try:
            posicao = int(token)
        except ValueError:
            return ""
        return tabela[posicao - 1] if 1 <= posicao <= len(tabela) else ""

    encontrados: list[dict[str, str]] = []
    vistos: set[str] = set()
    for nome_tk, codigo_tk in _registros(resposta, _TIPO_MUNICIPIO, 2):
        nome = texto(nome_tk)
        if not nome or not codigo_tk.isdigit():
            continue
        codigo = f"{uf_codigo}{int(codigo_tk):05d}"
        if codigo in vistos:
            continue
        vistos.add(codigo)
        encontrados.append({"codigo": codigo, "nome": nome})
    encontrados.sort(key=lambda m: m["nome"])
    if encontrados:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(encontrados, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return encontrados


_TIPO_UF = "br.com.eicon.nfseweb.client.vo.EstadoVO/3947169100"
_TIPO_MUNICIPIO = "br.com.eicon.nfseweb.client.vo.MunicipioVO/2818755302"


def nome_do_codigo(codigo: str) -> str:
    """Nome do município a partir do código IBGE, usando só o cache local."""
    codigo = str(codigo).strip()
    if len(codigo) != 7:
        return ""
    cache = paths.CONFIG_DIR / f"municipios_{codigo[:2]}.json"
    try:
        for item in json.loads(cache.read_text(encoding="utf-8")):
            if item.get("codigo") == codigo:
                return str(item.get("nome", ""))
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return ""

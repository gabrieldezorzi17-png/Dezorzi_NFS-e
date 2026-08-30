"""Obras cadastradas da empresa, para os serviços de construção civil.

Os serviços do item 7 que exigem Código da Obra só emitem com uma obra
informada. As obras são cadastradas no portal, por empresa, e a lista fica aqui
em ``config/obras_<CCM>.json`` — mesmo lugar e mesmo formato dos serviços.

A consulta é ``listaObra``, por município e competência — o município vai como
``long`` do GWT (48708, São Bernardo sem o prefixo da UF, que vira ``L5E``).

O que **não** foi possível confirmar: o formato de uma resposta **com** obras. O
login de teste só alcança uma empresa sem obras cadastradas, e essa responde
lista vazia. Por isso ``ler_resposta`` tem dois níveis e o campo continua
aceitando o código digitado — e por isso existe ``resposta_bruta()``, ligada ao
botão "Ver obras (bruto)" em Configurações, que mostra o que o portal devolveu
sem interpretar.

Formato do arquivo:

```json
[{"codigo": "12345", "descricao": "Obra da Rua X, 100"}]
```
"""
from __future__ import annotations

import json

import paths


def _arquivo(ccm: str) -> "paths.Path":
    return paths.CONFIG_DIR / f"obras_{str(ccm).strip()}.json"


def disponiveis(ccm: str = "") -> list[dict[str, str]]:
    """Obras conhecidas da empresa. Lista vazia quando não há cadastro local."""
    import config

    ccm = (ccm or config.empresa_ativa()).strip()
    if not ccm:
        return []
    try:
        dados = json.loads(_arquivo(ccm).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(dados, list):
        return []
    limpas = []
    for item in dados:
        if not isinstance(item, dict):
            continue
        codigo = str(item.get("codigo", "")).strip()
        if codigo:
            limpas.append({"codigo": codigo,
                           "descricao": str(item.get("descricao", "")).strip()})
    return limpas


def gravar(ccm: str, lista: list[dict[str, str]]) -> None:
    """Grava a lista da empresa — usado quando o portal responder a consulta."""
    arquivo = _arquivo(ccm)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")


def rotulo(obra: dict[str, str]) -> str:
    descricao = obra.get("descricao", "")
    return f"{obra['codigo']}  —  {descricao}" if descricao else obra["codigo"]


# O portal lista as obras por município e data de competência. O long 48708 é o
# código de São Bernardo sem o prefixo da UF — conferido contra a captura, onde
# ele aparece codificado como "L5E".
MUNICIPIO_PADRAO = 48708
CORPO_LISTA = (
    "7|0|7|https://nfse.isssbc.com.br/nfseweb/|{{env:NFSE_GWT_POLICY}}|"
    "br.com.eicon.nfseweb.client.service.ControllerService|listaObra|"
    "java.lang.Long/4227064769|java.lang.String/2004016611|{data}|"
    "1|2|3|4|2|5|6|5|{municipio}|7|"
)


def do_portal(*, quando=None, municipio: int = MUNICIPIO_PADRAO) -> list[dict[str, str]]:
    """Consulta as obras no portal e grava o resultado da empresa logada.

    A leitura é por vizinhança: dentro de cada item, o token numérico é o
    código e o de texto é a descrição. Ver ``ler_resposta`` para os limites
    dessa leitura.
    """
    from datetime import date

    import config
    import nfse_client
    import session

    corpo = CORPO_LISTA.format(
        data=(quando or date.today()).strftime("%d/%m/%Y"),
        municipio=nfse_client.long_gwt(municipio),
    )
    resposta = session.get_session().consultar({
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
        "body": corpo,
    })
    encontradas = ler_resposta(resposta)
    if encontradas:
        gravar(config.empresa_ativa(), encontradas)
    return encontradas


def _e_classe(valor: str) -> bool:
    return "/" in valor and "." in valor.split("/")[0]


def ler_resposta(resposta: str) -> list[dict[str, str]]:
    """Extrai as obras de uma resposta de ``listaObra``.

    A leitura é feita em dois níveis, de propósito. A primeira tentativa usa o
    nome da classe de cada item como âncora — é o jeito certo. Mas o nome dessa
    classe só é conhecido vendo uma resposta **com** obras, e a única a que o
    login de teste dá acesso vem vazia. Então, se nenhuma classe de item for
    reconhecida, a segunda tentativa varre os valores soltos e emparelha código
    com descrição. Melhor mostrar a lista de um jeito imperfeito do que deixar o
    campo vazio numa empresa que tem obras cadastradas.
    """
    import nfse_client

    tokens, tabela = nfse_client.gwt_tokens(resposta)
    if not tabela:
        return []

    def texto(token: str) -> str:
        try:
            posicao = int(token)
        except ValueError:
            return ""
        return tabela[posicao - 1] if 1 <= posicao <= len(tabela) else ""

    # "obra" em vez de "ObraVO": o portal pode chamar a classe de TbObra,
    # ObraDTO ou o que for, e exigir o sufixo certo já custou uma lista vazia.
    envolucro = "listaobra"
    tipos = [t for t in tabela if _e_classe(t) and "obra" in t.lower()
             and envolucro not in t.lower().replace(".", "").replace("_", "")]

    encontradas: list[dict[str, str]] = []
    vistos: set[str] = set()

    def guardar(codigo: str, descricao: str) -> None:
        if codigo and codigo not in vistos:
            vistos.add(codigo)
            encontradas.append({"codigo": codigo, "descricao": descricao})

    for tipo in tipos:
        for indice, token in enumerate(tokens):
            if texto(token) != tipo:
                continue
            codigo, descricao = "", ""
            for adiante in tokens[indice + 1: indice + 8]:
                valor = texto(adiante)
                if not valor or _e_classe(valor):
                    continue
                if not codigo and valor.isdigit():
                    codigo = valor
                elif not descricao and not valor.isdigit():
                    descricao = valor
            guardar(codigo, descricao)
        if encontradas:
            return encontradas

    # Nenhuma classe de item reconhecida: emparelha os valores na ordem em que
    # aparecem — número vira código, o texto seguinte vira descrição.
    pendente = ""
    for valor in tabela:
        if _e_classe(valor) or not valor.strip() or valor.startswith("rO0AB"):
            continue
        if valor.isdigit():
            if pendente:
                guardar(pendente, "")
            pendente = valor
        elif pendente:
            guardar(pendente, valor)
            pendente = ""
    if pendente:
        guardar(pendente, "")
    return encontradas


def resposta_bruta(*, quando=None, municipio: int = MUNICIPIO_PADRAO) -> str:
    """A resposta crua de ``listaObra`` — para diagnosticar uma lista vazia."""
    from datetime import date

    import nfse_client
    import session

    corpo = CORPO_LISTA.format(
        data=(quando or date.today()).strftime("%d/%m/%Y"),
        municipio=nfse_client.long_gwt(municipio),
    )
    return session.get_session().consultar({
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
        "body": corpo,
    })

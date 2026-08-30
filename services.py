"""Lista os códigos de serviço habilitados para a empresa logada.

O portal responde isso na chamada GWT-RPC `consultarServicos`. Como a lista
depende do login, trocar de empresa troca os serviços automaticamente — nada
fica gravado no código.

Sobre o parser: uma resposta GWT-RPC tem a forma

    //OK[ <índices...>, ["tabela","de","strings"], 0, 7]

Reconstruir os objetos exigiria um desserializador GWT completo. Em vez disso
lemos a tabela de strings, que é suficiente e observável:

* o código do serviço tem formato inequívoco (``14.05/107120/1581``);
* a descrição oficial vem logo depois da entrada do item (``14.05``);
* o apelido cadastrado pela empresa é uma entrada em maiúsculas começando com
  "SERVIÇOS" — elas aparecem na mesma ordem dos códigos.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date
from typing import Any

import nfse_client
import paths
import session

CODE = re.compile(r"\d+\.\d+/\d+/\d+")
ALIAS = re.compile(r"^SERVI[ÇC]OS\b.*", re.IGNORECASE)
_lock = threading.Lock()


def _corpo_consulta(quando: date) -> str:
    return (
        "7|0|8|https://nfse.isssbc.com.br/nfseweb/|{{env:NFSE_GWT_POLICY}}|"
        "br.com.eicon.nfseweb.client.service.ControllerService|consultarServicos|"
        f"java.lang.String/2004016611|{quando:%d}|{quando:%m}|{quando:%Y}|1|2|3|4|3|5|5|5|6|7|8|"
    )


def tabela_de_strings(resposta: str) -> list[str]:
    """Extrai a tabela de strings — o último vetor JSON da resposta."""
    if not resposta.startswith("//OK"):
        raise nfse_client.NfseError(
            "o portal não respondeu //OK à consulta de serviços; a sessão pode ter caído"
        )
    vetores = re.findall(r'\[(?:\s*"(?:[^"\\]|\\.)*"\s*,?)+\]', resposta)
    if not vetores:
        raise nfse_client.NfseError("não encontrei a tabela de strings na resposta do portal")
    try:
        return json.loads(vetores[-1])
    except json.JSONDecodeError as exc:
        raise nfse_client.NfseError(f"tabela de strings ilegível: {exc}") from exc


def interpretar(resposta: str) -> list[dict[str, str]]:
    """Converte a resposta em [{codigo, item, nome, descricao}, ...]."""
    tabela = tabela_de_strings(resposta)
    codigos = [texto for texto in tabela if CODE.fullmatch(texto)]
    apelidos = [texto for texto in tabela if texto.isupper() and ALIAS.match(texto)]

    servicos = []
    for posicao, codigo in enumerate(codigos):
        item = codigo.split("/", 1)[0]
        descricao = ""
        if item in tabela:
            seguinte = tabela.index(item) + 1
            if seguinte < len(tabela):
                descricao = tabela[seguinte]
        # Os apelidos saem na mesma ordem dos códigos; se a contagem não bater,
        # a descrição oficial assume — melhor um rótulo longo que um errado.
        nome = apelidos[posicao] if len(apelidos) == len(codigos) else (descricao or codigo)
        servicos.append({"codigo": codigo, "item": item, "nome": nome, "descricao": descricao})
    return servicos


def consultar(quando: date | None = None) -> list[dict[str, str]]:
    """Pergunta ao portal quais serviços a empresa logada pode emitir."""
    portal = session.get_session()
    if not portal.usable:
        raise nfse_client.NfseError(
            "configure o login automático (NFSE_USUARIO/NFSE_SENHA) para consultar os serviços"
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
        "body": _corpo_consulta(quando or date.today()),
    })
    servicos = interpretar(resposta)
    if servicos:
        salvar(servicos)
    return servicos


def cache_da_empresa(ccm: str = "") -> Any:
    """Arquivo de cache **por empresa**.

    Um cache único faria a lista de uma empresa aparecer depois de trocar para
    outra — e o serviço escolhido seria de quem não está logado.
    """
    import config

    ccm = (ccm or config.empresa_ativa() or "sem-empresa").strip()
    return paths.CONFIG_DIR / f"servicos_{ccm}.json"


def salvar(servicos: list[dict[str, str]], ccm: str = "") -> None:
    destino = cache_da_empresa(ccm)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(servicos, ensure_ascii=False, indent=2), encoding="utf-8")


def em_cache(ccm: str = "") -> list[dict[str, str]]:
    """Última lista consultada para esta empresa."""
    try:
        dados = json.loads(cache_da_empresa(ccm).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [s for s in dados if isinstance(s, dict) and s.get("codigo")]


def disponiveis(*, atualizar: bool = False) -> list[dict[str, str]]:
    """Serviços para o formulário: usa o cache e só vai ao portal se preciso."""
    with _lock:
        if not atualizar:
            guardados = em_cache()
            if guardados:
                return guardados
        return consultar()


def por_codigo(codigo: str) -> dict[str, Any] | None:
    for servico in em_cache():
        if servico.get("codigo") == codigo:
            return servico
    return None

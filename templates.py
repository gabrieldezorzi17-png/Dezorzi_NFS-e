"""Escolhe o modelo de emissão certo para cada caso.

Por que existe mais de um modelo
--------------------------------
O corpo GWT-RPC do portal é uma fotografia de uma emissão real. Ele carrega
embutido tudo o que não virou marcador: **o prestador** (CCM, razão social,
endereço, contato), **o tomador** (CNPJ, endereço, id interno no portal) e os
campos que aquele tipo de serviço exige — o 7.02, por exemplo, precisa do
Código da Obra, que não existe no corpo do 14.05.

Isso significa que um modelo cobre uma combinação, não o portal inteiro. A
saída não é adivinhar: é ter um modelo por caso, em ``config/templates/``, cada
um declarando o que cobre. O programa escolhe sozinho e **recusa quando não tem
modelo para o caso** — nunca improvisa com o corpo errado.

Formato de cada arquivo (além de method/url/headers/body):

    "cobre": {
      "prestador.ccm":     "304838",
      "tomador.documento": "11222333000181",
      "servico.codigo":    "14.05/107120/1581"
    }

Chave ausente = "serve para qualquer valor". Assim, um modelo que sirva a
qualquer tomador é só omitir ``tomador.documento``.
"""
from __future__ import annotations

import json
from typing import Any

import paths

PASTA = paths.CONFIG_DIR / "templates"


def _ccm_logado() -> str:
    """CCM da empresa autenticada — é o próprio usuário do portal."""
    import config

    return config.empresa_ativa()


def _valor_do_caso(chave: str, payload: dict[str, Any]) -> str:
    if chave == "prestador.ccm":
        return _ccm_logado()
    atual: Any = payload
    for parte in chave.split("."):
        if not isinstance(atual, dict) or parte not in atual:
            return ""
        atual = atual[parte]
    return str(atual).strip()


def carregar() -> list[dict[str, Any]]:
    """Todos os modelos disponíveis, com o nome do arquivo em ``_nome``."""
    modelos = []
    if PASTA.is_dir():
        for arquivo in sorted(PASTA.glob("*.json")):
            try:
                dados = json.loads(arquivo.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[templates] ignorando {arquivo.name}: {exc}")
                continue
            if isinstance(dados, dict) and dados.get("body"):
                dados["_nome"] = arquivo.stem
                modelos.append(dados)
    # Compatibilidade: instalação antiga com um único modelo solto.
    if not modelos and paths.REQUEST_TEMPLATE.exists():
        try:
            dados = json.loads(paths.REQUEST_TEMPLATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(dados, dict) and dados.get("body"):
            dados["_nome"] = "request_template"
            modelos.append(dados)
    return modelos


def cobertura(modelo: dict[str, Any]) -> dict[str, str]:
    bloco = modelo.get("cobre") or modelo.get("fixed") or {}
    return {str(k): str(v) for k, v in bloco.items()} if isinstance(bloco, dict) else {}


def atende(modelo: dict[str, Any], payload: dict[str, Any]) -> bool:
    return all(
        _valor_do_caso(chave, payload) == esperado
        for chave, esperado in cobertura(modelo).items()
    )


def descrever(modelo: dict[str, Any]) -> str:
    itens = cobertura(modelo)
    if not itens:
        return f"{modelo.get('_nome', '?')} (serve para qualquer caso)"
    resumo = ", ".join(f"{k}={v}" for k, v in itens.items())
    return f"{modelo.get('_nome', '?')} ({resumo})"


class SemModelo(RuntimeError):
    """Nenhum modelo cobre este caso — emitir seria usar o corpo errado."""


def escolher(payload: dict[str, Any]) -> dict[str, Any]:
    """Modelo que cobre este rascunho, ou um erro explicando o que falta."""
    modelos = carregar()
    if not modelos:
        raise SemModelo(
            "nenhum modelo de emissão encontrado. Gere um com "
            "'python import_curl.py captura/emitir.txt --conter emitirNfs'."
        )
    servem = [m for m in modelos if atende(m, payload)]
    if len(servem) == 1:
        return servem[0]
    if servem:
        # Mais específico primeiro: quem declara mais condições ganha.
        servem.sort(key=lambda m: len(cobertura(m)), reverse=True)
        return servem[0]

    servico = (payload.get("servico") or {}).get("codigo", "?")
    tomador = (payload.get("tomador") or {}).get("documento", "?")
    disponiveis = "\n".join(f"  • {descrever(m)}" for m in modelos)
    raise SemModelo(
        f"nenhum modelo cobre este caso:\n"
        f"  empresa (CCM) : {_ccm_logado() or '(login não configurado)'}\n"
        f"  tomador       : {tomador}\n"
        f"  serviço       : {servico}\n\n"
        f"Modelos disponíveis:\n{disponiveis}\n\n"
        f"Capture uma emissão real desse caso no portal e gere um modelo novo — "
        f"o corpo traz dados do prestador e do tomador que não podem ser deduzidos."
    )

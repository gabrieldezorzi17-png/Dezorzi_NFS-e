"""O que o portal libera para a empresa logada.

O portal decide, empresa a empresa, o que a tela de emissão mostra: se pode
reter ISS, se pode informar deduções, se pode alterar a alíquota. Ele responde
isso em chamadas próprias, e a tela do portal simplesmente esconde o que está
desligado.

Este módulo pergunta o mesmo. O motivo é concreto: uma nota foi emitida aqui com
"ISS retido" marcado e saiu **sem** retenção, porque o portal nem oferecia a
opção para aquela empresa. Um campo que não faz nada é pior que campo nenhum —
ele faz o usuário acreditar num imposto que não vai acontecer.

Todas as respostas ficam em cache por empresa, e são descartadas ao trocar de
login (``esquecer``).
"""
from __future__ import annotations

from datetime import date

import nfse_client

CABECALHOS = {
    "Accept": "*/*",
    "Content-Type": "text/x-gwt-rpc; charset=UTF-8",
    "Origin": "https://nfse.isssbc.com.br",
    "Referer": "https://nfse.isssbc.com.br/",
    "X-GWT-Module-Base": "https://nfse.isssbc.com.br/nfseweb/",
    "X-GWT-Permutation": "{{env:NFSE_GWT_PERMUTATION}}",
}
_PREFIXO = (
    "https://nfse.isssbc.com.br/nfseweb/|{{env:NFSE_GWT_POLICY}}|"
    "br.com.eicon.nfseweb.client.service.ControllerService|"
)

_cache: dict[str, bool] = {}


def _perguntar(corpo: str) -> bool:
    import session

    resposta = session.get_session().consultar({
        "method": "POST",
        "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
        "headers": CABECALHOS,
        "escape": "raw",
        "body": corpo,
    })
    return nfse_client.gwt_booleano(resposta)


def _chave(nome: str) -> str:
    import config

    return f"{config.empresa_ativa()}:{nome}"


def _flag(nome: str, corpo: str) -> bool:
    chave = _chave(nome)
    if chave not in _cache:
        _cache[chave] = _perguntar(corpo)
    return _cache[chave]


def pode_reter_iss() -> bool:
    """A empresa pode emitir nota com ISS retido?

    O portal chama isso de "prestador substituto". Quando é falso, a tela do
    portal não mostra a opção de retenção — e a nossa também não deve mostrar.
    """
    corpo = (f"7|0|6|{_PREFIXO}isPrestadorSubstituto|java.lang.String/2004016611|"
             f"{date.today().isoformat()}|1|2|3|4|1|5|6|")
    return _flag("reter_iss", corpo)


def pode_informar_deducoes() -> bool:
    return _flag("deducoes", f"7|0|4|{_PREFIXO}isDeducoesLiberadaEmpresa|1|2|3|4|0|")


def pode_alterar_aliquota() -> bool:
    return _flag("aliquota", f"7|0|4|{_PREFIXO}isAliquotaLiberadaEmpresa|1|2|3|4|0|")


def esquecer() -> None:
    """Descarta o que foi lido — usado ao trocar de empresa."""
    _cache.clear()

"""Descobre em que versão o portal da prefeitura está.

O portal é um aplicativo GWT. Cada publicação nova gera identificações novas
(as "permutações"), uma por navegador, e o servidor recusa qualquer requisição
que cite uma identificação que ele não conhece mais. O sintoma é brutal e sem
pista: **o login para de funcionar**, com erro 500 e "see server log for
details" — nada que aponte para a causa.

Foi o que aconteceu em 17/08/2026: a prefeitura publicou versão nova e o valor
gravado no .env (``03277F09…``) sumiu da lista. O programa parou de acessar, e
nada no programa havia mudado.

Por isso a identificação deixou de ser um número fixo em arquivo e passou a ser
lida do próprio portal, do mesmo ``nfseweb.nocache.js`` que o navegador lê. A
leitura é guardada em disco por alguns dias, para não ir à rede a cada abertura.

O programa se identifica como Chrome, e o GWT chama de ``safari`` a família de
navegadores baseados em WebKit — Chrome inclusive. É essa a permutação usada.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import date, timedelta

import paths

BASE = "https://nfse.isssbc.com.br/nfseweb/"
ENDERECO = BASE + "nfseweb.nocache.js"
NAVEGADOR = "safari"          # como o GWT chama a família do Chrome
ARQUIVO = paths.CONFIG_DIR / "portal_versao.json"
VALIDADE = timedelta(days=3)  # relê o portal de tempos em tempos
VARIAVEL = "NFSE_GWT_PERMUTATION"

# A assinatura do serviço viaja DENTRO do corpo de cada chamada, não no
# cabeçalho — e muda junto com a publicação. Foi a segunda metade da pane de
# 17/08/2026: com a identificação já corrigida, o portal continuava recusando o
# login, porque o corpo citava uma assinatura que ele havia acabado de aposentar.
VARIAVEL_POLITICA = "NFSE_GWT_POLICY"


class PortalMudou(RuntimeError):
    """Não consegui descobrir a versão do portal."""


def _baixar() -> str:
    import nfse_client

    pedido = urllib.request.Request(ENDERECO, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(pedido, timeout=25,
                                context=nfse_client.ssl_context()) as resposta:
        return resposta.read(2_000_000).decode("iso-8859-1", errors="replace")


def ler_permutacoes(js: str) -> dict[str, str]:
    """Mapa navegador → identificação, extraído do nocache.js.

    O arquivo é minificado: as identificações ficam em variáveis (``Qb='182A…'``)
    e o mapeamento aparece como ``G([Fb],Qb)``, onde ``Fb`` é outra variável com
    o nome do navegador. Resolver os dois níveis é o que dá o mapa.
    """
    constantes = dict(re.findall(r"(\w+)='([^']*)'", js))
    identificacoes = {nome: valor for nome, valor in constantes.items()
                      if re.fullmatch(r"[0-9A-F]{32}", valor)}
    mapa: dict[str, str] = {}
    for chave, valor in re.findall(r"G\(\[(\w+)\],(\w+)\)", js):
        navegador = constantes.get(chave)
        identificacao = identificacoes.get(valor)
        if navegador and identificacao:
            mapa[navegador] = identificacao
    return mapa


def ler_politica(html: str, permutacao: str) -> str:
    """A assinatura do serviço, extraída do arquivo compilado da permutação.

    O ``<permutação>.cache.html`` é o programa que o navegador executa. Dentro
    dele há duas sequências de 32 hexadecimais: a própria permutação e a
    assinatura do serviço. A que não é a permutação é a que se procura.
    """
    achados = [h for h in dict.fromkeys(re.findall(r"\b[0-9A-F]{32}\b", html))
               if h != permutacao]
    return achados[0] if len(achados) == 1 else ""


def _baixar_politica(permutacao: str) -> str:
    import nfse_client

    pedido = urllib.request.Request(f"{BASE}{permutacao}.cache.html",
                                    headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(pedido, timeout=60,
                                context=nfse_client.ssl_context()) as resposta:
        html = resposta.read(8_000_000).decode("iso-8859-1", errors="replace")
    return ler_politica(html, permutacao)


def _guardado() -> dict:
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _guardar(mapa: dict[str, str], politica: str = "") -> None:
    try:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        dados = {"lido_em": date.today().isoformat(), "permutacoes": mapa}
        if politica:
            dados["politica"] = politica
        ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    except OSError:
        pass      # não poder guardar o cache não é motivo para não funcionar


def descobrir(*, forcar: bool = False) -> dict[str, str]:
    """O mapa de identificações, do cache ou do portal."""
    guardado = _guardado()
    if not forcar and guardado.get("permutacoes"):
        try:
            lido = date.fromisoformat(guardado.get("lido_em", ""))
        except ValueError:
            lido = None
        if lido and date.today() - lido < VALIDADE:
            return dict(guardado["permutacoes"])

    try:
        mapa = ler_permutacoes(_baixar())
    except Exception:
        # Sem rede, vale o que foi guardado antes — melhor que nada.
        return dict(guardado.get("permutacoes") or {})
    if mapa:
        _guardar(mapa)
    return mapa


def sincronizar(*, forcar: bool = False) -> str:
    """Deixa ``NFSE_GWT_PERMUTATION`` valendo a versão que o portal publica hoje.

    Devolve a identificação em uso. O valor do .env só é trocado quando ele
    realmente não consta mais da lista publicada — quem configurou à mão
    continua no comando enquanto o que configurou ainda funciona.
    """
    atual = os.getenv(VARIAVEL, "").strip()
    mapa = descobrir(forcar=forcar)
    if not mapa:
        return atual

    # Quem configurou à mão continua no comando enquanto a escolha funcionar.
    vale = bool(atual) and atual in mapa.values()
    nova = atual if vale else (mapa.get(NAVEGADOR) or next(iter(mapa.values())))
    _aplicar(VARIAVEL, nova)
    _garantir_politica(nova, mapa, forcar=forcar or not vale)
    return nova


def _garantir_politica(permutacao: str, mapa: dict[str, str], *, forcar: bool) -> None:
    """A assinatura do serviço tem de acompanhar a permutação.

    Conferida também quando a permutação não mudou: é possível chegar aqui com
    a identificação certa e a assinatura ainda vazia — foi exatamente o estado
    em que o portal respondia HTTP 200 recusando o login.
    """
    if not forcar and politica_em_uso():
        return
    guardada = str(_guardado().get("politica") or "")
    if not forcar and guardada:
        _aplicar(VARIAVEL_POLITICA, guardada)
        return
    try:
        politica = _baixar_politica(permutacao)
    except Exception:
        politica = guardada
    if politica:
        _aplicar(VARIAVEL_POLITICA, politica)
        _guardar(mapa, politica)


def _aplicar(variavel: str, valor: str) -> None:
    """Passa a valer agora e na próxima abertura."""
    if os.environ.get(variavel) == valor:
        return
    os.environ[variavel] = valor
    import config
    try:
        config.definir_no_env(variavel, valor)
    except OSError:
        pass          # em pasta somente-leitura, vale só nesta sessão


def em_uso() -> str:
    return os.getenv(VARIAVEL, "").strip()


def politica_em_uso() -> str:
    return os.getenv(VARIAVEL_POLITICA, "").strip()

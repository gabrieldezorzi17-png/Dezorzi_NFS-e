"""Atualização automática do programa: procura, baixa e troca o executável.

    NFSE_ATUALIZACAO_URL=https://…/version.json     no .env, liga o recurso

COMO FUNCIONA
-------------
Ao abrir, o programa pergunta a um endereço na internet qual é a última versão
publicada. Se for maior que a daqui, oferece a troca. Aceita, ele baixa o novo
executável, confere a impressão digital, e sai — deixando um roteiro `.bat`
encarregado de trocar o arquivo e reabrir o programa.

O rodeio do `.bat` existe porque o Windows não deixa sobrescrever um `.exe` que
está rodando. O programa precisa fechar antes, e algo tem de continuar vivo
depois dele para fazer a troca. Esse algo é o roteiro.

O QUE ESTE MÓDULO SE RECUSA A FAZER
-----------------------------------
Baixar e executar um binário da internet é a operação mais perigosa que um
programa pode fazer sozinho — e este emite nota fiscal com o login da
prefeitura. Por isso há três travas, e nenhuma delas é opcional:

1. **Só HTTPS.** Endereço em `http://` é recusado. Sem isso, quem estiver no
   caminho da rede escolhe qual programa a máquina vai executar amanhã.
2. **Impressão digital obrigatória.** O anúncio da versão tem de trazer o
   SHA-256 do arquivo, e o que chega tem de bater com ele. Sem conferência,
   um servidor trocado ou um download corrompido viram código executado.
   `empacotar.py` já publica esse número — não custa nada.
3. **Nunca sem perguntar.** A troca reinicia o programa. Fazer isso por conta
   própria no meio de uma emissão é perder a nota que estava sendo digitada.

FORMATO DE PASTA
----------------
Só o executável de arquivo único se atualiza sozinho. No formato de pasta o
`.exe` não anda sem o `_internal/` do lado, e trocar só o `.exe` deixaria os
dois de versões diferentes — que é pior que não atualizar. Nesse formato o
programa avisa que há versão nova e mostra onde baixá-la.

O ANÚNCIO
---------
Aceita as duas formas, reconhecidas pelo próprio conteúdo:

    {"versao": "1.2.0", "arquivo": "https://…/App.exe",
     "sha256": "…", "notas": "o que mudou"}

ou a resposta da API de *releases* do GitHub, de onde saem `tag_name`, o
primeiro *asset* `.exe` e o corpo do texto. Aí o SHA-256 é procurado num
*asset* chamado `version.json` ou `SHA256SUMS`, pela mesma regra da trava 2.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import registro

# A versão desta compilação. `empacotar.py` a lê para nomear o que publica, e
# a tela de Ajustes a mostra — quem dá suporte precisa saber o que está rodando
# sem pedir para o usuário abrir arquivo nenhum.
VERSAO_ATUAL = "1.0.0"

VARIAVEL_URL = "NFSE_ATUALIZACAO_URL"
ESPERA_REDE = 12          # segundos; a abertura não pode depender da internet
LIMITE_ANUNCIO = 512 * 1024
LIMITE_EXECUTAVEL = 300 * 1024 * 1024


class AtualizacaoRecusada(Exception):
    """O anúncio existe mas não passou nas travas."""


@dataclass(frozen=True)
class Atualizacao:
    """Uma versão publicada, já conferida como maior que a daqui."""

    versao: str
    url: str
    sha256: str
    notas: str = ""


# --------------------------------------------------------------------------- #
# Versão
# --------------------------------------------------------------------------- #
def como_numeros(texto: str) -> tuple[int, ...]:
    """"v1.10.2" -> (1, 10, 2). Serve para comparar, não para exibir.

    Comparar como texto diria que "1.9.0" é maior que "1.10.0", porque "9" vem
    depois de "1". Numa correção de bug urgente isso é a atualização que não
    chega.
    """
    numeros = re.findall(r"\d+", str(texto or ""))
    return tuple(int(n) for n in numeros[:4]) or (0,)


def e_mais_nova(remota: str, local: str | None = None) -> bool:
    """A versão publicada é maior que a daqui?

    `local=None` e a leitura de `VERSAO_ATUAL` aqui dentro, e não como valor
    padrão do parâmetro: o padrão seria fixado quando o arquivo é lido, e
    quem trocasse `updater.VERSAO_ATUAL` depois — um teste, o empacotador —
    continuaria comparando com o valor antigo sem nenhum sinal de que isso
    aconteceu. Foi assim que a primeira conferência da publicação de verdade
    disse "não há versão nova" com a versão nova publicada.
    """
    return como_numeros(remota) > como_numeros(VERSAO_ATUAL if local is None
                                               else local)


# --------------------------------------------------------------------------- #
# Em que formato estamos rodando
# --------------------------------------------------------------------------- #
def formato() -> str:
    """"unico", "pasta" ou "codigo" — decide o que dá para fazer.

    Só o "unico" se troca sozinho. No "pasta", o `.exe` depende do `_internal/`
    ao lado; no "codigo" não há executável nenhum para trocar.
    """
    if not getattr(sys, "frozen", False):
        return "codigo"
    interno = getattr(sys, "_MEIPASS", "")
    if interno and Path(interno).parent == Path(sys.executable).parent:
        return "pasta"
    return "unico"


def executavel_em_uso() -> Path:
    return Path(sys.executable).resolve()


# --------------------------------------------------------------------------- #
# Procurar
# --------------------------------------------------------------------------- #
def _buscar(url: str, limite: int) -> bytes:
    if not url.lower().startswith("https://"):
        raise AtualizacaoRecusada(f"endereço não é https: {url[:60]}")
    pedido = urllib.request.Request(
        url, headers={"User-Agent": "Dezorzi-NFSe-Updater",
                      "Accept": "application/vnd.github+json, application/json, */*"})
    with urllib.request.urlopen(pedido, timeout=ESPERA_REDE) as resposta:
        return resposta.read(limite + 1)[:limite]


def _do_github(dados: dict) -> tuple[str, str, str, str]:
    """Extrai (versão, url do exe, sha256, notas) de um release do GitHub."""
    versao = str(dados.get("tag_name") or "")
    assets = dados.get("assets") or []

    def endereco(condicao) -> str:
        for asset in assets:
            nome = str(asset.get("name") or "")
            if condicao(nome.lower()):
                return str(asset.get("browser_download_url") or "")
        return ""

    exe = endereco(lambda n: n.endswith(".exe"))
    sha = ""
    manifesto = endereco(lambda n: n in ("version.json", "sha256sums",
                                         "sha256sums.txt"))
    if manifesto:
        bruto = _buscar(manifesto, LIMITE_ANUNCIO).decode("utf-8", "replace")
        try:
            sha = str((json.loads(bruto) or {}).get("sha256") or "")
        except json.JSONDecodeError:
            # Formato do `sha256sum`: "<hash>  <arquivo>", uma linha por arquivo.
            achado = re.search(r"\b([0-9a-fA-F]{64})\b", bruto)
            sha = achado.group(1) if achado else ""
    return versao, exe, sha, str(dados.get("body") or "")


def _do_manifesto(dados: dict) -> tuple[str, str, str, str]:
    return (str(dados.get("versao") or dados.get("version") or ""),
            str(dados.get("arquivo") or dados.get("url") or ""),
            str(dados.get("sha256") or ""),
            str(dados.get("notas") or dados.get("notes") or ""))


def verificar_atualizacao(url: str | None = None) -> Atualizacao | None:
    """A versão publicada é maior que esta? Devolve o que baixar, ou ``None``.

    Levanta ``AtualizacaoRecusada`` quando há versão nova mas o anúncio não
    passa nas travas — isso é problema de publicação, e tem de aparecer no
    diário em vez de sumir como "nada novo".
    """
    endereco = (url if url is not None else os.getenv(VARIAVEL_URL, "")).strip()
    if not endereco:
        return None

    bruto = _buscar(endereco, LIMITE_ANUNCIO)
    dados = json.loads(bruto.decode("utf-8", "replace"))
    if not isinstance(dados, dict):
        raise AtualizacaoRecusada("o anúncio não é um objeto JSON")

    # Reconhecido pelo conteúdo, não por configuração: um campo a menos para
    # alguém preencher errado.
    versao, arquivo, sha, notas = (_do_github(dados) if "tag_name" in dados
                                   else _do_manifesto(dados))
    if not versao:
        raise AtualizacaoRecusada("o anúncio não diz qual é a versão")
    if not e_mais_nova(versao):
        return None
    if not arquivo:
        raise AtualizacaoRecusada(f"a versão {versao} não traz o executável")
    if not arquivo.lower().startswith("https://"):
        raise AtualizacaoRecusada(f"o executável da {versao} não está em https")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha or ""):
        raise AtualizacaoRecusada(
            f"a versão {versao} foi publicada sem SHA-256; sem ele não há como "
            "saber se o arquivo que chegou é o que você publicou")
    return Atualizacao(versao=versao, url=arquivo, sha256=sha.lower(),
                       notas=" ".join(str(notas).split())[:600])


# --------------------------------------------------------------------------- #
# Baixar e trocar
# --------------------------------------------------------------------------- #
def pasta_de_trabalho() -> Path:
    """Onde o download cai: pasta do usuário, nunca Program Files.

    Escrever ao lado do programa exigiria privilégio de administrador quando
    ele estiver instalado em Program Files — e pedir administrador para
    atualizar é o que faz o usuário nunca atualizar.
    """
    base = os.getenv("LOCALAPPDATA") or tempfile.gettempdir()
    alvo = Path(base) / "Dezorzi NFS-e" / "atualizacao"
    alvo.mkdir(parents=True, exist_ok=True)
    return alvo


def baixar(atualizacao: Atualizacao,
           progresso: Callable[[int, int], None] | None = None) -> Path:
    """Traz o executável e confere a impressão digital. Devolve o caminho.

    A conferência é feita ANTES de o arquivo ter qualquer chance de ser
    executado: se não bater, ele é apagado e nada acontece.
    """
    destino = pasta_de_trabalho() / "update_temp.exe"
    destino.unlink(missing_ok=True)
    digestor = hashlib.sha256()
    baixados = 0

    pedido = urllib.request.Request(
        atualizacao.url, headers={"User-Agent": "Dezorzi-NFSe-Updater"})
    with urllib.request.urlopen(pedido, timeout=ESPERA_REDE) as resposta:
        total = int(resposta.headers.get("Content-Length") or 0)
        with destino.open("wb") as saida:
            while True:
                pedaco = resposta.read(256 * 1024)
                if not pedaco:
                    break
                baixados += len(pedaco)
                if baixados > LIMITE_EXECUTAVEL:
                    saida.close()
                    destino.unlink(missing_ok=True)
                    raise AtualizacaoRecusada("o arquivo passou do tamanho aceito")
                digestor.update(pedaco)
                saida.write(pedaco)
                if progresso is not None:
                    progresso(baixados, total)

    if digestor.hexdigest() != atualizacao.sha256:
        destino.unlink(missing_ok=True)
        raise AtualizacaoRecusada(
            "o arquivo baixado não confere com a impressão digital publicada; "
            "nada foi trocado")
    return destino


def _roteiro(novo: Path, alvo: Path, pasta: Path) -> Path:
    """Escreve o `.bat` que troca o executável depois que o programa fechar.

    Ele tenta a troca várias vezes: o OneDrive e o antivírus costumam segurar
    o arquivo por um instante depois de o processo morrer, e uma tentativa só
    falharia justamente nas máquinas onde o programa vive — dentro do OneDrive.

    Dê certo ou não, a última linha abre o programa. Uma atualização que falha
    não pode deixar o usuário sem programa nenhum.
    """
    roteiro = pasta / "update.bat"
    # A espera é feita com `ping`, e não com `timeout`. O `timeout` do Windows
    # precisa de um console para poder ser interrompido com uma tecla, e sai
    # com erro na hora quando não há um — que é exatamente o caso aqui: o
    # roteiro é disparado com CREATE_NO_WINDOW, sem console nenhum. Com ele,
    # as quinze tentativas queimavam em milissegundos em vez de durarem quinze
    # segundos, e qualquer arquivo momentaneamente preso — o caso normal em
    # máquina com OneDrive — perdia a atualização. `ping -n N 127.0.0.1` espera
    # N-1 segundos e não depende de console.
    #
    # O laço também não usa bloco entre parênteses: dentro dele o cmd expande
    # %TENTATIVA% na hora de ler o bloco, não na de executá-lo.
    espera = "ping -n 2 127.0.0.1 > nul"
    roteiro.write_text(
        "@echo off\r\n"
        "chcp 65001 > nul\r\n"
        "ping -n 3 127.0.0.1 > nul\r\n"      # ~2s: o programa precisa fechar
        "set TENTATIVA=0\r\n"
        ":tentar\r\n"
        f'move /y "{novo}" "{alvo}" > nul 2>&1\r\n'
        "if not errorlevel 1 goto abrir\r\n"
        "set /a TENTATIVA+=1\r\n"
        "if %TENTATIVA% geq 15 goto abrir\r\n"
        f"{espera}\r\n"
        "goto tentar\r\n"
        ":abrir\r\n"
        f'start "" "{alvo}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    return roteiro


def aplicar_atualizacao(baixado: Path, alvo: Path | None = None) -> Path:
    """Dispara a troca. Quem chama tem de encerrar o programa em seguida.

    Devolve o caminho do roteiro, para o chamador poder registrá-lo.
    """
    destino = Path(alvo) if alvo is not None else executavel_em_uso()
    roteiro = _roteiro(Path(baixado), destino, pasta_de_trabalho())
    # Solto do programa: ele precisa sobreviver ao `sys.exit` que vem a seguir.
    criacao = 0
    if sys.platform == "win32":
        criacao = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["cmd", "/c", str(roteiro)], cwd=str(roteiro.parent),
                     creationflags=criacao, close_fds=True)
    registro.escrever("atualizacao disparada", f"{baixado} -> {destino}")
    return roteiro


# --------------------------------------------------------------------------- #
# O que o programa chama
# --------------------------------------------------------------------------- #
def procurar_em_segundo_plano(quando_achar: Callable[[Atualizacao], None],
                              *, url: str | None = None) -> None:
    """Pergunta pela versão nova sem segurar a abertura da janela.

    Falha calada, de propósito: rede caída, servidor fora, DNS de empresa
    barrando — nada disso pode impedir alguém de emitir uma nota. O motivo vai
    para o diário, e a tela abre normalmente.
    """
    if formato() == "codigo":
        return

    def trabalho() -> None:
        try:
            achada = verificar_atualizacao(url)
        except AtualizacaoRecusada as exc:
            registro.escrever("atualizacao recusada", str(exc))
            return
        except Exception as exc:
            registro.falha("procura de atualizacao", exc)
            return
        if achada is None:
            return
        registro.escrever("atualizacao encontrada",
                          f"{VERSAO_ATUAL} -> {achada.versao}")
        try:
            quando_achar(achada)
        except Exception as exc:
            registro.falha("aviso de atualizacao", exc)

    threading.Thread(target=trabalho, daemon=True).start()

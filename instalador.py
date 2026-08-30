"""Põe o programa no computador e sai da frente.

POR QUE ISTO EXISTE
-------------------
O PyInstaller entrega dois formatos, e cada um resolve metade do problema:

* **arquivo único** — um .exe só, fácil de mandar por link. Mas ele
  descompacta o programa inteiro numa pasta temporária TODA vez que abre.
  Cronometrado neste Windows, com o .exe de verdade: 3,60 s até a janela.
* **pasta** — não descompacta nada, abre em 0,68 s. São 1021 arquivos e
  28 MB: não se manda por link, e o atualizador, que troca um arquivo, não
  sabe o que fazer com uma pasta.

Este instalador junta as duas pontas: é um arquivo único (o que se baixa) que
carrega a pasta dentro (o que se usa). Roda uma vez, deixa o programa em

    %LOCALAPPDATA%/Dezorzi NFS-e/app/

cria o atalho, abre o programa e some. Da segunda abertura em diante quem
abre é o atalho, e abrir custa 0,68 s.

O QUE ELE NUNCA TOCA
--------------------
`.env`, `config/` e `data/` ficam UMA PASTA ACIMA de `app/`, e a atualização
troca só `app/`. Isso não é detalhe de arrumação: `data/` é o histórico das
notas emitidas, documento fiscal. Uma atualização que passasse por cima
apagaria prova.

A TROCA
-------
Pasta nova é montada ao lado, com outro nome, e só então as duas trocam de
nome. Se faltar energia no meio, ou o programa antigo continua inteiro (a
troca não começou) ou o novo já está inteiro (a troca terminou) — nunca uma
pasta pela metade, que é o estado em que o programa não abre e ninguém sabe
por quê.

Renomear pasta com programa rodando dentro o Windows permite; apagar, não.
Por isso a antiga é renomeada e só depois apagada, e a falha em apagar é
ignorada: sobra uma pasta velha, que a próxima instalação recolhe.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

NOME = "Dezorzi NFS-e"
EXECUTAVEL = f"{NOME}.exe"
PASTA_DO_PROGRAMA = "app"
# A pasta viaja compactada: 27 MB de programa viram 12,6 MB de download, e
# descompactar um arquivo só leva ~1,2 s contra os 412 que o PyInstaller
# guardaria soltos. Quem baixa não paga pelo formato que escolhemos.
ARQUIVO_DA_CARGA = "app.zip"
# Escrito pelo empacotador dentro da carga. Serve para o instalador saber se
# o que já está instalado é o mesmo que ele carrega — ver `instalar`.
ARQUIVO_DA_VERSAO = "versao.txt"
ESPERA_MAXIMA = 40          # segundos aguardando o programa antigo fechar


def pasta_do_usuario() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / NOME


def carga() -> Path:
    """O programa que veio dentro deste instalador: o .zip, ou uma pasta.

    A pasta é o formato dos ensaios — dá para instalar de um diretório solto
    sem compactar nada, e é assim que os testes exercitam a troca.
    """
    dentro = getattr(sys, "_MEIPASS", "")
    origem = Path(dentro) if dentro else Path(__file__).resolve().parent
    embrulho = origem / ARQUIVO_DA_CARGA
    return embrulho if embrulho.is_file() else origem / PASTA_DO_PROGRAMA


def _tem_o_programa(de: Path) -> bool:
    if de.is_file():
        try:
            with zipfile.ZipFile(de) as pacote:
                return any(Path(nome).name == EXECUTAVEL
                           for nome in pacote.namelist())
        except (OSError, zipfile.BadZipFile):
            return False
    return (de / EXECUTAVEL).is_file()


def _versao(de: Path) -> str:
    """A versão que está aqui dentro — no .zip da carga ou na pasta instalada."""
    try:
        if de.is_file():
            with zipfile.ZipFile(de) as pacote:
                return pacote.read(ARQUIVO_DA_VERSAO).decode("utf-8").strip()
        return (de / ARQUIVO_DA_VERSAO).read_text(encoding="utf-8").strip()
    except (OSError, KeyError, UnicodeDecodeError, zipfile.BadZipFile):
        return ""


def _desembrulhar(de: Path, para: Path) -> None:
    """Põe o programa em `para`, venha ele de .zip ou de pasta.

    `extractall` do Python já recusa caminho absoluto e `..` dentro do zip —
    não dá para um pacote adulterado escrever fora do destino.
    """
    if de.is_file():
        with zipfile.ZipFile(de) as pacote:
            pacote.extractall(para)
    else:
        shutil.copytree(de, para)


# --------------------------------------------------------------------------- #
# Instalação
# --------------------------------------------------------------------------- #

def esperar_fechar(pid: int, limite: float = ESPERA_MAXIMA) -> bool:
    """Aguarda o programa antigo terminar. Devolve se ele terminou.

    Numa atualização, quem chama este instalador é o programa que está aberto.
    Ele pede para fechar e sai; enquanto não sai, os arquivos dele estão
    presos. Renomear a pasta funcionaria mesmo assim, mas apagar a antiga não
    — e ficaria lixo a cada versão.
    """
    fim = time.time() + limite
    while time.time() < fim:
        if not vivo(pid):
            # Um instante a mais: o processo sai da lista antes de o Windows
            # soltar os arquivos que ele tinha abertos.
            time.sleep(1.0)
            return True
        time.sleep(0.3)
    return False


def vivo(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        saida = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return str(pid) in (saida.stdout or "")


def _apagar(pasta: Path) -> None:
    """Apaga o que der. O que não der fica para a próxima instalação."""
    shutil.rmtree(pasta, ignore_errors=True)


def _recolher_restos(raiz: Path) -> None:
    for resto in raiz.glob(f"{PASTA_DO_PROGRAMA}.*"):
        if resto.is_dir():
            _apagar(resto)


def _renomear_insistindo(de: Path, para: Path, tentativas: int = 20) -> None:
    """Renomeia, esperando o Windows soltar a pasta.

    MEDIDO: com o programa ainda aberto, renomear a pasta dele falha — o
    Windows segura a pasta enquanto houver arquivo aberto lá dentro, e um
    .exe rodando é um arquivo aberto. O antivírus também segura, por alguns
    instantes, o que acabou de ser gravado.

    Por isso insiste em vez de desistir na primeira: quem chama já pediu para
    o programa fechar, e fechar leva um tempo que ninguém controla.
    """
    ultima: OSError | None = None
    for tentativa in range(tentativas):
        try:
            de.rename(para)
            return
        except OSError as erro:
            ultima = erro
            time.sleep(1.0 if tentativa else 0.2)
    raise ultima if ultima else OSError(f"não consegui renomear {de}")


def instalar(destino: Path | None = None, *, origem: Path | None = None,
             forcar: bool = False) -> Path:
    """Deixa a pasta do programa em `destino/app`. Devolve o .exe instalado.

    Se o que já está instalado for desta mesma versão, não copia nada — só
    devolve o caminho. Isso importa para quem chegou aqui pela travessia: o
    .exe antigo da pessoa vira este instalador, e abrir aquele arquivo passa
    a ser "instalar de novo". Sem esta conferência, seriam 4 s de cópia
    inútil toda vez.
    """
    raiz = (destino or pasta_do_usuario()).resolve()
    de = (origem or carga()).resolve()
    if not _tem_o_programa(de):
        raise FileNotFoundError(f"não achei {EXECUTAVEL} em {de}")

    ja_instalado = raiz / PASTA_DO_PROGRAMA / EXECUTAVEL
    minha = _versao(de)
    if (not forcar and minha and ja_instalado.is_file()
            and _versao(ja_instalado.parent) == minha):
        return ja_instalado

    raiz.mkdir(parents=True, exist_ok=True)
    _recolher_restos(raiz)

    novo = raiz / f"{PASTA_DO_PROGRAMA}.novo"
    _apagar(novo)
    _desembrulhar(de, novo)

    atual = raiz / PASTA_DO_PROGRAMA
    if atual.exists():
        antiga = raiz / f"{PASTA_DO_PROGRAMA}.antiga"
        _apagar(antiga)
        # Renomear é instantâneo e não copia nada: entre uma linha e a outra
        # não existe momento em que a pasta esteja meio velha, meio nova.
        try:
            _renomear_insistindo(atual, antiga)
        except OSError:
            # Não deu para tirar a antiga do caminho — quase sempre porque o
            # programa continua aberto. Some com a pasta nova antes de sair:
            # meia instalação largada é pior que instalação nenhuma, porque a
            # próxima tentativa começaria de um estado que ninguém previu.
            _apagar(novo)
            raise
        novo.rename(atual)
        _apagar(antiga)
    else:
        novo.rename(atual)
    return atual / EXECUTAVEL


# --------------------------------------------------------------------------- #
# Atalhos
# --------------------------------------------------------------------------- #

def criar_atalhos(exe: Path) -> list[Path]:
    """Atalho na Área de Trabalho e no menu Iniciar. Devolve os que saíram.

    Feito pelo próprio Windows, via WScript.Shell — sem biblioteca de
    terceiros. Um .lnk é um formato binário; escrevê-lo à mão seria inventar
    problema onde o sistema já tem resposta.
    """
    if sys.platform != "win32":
        return []
    alvos = []
    area = os.environ.get("USERPROFILE")
    if area:
        alvos.append(Path(area) / "Desktop" / f"{NOME}.lnk")
        alvos.append(Path(area) / "OneDrive" / "Desktop" / f"{NOME}.lnk")
    menu = os.environ.get("APPDATA")
    if menu:
        alvos.append(Path(menu) / "Microsoft" / "Windows" / "Start Menu"
                     / "Programs" / f"{NOME}.lnk")

    feitos: list[Path] = []
    for atalho in alvos:
        if not atalho.parent.is_dir():
            continue          # esta máquina não tem essa pasta; segue
        receita = (
            "$s = (New-Object -ComObject WScript.Shell)."
            f"CreateShortcut('{atalho}'); "
            f"$s.TargetPath = '{exe}'; "
            f"$s.WorkingDirectory = '{exe.parent}'; "
            f"$s.IconLocation = '{exe}'; "
            f"$s.Description = 'Emissao de NFS-e'; $s.Save()"
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", receita],
                           capture_output=True, timeout=40)
        except (OSError, subprocess.SubprocessError):
            continue
        if atalho.exists():
            feitos.append(atalho)
    return feitos


def abrir(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)


# --------------------------------------------------------------------------- #
# Tela
# --------------------------------------------------------------------------- #

def _janela():
    """Uma janelinha dizendo o que está acontecendo. Falha em silêncio.

    Sem ela, quem clica no instalador vê alguns segundos de nada e clica de
    novo. Se o Tk não subir por qualquer motivo, a instalação continua — ela
    é o que importa; a janela é cortesia.
    """
    try:
        import tkinter as tk
    except Exception:
        return None, None
    try:
        janela = tk.Tk()
        janela.title(NOME)
        janela.configure(bg="#0f1117")
        janela.resizable(False, False)
        largura, altura = 380, 130
        x = (janela.winfo_screenwidth() - largura) // 2
        y = (janela.winfo_screenheight() - altura) // 2
        janela.geometry(f"{largura}x{altura}+{x}+{y}")
        tk.Label(janela, text=NOME, bg="#0f1117", fg="#f2f4fb",
                 font=("Segoe UI", 14, "bold")).pack(pady=(28, 4))
        recado = tk.Label(janela, text="Instalando no computador…",
                          bg="#0f1117", fg="#98a1bd", font=("Segoe UI", 10))
        recado.pack()
        janela.update()
        return janela, recado
    except Exception:
        return None, None


def _dizer(janela, recado, texto: str) -> None:
    if janela is None:
        return
    try:
        recado.configure(text=texto)
        janela.update()
    except Exception:
        pass


# --------------------------------------------------------------------------- #

def main(argumentos: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argumentos is None else argumentos)
    silencioso = "--silencioso" in argumentos
    pid = 0
    if "--esperar" in argumentos:
        posicao = argumentos.index("--esperar")
        if posicao + 1 < len(argumentos):
            try:
                pid = int(argumentos[posicao + 1])
            except ValueError:
                pid = 0

    janela, recado = (None, None) if silencioso else _janela()
    try:
        if pid:
            _dizer(janela, recado, "Fechando a versão anterior…")
            esperar_fechar(pid)
        _dizer(janela, recado, "Instalando no computador…")
        exe = instalar()
        _dizer(janela, recado, "Criando o atalho…")
        criar_atalhos(exe)
        _dizer(janela, recado, "Pronto. Abrindo…")
        abrir(exe)
    except Exception as exc:
        if janela is not None:
            try:
                from tkinter import messagebox

                messagebox.showerror(
                    NOME,
                    "Não consegui instalar o programa.\n\n"
                    f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
        return 1
    finally:
        if janela is not None:
            try:
                janela.destroy()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

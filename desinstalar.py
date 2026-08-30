"""Remover o programa — pelo caminho que o Windows já oferece.

O que faz um aplicativo parecer aplicativo não é só instalar bonito: é
aparecer em "Aplicativos instalados" e poder sair de lá. O instalador
registra o programa; este módulo é o outro lado, chamado pelo próprio
executável com ``--desinstalar``.

O QUE SAI E O QUE FICA
----------------------
Sai o programa: a pasta ``app/``, os atalhos e o registro no Windows.

**As notas ficam**, e a caixa que as apaga vem desmarcada. Nota emitida é
documento fiscal, e a prefeitura não guarda cópia para o contribuinte —
desinstalar um programa não pode ser o gesto que apaga cinco anos de
histórico. Quem quiser apagar marca a caixa, e ainda lê quantas são.

POR QUE UM ROTEIRO
------------------
Um programa não apaga a própria pasta enquanto está aberto: o Windows segura
o .exe em uso. Então o que apaga é um roteiro solto, que espera este processo
morrer e só então limpa — o mesmo desenho da atualização, e pelo mesmo
motivo.

O roteiro é ASCII puro, com os caminhos entrando por variável de ambiente. Um
`.bat` com acento no meio já quebrou a atualização deste programa: o `cmd` lê
o arquivo na página de código 850, e "Área de Trabalho" vira outra coisa.
Variável de ambiente passa em Unicode e não sofre disso.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import instalador
import paths
import registro

ROTEIRO = """@echo off
rem Espera o programa fechar e entao apaga o que sobrou. Sem acento aqui
rem de proposito: o cmd le este arquivo na pagina de codigo 850.
:esperar
ping -n 2 127.0.0.1 >nul
tasklist /FI "PID eq %NFSE_PID%" /NH | find "%NFSE_PID%" >nul
if not errorlevel 1 goto esperar
rmdir /s /q "%NFSE_APP%"
if "%NFSE_TUDO%"=="1" rmdir /s /q "%NFSE_RAIZ%"
del "%~f0"
"""


def notas_guardadas() -> int:
    try:
        return len(list(paths.DATA_DIR.glob("*.json")))
    except OSError:
        return 0


def _roteiro(raiz: Path, apagar_tudo: bool) -> tuple[Path, dict]:
    """Escreve o roteiro que limpa depois. Devolve ele e o ambiente."""
    pasta = Path(tempfile.gettempdir()) / "dezorzi-nfse"
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "desinstalar.bat"
    arquivo.write_text(ROTEIRO, encoding="ascii")
    ambiente = dict(os.environ)
    ambiente["NFSE_PID"] = str(os.getpid())
    ambiente["NFSE_APP"] = str(raiz / instalador.PASTA_DO_PROGRAMA)
    ambiente["NFSE_RAIZ"] = str(raiz)
    ambiente["NFSE_TUDO"] = "1" if apagar_tudo else "0"
    return arquivo, ambiente


def remover(raiz: Path | None = None, *, apagar_dados: bool = False) -> Path:
    """Tira atalhos e registro agora; agenda a pasta para depois de fechar."""
    raiz = Path(raiz) if raiz is not None else paths.BASE_DIR
    instalador.apagar_atalhos()
    instalador.tirar_do_registro()
    arquivo, ambiente = _roteiro(raiz, apagar_dados)
    criacao = 0
    if sys.platform == "win32":
        criacao = (getattr(subprocess, "DETACHED_PROCESS", 0)
                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.Popen(["cmd", "/c", str(arquivo)], cwd=str(arquivo.parent),
                     env=ambiente, creationflags=criacao, close_fds=True)
    registro.escrever("desinstalacao disparada",
                      f"{raiz} (dados: {'apagados' if apagar_dados else 'mantidos'})")
    return arquivo


# --------------------------------------------------------------------------- #
# A tela
# --------------------------------------------------------------------------- #

def perguntar() -> bool:
    """Confirma com quem clicou. Devolve se a remoção foi disparada."""
    import tkinter as tk
    from tkinter import ttk

    import marca
    import ui

    escala = ui.ativar_nitidez()
    janela = tk.Tk()
    ui.aplicar_escala(janela, escala)
    ui.usar_tema("escuro")
    ui.escolher_familia(janela)
    ui.aplicar_estilo(janela)
    janela.title(f"Remover {instalador.NOME_VISIVEL}")
    janela.configure(bg=ui.BG)
    janela.resizable(False, False)
    try:
        janela._icone = marca.icone(56, janela)
        janela.iconphoto(True, janela._icone)
    except tk.TclError:
        pass

    feito = {"sim": False}
    corpo = tk.Frame(janela, bg=ui.BG, padx=ui.E6, pady=ui.E5)
    corpo.pack(fill="both", expand=True)
    tk.Label(corpo, text=f"Remover o {instalador.NOME_VISIVEL}?",
             font=(ui.FAMILIA, 15, "bold"), bg=ui.BG, fg=ui.INK).pack(anchor="w")

    cartao = ui.Redondo(corpo, raio=14, fundo=ui.SURFACE, borda=ui.BORDER,
                        fundo_externo=ui.BG, padx=ui.E4, pady=ui.E4)
    cartao.pack(fill="x", pady=(ui.E4, 0))
    dentro = cartao.interior

    quantas = notas_guardadas()
    tk.Label(dentro, text="Saem o programa, os atalhos e o registro em "
                          "Aplicativos instalados.",
             bg=ui.SURFACE, fg=ui.INK_2, font=ui.PEQUENO, justify="left",
             anchor="w", wraplength=ui.px(420)).pack(fill="x")

    apagar = tk.BooleanVar(value=False)
    ui.Marcador(dentro,
                f"Apagar também as {quantas} nota(s) emitidas e os ajustes"
                if quantas else "Apagar também os ajustes e o histórico",
                variavel=apagar, fundo=ui.SURFACE).pack(anchor="w",
                                                        pady=(ui.E4, 0))
    aviso = tk.Label(dentro, bg=ui.SURFACE, fg=ui.INK_3, font=ui.MICRO,
                     justify="left", anchor="w", wraplength=ui.px(420),
                     text=f"Desmarcado, o histórico continua em {paths.BASE_DIR}.")
    aviso.pack(fill="x", pady=(ui.E2, 0))

    def rever(*_):
        if apagar.get():
            aviso.configure(
                fg=ui.ERRO,
                text="Nota emitida é documento fiscal e a prefeitura não "
                     "guarda cópia para você. Apagado aqui, não volta.")
        else:
            aviso.configure(
                fg=ui.INK_3,
                text=f"Desmarcado, o histórico continua em {paths.BASE_DIR}.")

    apagar.trace_add("write", rever)

    botoes = tk.Frame(dentro, bg=ui.SURFACE)
    botoes.pack(fill="x", pady=(ui.E5, 0))

    def confirmar() -> None:
        try:
            remover(apagar_dados=apagar.get())
            feito["sim"] = True
        except Exception as exc:
            registro.falha("desinstalar", exc)
        janela.destroy()

    ttk.Button(botoes, text="Remover", style="Perigo.TButton",
               command=confirmar).pack(side="right", ipady=3)
    ttk.Button(botoes, text="Cancelar", style="Discreto.TButton",
               command=janela.destroy).pack(side="right", padx=(0, ui.E2))

    janela.update_idletasks()
    ui.centralizar(janela, janela.winfo_reqwidth(), janela.winfo_reqheight())
    try:
        ui.pintar_barra_de_titulo(janela, escuro=True, cor=ui.NAVY)
    except Exception:
        pass
    janela.mainloop()
    return feito["sim"]


def main(argumentos: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argumentos is None else argumentos)
    if "--silencioso" in argumentos:
        # Vem do "QuietUninstallString": o Windows já perguntou por nós.
        try:
            remover()
        except Exception as exc:
            registro.falha("desinstalar em silencio", exc)
            return 1
        return 0
    perguntar()
    return 0

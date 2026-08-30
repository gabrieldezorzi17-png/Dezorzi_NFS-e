"""O instalador: pergunta onde, pergunta se quer atalho, e instala.

POR QUE ISTO EXISTE
-------------------
O PyInstaller entrega dois formatos, e cada um resolve metade do problema:

* **arquivo único** — um .exe só, fácil de mandar por link. Mas ele
  descompacta o programa inteiro numa pasta temporária TODA vez que abre.
  Cronometrado neste Windows, com o .exe de verdade: 3,60 s até a janela.
* **pasta** — não descompacta nada, abre em 0,46 s. São 412 arquivos e 27 MB:
  não se manda por link, e o atualizador, que troca um arquivo, não sabe o
  que fazer com uma pasta.

Este instalador junta as duas pontas: é um arquivo único (o que se baixa) que
carrega a pasta compactada dentro (o que se usa).

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

Renomear pasta com programa rodando dentro o Windows recusa; por isso o
instalador espera o processo fechar (`--esperar`) e ainda insiste no rename.

COMO É CHAMADO
--------------
    (sem nada)                    abre o assistente e pergunta tudo
    --silencioso --destino P      atualização: instala em P, sem perguntar
    --esperar PID                 espera o programa fechar antes de mexer
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# ENDEREÇO, não rótulo: é o nome da pasta instalada, do executável e da
# chave no registro. Trocá-lo obrigaria a mover a instalação que já existe —
# com as notas dentro — e nota emitida é documento fiscal. Fica como está.
NOME = "Dezorzi NFS-e"
EXECUTAVEL = f"{NOME}.exe"

# O que a pessoa lê. Onde os dois se cruzam, vale este.
NOME_VISIVEL = "DINELLY NFS-e"
# Nomes de atalho de versões anteriores, recolhidos ao instalar: sem isso a
# Área de Trabalho ficaria com dois ícones do mesmo programa.
ATALHOS_ANTIGOS = ("Dezorzi NFS-e",)
PASTA_DO_PROGRAMA = "app"
# A pasta viaja compactada: 27 MB de programa viram 12,6 MB de download, e
# descompactar um arquivo só leva ~1,2 s contra os 412 que o PyInstaller
# guardaria soltos. Quem baixa não paga pelo formato que escolhemos.
ARQUIVO_DA_CARGA = "app.zip"
# Escrito pelo empacotador dentro da carga. Serve para o instalador saber se
# o que já está instalado é o mesmo que ele carrega — ver `instalar`.
ARQUIVO_DA_VERSAO = "versao.txt"
# O que a pessoa escolheu, guardado FORA de `app/` para sobreviver à troca.
# É o que faz a atualização repetir as escolhas dela sem perguntar de novo.
ARQUIVO_DA_ESCOLHA = "instalacao.json"
ESPERA_MAXIMA = 40          # segundos aguardando o programa antigo fechar

CHAVE_DO_WINDOWS = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DezorziNFSe")


def pasta_do_usuario() -> Path:
    """Onde instalar por padrão: a pasta de aplicativos do usuário.

    %LOCALAPPDATA% e não "Arquivos de Programas" porque ali não é preciso
    administrador — nem para instalar, nem para atualizar depois. Pedir
    administrador a cada atualização é o que faz ninguém atualizar.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / NOME


def area_de_trabalho() -> Path | None:
    """A Área de Trabalho desta máquina, com OneDrive ou sem.

    Quem usa OneDrive tem a Área de Trabalho sincronizada em
    `%USERPROFILE%/OneDrive/Desktop`, e a pasta antiga fica lá parada. Um
    atalho criado no lugar errado é um atalho que ninguém vê.
    """
    perfil = os.environ.get("USERPROFILE")
    if not perfil:
        return None
    candidatas = [Path(perfil) / "OneDrive" / "Desktop",
                  Path(perfil) / "OneDrive" / "Área de Trabalho",
                  Path(perfil) / "Desktop"]
    existentes = [c for c in candidatas if c.is_dir()]
    return existentes[0] if existentes else None


def menu_iniciar() -> Path | None:
    dados = os.environ.get("APPDATA")
    if not dados:
        return None
    pasta = (Path(dados) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return pasta if pasta.is_dir() else None


# --------------------------------------------------------------------------- #
# A carga
# --------------------------------------------------------------------------- #

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


def versao_que_carrego() -> str:
    return _versao(carga())


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
# O que a pessoa escolheu
# --------------------------------------------------------------------------- #

def escolha_guardada(raiz: Path) -> dict:
    """O que foi marcado na instalação anterior. Vazio se for a primeira."""
    try:
        dados = json.loads((raiz / ARQUIVO_DA_ESCOLHA).read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def guardar_escolha(raiz: Path, *, area: bool, menu: bool) -> None:
    """Grava as escolhas para a atualização não perguntar de novo.

    Fora de `app/` de propósito: aquela pasta é substituída inteira, e a
    escolha tem de sobreviver a isso.
    """
    try:
        raiz.mkdir(parents=True, exist_ok=True)
        (raiz / ARQUIVO_DA_ESCOLHA).write_text(
            json.dumps({"atalho_area_de_trabalho": bool(area),
                        "atalho_menu_iniciar": bool(menu)},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    except OSError:
        pass      # sem isto a atualização recria os dois atalhos; não é grave


def pasta_aceita_escrita(pasta: Path) -> bool:
    """Dá para gravar aqui? Perguntado ANTES, não na hora de salvar a nota.

    Em "Arquivos de Programas" o Windows recusa escrita sem administrador. Se
    a pessoa instalar ali, o programa abre e só falha quando ela terminar de
    preencher a primeira nota — que é o pior momento possível para descobrir.
    """
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        teste = pasta / ".escrita"
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Instalação
# --------------------------------------------------------------------------- #

def esperar_fechar(pid: int, limite: float = ESPERA_MAXIMA) -> bool:
    """Aguarda o programa antigo terminar. Devolve se ele terminou.

    Numa atualização, quem chama este instalador é o programa que está aberto.
    Ele pede para fechar e sai; enquanto não sai, os arquivos dele estão
    presos e o Windows recusa renomear a pasta.
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
    a ser "instalar de novo". Sem esta conferência, seriam segundos de cópia
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

def criar_atalhos(exe: Path, *, area: bool = True,
                  menu: bool = True) -> list[Path]:
    """Atalho na Área de Trabalho e no menu Iniciar, conforme pedido.

    Feito pelo próprio Windows, via WScript.Shell — sem biblioteca de
    terceiros. Um .lnk é formato binário; escrevê-lo à mão seria inventar
    problema onde o sistema já tem resposta.
    """
    if sys.platform != "win32":
        return []
    _recolher_atalhos_antigos()
    alvos: list[Path] = []
    if area:
        pasta = area_de_trabalho()
        if pasta is not None:
            alvos.append(pasta / f"{NOME_VISIVEL}.lnk")
    if menu:
        pasta = menu_iniciar()
        if pasta is not None:
            alvos.append(pasta / f"{NOME_VISIVEL}.lnk")

    feitos: list[Path] = []
    for atalho in alvos:
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


def _recolher_atalhos_antigos() -> None:
    """Apaga atalhos com o nome de antes. Um programa, um ícone."""
    for pasta in (area_de_trabalho(), menu_iniciar()):
        if pasta is None:
            continue
        for antigo in ATALHOS_ANTIGOS:
            try:
                (pasta / f"{antigo}.lnk").unlink(missing_ok=True)
            except OSError:
                pass


def apagar_atalhos() -> list[Path]:
    """Tira os atalhos deste programa — os de agora e os de antes."""
    apagados = []
    for pasta in (area_de_trabalho(), menu_iniciar()):
        if pasta is None:
            continue
        for nome in (NOME_VISIVEL, *ATALHOS_ANTIGOS):
            atalho = pasta / f"{nome}.lnk"
            try:
                if atalho.exists():
                    atalho.unlink()
                    apagados.append(atalho)
            except OSError:
                pass
    return apagados


def abrir(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)


# --------------------------------------------------------------------------- #
# "Aplicativos instalados", do Windows
# --------------------------------------------------------------------------- #

def registrar_no_windows(raiz: Path, exe: Path, versao: str) -> bool:
    """Faz o programa aparecer em Configurações > Aplicativos instalados.

    É o que separa "um .exe que alguém copiou" de um aplicativo: aparece na
    lista, mostra versão e ocupa espaço declarado, e tem como ser removido
    pelo caminho que a pessoa já conhece.

    Em HKEY_CURRENT_USER, não em HKEY_LOCAL_MACHINE: vale só para quem
    instalou e não pede administrador — a mesma razão de instalar em
    %LOCALAPPDATA%.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except ImportError:
        return False
    try:
        tamanho = sum(f.stat().st_size for f in raiz.rglob("*") if f.is_file())
    except OSError:
        tamanho = 0
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CHAVE_DO_WINDOWS) as chave:
            texto = winreg.REG_SZ
            for nome, valor in (
                ("DisplayName", f"{NOME_VISIVEL} — Emissor de NFS-e"),
                ("DisplayVersion", versao or "1.0"),
                ("Publisher", "DINELLY"),
                ("InstallLocation", str(raiz)),
                ("DisplayIcon", str(exe)),
                ("UninstallString", f'"{exe}" --desinstalar'),
                ("QuietUninstallString", f'"{exe}" --desinstalar --silencioso'),
            ):
                winreg.SetValueEx(chave, nome, 0, texto, valor)
            for nome, valor in (("NoModify", 1), ("NoRepair", 1),
                                ("EstimatedSize", max(1, tamanho // 1024))):
                winreg.SetValueEx(chave, nome, 0, winreg.REG_DWORD, valor)
        return True
    except OSError:
        return False


def tirar_do_registro() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, CHAVE_DO_WINDOWS)
        return True
    except (ImportError, OSError):
        return False


def registrado() -> dict:
    """O que o Windows sabe sobre esta instalação. Vazio se não souber nada."""
    if sys.platform != "win32":
        return {}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_DO_WINDOWS) as chave:
            dados = {}
            for indice in range(winreg.QueryInfoKey(chave)[1]):
                nome, valor, _tipo = winreg.EnumValue(chave, indice)
                dados[nome] = valor
            return dados
    except (ImportError, OSError):
        return {}


# --------------------------------------------------------------------------- #
# O assistente
# --------------------------------------------------------------------------- #

def _tela():
    """A janela do instalador, com a cara do programa. Falha em silêncio.

    Usa o mesmo `ui.py` do programa — mesma paleta, mesma fonte, mesmos
    cantos. Um instalador com cara de outro programa é a primeira coisa que
    a pessoa vê, e já começa dizendo que as duas coisas não são a mesma.

    Se o Tk não subir por qualquer motivo, devolve `None` e a instalação
    segue sem janela: ela é o que importa; a tela é cortesia.
    """
    try:
        import tkinter as tk

        import ui
    except Exception:
        return None
    try:
        escala = ui.ativar_nitidez()
        ui.identificar_no_windows("Dezorzi.NFSe.Instalador")
        janela = tk.Tk()
        ui.aplicar_escala(janela, escala)
        ui.usar_tema("escuro")
        ui.escolher_familia(janela)
        ui.aplicar_estilo(janela)
        janela.title(f"Instalar {NOME_VISIVEL}")
        janela.configure(bg=ui.BG)
        janela.resizable(False, False)
        try:
            import marca

            janela._icone = marca.icone(56, janela)
            janela.iconphoto(True, janela._icone)
        except Exception:
            pass
        return janela
    except Exception:
        return None


class Assistente:
    """Pergunta onde instalar e se quer atalho. Depois instala e abre."""

    def __init__(self, janela, versao: str) -> None:
        import tkinter as tk

        import ui

        self.tk = tk
        self.ui = ui
        self.janela = janela
        self.versao = versao
        self.destino = tk.StringVar(value=str(pasta_do_usuario()))
        anterior = escolha_guardada(pasta_do_usuario())
        self.quer_area = tk.BooleanVar(
            value=bool(anterior.get("atalho_area_de_trabalho", True)))
        self.quer_menu = tk.BooleanVar(
            value=bool(anterior.get("atalho_menu_iniciar", True)))
        self.instalado: Path | None = None
        self._montar()

    # -- desenho --------------------------------------------------------- #

    # Largura fixa, altura conforme o passo. Sem fixar, cada passo pedia uma
    # largura diferente e a janela pulava de tamanho entre uma tela e outra —
    # e o texto do passo seguinte saía cortado na moldura do anterior.
    LARGURA = 520

    def _ajustar(self) -> None:
        """Refaz a altura da janela para o que o passo atual precisa."""
        self.janela.update_idletasks()
        self.ui.centralizar(self.janela, self.ui.px(self.LARGURA),
                            self.janela.winfo_reqheight())
        self.janela.update_idletasks()

    def _montar(self) -> None:
        tk, ui = self.tk, self.ui
        self.corpo = tk.Frame(self.janela, bg=ui.BG, padx=ui.E6, pady=ui.E5)
        self.corpo.pack(fill="both", expand=True)

        topo = tk.Frame(self.corpo, bg=ui.BG)
        topo.pack(fill="x")
        try:
            import marca

            # O mesmo emblema do programa: quem instala e quem abre têm de
            # ver a mesma marca, com a mesma placa e o mesmo canto.
            marca.emblema(topo, ui.px(42), ui.BG).pack(side="left",
                                                       padx=(0, ui.E3))
        except Exception:
            pass
        titulos = tk.Frame(topo, bg=ui.BG)
        titulos.pack(side="left", anchor="w")
        tk.Label(titulos, text=NOME_VISIVEL, font=(ui.FAMILIA, 17, "bold"),
                 bg=ui.BG, fg=ui.INK).pack(anchor="w")
        tk.Label(titulos, text=f"Emissor de NFS-e · versão {self.versao}",
                 font=ui.PEQUENO, bg=ui.BG, fg=ui.INK_3).pack(anchor="w")

        self.cartao = ui.Redondo(self.corpo, raio=14, fundo=ui.SURFACE,
                                 borda=ui.BORDER, fundo_externo=ui.BG,
                                 padx=ui.E4, pady=ui.E4)
        self.cartao.pack(fill="x", pady=(ui.E5, 0))
        self.dentro = self.cartao.interior
        self._passo_escolha()

    def _limpar(self) -> None:
        for filho in self.dentro.winfo_children():
            filho.destroy()

    def _passo_escolha(self) -> None:
        tk, ui = self.tk, self.ui
        from tkinter import ttk

        self._limpar()
        ui.etiqueta_campo(self.dentro, "Onde instalar").pack(anchor="w")

        linha = tk.Frame(self.dentro, bg=ui.SURFACE)
        linha.pack(fill="x", pady=(ui.E2, 2))
        linha.columnconfigure(0, weight=1)
        campo = ttk.Entry(linha, textvariable=self.destino, font=ui.PEQUENO)
        campo.grid(row=0, column=0, sticky="ew")
        ttk.Button(linha, text="Procurar…", style="Discreto.TButton",
                   command=self._procurar).grid(row=0, column=1,
                                                padx=(ui.E2, 0))

        self.aviso = tk.Label(
            self.dentro, bg=ui.SURFACE, fg=ui.INK_3, font=ui.MICRO,
            justify="left", anchor="w", wraplength=ui.px(396),
            text="As notas emitidas e os ajustes ficam nesta pasta, fora da "
                 "parte que a atualização troca — atualizar não apaga nada.")
        self.aviso.pack(fill="x", pady=(ui.E2, ui.E4))

        for variavel, texto in (
                (self.quer_area, "Criar atalho na Área de Trabalho"),
                (self.quer_menu, "Criar atalho no menu Iniciar")):
            ui.Marcador(self.dentro, texto, variavel=variavel,
                        fundo=ui.SURFACE).pack(anchor="w", pady=3)

        botoes = tk.Frame(self.dentro, bg=ui.SURFACE)
        botoes.pack(fill="x", pady=(ui.E5, 0))
        self.botao = ttk.Button(botoes, text="Instalar",
                                style="Primaria.TButton", command=self._instalar)
        self.botao.pack(side="right", ipady=3)
        ttk.Button(botoes, text="Cancelar", style="Discreto.TButton",
                   command=self.janela.destroy).pack(side="right",
                                                     padx=(0, ui.E2))
        self.destino.trace_add("write", lambda *_: self._conferir())
        self._conferir()
        self._ajustar()
        campo.focus_set()

    def _procurar(self) -> None:
        from tkinter import filedialog

        escolhida = filedialog.askdirectory(
            parent=self.janela, title="Onde instalar o programa",
            initialdir=str(Path(self.destino.get()).parent))
        if escolhida:
            # A pasta escolhida é o PAI: ninguém espera que "Documentos" vire
            # a pasta do programa com tudo solto dentro dela.
            alvo = Path(escolhida)
            if alvo.name != NOME:
                alvo = alvo / NOME
            self.destino.set(str(alvo))

    def _conferir(self) -> None:
        """O botão só liga se dá para gravar na pasta escolhida."""
        ui = self.ui
        caminho = self.destino.get().strip()
        if not caminho:
            self.aviso.configure(text="Escolha uma pasta.", fg=ui.ERRO)
            self.botao.state(["disabled"])
            return
        alvo = Path(caminho)
        ja = (alvo / PASTA_DO_PROGRAMA / EXECUTAVEL).is_file()
        if not pasta_aceita_escrita(alvo):
            self.aviso.configure(
                text="O Windows não deixa gravar nesta pasta. Escolha outra — "
                     "a pasta do usuário serve e não pede administrador.",
                fg=ui.ERRO)
            self.botao.state(["disabled"])
            return
        self.botao.state(["!disabled"])
        self.botao.configure(text="Atualizar" if ja else "Instalar")
        self.aviso.configure(
            fg=ui.INK_3,
            text=(f"Já existe um {NOME_VISIVEL} aqui. As notas e os ajustes "
                  "continuam onde estão; só o programa é trocado." if ja else
                  "As notas emitidas e os ajustes ficam nesta pasta, fora da "
                  "parte que a atualização troca — atualizar não apaga nada."))

    # -- ação ------------------------------------------------------------ #

    def _instalar(self) -> None:
        tk, ui = self.tk, self.ui
        raiz = Path(self.destino.get().strip())
        self._limpar()
        faixa = tk.Frame(self.dentro, bg=ui.SURFACE)
        faixa.pack(fill="x", pady=ui.E3)
        girador = ui.Girador(faixa, fundo=ui.SURFACE, lado=18)
        girador.pack(side="left", padx=(0, ui.E3))
        girador.girar()
        recado = tk.Label(faixa, text="Copiando os arquivos…", bg=ui.SURFACE,
                          fg=ui.INK, font=ui.CORPO)
        recado.pack(side="left")
        self._ajustar()

        try:
            exe = instalar(raiz)
            recado.configure(text="Criando os atalhos…")
            self.janela.update()
            criar_atalhos(exe, area=self.quer_area.get(),
                          menu=self.quer_menu.get())
            guardar_escolha(raiz, area=self.quer_area.get(),
                            menu=self.quer_menu.get())
            registrar_no_windows(raiz, exe, self.versao)
        except Exception as exc:
            girador.parar()
            self._falhou(exc)
            return
        girador.parar()
        self.instalado = exe
        self._pronto(exe)

    def _pronto(self, exe: Path) -> None:
        tk, ui = self.tk, self.ui
        from tkinter import ttk

        self._limpar()
        tk.Label(self.dentro, text="Instalado.", bg=ui.SURFACE, fg=ui.SUCESSO,
                 font=(ui.FAMILIA, 15, "bold")).pack(anchor="w")
        onde = ("O atalho está na Área de Trabalho."
                if self.quer_area.get() else
                "Procure por DINELLY no menu Iniciar."
                if self.quer_menu.get() else
                f"O programa está em {exe.parent}.")
        tk.Label(self.dentro, text=onde + " Abrir daqui em diante leva menos "
                 "de um segundo.", bg=ui.SURFACE, fg=ui.INK_2, font=ui.PEQUENO,
                 justify="left", anchor="w", wraplength=ui.px(396)).pack(
            fill="x", pady=(ui.E2, ui.E5))

        botoes = tk.Frame(self.dentro, bg=ui.SURFACE)
        botoes.pack(fill="x")
        ttk.Button(botoes, text="Abrir o programa", style="Primaria.TButton",
                   command=self._abrir_e_sair).pack(side="right", ipady=3)
        ttk.Button(botoes, text="Fechar", style="Discreto.TButton",
                   command=self.janela.destroy).pack(side="right",
                                                     padx=(0, ui.E2))
        self._ajustar()

    def _abrir_e_sair(self) -> None:
        if self.instalado is not None:
            abrir(self.instalado)
        self.janela.destroy()

    def _falhou(self, exc: Exception) -> None:
        tk, ui = self.tk, self.ui
        from tkinter import ttk

        self._limpar()
        tk.Label(self.dentro, text="Não deu para instalar.", bg=ui.SURFACE,
                 fg=ui.ERRO, font=(ui.FAMILIA, 14, "bold")).pack(anchor="w")
        tk.Label(self.dentro, text=f"{type(exc).__name__}: {exc}",
                 bg=ui.SURFACE, fg=ui.INK_2, font=ui.PEQUENO, justify="left",
                 anchor="w", wraplength=ui.px(396)).pack(fill="x",
                                                         pady=(ui.E2, ui.E4))
        ttk.Button(self.dentro, text="Tentar de novo", style="Discreto.TButton",
                   command=self._passo_escolha).pack(anchor="e")
        self._ajustar()


# --------------------------------------------------------------------------- #

def _sem_janela(raiz: Path | None) -> int:
    """Instala sem perguntar nada. É o caminho da atualização."""
    alvo = raiz or pasta_do_usuario()
    exe = instalar(alvo)
    escolha = escolha_guardada(alvo)
    criar_atalhos(exe,
                  area=bool(escolha.get("atalho_area_de_trabalho", True)),
                  menu=bool(escolha.get("atalho_menu_iniciar", True)))
    registrar_no_windows(alvo, exe, _versao(exe.parent))
    abrir(exe)
    return 0


def _argumento(argumentos: list[str], nome: str) -> str:
    if nome not in argumentos:
        return ""
    posicao = argumentos.index(nome)
    return argumentos[posicao + 1] if posicao + 1 < len(argumentos) else ""


def main(argumentos: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argumentos is None else argumentos)
    silencioso = "--silencioso" in argumentos
    destino = _argumento(argumentos, "--destino")
    try:
        pid = int(_argumento(argumentos, "--esperar") or 0)
    except ValueError:
        pid = 0

    if pid:
        esperar_fechar(pid)

    if silencioso:
        try:
            return _sem_janela(Path(destino) if destino else None)
        except Exception:
            return 1

    janela = _tela()
    if janela is None:
        # Sem Tk não há como perguntar; instalar no lugar padrão ainda é
        # melhor que não instalar.
        try:
            return _sem_janela(Path(destino) if destino else None)
        except Exception:
            return 1

    import ui

    assistente = Assistente(janela, versao_que_carrego() or "")
    if destino:
        assistente.destino.set(destino)
    assistente._ajustar()
    try:
        ui.pintar_barra_de_titulo(janela, escuro=True, cor=ui.NAVY)
    except Exception:
        pass
    janela.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

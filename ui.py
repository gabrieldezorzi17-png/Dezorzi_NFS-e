"""Sistema visual do aplicativo: temas, tipografia, estilos ttk e componentes.

Separado de ``desktop.py`` por um motivo prático: enquanto as cores moravam
soltas no meio das telas, cada tela acabava com um cinza ligeiramente diferente.
Aqui elas têm nome e um lugar só — mudar a paleta é mudar este arquivo.

Nada aqui conhece regra fiscal. É camada de apresentação pura.

COMO O TEMA TROCA
-----------------
As cores são variáveis deste módulo, e ``usar_tema()`` as reescreve de uma vez.
Quem lê ``ui.SURFACE`` na hora de criar o widget pega a cor do tema em vigor.

Isso tem uma consequência que precisa ser respeitada: **cor nenhuma pode ser
capturada no import** — nem em valor padrão de parâmetro, nem em constante de
módulo. `def cartao(pai, fundo=SURFACE)` congelaria o branco do tema claro para
sempre. Por isso os padrões aqui são ``None``, resolvidos dentro da função.

E como widget já criado não muda de cor sozinho, trocar de tema significa
redesenhar a tela — é o que ``desktop.py`` faz.
"""
from __future__ import annotations

import math
import sys
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable

# --------------------------------------------------------------------------- #
# Temas
# --------------------------------------------------------------------------- #
# Dois conjuntos com exatamente as mesmas chaves. A conferência disso é feita
# por teste: uma chave só no claro deixaria a tela escura com um buraco preto.

CLARO = {
    # Gelo no fundo, branco puro na chapa: o cartão precisa de onde se destacar.
    "BG": "#eceef5",
    "SURFACE": "#ffffff",
    "SURFACE_ALT": "#ffffff",
    "SURFACE_FUNDA": "#e6e9f2",
    "BORDER": "#ffffff",
    "BORDER_FORTE": "#dbe0ec",
    "INK": "#10131f",
    "INK_2": "#4e5670",
    # #8a92a9 dava 2,68:1 sobre o branco — a WCAG pede 4,5:1 para texto
    # normal, e este tom carrega o CCM, a data e os rótulos das colunas.
    "INK_3": "#636c87",

    # A barra de comando, no alto. Não é mais uma coluna escura à esquerda:
    # é uma faixa da mesma família da chapa, separada por um fio.
    "NAVY": "#ffffff",
    "NAVY_HOVER": "#f5f6fb",
    "NAVY_ATIVO": "#efeafe",
    "NAV_TEXTO": "#4e5670",
    "NAV_LEGENDA": "#6c7693",   # era #8a92a9: 3,10:1 na barra clara
    "NAV_ACAO": "#4e5670",
    "NAV_ASSINATURA": "#a3aabd",
    "NAV_DESTAQUE": "#5b34f0",
    "NAV_MONO": "#4e5670",

    # Violeta royal, e o ciano como segunda voz da marca.
    "PRIMARIA": "#5b34f0",
    "PRIMARIA_HOVER": "#4d2ade",
    "PRIMARIA_PRESS": "#4122c2",
    "PRIMARIA_CLARA": "#efeafe",
    "PRIMARIA_FRACA": "#c3b2fa",
    "ONDA": "#0e9cb8",

    "SUCESSO": "#077e52", "SUCESSO_BG": "#dcf7ec",
    "ALERTA": "#966400", "ALERTA_BG": "#fdf0d6",   # 4,08:1 -> 4,52:1
    "ERRO": "#cd2548", "ERRO_BG": "#fde7ec",
    "INFO": "#4122c2", "INFO_BG": "#efeafe",
    "NEUTRO": "#4e5670", "NEUTRO_BG": "#eef0f6",

    "ERRO_SOLIDO": "#d02649", "ERRO_SOLIDO_HOVER": "#b01d3d",
    "DESLIGADO": "#dfe3ee", "DESLIGADO_TEXTO": "#9aa2b6",

    "PONTO_ATIVO": "#a06a00",
    "PONTO_SEGURO": "#08935f",

    "SOMBRA": "#d7dbe8",
}

ESCURO = {
    "BG": "#06070d",
    "SURFACE": "#0d1018",
    "SURFACE_ALT": "#111624",
    "SURFACE_FUNDA": "#1a2032",
    "BORDER": "#0d1018",
    "BORDER_FORTE": "#232b3d",
    "INK": "#e9ecf7",
    "INK_2": "#97a0bb",
    "INK_3": "#7983a0",     # era #5b6480: 2,90:1 sobre o fundo, reprovava

    "NAVY": "#10141f",
    "NAVY_HOVER": "#171d2c",
    "NAVY_ATIVO": "#1c1a3d",
    "NAV_TEXTO": "#97a0bb",
    "NAV_LEGENDA": "#737d9c",   # era #5b6480: 3,13:1 na barra escura
    "NAV_ACAO": "#97a0bb",
    "NAV_ASSINATURA": "#454e66",
    "NAV_DESTAQUE": "#a58bff",
    "NAV_MONO": "#97a0bb",

    # Escurecida o bastante para o branco por cima passar: era 4,36:1.
    "PRIMARIA": "#7858ff",
    "PRIMARIA_HOVER": "#6a49f5",
    "PRIMARIA_PRESS": "#5a39e6",
    "PRIMARIA_CLARA": "#1c1a3d",
    "PRIMARIA_FRACA": "#3b3470",
    "ONDA": "#22d3ee",

    # No escuro o fundo do selo é o tom profundo e o texto é o claro — a
    # mesma leitura, invertida. Pastel de tema claro brilha demais aqui.
    "SUCESSO": "#2ee6a8", "SUCESSO_BG": "#0a2b21",
    "ALERTA": "#ffc14d", "ALERTA_BG": "#33260a",
    "ERRO": "#ff5c7c", "ERRO_BG": "#32131c",
    "INFO": "#a58bff", "INFO_BG": "#1c1a3d",
    "NEUTRO": "#97a0bb", "NEUTRO_BG": "#161c2b",

    "ERRO_SOLIDO": "#e11d48", "ERRO_SOLIDO_HOVER": "#f43f5e",
    "DESLIGADO": "#1e2536", "DESLIGADO_TEXTO": "#525c75",

    "PONTO_ATIVO": "#ffc14d",
    "PONTO_SEGURO": "#2ee6a8",

    "SOMBRA": "#03040a",
}

TEMAS = {"claro": CLARO, "escuro": ESCURO}
TEMA = "claro"

globals().update(CLARO)


def usar_tema(nome: str) -> str:
    """Troca a paleta em vigor. Devolve o nome realmente aplicado.

    Nome desconhecido cai no claro em vez de estourar: um ``.env`` editado à
    mão não deve impedir o programa de abrir.
    """
    global TEMA
    TEMA = nome if nome in TEMAS else "claro"
    globals().update(TEMAS[TEMA])
    return TEMA


def outro_tema() -> str:
    """O tema que não está em uso — para o botão que alterna entre os dois."""
    return "escuro" if TEMA == "claro" else "claro"


def escuro() -> bool:
    return TEMA == "escuro"


# --------------------------------------------------------------------------- #
# Tipografia
# --------------------------------------------------------------------------- #
# Tamanhos positivos são pontos: escalam sozinhos quando o Windows está em
# 125%/150%. Pixels (negativos) ficariam minúsculos nessas telas.
FAMILIA = "Segoe UI"
MONO = "Consolas"

DISPLAY = (FAMILIA, 23, "bold")
NUMERO = (FAMILIA, 23, "bold")
TITULO = (FAMILIA, 18, "bold")
SUBTITULO = (FAMILIA, 14)
CORPO = (FAMILIA, 11)
CORPO_FORTE = (FAMILIA, 11, "bold")
PEQUENO = (FAMILIA, 10)
PEQUENO_FORTE = (FAMILIA, 10, "bold")
MICRO = (FAMILIA, 9)
MICRO_FORTE = (FAMILIA, 9, "bold")
ETIQUETA = (FAMILIA, 9, "bold")  # rótulos de campo, em caixa alta

# Espaçamento — múltiplos de 4, para o ritmo não sair torto
E1, E2, E3, E4, E5, E6 = 4, 8, 12, 16, 24, 32

RAIO = 9  # arredondamento das pílulas e botões desenhados

# Quantos pixels de tela vale um pixel de projeto. 1.0 a 96 dpi (100%), 1.25
# a 120 (125%), 1.5 a 144 (150%). Quem escreve tamanho em pixel passa por
# `px`: a letra cresce com a densidade, e o que a segura tem de crescer junto.
ESCALA = 1.0
_ESPACOS_BASE = (4, 8, 12, 16, 24, 32)
_RAIO_BASE = 9


def px(medida: float) -> int:
    """Pixel de projeto convertido para o pixel desta tela."""
    return max(1, round(medida * ESCALA))


def escolher_familia(raiz: tk.Misc) -> str:
    """Segoe UI primeiro. É a que sai nítida nesta tela — medido.

    A ordem era Inter → Segoe UI. Trocada depois de medir: renderizando a
    mesma frase e comparando o gradiente médio da imagem (quanto mais abrupta
    a borda da letra, mais nítido o olho lê), a Segoe UI ganha em todos os
    tamanhos, de 15% a 25%. Na comparação mais justa — Inter 9pt e Segoe UI
    10pt ocupam a mesma caixa, 23px de altura e ~270 de largura — dá 24,5
    contra 25,3.

    Não é acaso: o Tk desenha texto pelo GDI, que depende do *hinting* embutido
    na fonte para encaixar a haste da letra num pixel inteiro. A Segoe UI é
    ajustada à mão para os tamanhos de interface do Windows; a Inter é ajustada
    para telas de densidade alta, e aqui espalha cada haste por dois pixels —
    o que o olho lê como borrado. De quebra, a Segoe UI é ~8% mais estreita,
    o que devolve espaço para os nomes das empresas na lista.
    """
    global FAMILIA, DISPLAY, TITULO, SUBTITULO, CORPO, CORPO_FORTE
    global PEQUENO, PEQUENO_FORTE, MICRO, MICRO_FORTE, NUMERO, ETIQUETA
    try:
        instaladas = {nome.lower() for nome in tkfont.families(raiz)}
    except tk.TclError:
        return FAMILIA
    for candidata in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Roboto"):
        if candidata.lower() in instaladas:
            FAMILIA = candidata
            break
    # Um ponto acima da escala antiga em toda a régua. A Segoe UI é mais
    # estreita que a Inter, então isto sai quase de graça em largura — e o que
    # era 8pt (o "CCM 304838", o "SÃO BERNARDO DO CAMPO") estava no limite em
    # que a letra some.
    # A régua de cima segue uma escala modular de razão ~1,27: 11, 14, 18, 23.
    #
    # Antes eram 11, 12, 16, 22, 23 — com razões de 1,045 a 1,375. Um degrau
    # de 1,045 (o 22 para o 23) não se enxerga: NUMERO e DISPLAY eram dois
    # tamanhos que o olho lia como um só, e o SUBTITULO mal se separava do
    # corpo. Agora cada degrau é visivelmente maior que o anterior.
    #
    # Embaixo ficam 9 e 10, que a escala não alcança: 11÷1,27 daria 8,7, e
    # abaixo de 9 a letra some. Esses dois degraus existem por densidade —
    # esta é uma tela de dados — e a hierarquia entre eles é sustentada por
    # cor e caixa alta, não por tamanho.
    #
    # Tentei subir PEQUENO de 10 para 11 e a conta não fechou: o painel de
    # detalhe engordou de 340 para 377px e espremeu a tabela até os nomes das
    # empresas voltarem a ser cortados. Medido, não suposto.
    DISPLAY = (FAMILIA, 23, "bold")
    NUMERO = (FAMILIA, 23, "bold")
    TITULO = (FAMILIA, 18, "bold")
    SUBTITULO = (FAMILIA, 14)
    CORPO = (FAMILIA, 11)
    CORPO_FORTE = (FAMILIA, 11, "bold")
    PEQUENO = (FAMILIA, 10)
    PEQUENO_FORTE = (FAMILIA, 10, "bold")
    MICRO = (FAMILIA, 9)
    MICRO_FORTE = (FAMILIA, 9, "bold")
    ETIQUETA = (FAMILIA, 9, "bold")
    return FAMILIA


# --------------------------------------------------------------------------- #
# Janela
# --------------------------------------------------------------------------- #

def ativar_nitidez() -> float:
    """Diz ao Windows que o app desenha na resolução real do monitor.

    Sem isto, telas em 125% ou 150% mostram o aplicativo esticado por
    interpolação — o texto sai borrado. Devolve o fator de escala aplicado.

    Três tentativas, da melhor para a que sempre existe:

    1. *por monitor v2* — o programa é redesenhado na densidade de cada
       monitor, e o Windows ainda escala sozinho a barra de título. É o que
       elimina o borrado ao arrastar a janela entre dois monitores de
       densidades diferentes, caso cada vez mais comum: notebook 4K com um
       monitor Full HD ao lado.
    2. *por monitor v1* — o mesmo, sem a ajuda na barra de título. Windows 8.1
       em diante.
    3. *por sistema* — o que havia aqui antes. Nítido no monitor principal,
       esticado nos outros.

    Tem de rodar antes de a janela existir; depois, o Windows já decidiu.
    """
    if sys.platform != "win32":
        return 1.0
    try:
        import ctypes

        usuario = ctypes.windll.user32
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        try:
            usuario.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            usuario.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
            if not usuario.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                raise OSError("v2 recusada")
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return usuario.GetDpiForSystem() / 96.0
    except Exception:
        # Windows antigo ou shcore ausente: segue sem nitidez extra.
        return 1.0


def densidade_da_janela(janela: tk.Misc) -> float:
    """A escala do monitor onde a janela ESTÁ, não a do monitor principal.

    Só faz diferença com ciência por monitor — e é justamente aí que faz toda
    a diferença: sem perguntar, a janela arrastada para o outro monitor
    continuaria desenhando na densidade do primeiro.
    """
    if sys.platform != "win32":
        return ESCALA
    try:
        import ctypes

        usuario = ctypes.windll.user32
        if not hasattr(usuario, "GetDpiForWindow"):
            return ESCALA
        alça = usuario.GetParent(janela.winfo_id()) or janela.winfo_id()
        dpi = usuario.GetDpiForWindow(alça)
        return (dpi / 96.0) if dpi else ESCALA
    except Exception:
        return ESCALA


def identificar_no_windows(identidade: str) -> None:
    """Diz ao Windows que este processo é o programa, e não "python.exe".

    Sem isto, a barra de tarefas agrupa a janela sob o ícone do interpretador
    e um atalho fixado aponta para o lugar errado. É o mesmo identificador que
    o atalho da área de trabalho carrega — precisa bater para o Windows
    entender que a janela aberta e o atalho fixado são a mesma coisa.

    Tem de rodar ANTES de a janela nascer; depois, o Windows já decidiu.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(identidade)
    except Exception:
        pass      # Windows antigo: perde-se o agrupamento, não o programa


def pintar_barra_de_titulo(janela: tk.Misc, *, escuro: bool,
                           cor: str | None = None) -> None:
    """Pede ao Windows que a barra de título acompanhe o programa.

    A faixa com minimizar, maximizar e fechar é desenhada pelo sistema, não
    pelo Tk — nenhuma opção de widget a alcança. O DWM aceita dois pedidos:
    o modo escuro (que já pinta a faixa e inverte os ícones) e, no Windows 11,
    a cor exata. Sem isso, uma barra branca fica no alto de um programa
    escuro, e é a única parte da janela fora do tom.

    Falha em silêncio no Windows 10 antigo: lá a cor não existe e o modo
    escuro basta.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        janela.update_idletasks()
        alça = ctypes.windll.user32.GetParent(janela.winfo_id())
        if not alça:
            return
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (19 em builds antigas do W10)
        valor = ctypes.c_int(1 if escuro else 0)
        for atributo in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                alça, atributo, ctypes.byref(valor), ctypes.sizeof(valor))
        if cor:
            # DWMWA_CAPTION_COLOR = 35, só no Windows 11. O DWM quer
            # 0x00BBGGRR — azul primeiro, ao contrário do hexadecimal usual.
            r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
            referencia = ctypes.c_int((b << 16) | (g << 8) | r)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                alça, 35, ctypes.byref(referencia), ctypes.sizeof(referencia))
            # DWMWA_TEXT_COLOR = 36: o título acompanha o contraste da faixa.
            tinta = contraste(cor)
            r, g, b = (int(tinta[i:i + 2], 16) for i in (1, 3, 5))
            referencia = ctypes.c_int((b << 16) | (g << 8) | r)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                alça, 36, ctypes.byref(referencia), ctypes.sizeof(referencia))
    except Exception:
        # Windows antigo, DWM desligado: a barra fica no padrão do sistema.
        pass


def aplicar_escala(raiz: tk.Misc, fator: float) -> None:
    """Reajusta o app inteiro para a densidade da tela.

    Duas metades, e faltava a segunda. `tk scaling` faz a LETRA crescer: as
    fontes daqui são declaradas em pontos, e ponto é medida de papel — o Tk
    resolve para pixel usando esta escala. O que não crescia era o que segura
    a letra: coluna, espaçamento, raio de canto, tudo pixel cravado. A 150% a
    letra ficava 1,5 vez maior dentro da mesma caixa, e o valor da nota
    aparecia cortado.

    Recalculado sempre a partir das medidas originais. Aplicar sobre o
    resultado anterior comporia os fatores, e uma segunda troca de monitor
    deixaria o programa com o dobro do espaçamento.
    """
    global ESCALA, E1, E2, E3, E4, E5, E6, RAIO
    global ALTURA_LINHA, ALTURA_CABECALHO

    fator = float(fator or 1.0)
    if fator <= 0:
        fator = 1.0
    ESCALA = fator
    E1, E2, E3, E4, E5, E6 = (max(1, round(medida * fator))
                              for medida in _ESPACOS_BASE)
    RAIO = max(1, round(_RAIO_BASE * fator))
    # A linha da tabela tem duas linhas de texto: a razão social e, embaixo,
    # o CCM. A 125% a segunda saía cortada ao meio — a letra crescia, a linha
    # não. O mesmo vale para o cabeçalho e para a barra de seções.
    ALTURA_LINHA = max(1, round(_ALTURA_LINHA_BASE * fator))
    ALTURA_CABECALHO = max(1, round(_ALTURA_CABECALHO_BASE * fator))
    Segmentado.ALTURA = max(1, round(Segmentado.ALTURA_BASE * fator))
    if abs(fator - 1.0) > 0.01:
        raiz.tk.call("tk", "scaling", fator * 96.0 / 72.0)


def area_util(janela: tk.Misc) -> tuple[int, int, int, int]:
    """A parte da tela que não é barra de tarefas: (x, y, largura, altura).

    ``winfo_screenheight`` devolve a tela inteira, barra de tarefas incluída.
    Uma janela dimensionada por ele encosta o próprio rodapé atrás da barra —
    e o rodapé é justamente onde ficam os botões de emitir e confirmar. Já
    aconteceu nesta tela: 1366x768 com o app pedindo 730 de altura.
    """
    largura, altura = janela.winfo_screenwidth(), janela.winfo_screenheight()
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            retangulo = wintypes.RECT()
            # SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(
                    0x0030, 0, ctypes.byref(retangulo), 0):
                return (retangulo.left, retangulo.top,
                        retangulo.right - retangulo.left,
                        retangulo.bottom - retangulo.top)
        except Exception:
            pass
    # Sem a medida do sistema, desconta uma barra de tarefas típica.
    return (0, 0, largura, altura - 48)


# Barra de título mais bordas do Windows a 100%. É só o palpite inicial: a
# medida de verdade vem em `encaixar`, depois de a janela existir na tela.
MOLDURA = 40


def moldura_de(janela: tk.Misc) -> int:
    """Altura da barra de título, medida — 0 enquanto a janela não apareceu."""
    try:
        return max(0, janela.winfo_rooty() - janela.winfo_y())
    except tk.TclError:
        return 0


def encaixar(janela: tk.Misc, tentativas: int = 5, intervalo: int = 120) -> None:
    """Encolhe a janela se, já na tela, ela passar da área livre.

    `geometry()` dimensiona a área INTERNA; a barra de título fica fora dela.
    Uma janela com a altura cheia da área livre nasce, portanto, um título
    mais alta que o espaço — e o que sobra para fora é o rodapé, justamente
    onde ficam os botões de emitir e confirmar. Foi assim que a barra lateral
    apareceu sem o seletor de tema e sem a assinatura.

    Aqui a conta usa a posição real na tela, então vale para qualquer barra de
    tarefas, em qualquer borda, com qualquer escala de tela.
    """
    if not janela.winfo_exists():
        return
    janela.update_idletasks()
    origem_x, origem_y, disponivel_l, disponivel_a = area_util(janela)
    try:
        largura, altura = janela.winfo_width(), janela.winfo_height()
        cliente_x, cliente_y = janela.winfo_rootx(), janela.winfo_rooty()
        quadro_x, quadro_y = janela.winfo_x(), janela.winfo_y()
    except tk.TclError:
        return
    sobra_baixo = (cliente_y + altura) - (origem_y + disponivel_a)
    sobra_lado = (cliente_x + largura) - (origem_x + disponivel_l)

    # Antes de encolher, subir: quase sempre a janela só estourou embaixo
    # porque nasceu centralizada, e há folga sobrando em cima. Mover resolve
    # sem tirar altura útil de ninguém — encolher é o último recurso.
    if sobra_baixo > 0:
        subir = min(sobra_baixo, max(0, quadro_y - origem_y))
        if subir > 0:
            janela.geometry(f"+{int(quadro_x)}+{int(quadro_y - subir)}")
            janela.update_idletasks()
            cliente_y = janela.winfo_rooty()
            sobra_baixo = (cliente_y + altura) - (origem_y + disponivel_a)

    if sobra_baixo > 0 or sobra_lado > 0:
        nova_altura = max(200, altura - max(0, sobra_baixo))
        nova_largura = max(320, largura - max(0, sobra_lado))
        # Sem +x+y: a posição fica onde está, só o tamanho muda.
        janela.geometry(f"{nova_largura}x{nova_altura}")

    # A conferência volta algumas vezes, e não só quando mexeu em algo: o
    # Windows informa a altura da barra de título aos poucos — 31px logo após
    # posicionar, 51px com a janela composta —, então a primeira leitura fecha
    # a conta e a definitiva estoura. Parar na primeira era o que deixava o
    # rodapé da barra lateral atrás da barra de tarefas. A função não faz nada
    # quando já cabe, então as voltas extras custam uma medida cada.
    if tentativas > 1:
        janela.after(intervalo, lambda: encaixar(janela, tentativas - 1, intervalo))


def centralizar(janela: tk.Misc, largura: int, altura: int) -> None:
    """Abre a janela no meio da área livre, nunca maior que ela."""
    janela.update_idletasks()
    origem_x, origem_y, disponivel_l, disponivel_a = area_util(janela)
    reserva = moldura_de(janela) or MOLDURA
    largura = min(largura, disponivel_l)
    altura = min(altura, disponivel_a - reserva)
    x = origem_x + max(0, (disponivel_l - largura) // 2)
    y = origem_y + max(0, (disponivel_a - altura) // 3)
    janela.geometry(f"{largura}x{altura}+{int(x)}+{int(y)}")
    # A conta acima usa a moldura estimada. Assim que a janela existir de
    # verdade, `encaixar` confere com a medida real e corrige se preciso.
    janela.after_idle(lambda: encaixar(janela))


def dimensionar(janela: tk.Misc, largura: int) -> None:
    """Ajusta a altura da janela ao conteúdo e centraliza.

    Altura chutada é armadilha: o conteúdo cresce (um aviso a mais, um campo a
    mais) e o que estava embaixo — justamente os botões — sai da área visível
    sem erro nenhum. Foi o que deixou o "Limpar histórico" sem botão de
    confirmar. Aqui a altura vem do que o conteúdo pede, limitada à tela.
    """
    janela.update_idletasks()
    pedida = janela.winfo_reqheight()
    teto = area_util(janela)[3]
    centralizar(janela, largura, max(200, min(pedida, teto)))


# --------------------------------------------------------------------------- #
# Estilos ttk
# --------------------------------------------------------------------------- #

def aplicar_estilo(raiz: tk.Misc) -> ttk.Style:
    """Configura o tema. O padrão do Windows não aceita cor em quase nada.

    Pode ser chamada de novo a cada troca de tema: reconfigurar um estilo já
    existente vale para os widgets criados dali em diante.
    """
    estilo = ttk.Style(raiz)
    estilo.theme_use("clam")

    # --- Botões ---------------------------------------------------------- #
    estilo.configure(
        "TButton", font=CORPO, padding=(E3, 8), relief="flat",
        background=SURFACE, foreground=INK, borderwidth=1, bordercolor=BORDER_FORTE,
        focuscolor=PRIMARIA_CLARA,
    )
    estilo.map(
        "TButton",
        background=[("pressed", SURFACE_ALT), ("active", SURFACE_ALT),
                    ("disabled", SURFACE_ALT)],
        foreground=[("disabled", INK_3)],
        bordercolor=[("active", BORDER_FORTE)],
    )

    estilo.configure(
        "Primaria.TButton", font=CORPO_FORTE, padding=(E4, 9),
        background=PRIMARIA, foreground="white", borderwidth=0,
        focuscolor=PRIMARIA_HOVER,
    )
    estilo.map(
        "Primaria.TButton",
        background=[("pressed", PRIMARIA_PRESS), ("active", PRIMARIA_HOVER),
                    ("disabled", DESLIGADO)],
        foreground=[("disabled", DESLIGADO_TEXTO)],
    )

    estilo.configure(
        "Perigo.TButton", font=CORPO_FORTE, padding=(E4, 9),
        background=ERRO_SOLIDO, foreground="white", borderwidth=0,
    )
    estilo.map("Perigo.TButton",
               background=[("active", ERRO_SOLIDO_HOVER), ("disabled", DESLIGADO)],
               foreground=[("disabled", DESLIGADO_TEXTO)])

    # Caixa de marcar. O tema nativo do Windows desenha o quadradinho com a
    # cor do sistema e ignora tudo que se peça — no "clam" ele é desenhado
    # pelo Tk, e aí aceita a paleta daqui.
    estilo.configure(
        "Escolha.TCheckbutton", font=CORPO, background=SURFACE, foreground=INK,
        focuscolor=SURFACE, padding=(0, 4), indicatorrelief="flat",
        indicatormargin=(0, 0, E2, 0), indicatorbackground=SURFACE_ALT,
        indicatorforeground="white", bordercolor=BORDER_FORTE,
    )
    estilo.map(
        "Escolha.TCheckbutton",
        background=[("active", SURFACE)],
        foreground=[("disabled", INK_3)],
        indicatorbackground=[("selected", PRIMARIA), ("active", SURFACE_ALT),
                             ("disabled", DESLIGADO)],
        indicatorforeground=[("selected", "white")],
        bordercolor=[("selected", PRIMARIA)],
    )

    estilo.configure(
        "Discreto.TButton", font=PEQUENO, padding=(10, 6),
        background=SURFACE, foreground=INK_2, borderwidth=1, bordercolor=BORDER_FORTE,
    )
    estilo.map("Discreto.TButton", background=[("active", SURFACE_ALT)],
               foreground=[("active", INK)])

    # Ação destrutiva que ainda não é a confirmação: vermelha no texto, não no
    # fundo — o vermelho cheio fica reservado para o botão que de fato apaga.
    estilo.configure(
        "PerigoLeve.TButton", font=CORPO, padding=(E3, 8),
        background=SURFACE, foreground=ERRO, borderwidth=1, bordercolor=BORDER_FORTE,
    )
    estilo.map(
        "PerigoLeve.TButton",
        background=[("active", ERRO_BG)],
        bordercolor=[("active", ERRO)],
        foreground=[("disabled", INK_3)],
    )

    # --- Campos ---------------------------------------------------------- #
    for nome in ("TEntry", "TCombobox"):
        estilo.configure(
            nome, padding=9, relief="flat", borderwidth=1,
            bordercolor=BORDER_FORTE, lightcolor=BORDER_FORTE, darkcolor=BORDER_FORTE,
            fieldbackground=SURFACE, background=SURFACE, foreground=INK,
            insertcolor=INK, arrowcolor=INK_2, selectbackground=PRIMARIA_CLARA,
            selectforeground=INK,
        )
        estilo.map(
            nome,
            bordercolor=[("focus", PRIMARIA), ("hover", BORDER_FORTE)],
            lightcolor=[("focus", PRIMARIA)],
            darkcolor=[("focus", PRIMARIA)],
            fieldbackground=[("readonly", SURFACE), ("disabled", SURFACE_ALT)],
            foreground=[("disabled", INK_3)],
        )
    # A lista suspensa do Combobox não é ttk: é um Listbox do Tk, e só obedece
    # a estas opções globais. Sem elas, o tema escuro abre uma lista branca.
    # Sem moldura própria: esta variante vai DENTRO de um cartão redondo, e
    # a moldura quadrada do clam por cima do canto arredondado era o que
    # deixava a lista de empresas destoando dos campos ao lado.
    estilo.configure(
        "Plano.TCombobox", borderwidth=0, relief="flat", padding=(E2, 5),
        bordercolor=SURFACE, lightcolor=SURFACE, darkcolor=SURFACE,
        fieldbackground=SURFACE, background=SURFACE, foreground=INK,
        arrowcolor=INK_2, selectbackground=SURFACE, selectforeground=INK,
    )
    estilo.map(
        "Plano.TCombobox",
        fieldbackground=[("readonly", SURFACE), ("focus", SURFACE)],
        background=[("readonly", SURFACE), ("focus", SURFACE)],
        bordercolor=[("focus", SURFACE)], lightcolor=[("focus", SURFACE)],
        darkcolor=[("focus", SURFACE)], arrowcolor=[("active", INK)],
    )

    raiz.option_add("*TCombobox*Listbox.background", SURFACE)
    raiz.option_add("*TCombobox*Listbox.foreground", INK)
    raiz.option_add("*TCombobox*Listbox.selectBackground", PRIMARIA)
    raiz.option_add("*TCombobox*Listbox.selectForeground", "white")
    raiz.option_add("*TCombobox*Listbox.font", CORPO)

    # --- Tabela ---------------------------------------------------------- #
    estilo.configure(
        "Treeview", rowheight=38, font=CORPO, background=SURFACE,
        fieldbackground=SURFACE, foreground=INK, borderwidth=0, relief="flat",
    )
    estilo.map(
        "Treeview",
        background=[("selected", PRIMARIA_CLARA)],
        foreground=[("selected", INK)],
    )
    estilo.configure(
        "Treeview.Heading", font=MICRO_FORTE, background=SURFACE_ALT,
        foreground=INK_3, relief="flat", borderwidth=0, padding=(E3, 11),
    )
    estilo.map("Treeview.Heading", background=[("active", BORDER)])

    # --- Barra de rolagem ------------------------------------------------ #
    # Sem setas e sem os biséis do clam. O tema desenha cada canto com um par
    # de linhas claras, e numa janela escura elas viram exatamente as bordas
    # brancas que não se quer: uma moldura pálida grudada na direita da tela.
    # Sobra a calha na cor do fundo e um polegar fino — que só aparece quando
    # de fato falta espaço.
    estilo.layout("Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    estilo.configure(
        "Vertical.TScrollbar", background=BORDER_FORTE, troughcolor=BG,
        bordercolor=BG, lightcolor=BORDER_FORTE, darkcolor=BORDER_FORTE,
        borderwidth=0, arrowcolor=INK_3, relief="flat", width=9,
    )
    estilo.map("Vertical.TScrollbar", background=[("active", INK_3)],
               lightcolor=[("active", INK_3)], darkcolor=[("active", INK_3)])

    # A lupa precisa de uma fonte com emoji; a padrão desenha um quadradinho.
    estilo.configure("Lupa.TButton", font=("Segoe UI Emoji", 9), padding=(2, 4),
                     background=SURFACE, foreground=INK_2, borderwidth=1,
                     bordercolor=BORDER_FORTE)
    estilo.map("Lupa.TButton", background=[("active", SURFACE_ALT)])

    estilo.configure("TSeparator", background=BORDER)
    estilo.configure("TProgressbar", background=PRIMARIA, troughcolor=BORDER,
                     borderwidth=0)
    return estilo


# --------------------------------------------------------------------------- #
# Desenho
# --------------------------------------------------------------------------- #

def retangulo_redondo(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float,
                      raio: float, **kwargs):
    """Retângulo de cantos arredondados num Canvas.

    O Tk não arredonda Frame nenhum, e é o canto arredondado que separa uma
    tela de 2010 de uma de hoje. Onde ele conta — cartão, campo, selo de
    status — a forma é desenhada aqui.

    Os pontos do quarto de círculo são calculados um a um, e o polígono passa
    reto entre eles. O caminho óbvio — `smooth=True` com os cantos repetidos —
    faz o Tk traçar uma Bézier que corta bem menos que o pedido: com raio 12,
    o canto saía com uns 5 de raio efetivo, e de longe parecia quadrado.
    """
    pontos = pontos_redondos(x0, y0, x1, y1, raio)
    if pontos is None:
        return canvas.create_rectangle(x0, y0, x1, y1, **kwargs)
    return canvas.create_polygon(pontos, smooth=False, **kwargs)


def pontos_redondos(x0: float, y0: float, x1: float, y1: float,
                    raio: float) -> list[float] | None:
    """As coordenadas de um retângulo arredondado, sem desenhar nada.

    Separado do desenho porque a animação do realce pede a mesma forma a cada
    quadro; criar um Canvas descartável só para perguntar as coordenadas seria
    desperdício. Devolve ``None`` quando o raio é zero — aí é um retângulo.
    """
    raio = max(0, min(raio, (x1 - x0) / 2, (y1 - y0) / 2))
    if raio <= 0:
        return None
    # O Tk rasteriza polígono sem suavização: cada segmento vira degrau de
    # pixel inteiro. Com um ponto por pixel de raio, um canto de 10px saía com
    # dez facetas visíveis a olho nu — parecia chanfro, não curva. Dobrando a
    # densidade, os degraus caem em cima da circunferência de verdade e o que
    # sobra é o serrilhado do próprio pixel, que não tem como evitar aqui.
    passos = max(8, int(raio * 3))
    pontos: list[float] = []
    quinas = (
        (x1 - raio, y0 + raio, -90),   # superior direita
        (x1 - raio, y1 - raio, 0),     # inferior direita
        (x0 + raio, y1 - raio, 90),    # inferior esquerda
        (x0 + raio, y0 + raio, 180),   # superior esquerda
    )
    for centro_x, centro_y, inicio in quinas:
        for passo in range(passos + 1):
            angulo = math.radians(inicio + 90 * passo / passos)
            pontos.append(centro_x + raio * math.cos(angulo))
            pontos.append(centro_y + raio * math.sin(angulo))
    return pontos


def encurtar(rotulo: tk.Label, texto: str, largura: int) -> None:
    """Escreve o texto no rótulo, com reticência se não couber na largura.

    O Tk não tem `text-overflow`; sem isto ele corta no meio da letra e o
    resultado parece defeito, não abreviação.

    O corte é por busca binária. Tirar uma letra por vez custava uma medida
    por letra — trinta medidas para abreviar um nome de empresa, numa tela que
    tem dezenas deles.
    """
    rotulo.texto_inteiro = texto
    if largura <= 8 or not texto:
        rotulo.configure(text=texto)
        return
    fonte = rotulo.cget("font")
    if medir(texto, fonte) <= largura:
        rotulo.configure(text=texto)
        return
    disponivel = largura - medir("…", fonte)
    baixo, alto = 0, len(texto)
    while baixo < alto:
        meio = (baixo + alto + 1) // 2
        if medir(texto[:meio], fonte) <= disponivel:
            baixo = meio
        else:
            alto = meio - 1
    cortado = texto[:baixo].rstrip()
    rotulo.configure(text=(cortado + "…") if cortado else "…")


# Medir texto é a pergunta mais repetida do programa: cada rótulo que pode ser
# abreviado a faz, e a tela de notas tem centenas. Sem guardar nada, desenhar
# a lista criava 492 objetos de fonte no Tcl — 263 dos 657 ms da tela.
_FONTES: dict[str, tkfont.Font] = {}
_LARGURAS: dict[tuple[str, str], int] = {}
_INTERPRETE: list = [None]
LIMITE_MEDIDAS = 6000


def _limpar_se_trocou_de_janela() -> None:
    """Uma fonte pertence ao interpretador que a criou.

    A suíte de testes abre e fecha dezenas de janelas; guardar a fonte de uma
    janela morta daria TclError na primeira medida da seguinte — e o programa
    cairia num lugar sem nenhuma relação com a causa.
    """
    atual = getattr(tk, "_default_root", None)
    if _INTERPRETE[0] is not atual:
        _INTERPRETE[0] = atual
        _FONTES.clear()
        _LARGURAS.clear()


def _fonte(especificacao) -> tkfont.Font:
    chave = str(especificacao)
    fonte = _FONTES.get(chave)
    if fonte is None:
        fonte = tkfont.Font(font=especificacao)
        _FONTES[chave] = fonte
    return fonte


def medir(texto: str, fonte) -> int:
    """Largura do texto em pixels, para dimensionar o que é desenhado à mão."""
    _limpar_se_trocou_de_janela()
    chave = (str(fonte), texto)
    guardada = _LARGURAS.get(chave)
    if guardada is not None:
        return guardada
    try:
        largura = _fonte(fonte).measure(texto)
    except tk.TclError:
        # Fonte de uma janela que já morreu, ou nome de fonte inválido: joga
        # fora o que estava guardado e tenta uma vez do zero.
        _FONTES.clear()
        _LARGURAS.clear()
        try:
            largura = tkfont.Font(font=fonte).measure(texto)
        except tk.TclError:
            return len(texto) * 7
    if len(_LARGURAS) >= LIMITE_MEDIDAS:
        _LARGURAS.clear()
    _LARGURAS[chave] = largura
    return largura


# --------------------------------------------------------------------------- #
# Componentes
# --------------------------------------------------------------------------- #

def cartao(pai: tk.Widget, *, padx: int = E5, pady: int = E5,
           raio: int = 14, fundo: str | None = None,
           borda: str | None = None, **kwargs) -> "Redondo":
    """Painel de superfície arredondado — a unidade de composição das telas.

    Devolve um ``Redondo``: o conteúdo vai em ``.interior``, não no próprio
    widget. Era um Frame, e Frame do Tk é retângulo de canto vivo — enquanto
    ele fosse a base das telas, o programa continuava com cara de antes.
    """
    return Redondo(pai, raio=raio, fundo=fundo or SURFACE, borda=borda or BORDER,
                   padx=padx, pady=pady, **kwargs)


def rotulo(pai: tk.Widget, texto: str, *, fonte=None, cor=None, fundo=None,
           **kwargs) -> tk.Label:
    return tk.Label(pai, text=texto, font=fonte or CORPO, fg=cor or INK,
                    bg=fundo or SURFACE, **kwargs)


def dica_no_campo(campo: tk.Entry, texto: str, *, fundo: str | None = None) -> None:
    """Põe uma dica em cinza sobre um campo vazio — "dd/mm/aaaa", por exemplo.

    A dica é um rótulo POR CIMA do campo, não o texto dele. Escrever a dica
    dentro do campo é o caminho curto e o errado: quem lê o valor passa a ler
    a dica junto, e num filtro de data isso vira uma data inventada. Como
    rótulo, ela não existe para o resto do programa.
    """
    fundo = fundo or SURFACE
    # Cursor de texto, e não de mão: a dica fica por cima de um campo em que
    # se digita, e a mãozinha ali prometeria um botão que não existe.
    aviso = tk.Label(campo, text=texto, bg=fundo, fg=INK_3, font=PEQUENO,
                     cursor="xterm")

    def rever(_evento=None) -> None:
        if not campo.winfo_exists():
            return
        vazio = not campo.get().strip()
        if vazio and campo.focus_get() is not campo:
            aviso.place(x=2, rely=0.5, anchor="w")
        else:
            aviso.place_forget()

    campo.bind("<KeyRelease>", rever, add="+")
    campo.bind("<FocusIn>", lambda _e: aviso.place_forget(), add="+")
    campo.bind("<FocusOut>", rever, add="+")
    aviso.bind("<Button-1>", lambda _e: campo.focus_set())
    campo.after(60, rever)


def etiqueta_campo(pai: tk.Widget, texto: str, *, fundo=None) -> tk.Label:
    """Rótulo em caixa alta acima de um campo."""
    return tk.Label(pai, text=texto.upper(), font=ETIQUETA, fg=INK_2,
                    bg=fundo or SURFACE)


def separador(pai: tk.Widget, *, fundo=None, espaco: int = E4) -> tk.Frame:
    linha = tk.Frame(pai, bg=BORDER, height=1)
    linha.pack(fill="x", pady=espaco)
    return linha


TONS = ("sucesso", "alerta", "erro", "info", "neutro")


def cores_do_tom(tom: str) -> tuple[str, str]:
    """O par (texto, fundo) de um tom semântico, resolvido no tema em vigor."""
    tabela = {
        "sucesso": (SUCESSO, SUCESSO_BG),
        "alerta": (ALERTA, ALERTA_BG),
        "erro": (ERRO, ERRO_BG),
        "info": (INFO, INFO_BG),
        "neutro": (NEUTRO, NEUTRO_BG),
    }
    return tabela.get(tom, tabela["neutro"])


def pilula(pai: tk.Widget, texto: str, *, cor: str | None = None,
           fundo_pilula: str | None = None, tom: str = "", fundo=None) -> tk.Canvas:
    """Selo arredondado de status — lê-se num relance melhor que texto solto.

    Aceita as duas formas: ``tom="sucesso"`` (o caminho novo, que segue o tema)
    ou o par ``cor``/``fundo_pilula`` explícito, que já era usado nas telas.
    """
    if tom:
        cor, fundo_pilula = cores_do_tom(tom)
    cor = cor or NEUTRO
    fundo_pilula = fundo_pilula or NEUTRO_BG
    fundo = fundo or SURFACE

    fonte = MICRO_FORTE
    largura = medir(texto, fonte) + 2 * E3
    altura = 22
    tela = tk.Canvas(pai, width=largura, height=altura, bg=fundo,
                     highlightthickness=0, bd=0)
    # As pontas são meio-círculo, e para meio-círculo o `create_oval` do Tk
    # desenha melhor que qualquer polígono: ele tem um rasterizador de círculo
    # de verdade, enquanto o polígono aproxima por segmentos e, sem suavização,
    # as pontas saíam chanfradas nesse tamanho. O miolo é um retângulo simples.
    raio = altura / 2
    tela.create_oval(0, 0, altura, altura, fill=fundo_pilula, outline=fundo_pilula)
    tela.create_oval(largura - altura, 0, largura, altura,
                     fill=fundo_pilula, outline=fundo_pilula)
    tela.create_rectangle(raio, 0, largura - raio, altura,
                          fill=fundo_pilula, outline=fundo_pilula)
    tela.create_text(largura / 2, altura / 2 + 1, text=texto, fill=cor, font=fonte)
    return tela


def assinatura(pai: tk.Widget, nome: str, *, fundo: str, cor: str,
               tamanho: int = 14, espaco: float = 2.2,
               registrada: str = "", cor_registrada: str | None = None) -> tk.Canvas:
    """A assinatura da marca, desenhada letra a letra.

    Rótulo do Tk não tem entrelinha nem espaçamento entre letras, e não sabe
    erguer um símbolo — o ``®`` sairia deitado na linha de base, do tamanho da
    palavra, parecendo erro de digitação. Aqui cada letra é posta na posição
    calculada, com respiro entre elas, e o ``®`` vai pequeno, encostado no
    alto da maiúscula, que é onde ele pertence numa assinatura.

    O respiro entre as letras é o que separa uma palavra escrita de uma
    palavra desenhada: em caixa alta, sem ele, as hastes se tocam e o nome lê
    como bloco.
    """
    fonte = tkfont.Font(family=FAMILIA, size=tamanho, weight="bold")
    alto, baixo = fonte.metrics("ascent"), fonte.metrics("descent")
    # O Tk informa `ascent` e `descent`, nunca a altura da maiúscula — e o
    # topo do ascent fica acima do "D", que é onde caberia um acento. As duas
    # razões abaixo foram medidas no pixel, fotografando a barra e contando as
    # linhas de tinta: a maiúscula ocupa 13 de 20 do ascent, e a tinta do ®
    # começa 3 de 10 do ascent dele acima da linha de base.
    altura_maiuscula = round(alto * 0.65)
    base = alto

    larguras = [fonte.measure(letra) for letra in nome]
    largura = sum(larguras) + espaco * max(0, len(nome) - 1)

    # 0,62 e não 0,48: no tamanho anterior o símbolo saía com dois pixels de
    # largura e lia-se como um pingo de sujeira, não como um ®.
    fonte_r = tkfont.Font(family=FAMILIA, size=max(7, round(tamanho * 0.62)))
    alto_r = fonte_r.metrics("ascent")
    largura_r = (fonte_r.measure(registrada) + espaco) if registrada else 0

    tela = tk.Canvas(pai, width=round(largura + largura_r) + 2,
                     height=alto + baixo, bg=fundo, highlightthickness=0, bd=0)
    x = 0.0
    for letra, passo in zip(nome, larguras):
        tela.create_text(x, base, text=letra, fill=cor, font=fonte, anchor="sw")
        x += passo + espaco
    if registrada:
        # Preso pela linha de base, não pelo alto da caixa: a caixa do texto
        # traz espaço vazio acima do glifo, e prendê-la ao topo da maiúscula
        # deixava o ® flutuando no meio da palavra.
        base_r = base - altura_maiuscula + round(alto_r * 0.30)
        tela.create_text(x - espaco + 3, base_r, text=registrada,
                         fill=cor_registrada or cor, font=fonte_r, anchor="sw")
    return tela


def dica(widget: tk.Widget, texto: str, *, espera: int = 450) -> None:
    """Diz o que o controle faz, ao pousar o mouse nele.

    Um ícone sem legenda só se explica clicando — e clicar num ícone que não
    se sabe o que faz é justamente o que ninguém quer fazer num programa de
    nota fiscal.

    A janelinha nasce sem barra de título e SEM `transient`: no Windows, uma
    janela que é as duas coisas simplesmente não aparece. Foi o que já deixou
    os avisos invisíveis aqui, e a lição vale para qualquer flutuante.
    """
    estado: dict = {"tarefa": None, "janela": None}

    def esconder(_evento=None) -> None:
        if estado["tarefa"] is not None:
            try:
                widget.after_cancel(estado["tarefa"])
            except tk.TclError:
                pass
            estado["tarefa"] = None
        janela = estado["janela"]
        estado["janela"] = None
        if janela is not None:
            try:
                janela.destroy()
            except tk.TclError:
                pass

    def mostrar() -> None:
        estado["tarefa"] = None
        if not widget.winfo_exists() or estado["janela"] is not None:
            return
        try:
            janela = tk.Toplevel(widget)
            janela.overrideredirect(True)
            janela.configure(bg=BORDER_FORTE)
            tk.Label(janela, text=texto, bg=SURFACE_FUNDA, fg=INK,
                     font=MICRO, padx=E2, pady=3).pack(padx=1, pady=1)
            janela.update_idletasks()
            x = widget.winfo_rootx() + widget.winfo_width() // 2
            x -= janela.winfo_width() // 2
            y = widget.winfo_rooty() - janela.winfo_height() - 6
            janela.geometry(f"+{max(0, x)}+{max(0, y)}")
            janela.lift()
        except tk.TclError:
            return
        estado["janela"] = janela

    def pousar(_evento=None) -> None:
        esconder()
        estado["tarefa"] = widget.after(espera, mostrar)

    widget.bind("<Enter>", pousar, add="+")
    widget.bind("<Leave>", esconder, add="+")
    widget.bind("<Button-1>", esconder, add="+")
    widget.bind("<Destroy>", esconder, add="+")


def atenuar(fracao: float) -> float:
    """Curva de atenuação cúbica: sai devagar, acelera, chega devagar.

    A mesma que as transições da web usam por padrão. Serve tanto ao
    indicador da navegação quanto ao realce dos cartões.
    """
    if fracao < 0.5:
        return 4 * fracao ** 3
    return 1 - ((-2 * fracao + 2) ** 3) / 2


def misturar(inicio: str, fim: str, fracao: float) -> str:
    """A cor a meio caminho entre duas — o que falta ao Tk para transição.

    No navegador, `transition` faz isso sozinho. Aqui a cor de cada quadro é
    calculada e aplicada na mão, que é o preço de não ter folha de estilo.
    """
    try:
        a = [int(inicio.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        b = [int(fim.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    except (ValueError, IndexError):
        return fim
    fracao = max(0.0, min(1.0, fracao))
    return "#%02x%02x%02x" % tuple(
        round(x + (y - x) * fracao) for x, y in zip(a, b))


def ponto(pai: tk.Widget, cor: str, *, fundo=None, lado: int = 10) -> tk.Canvas:
    """Bolinha colorida de status — o indicador de transmissão da barra lateral."""
    tela = tk.Canvas(pai, width=lado, height=lado, bg=fundo or SURFACE,
                     highlightthickness=0, bd=0)
    folga = 1
    tela.create_oval(folga, folga, lado - folga, lado - folga, fill=cor, outline=cor)
    return tela


def banner(pai: tk.Widget, titulo: str, linhas: list[str], *, tom: str = "alerta") -> tk.Frame:
    """Aviso destacado no topo de uma tela."""
    cor, fundo = cores_do_tom(tom)
    caixa = tk.Frame(pai, bg=fundo, highlightbackground=cor, highlightthickness=0,
                     padx=E4, pady=E3)
    faixa = tk.Frame(caixa, bg=cor, width=3)
    faixa.place(x=0, y=0, relheight=1.0)
    interno = tk.Frame(caixa, bg=fundo)
    interno.pack(fill="x", padx=(E2, 0))
    tk.Label(interno, text=titulo, font=PEQUENO_FORTE, fg=cor, bg=fundo).pack(anchor="w")
    for linha in linhas:
        tk.Label(interno, text=f"•  {linha}", font=PEQUENO, fg=cor, bg=fundo,
                 justify="left", anchor="w").pack(anchor="w", pady=(2, 0))
    return caixa


def cartao_numero(pai: tk.Widget, titulo: str, valor: str, detalhe: str,
                  *, tom: str = "") -> "Redondo":
    """Cartão de indicador do painel.

    Mesma forma dos contadores da lista de notas: as duas telas mostram a
    mesma coisa e não podem ter aparências diferentes.
    """
    cor = globals().get(TONS_DE_FILTRO.get(tom, ""), INK)
    caixa = Redondo(pai, raio=12, fundo=SURFACE, borda=BORDER, padx=E4, pady=E3)
    tk.Label(caixa.interior, text=titulo.upper(), font=ETIQUETA, fg=INK_3,
             bg=SURFACE, anchor="w").pack(anchor="w", fill="x")
    tk.Label(caixa.interior, text=valor, font=NUMERO, fg=cor if tom else INK,
             bg=SURFACE, anchor="w").pack(anchor="w", fill="x", pady=(E1, 0))
    tk.Label(caixa.interior, text=detalhe, font=MICRO, fg=INK_3, bg=SURFACE,
             anchor="w").pack(anchor="w", fill="x", pady=(2, 0))
    return caixa


def icone_vetor(pai: tk.Widget, nome: str, *, cor: str, fundo: str,
                lado: int = 21) -> tk.Canvas:
    """Ícone de linha, desenhado — não escrito.

    Caractere de fonte (▦ ＋ ▤ ⚙) vira quadradinho em máquina sem a fonte que
    o contém, e estes ficam na primeira tela que o programa mostra. Desenhados,
    aparecem em qualquer Windows.
    """
    tela = tk.Canvas(pai, width=lado, height=lado, bg=fundo,
                     highlightthickness=0, bd=0)
    u = lado / 24.0                      # as formas são pensadas numa grade 24
    linha = max(1, round(lado / 12))

    def retangulo(x0, y0, x1, y1):
        tela.create_rectangle(x0 * u, y0 * u, x1 * u, y1 * u,
                              outline=cor, width=linha)

    def traco(x0, y0, x1, y1):
        tela.create_line(x0 * u, y0 * u, x1 * u, y1 * u,
                         fill=cor, width=linha, capstyle="round")

    if nome == "emitir":
        tela.create_oval(3 * u, 3 * u, 21 * u, 21 * u, outline=cor, width=linha)
        traco(12, 8, 12, 16)
        traco(8, 12, 16, 12)
    elif nome == "notas":
        traco(6, 2, 15, 2)
        traco(15, 2, 20, 7)
        traco(20, 7, 20, 22)
        traco(20, 22, 6, 22)
        traco(6, 22, 6, 2)
        traco(9, 12, 16, 12)
        traco(9, 16, 14, 16)
    elif nome == "empresas":
        traco(3, 21, 21, 21)
        traco(5, 21, 5, 8)
        traco(5, 8, 12, 3)
        traco(12, 3, 19, 8)
        traco(19, 8, 19, 21)
        retangulo(10, 15, 14, 21)
    elif nome == "config":
        # Controles deslizantes: mais legível que uma engrenagem neste tamanho.
        traco(4, 7, 20, 7)
        traco(4, 12, 20, 12)
        traco(4, 17, 20, 17)
        for x, y in ((9, 7), (15, 12), (7, 17)):
            tela.create_oval((x - 2) * u, (y - 2) * u, (x + 2) * u, (y + 2) * u,
                             fill=fundo, outline=cor, width=linha)
    elif nome == "tema":
        # Lua crescente: dois círculos, o de cima na cor do fundo.
        tela.create_oval(4 * u, 4 * u, 20 * u, 20 * u, outline=cor, width=linha)
        tela.create_oval(9 * u, 1 * u, 25 * u, 17 * u, fill=fundo, outline=fundo)
    elif nome == "sair":
        traco(4, 12, 15, 12)
        traco(11, 8, 15, 12)
        traco(11, 16, 15, 12)
        traco(19, 4, 19, 20)
    return tela


def luminancia_relativa(cor: str) -> float:
    """A luminância relativa da cor, pela fórmula das WCAG 2.1.

    É a base da razão de contraste da norma. O canal passa por uma correção
    de gama antes de ser ponderado — média simples de RGB não descreve o que
    o olho enxerga, e é onde as aproximações caseiras erram.
    """
    def canal(valor: int) -> float:
        v = valor / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def razao_de_contraste(frente: str, fundo: str) -> float:
    """Quanto uma cor se destaca da outra. A WCAG AA pede 4,5:1 para texto."""
    a, b = luminancia_relativa(frente), luminancia_relativa(fundo)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def contraste(cor: str) -> str:
    """Preto ou branco — o que for legível sobre a cor dada.

    Existe porque o mesmo cartão é preenchido com verde claro no tema escuro e
    com verde escuro no claro. Fixar "branco" acertaria num tema e deixaria o
    outro ilegível; a conta decide sozinha, em qualquer paleta futura.
    """
    escuro, claro = "#0b1020", "#ffffff"
    try:
        alvo = luminancia_relativa(cor)
    except (ValueError, IndexError):
        return claro
    # Calcula a razão com as duas tintas e fica com a que ganha, em vez de
    # decidir por um limiar de brilho. O limiar antigo (0,6 sobre uma média
    # ponderada) escolhia branco sobre o rosa #ff5c7c e dava 2,97:1 — abaixo
    # dos 4,5:1 que a WCAG pede. A razão não tem limiar para errar.
    def razao(tinta: str) -> float:
        a, b = luminancia_relativa(tinta), alvo
        return (max(a, b) + 0.05) / (min(a, b) + 0.05)

    return escuro if razao(escuro) >= razao(claro) else claro


TONS_DE_FILTRO = {
    "sucesso": "SUCESSO", "alerta": "PONTO_ATIVO", "erro": "ERRO",
    "info": "PRIMARIA", "neutro": "INK_2",
}


def _rgb(cor: str) -> tuple[int, int, int]:
    return tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5))


def losango(pai: tk.Widget, texto: str, *, lado: int = 32,
            fundo: str | None = None) -> tk.Canvas:
    """O símbolo da marca: quadrado arredondado com degradê na diagonal.

    O Canvas do Tk não preenche em gradiente, então o degradê é desenhado
    linha a linha. Cada linha já nasce recortada pelo arco do canto — é isso
    que arredonda a forma, sem máscara nem pixel a pixel.
    """
    tela = tk.Canvas(pai, width=lado, height=lado, bg=fundo or NAVY,
                     highlightthickness=0, bd=0)
    inicio, fim = _rgb(PRIMARIA), _rgb(ONDA)
    raio = max(2, lado // 3.5)
    for y in range(lado):
        fracao = y / max(1, lado - 1)
        cor = "#%02x%02x%02x" % tuple(
            round(inicio[i] + (fim[i] - inicio[i]) * fracao) for i in range(3))
        # Quanto o arco come desta linha, de cada lado.
        recuo = 0.0
        if y < raio:
            recuo = raio - math.sqrt(max(0.0, raio * raio - (raio - y) ** 2))
        elif y > lado - raio:
            distancia = y - (lado - raio)
            recuo = raio - math.sqrt(max(0.0, raio * raio - distancia ** 2))
        tela.create_line(recuo, y, lado - recuo, y, fill=cor)
    tela.create_text(lado / 2, lado / 2 + 1, text=texto, fill="#ffffff",
                     font=(FAMILIA, max(8, lado // 3), "bold"))
    return tela


class Segmentado(tk.Canvas):
    """Navegação em pílula, com o realce deslizando de uma seção à outra.

    Desenhada, e não montada com widgets, por um motivo concreto: Label do Tk
    tem fundo opaco e taparia um marcador que passasse por baixo. No Canvas o
    marcador é uma forma, o texto vem depois, e mover um é trivial.
    """

    ALTURA = 38
    ALTURA_BASE = 38      # `aplicar_escala` recalcula ALTURA a partir daqui
    FOLGA = 18          # respiro de cada lado do rótulo

    def __init__(self, pai: tk.Widget, itens: list[tuple[str, str]],
                 ao_escolher: Callable[[str], None], *,
                 fundo: str | None = None) -> None:
        self.itens = itens
        self.ao_escolher = ao_escolher
        self.escolhida = itens[0][0]
        self._tarefa: str | None = None

        larguras = [medir(rotulo, CORPO) + self.FOLGA * 2 for _c, rotulo in itens]
        total = sum(larguras) + 8
        super().__init__(pai, width=total, height=self.ALTURA,
                         bg=fundo or NAVY, highlightthickness=0, bd=0,
                         cursor="hand2")

        retangulo_redondo(self, 0.5, 0.5, total - 0.5, self.ALTURA - 0.5,
                          self.ALTURA / 2, fill=SURFACE_ALT, outline=BORDER)

        self._faixas: dict[str, tuple[float, float]] = {}
        posicao = 4.0
        for (chave, _rotulo), largura in zip(itens, larguras):
            self._faixas[chave] = (posicao, largura)
            posicao += largura

        inicio, largura = self._faixas[self.escolhida]
        self._atual = inicio
        self._alvo = inicio
        self._marcador = self.create_polygon(
            self._forma(inicio, largura), fill=PRIMARIA, outline=PRIMARIA)

        self._textos: dict[str, int] = {}
        for chave, rotulo in itens:
            comeco, largura_item = self._faixas[chave]
            self._textos[chave] = self.create_text(
                comeco + largura_item / 2, self.ALTURA / 2 + 1, text=rotulo,
                font=CORPO,
                fill=contraste(PRIMARIA) if chave == self.escolhida else INK_2)

        self.bind("<Button-1>", self._clique)

    # -- forma ----------------------------------------------------------- #

    def _forma(self, x: float, largura: float) -> list[float]:
        return pontos_redondos(x, 4, x + largura, self.ALTURA - 4,
                               (self.ALTURA - 8) / 2) or []

    # -- interação ------------------------------------------------------- #

    def _clique(self, evento) -> None:
        for chave, (inicio, largura) in self._faixas.items():
            if inicio <= evento.x <= inicio + largura and chave != self.escolhida:
                self.ao_escolher(chave)
                return

    def escolher(self, chave: str, *, animar: bool = True) -> None:
        """Move o realce para a seção pedida."""
        if chave not in self._faixas or not self.winfo_exists():
            return
        self.escolhida = chave
        for outra, item in self._textos.items():
            self.itemconfigure(
                item, fill=contraste(PRIMARIA) if outra == chave else INK_2)
        self._alvo = self._faixas[chave][0]
        if animar:
            self._deslizar()
        else:
            self._atual = self._alvo
            self._repor()

    def _repor(self) -> None:
        largura = self._faixas[self.escolhida][1]
        self.coords(self._marcador, *self._forma(self._atual, largura))

    DURACAO = 220        # milissegundos do trajeto inteiro

    # A curva mora no módulo: o realce dos cartões usa a mesma. Substituiu uma
    # mola exponencial que partia na velocidade máxima — o que se lê como
    # solavanco — e nunca chegava ao destino, precisando de um corte de 0,6px
    # para declarar chegada.
    atenuar = staticmethod(atenuar)

    def _deslizar(self) -> None:
        """Anda o indicador até o alvo, ao longo de `DURACAO`."""
        if not self.winfo_exists():
            return
        if self._tarefa:
            try:
                self.after_cancel(self._tarefa)
            except tk.TclError:
                pass
            self._tarefa = None
        self._partida = self._atual
        self._inicio = time.monotonic()
        self._quadro()

    def _quadro(self) -> None:
        if not self.winfo_exists():
            return
        decorrido = (time.monotonic() - self._inicio) * 1000
        fracao = min(1.0, decorrido / self.DURACAO)
        self._atual = self._partida + (self._alvo - self._partida) * self.atenuar(fracao)
        self._repor()
        if fracao >= 1.0:
            self._tarefa = None
            return
        self._tarefa = self.after(16, self._quadro)


class Redondo(tk.Canvas):
    """Painel de cantos arredondados. O conteúdo vai em ``.interior``.

    Frame do Tk é retângulo de canto vivo, sem exceção — é o que dá à tela o
    ar de programa antigo. Aqui a moldura é desenhada num Canvas e o conteúdo
    entra por cima, num Frame de verdade: continua sendo `pack` e `grid` como
    em qualquer outro lugar.

    Custa uma redesenhada da moldura a cada mudança de tamanho, o que é
    barato: uma forma, não um widget.
    """

    def __init__(self, pai: tk.Widget, *, raio: int = 12, fundo: str | None = None,
                 borda: str | None = None, fundo_externo: str | None = None,
                 padx: int = E4, pady: int = E3, **kwargs) -> None:
        super().__init__(pai, bg=fundo_externo or BG, highlightthickness=0,
                         bd=0, **kwargs)
        self.raio = raio
        self.fundo = fundo or SURFACE
        self.borda = borda or BORDER
        self._medida = (0, 0)
        self.interior = tk.Frame(self, bg=self.fundo, padx=padx, pady=pady)
        self._janela = self.create_window(0, 0, window=self.interior, anchor="nw")
        self.interior.bind("<Configure>", self._acompanhar_conteudo)
        self.bind("<Configure>", self._redesenhar)

    @property
    def _margem(self) -> int:
        """Quanto o conteúdo recua para não tapar o canto arredondado.

        O canto do Frame fica em (m, m); o arco tem centro em (raio, raio) e
        raio `raio`. Para o canto caber dentro do arco: √2·(raio − m) ≤ raio,
        isto é, m ≥ 0,293·raio. Sem esse recuo o Frame cobre o canvas inteiro
        e a quina quadrada dele apaga todo o arredondamento — foi o que
        aconteceu na primeira versão, e não dava para ver diferença nenhuma.
        """
        return max(2, round(self.raio * 0.35))

    def _acompanhar_conteudo(self, _evento=None) -> None:
        """O Canvas passa a pedir o tamanho do conteúdo mais o recuo."""
        margem = self._margem
        largura = self.interior.winfo_reqwidth() + 2 * margem
        altura = self.interior.winfo_reqheight() + 2 * margem
        # Só quando mudou de verdade: reconfigurar sempre devolve outro
        # <Configure>, e os dois widgets ficam se empurrando para sempre.
        if (self.winfo_reqwidth(), self.winfo_reqheight()) != (largura, altura):
            self.configure(width=largura, height=altura)

    def _redesenhar(self, evento=None) -> None:
        largura = evento.width if evento else self.winfo_width()
        altura = evento.height if evento else self.winfo_height()
        if largura <= 1 or altura <= 1 or (largura, altura) == self._medida:
            return
        self._medida = (largura, altura)
        margem = self._margem
        self.coords(self._janela, margem, margem)
        # Só a largura é imposta; a altura fica em zero, que no Canvas quer
        # dizer "use a que o conteúdo pedir".
        #
        # Impor a altura travava o cartão: com ela presa, acrescentar campos
        # mudava a altura PEDIDA pelo interior mas não a desenhada — e sem
        # mudança na desenhada não vem <Configure>, então `_acompanhar_conteudo`
        # nunca rodava e o Canvas jamais ficava sabendo que precisava crescer.
        # Era um impasse: cada um esperando o outro. Foi o que cortou o bloco
        # do tomador ao voltar do portal, e o que fez o cartão do NBS nascer
        # com um pixel de altura e sumir da tela.
        self.itemconfigure(self._janela, width=max(1, largura - 2 * margem),
                           height=0)
        self.delete("moldura")
        retangulo_redondo(self, 0.5, 0.5, largura - 0.5, altura - 0.5, self.raio,
                          fill=self.fundo, outline=self.borda, tags="moldura")
        self.tag_lower("moldura")     # a moldura fica atrás do conteúdo

    def pintar(self, *, fundo: str | None = None, borda: str | None = None) -> None:
        """Troca as cores da moldura sem recriar nada."""
        if fundo is not None:
            self.fundo = fundo
            self.interior.configure(bg=fundo)
        if borda is not None:
            self.borda = borda
        self._medida = (0, 0)         # força a moldura a ser refeita
        self._redesenhar()


class CartaoFiltro(Redondo):
    """Cartão de contador que também é o filtro da lista.

    Preenchido quando selecionado, contornado quando não. É o que dispensa um
    segundo controle de "situação" ao lado: o número e o filtro são a mesma
    coisa, e clicar no que se está lendo é o gesto óbvio.

    Nasce uma vez e depois só troca de texto. Recriá-lo a cada tecla digitada
    era metade do custo de redesenhar a tela.
    """

    def __init__(self, pai: tk.Widget, titulo: str, *, tom: str = "info",
                 ao_clicar: Callable[[], None] | None = None) -> None:
        self.cor = globals().get(TONS_DE_FILTRO.get(tom, "PRIMARIA"), PRIMARIA)
        self.ativo = False
        self._realce = None
        self._fundo_agora, self._borda_agora = SURFACE, BORDER
        # A mãozinha só aparece quando há mesmo o que clicar. Antes ela era
        # fixa, e no Painel — onde estes cartões não tinham função — ela
        # prometia uma resposta que não vinha. Cursor é promessa; promessa
        # sem cumprimento é o mesmo que botão que não é botão.
        super().__init__(pai, raio=12, fundo=SURFACE, borda=BORDER,
                         padx=E4, pady=E3,
                         cursor="hand2" if ao_clicar is not None else "")
        self.titulo = tk.Label(self.interior, text=titulo.upper(), font=ETIQUETA,
                               bg=SURFACE, fg=INK_3, anchor="w")
        self.numero = tk.Label(self.interior, text="0", font=NUMERO, bg=SURFACE,
                               fg=self.cor, anchor="w")
        self.detalhe = tk.Label(self.interior, text="", font=MICRO, bg=SURFACE,
                                fg=INK_3, anchor="w")
        self.titulo.pack(anchor="w")
        self.numero.pack(anchor="w", pady=(E1, 0))
        self.detalhe.pack(anchor="w", pady=(2, 0))

        if ao_clicar is not None:
            for widget in (self, self.interior, self.titulo, self.numero, self.detalhe):
                # A mãozinha vai em TODOS, não só no cartão: os rótulos cobrem
                # quase toda a área dele, e sem isto o cursor trocava conforme
                # o mouse passasse por cima de uma letra ou do vão ao lado —
                # o cartão parecia clicável só em pedaços.
                widget.configure(cursor="hand2")
                widget.bind("<Enter>", self._entrar)
                widget.bind("<Leave>", self._sair)
                widget.bind("<Button-1>", lambda _e: ao_clicar())

    # -- aparência ------------------------------------------------------- #

    def _vestir(self, fundo: str, borda: str, tinta_titulo: str,
                tinta_numero: str) -> None:
        # Guardadas para o esmaecer saber de onde parte.
        self._fundo_agora, self._borda_agora = fundo, borda
        self.pintar(fundo=fundo, borda=borda)
        self.titulo.configure(bg=fundo, fg=tinta_titulo)
        self.numero.configure(bg=fundo, fg=tinta_numero)
        self.detalhe.configure(bg=fundo, fg=tinta_titulo)

    REALCE = 140         # milissegundos do esmaecer

    def _entrar(self, _evento=None) -> None:
        if not self.ativo:
            self._esmaecer(SURFACE_ALT, self.cor)

    def _sair(self, _evento=None) -> None:
        if not self.ativo:
            self._esmaecer(SURFACE, BORDER)

    def _esmaecer(self, fundo: str, borda: str) -> None:
        """Vai da cor atual até a de destino ao longo de `REALCE`.

        Só nos cartões, de propósito. Na linha da tabela o realce continua
        instantâneo: numa lista que se percorre depressa, a cor que demora a
        chegar vira rastro atrás do ponteiro — ali o salto é a resposta certa.
        """
        if self._realce is not None:
            try:
                self.after_cancel(self._realce)
            except tk.TclError:
                pass
            self._realce = None
        partida = (self._fundo_agora, self._borda_agora)
        destino = (fundo, borda)
        if partida == destino:
            return
        comeco = time.monotonic()

        def quadro() -> None:
            if not self.winfo_exists():
                return
            fracao = min(1.0, (time.monotonic() - comeco) * 1000 / self.REALCE)
            andado = atenuar(fracao)
            self._vestir(misturar(partida[0], destino[0], andado),
                         misturar(partida[1], destino[1], andado),
                         INK_3, self.cor)
            self._realce = None if fracao >= 1.0 else self.after(16, quadro)

        quadro()

    # -- conteúdo -------------------------------------------------------- #

    def atualizar(self, quantidade: str, detalhe: str, *, ativo: bool) -> None:
        """Troca os números; repinta só quando a seleção mudou de fato."""
        self.numero.configure(text=quantidade)
        self.detalhe.configure(text=detalhe)
        if ativo == self.ativo:
            return
        self.ativo = ativo
        if ativo:
            tinta = contraste(self.cor)
            self._vestir(self.cor, self.cor, tinta, tinta)
        else:
            self._vestir(SURFACE, BORDER, INK_3, self.cor)


ALTURA_LINHA = 48        # o padrão confortável das tabelas de dados
ALTURA_CABECALHO = 38
_ALTURA_LINHA_BASE = 48
_ALTURA_CABECALHO_BASE = 38


class Celula:
    """Como uma coluna se desenha. Só descrição — quem desenha é a Linha."""

    def __init__(self, chave: str, titulo: str, largura: int, *,
                 tipo: str = "texto", peso: int = 0, fim: bool = False,
                 minimo: int = 0, ordenavel: bool = True) -> None:
        self.chave = chave
        self.titulo = titulo
        self.largura = largura
        self.tipo = tipo          # texto | duplo | dinheiro | pilula | marca | acoes
        self.peso = peso          # >0 = divide a sobra, e cede quando falta
        self.fim = fim            # alinhado à direita
        # A coluna de ícones não ordena nada: não há o que comparar nela.
        self.ordenavel = ordenavel
        # Piso: em janela estreita a coluna encolhe até aqui e para. Sem ele,
        # apertar a janela espremeria uma coluna até zero.
        self.minimo = minimo or max(40, largura // 2)


class Linha(tk.Frame):
    """Uma linha da tabela. Nasce uma vez, depois só troca de conteúdo."""

    def __init__(self, pai: tk.Widget, colunas: list[Celula], *,
                 ao_clicar, ao_abrir, ao_agir) -> None:
        super().__init__(pai, bg=SURFACE, height=ALTURA_LINHA, cursor="hand2")
        self.pack_propagate(False)
        self.colunas = colunas
        self.identidade = ""
        self.marcada = False
        self.fundo = SURFACE
        self._ao_agir = ao_agir

        # Faixa da esquerda: some quando a linha não está marcada.
        self.faixa = tk.Frame(self, bg=SURFACE, width=3)
        self.faixa.pack(side="left", fill="y")

        self.partes: dict[str, dict] = {}
        self.caixas: dict[str, tk.Frame] = {}
        for coluna in colunas:
            caixa = tk.Frame(self, bg=SURFACE, width=coluna.largura)
            caixa.pack_propagate(False)
            # Sem `expand`: a largura é dada pela Tabela, que sabe quanto há
            # para repartir. Com `expand`, o pack dividia a sobra em partes
            # iguais e o peso da coluna não valia nada.
            caixa.pack(side="left", fill="y", padx=(E3, 0))
            self.caixas[coluna.chave] = caixa
            self.partes[coluna.chave] = self._montar(caixa, coluna)

        # `add="+"` em todos: sem isso, este laço APAGA o que já foi ligado
        # nos filhos ao montá-los. Foi o que deixou os dois ícones do fim da
        # linha decorativos — clicar no de PDF só selecionava a linha, porque
        # a ação deles tinha sido sobrescrita aqui. E, mais tarde, foi o que
        # engoliu a dica que aparece ao pousar o mouse.
        for widget in self._tudo():
            # A linha inteira responde ao clique, então a linha inteira mostra
            # a mãozinha — inclusive as células. Só no Frame de fora, o cursor
            # mudava nos vãos e voltava ao normal em cima do texto.
            try:
                widget.configure(cursor="hand2")
            except tk.TclError:
                pass
            widget.bind("<Button-1>", lambda _e: ao_clicar(self), add="+")
            widget.bind("<Double-1>", lambda _e: ao_abrir(self), add="+")
            widget.bind("<Enter>", self._entrar, add="+")
            widget.bind("<Leave>", self._sair, add="+")

    # -- montagem ------------------------------------------------------- #

    def _montar(self, caixa: tk.Frame, coluna: Celula) -> dict:
        lado = "e" if coluna.fim else "w"
        if coluna.tipo == "duplo":
            # Duas linhas: o principal e, abaixo, o secundário em corpo menor.
            dentro = tk.Frame(caixa, bg=SURFACE)
            dentro.pack(fill="both", expand=True)
            cima = tk.Label(dentro, bg=SURFACE, fg=INK, font=CORPO, anchor=lado)
            baixo = tk.Label(dentro, bg=SURFACE, fg=INK_3, font=MICRO, anchor=lado)
            cima.pack(fill="x", pady=(9, 0))
            baixo.pack(fill="x")
            parte = {"tipo": "duplo", "caixa": caixa, "cima": cima, "baixo": baixo}
            self._reencaixar_ao_mudar(caixa, (cima, baixo))
            return parte

        if coluna.tipo == "dinheiro":
            # Símbolo mais leve que o número, e o número em fonte tabular:
            # é o que deixa os valores alinhados na vertical, dígito a dígito.
            dentro = tk.Frame(caixa, bg=SURFACE)
            dentro.pack(fill="both", expand=True)
            interno = tk.Frame(dentro, bg=SURFACE)
            interno.pack(side="right", pady=(1, 0), fill="y")
            simbolo = tk.Label(interno, text="R$", bg=SURFACE, fg=INK_3, font=MICRO)
            valor = tk.Label(interno, bg=SURFACE, fg=INK, font=(MONO, 10))
            simbolo.pack(side="left", pady=(3, 0))
            valor.pack(side="left", padx=(3, 0))
            return {"tipo": "dinheiro", "caixa": caixa, "interno": interno,
                    "simbolo": simbolo, "valor": valor}

        if coluna.tipo == "pilula":
            dentro = tk.Frame(caixa, bg=SURFACE)
            dentro.pack(fill="both", expand=True)
            return {"tipo": "pilula", "caixa": caixa, "dentro": dentro, "atual": None}

        if coluna.tipo == "acoes":
            dentro = tk.Frame(caixa, bg=SURFACE)
            dentro.pack(side="right", fill="y")
            botoes = {}
            for nome, dica_do_icone in (("pdf", "Abrir em PDF"),
                                        ("enviar", "Enviar ao portal")):
                alvo = tk.Frame(dentro, bg=SURFACE, cursor="hand2", padx=5, pady=5)
                alvo.pack(side="left", pady=(9, 0))
                # 18px e um cinza mais claro: com o texto da linha maior, o
                # ícone de 16 em INK_3 sumia ao lado dele.
                desenho = icone_vetor(alvo, "notas" if nome == "pdf" else "emitir",
                                      cor=INK_2, fundo=SURFACE, lado=18)
                desenho.pack()
                for widget in (alvo, desenho):
                    widget.bind("<Button-1>",
                                lambda _e, n=nome: self._agir(n))
                    # O ícone come o clique quando age: senão a linha também
                    # se selecionaria, e um clique faria duas coisas.
                # A legenda já existia nesta tupla desde o começo, sem uso.
                dica(alvo, dica_do_icone)
                botoes[nome] = {"caixa": alvo, "desenho": desenho,
                                "icone": "notas" if nome == "pdf" else "emitir",
                                "cor": INK_2, "ligado": True}
            return {"tipo": "acoes", "caixa": caixa, "dentro": dentro, "botoes": botoes}

        rotulo = tk.Label(caixa, bg=SURFACE, fg=INK, font=CORPO, anchor=lado)
        rotulo.pack(fill="both", expand=True)
        self._reencaixar_ao_mudar(caixa, (rotulo,))
        return {"tipo": "texto", "caixa": caixa, "rotulo": rotulo}

    @staticmethod
    def _reencaixar_ao_mudar(caixa: tk.Frame, rotulos: tuple) -> None:
        """Recorta de novo quando a coluna muda de largura.

        Três colunas esticam com a janela. Truncar só pela largura declarada
        abreviaria textos que caberiam inteiros numa janela maior.
        """
        def ao_mudar(evento) -> None:
            for rotulo in rotulos:
                inteiro = getattr(rotulo, "texto_inteiro", None)
                if inteiro is not None:
                    encurtar(rotulo, inteiro, evento.width - E2)

        caixa.bind("<Configure>", ao_mudar)

    def _agir(self, nome: str):
        parte = self.partes.get("acoes")
        if parte and parte["botoes"][nome]["ligado"]:
            self._ao_agir(self, nome)
            return "break"
        return None


    def _tudo(self):
        """Todo widget da linha, para pintar e ouvir cliques de uma vez."""
        achados = [self, self.faixa]

        def descer(widget):
            for filho in widget.winfo_children():
                achados.append(filho)
                descer(filho)

        descer(self)
        return achados

    # -- pintura -------------------------------------------------------- #

    def pintar(self, fundo: str) -> None:
        self.fundo = fundo
        for widget in self._tudo():
            if isinstance(widget, tk.Canvas):
                widget.configure(bg=fundo)
            elif widget is not self.faixa:
                try:
                    widget.configure(bg=fundo)
                except tk.TclError:
                    pass
        self.faixa.configure(bg=PRIMARIA if self.marcada else fundo)

    def _entrar(self, _evento=None) -> None:
        if not self.marcada:
            self.pintar(PRIMARIA_CLARA)

    def _sair(self, _evento=None) -> None:
        if not self.marcada:
            self.pintar(self.fundo_normal)

    # -- conteúdo ------------------------------------------------------- #

    def mostrar(self, dados: dict, *, listrada: bool, marcada: bool) -> None:
        self.identidade = dados.get("id", "")
        self.marcada = marcada
        self.fundo_normal = SURFACE_ALT if listrada else SURFACE
        alvo = PRIMARIA_CLARA if marcada else self.fundo_normal

        for coluna in self.colunas:
            parte = self.partes[coluna.chave]
            valor = dados.get(coluna.chave)
            if parte["tipo"] == "duplo":
                cima, baixo = (valor or ("", ""))
                espaco = max(20, parte["caixa"].winfo_width() - E2)
                encurtar(parte["cima"], cima, espaco)
                encurtar(parte["baixo"], baixo, espaco)
            elif parte["tipo"] == "dinheiro":
                parte["valor"].configure(text=valor or "")
            elif parte["tipo"] == "pilula":
                for filho in parte["dentro"].winfo_children():
                    filho.destroy()
                if valor:
                    rotulo, tom = valor
                    cor, fundo_pilula = cores_do_tom(tom)
                    pilula(parte["dentro"], rotulo, cor=cor,
                           fundo_pilula=fundo_pilula, fundo=alvo).pack(
                        anchor="w", pady=(13, 0))
            elif parte["tipo"] == "acoes":
                for nome, botao in parte["botoes"].items():
                    ligado = bool((valor or {}).get(nome))
                    botao["ligado"] = ligado
                    cor = INK_2 if ligado else BORDER_FORTE
                    # O ícone é desenhado com linhas: mudar de cor é
                    # redesenhar. Só quando muda de fato — redesenhar toda
                    # linha a cada filtro devolveria o custo que a tabela
                    # reaproveitada acabou de economizar.
                    if cor != botao["cor"]:
                        botao["cor"] = cor
                        botao["desenho"].destroy()
                        novo_desenho = icone_vetor(botao["caixa"], botao["icone"],
                                                   cor=cor, fundo=alvo, lado=16)
                        novo_desenho.pack()
                        novo_desenho.bind(
                            "<Button-1>", lambda _e, n=nome: self._agir(n))
                        botao["desenho"] = novo_desenho
            else:
                espaco = max(20, parte["caixa"].winfo_width() - E2)
                encurtar(parte["rotulo"], str(valor or ""), espaco)
                parte["rotulo"].configure(
                    fg=INK_3 if str(valor or "").startswith("—") else INK)
        self.pintar(alvo)


class Tabela(tk.Frame):
    """Lista de notas, montada à mão.

    Reaproveita as linhas: filtrar não destrói widget nenhum, só troca o
    conteúdo e esconde o que sobrou. É o que permite ter pílula e ícone por
    linha sem a digitação engasgar.
    """

    def __init__(self, pai: tk.Widget, colunas: list[Celula], *,
                 ao_selecionar=None, ao_abrir=None, ao_agir=None,
                 ao_ordenar=None, altura_maxima: int = 9) -> None:
        super().__init__(pai, bg=SURFACE)
        self.colunas = colunas
        self.altura_maxima = altura_maxima
        self._ao_selecionar = ao_selecionar or (lambda _i: None)
        self._ao_abrir = ao_abrir or (lambda _i: None)
        self._ao_agir = ao_agir or (lambda _i, _n: None)
        self._ao_ordenar = ao_ordenar
        self.ordenado_por: str | None = None
        self.crescente = True
        self._titulos: dict[str, tk.Label] = {}
        self.marcada: str | None = None
        self._linhas: list[Linha] = []
        self._dados: list[dict] = []

        cabeca = tk.Frame(self, bg=SURFACE_ALT, height=ALTURA_CABECALHO)
        cabeca.pack(fill="x")
        cabeca.pack_propagate(False)
        tk.Frame(cabeca, bg=SURFACE_ALT, width=3).pack(side="left", fill="y")
        self._caixas_cabeca: dict[str, tk.Frame] = {}
        for coluna in colunas:
            caixa = tk.Frame(cabeca, bg=SURFACE_ALT, width=coluna.largura)
            caixa.pack_propagate(False)
            caixa.pack(side="left", fill="y", padx=(E3, 0))
            self._caixas_cabeca[coluna.chave] = caixa
            titulo = tk.Label(caixa, text=coluna.titulo.upper(), bg=SURFACE_ALT,
                              fg=INK_3, font=ETIQUETA,
                              anchor="e" if coluna.fim else "w")
            titulo.pack(fill="both", expand=True)
            self._titulos[coluna.chave] = titulo
            if self._ao_ordenar is not None and coluna.ordenavel and coluna.titulo:
                self._tornar_ordenavel(caixa, titulo, coluna.chave)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        self.corpo = tk.Frame(self, bg=SURFACE)
        self.corpo.pack(fill="both", expand=True)

        self._larguras: dict[str, int] = {}
        self.bind("<Configure>", self._repartir)

    # -- ordenação -------------------------------------------------------- #

    def _tornar_ordenavel(self, caixa: tk.Frame, titulo: tk.Label,
                          chave: str) -> None:
        for widget in (caixa, titulo):
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", lambda _e, c=chave: self.ordenar_por(c))
            widget.bind("<Enter>", lambda _e, t=titulo: t.configure(fg=INK))
            widget.bind("<Leave>", lambda _e, t=titulo, c=chave: t.configure(
                fg=INK if self.ordenado_por == c else INK_3))

    def ordenar_por(self, chave: str) -> None:
        """Primeiro clique ordena crescente; o seguinte inverte.

        A seta no cabeçalho diz qual é o sentido — sem ela, "clique de novo
        para inverter" é regra que só quem escreveu conhece.
        """
        if self.ordenado_por == chave:
            self.crescente = not self.crescente
        else:
            self.ordenado_por, self.crescente = chave, True
        self._marcar_ordenacao()
        if self._ao_ordenar is not None:
            self._ao_ordenar(chave, self.crescente)

    def _marcar_ordenacao(self) -> None:
        for coluna in self.colunas:
            titulo = self._titulos.get(coluna.chave)
            if titulo is None:
                continue
            nome = coluna.titulo.upper()
            if coluna.chave == self.ordenado_por:
                titulo.configure(text=f"{nome} {'▲' if self.crescente else '▼'}",
                                 fg=INK)
            else:
                titulo.configure(text=nome, fg=INK_3)

    # -- largura das colunas --------------------------------------------- #

    def _repartir(self, evento=None) -> None:
        """Divide a largura disponível entre as colunas, na razão do peso.

        Chamado a cada mudança de tamanho da tabela. O cálculo é o mesmo nos
        dois sentidos: sobrando espaço, quem tem peso cresce; faltando, quem
        tem peso encolhe — até o piso da coluna, nunca além.
        """
        largura = evento.width if evento is not None else self.winfo_width()
        if largura <= 1:
            return
        # 3 da faixa da esquerda, mais o respiro antes de cada coluna.
        disponivel = largura - 3 - E3 * len(self.colunas)
        base = sum(c.largura for c in self.colunas)
        pesos = sum(c.peso for c in self.colunas)
        folga = disponivel - base

        larguras: dict[str, int] = {}
        for coluna in self.colunas:
            parcela = round(folga * coluna.peso / pesos) if pesos else 0
            larguras[coluna.chave] = max(coluna.minimo, coluna.largura + parcela)
        if larguras == self._larguras:
            return
        self._larguras = larguras
        for chave, valor in larguras.items():
            caixa = self._caixas_cabeca.get(chave)
            if caixa is not None:
                caixa.configure(width=valor)
            for linha in self._linhas:
                alvo = linha.caixas.get(chave)
                if alvo is not None:
                    alvo.configure(width=valor)

    def _nova_linha(self) -> Linha:
        linha = Linha(self.corpo, self.colunas, ao_clicar=self._marcar,
                      ao_abrir=lambda l: self._ao_abrir(l.identidade),
                      ao_agir=lambda l, n: self._ao_agir(l.identidade, n))
        # Linha nascida depois do primeiro cálculo já entra na medida certa.
        for chave, valor in self._larguras.items():
            caixa = linha.caixas.get(chave)
            if caixa is not None:
                caixa.configure(width=valor)
        self._linhas.append(linha)
        return linha

    def _marcar(self, linha: Linha) -> None:
        self.marcada = None if self.marcada == linha.identidade else linha.identidade
        self.mostrar(self._dados)
        self._ao_selecionar(self.marcada)

    def mostrar(self, dados: list[dict]) -> None:
        """Repõe o conteúdo. Cria linha só quando faltar."""
        self._dados = dados
        if self.marcada and not any(d.get("id") == self.marcada for d in dados):
            self.marcada = None
        for indice, item in enumerate(dados[:self.altura_maxima * 6]):
            if indice >= len(self._linhas):
                self._nova_linha()
            linha = self._linhas[indice]
            linha.mostrar(item, listrada=indice % 2 == 1,
                          marcada=item.get("id") == self.marcada)
            if not linha.winfo_manager():
                linha.pack(fill="x")
            tk.Frame(linha, bg=BORDER, height=1).place(relx=0, rely=1.0, relwidth=1,
                                                       anchor="sw")
        for sobrando in self._linhas[len(dados):]:
            sobrando.pack_forget()


def vazio(pai: tk.Widget, simbolo: str, titulo: str, texto: str,
          acao: tuple[str, Callable[[], None]] | None = None) -> tk.Frame:
    """Estado vazio: uma lista sem itens precisa dizer o que fazer a seguir."""
    caixa = tk.Frame(pai, bg=SURFACE, padx=E5, pady=E6)
    tk.Label(caixa, text=simbolo, font=(FAMILIA, 30), fg=BORDER_FORTE, bg=SURFACE).pack()
    tk.Label(caixa, text=titulo, font=CORPO_FORTE, fg=INK_2, bg=SURFACE).pack(pady=(E2, 2))
    tk.Label(caixa, text=texto, font=PEQUENO, fg=INK_3, bg=SURFACE,
             justify="center", wraplength=px(380)).pack()
    if acao:
        ttk.Button(caixa, text=acao[0], style="Primaria.TButton",
                   command=acao[1]).pack(pady=(E4, 0))
    return caixa


def caixa_texto(pai: tk.Widget, *, altura: int = 4, fonte=None) -> tk.Text:
    """Campo de várias linhas com a mesma moldura dos ttk.Entry."""
    return tk.Text(
        pai, height=altura, font=fonte or CORPO, relief="flat", bd=0,
        bg=SURFACE, fg=INK, highlightbackground=BORDER_FORTE,
        highlightcolor=PRIMARIA, highlightthickness=1,
        padx=E2, pady=E2, wrap="word", insertbackground=INK,
        selectbackground=PRIMARIA_CLARA, selectforeground=INK,
    )


# --------------------------------------------------------------------------- #
# Listas com filtro
# --------------------------------------------------------------------------- #

LIMITE_LISTA = 300  # quantas opções a lista mostra de uma vez


def filtrar(valores: list[str], procurado: str, limite: int = LIMITE_LISTA) -> list[str]:
    """As opções que combinam com o que foi digitado, melhores primeiro.

    Função pura, separada do widget de propósito: é a regra que decide o que o
    usuário vê, e testá-la não deve depender de evento de teclado do Tk.

    O limite existe para a lista abrir rápido com 645 municípios; ele corta o
    que é exibido, nunca o que pode ser digitado.
    """
    procurado = (procurado or "").strip().upper()
    if not procurado:
        return valores[:limite]
    # Quem começa com o que foi digitado vem primeiro: procurando "SANTO",
    # SANTO ANDRE deve aparecer antes de ESPIRITO SANTO DO PINHAL.
    comeca = [i for i in valores if i.upper().startswith(procurado)]
    contem = [i for i in valores if procurado in i.upper() and i not in comeca]
    return (comeca + contem)[:limite]


def autocompletar(combo: ttk.Combobox, valores: Callable[[], list[str]]) -> None:
    """Deixa a lista filtrar conforme se digita.

    Uma lista de 645 municípios não se navega arrastando a barra. Aqui o texto
    digitado filtra as opções, e a lista completa volta quando o campo esvazia.

    ``valores`` é chamada a cada tecla porque a lista muda: trocar a UF troca os
    municípios, e uma cópia guardada aqui ficaria velha.

    O estado fica ``normal``, nunca ``readonly``: em ttk, ``readonly`` bloqueia
    o teclado, que é exatamente o que se quer aqui.
    """
    ignorar = {"Up", "Down", "Return", "Tab", "Escape", "Left", "Right",
               "Shift_L", "Shift_R", "Control_L", "Control_R"}

    def ao_digitar(evento) -> None:
        if evento.keysym in ignorar:
            return
        combo["values"] = filtrar(valores(), combo.get())

    combo.configure(state="normal")
    combo.bind("<KeyRelease>", ao_digitar, add="+")


def combina(doc_texto: str, procurado: str) -> bool:
    """A linha da tabela atende à busca? Compara sem acento nenhum no caminho.

    Pura, como ``filtrar``: a busca da tabela de notas se testa sem abrir Tk.
    """
    procurado = (procurado or "").strip().upper()
    if not procurado:
        return True
    alvo = doc_texto.upper()
    # Cada palavra digitada precisa aparecer em algum lugar da linha; assim
    # "mundial 250" acha a nota da Mundial de R$ 250,00 sem depender da ordem.
    return all(parte in alvo for parte in procurado.split())


# --------------------------------------------------------------------------- #
# Carregando
# --------------------------------------------------------------------------- #

class Girador(tk.Canvas):
    """Indicador de carregando, do tamanho de uma letra, desenhado à mão.

    Desenhado em vez de escrito com caractere de fonte porque os símbolos de
    giro (braille, blocos) saem como quadradinho em máquina sem a fonte certa —
    e o indicador de "estou trabalhando" é justamente o que não pode falhar.
    """

    def __init__(self, pai: tk.Widget, *, fundo: str | None = None,
                 cor: str | None = None, lado: int = 16) -> None:
        super().__init__(pai, width=lado, height=lado, bg=fundo or SURFACE,
                         highlightthickness=0, bd=0)
        self._lado = lado
        self._cor = cor or PRIMARIA
        self._angulo = 0
        self._tarefa: str | None = None
        # Trilho por baixo: sem ele o arco solto some no fundo e parece
        # sujeira na tela em vez de algo girando.
        self.create_oval(2, 2, lado - 2, lado - 2, outline=BORDER_FORTE, width=2)
        self._arco = self.create_arc(
            2, 2, lado - 2, lado - 2, start=0, extent=95, style="arc",
            outline=self._cor, width=3,
        )
        # Sem isto o `after` pendente dispara depois do widget destruído e o Tk
        # reclama de "invalid command name" na saída do programa.
        self.bind("<Destroy>", lambda _e: self.parar())

    def girar(self) -> None:
        if not self.winfo_exists():
            return
        self._angulo = (self._angulo - 24) % 360
        self.itemconfigure(self._arco, start=self._angulo)
        self._tarefa = self.after(50, self.girar)

    def parar(self) -> None:
        if self._tarefa:
            try:
                self.after_cancel(self._tarefa)
            except tk.TclError:
                pass
            self._tarefa = None


class Marcador(tk.Frame):
    """Caixa de marcar desenhada, para combinar com o resto da tela.

    O tema nativo do Windows pinta o quadradinho com a cor do sistema e
    ignora o que se peça; o tema "clam" aceita cor, mas desenha o sinal de
    marcado como um xis apertado, que num fundo escuro parece erro em vez de
    escolha. Como tudo mais aqui já é desenhado à mão, esta também é — e aí o
    ✓ é um ✓, no roxo da marca.
    """

    LADO = 17

    def __init__(self, pai: tk.Widget, texto: str, *,
                 variavel: tk.BooleanVar | None = None,
                 fundo: str | None = None, cor: str | None = None) -> None:
        fundo = fundo or SURFACE
        super().__init__(pai, bg=fundo, cursor="hand2")
        self.variavel = (variavel if variavel is not None
                         else tk.BooleanVar(value=True))
        lado = px(self.LADO)
        self.tela = tk.Canvas(self, width=lado, height=lado, bg=fundo,
                              highlightthickness=0, bd=0, cursor="hand2")
        self.tela.pack(side="left", padx=(0, E2))
        self.rotulo = tk.Label(self, text=texto, bg=fundo, fg=cor or INK,
                               font=CORPO, cursor="hand2")
        self.rotulo.pack(side="left")
        # O rótulo também alterna: mirar num quadrado de 17px é trabalho, e
        # em qualquer outro programa clicar no texto funciona.
        for widget in (self, self.tela, self.rotulo):
            widget.bind("<Button-1>", self._alternar)
        self.variavel.trace_add("write", lambda *_: self._pintar())
        self._pintar()

    def _alternar(self, _evento=None) -> None:
        self.variavel.set(not self.variavel.get())

    def get(self) -> bool:
        return bool(self.variavel.get())

    def _pintar(self) -> None:
        if not self.tela.winfo_exists():
            return
        lado = px(self.LADO)
        self.tela.delete("all")
        marcado = bool(self.variavel.get())
        retangulo_redondo(
            self.tela, 1, 1, lado - 1, lado - 1, px(5),
            fill=PRIMARIA if marcado else SURFACE_ALT,
            outline=PRIMARIA if marcado else BORDER_FORTE, width=1)
        if marcado:
            self.tela.create_line(
                lado * 0.27, lado * 0.53, lado * 0.43, lado * 0.69,
                lado * 0.74, lado * 0.31, fill="white",
                width=max(2, px(2)), capstyle="round", joinstyle="round")


class CampoBusca(tk.Frame):
    """Campo com lupa que avisa a cada tecla — a busca em tempo real da tabela.

    O aviso sai por ``after``, não a cada tecla: redesenhar a lista a cada
    letra digitada trava a digitação. 300 ms depois da última tecla é rápido o
    bastante para parecer instantâneo e lento o bastante para digitar uma
    palavra inteira antes de a tabela se mexer.
    """

    ESPERA = 300

    def __init__(self, pai: tk.Widget, aviso: Callable[[str], None], *,
                 dica: str = "Buscar…", largura: int = 26,
                 fundo: str | None = None) -> None:
        super().__init__(pai, bg=fundo or BG)
        self._aviso = aviso
        self._pendente: str | None = None
        self.variavel = tk.StringVar()

        caixa = Redondo(self, raio=10, fundo=SURFACE, borda=BORDER_FORTE,
                        fundo_externo=fundo or BG, padx=E2, pady=4)
        caixa.pack(fill="x")
        moldura = caixa.interior
        tk.Label(moldura, text="⌕", font=(FAMILIA, 13), fg=INK_3, bg=SURFACE,
                 padx=E1).pack(side="left")
        self.entrada = tk.Entry(
            moldura, textvariable=self.variavel, font=CORPO, width=largura,
            relief="flat", bd=0, bg=SURFACE, fg=INK, insertbackground=INK,
            selectbackground=PRIMARIA_CLARA, selectforeground=INK,
        )
        self.entrada.pack(side="left", fill="x", expand=True, ipady=5)
        # A moldura acende ao receber o cursor: em campo desenhado não há
        # `focus ring` do sistema para fazer isso sozinho.
        self.entrada.bind("<FocusIn>", lambda _e: caixa.pintar(borda=PRIMARIA))
        self.entrada.bind("<FocusOut>", lambda _e: caixa.pintar(borda=BORDER_FORTE))
        self._limpar = tk.Label(moldura, text="✕", font=MICRO, fg=INK_3, bg=SURFACE,
                                padx=E2, cursor="hand2")
        self._limpar.bind("<Button-1>", lambda _e: self.limpar())

        self._dica = tk.Label(moldura, text=dica, font=CORPO, fg=INK_3, bg=SURFACE)
        self._dica.place(in_=self.entrada, x=2, rely=0.5, anchor="w")
        self.variavel.trace_add("write", self._mudou)
        self.entrada.bind("<Escape>", lambda _e: self.limpar())

    def _mudou(self, *_args) -> None:
        texto = self.variavel.get()
        if texto:
            self._dica.place_forget()
            self._limpar.pack(side="left")
        else:
            self._dica.place(in_=self.entrada, x=2, rely=0.5, anchor="w")
            self._limpar.pack_forget()
        if self._pendente:
            try:
                self.after_cancel(self._pendente)
            except tk.TclError:
                pass
        self._pendente = self.after(self.ESPERA, lambda: self._aviso(self.variavel.get()))

    def limpar(self) -> None:
        self.variavel.set("")
        self.entrada.focus_set()


# --------------------------------------------------------------------------- #
# Notificações flutuantes
# --------------------------------------------------------------------------- #

class Notificacoes:
    """Avisos que aparecem no canto e somem sozinhos.

    Existem para tirar do caminho as caixas de diálogo de "deu certo" e "olha
    isto": elas param o programa e exigem um clique para dizer algo que já
    aconteceu. O modal fica reservado para o que de fato precisa de resposta —
    confirmar uma emissão, apagar um histórico.

    Cada aviso é uma janela sem moldura encostada no canto inferior direito da
    janela principal, empilhando para cima. Nenhuma delas pede o foco: digitar
    continua indo para onde estava.
    """

    LARGURA = 340
    FOLGA = 16
    ESPACO = 10

    def __init__(self, raiz: tk.Tk) -> None:
        self.raiz = raiz
        self._abertas: list[tk.Toplevel] = []
        # A janela principal arrastada leva os avisos junto; sem isto eles
        # ficariam parados no meio da tela, soltos de tudo.
        raiz.bind("<Configure>", lambda _e: self._reposicionar(), add="+")
        # E minimizada, leva os avisos junto também — o que transient faria,
        # se transient não impedisse os avisos de aparecer.
        raiz.bind("<Unmap>", lambda e: self._acompanhar_janela(e, False), add="+")
        raiz.bind("<Map>", lambda e: self._acompanhar_janela(e, True), add="+")

    def _acompanhar_janela(self, evento, visivel: bool) -> None:
        """Esconde e mostra os avisos junto com a janela principal."""
        # Só o evento da própria janela: widget filho que aparece ou some
        # dispara o mesmo evento e esconderia os avisos sem motivo.
        if evento.widget is not self.raiz:
            return
        for janela in list(self._abertas):
            try:
                if visivel:
                    janela.deiconify()
                else:
                    janela.withdraw()
            except tk.TclError:
                pass
        if visivel:
            self._reposicionar()

    # -- API ------------------------------------------------------------- #

    # Quanto mais grave, mais tempo na tela: um "deu certo" se lê de relance,
    # um erro precisa ser lido inteiro antes de sumir. `setdefault` e não
    # `segundos=N` fixo — senão quem passa o tempo na chamada colide com ele.
    def info(self, titulo: str, texto: str = "", **kwargs) -> None:
        self.mostrar(titulo, texto, tom="info", **kwargs)

    def sucesso(self, titulo: str, texto: str = "", **kwargs) -> None:
        self.mostrar(titulo, texto, tom="sucesso", **kwargs)

    def alerta(self, titulo: str, texto: str = "", **kwargs) -> None:
        kwargs.setdefault("segundos", 7)
        self.mostrar(titulo, texto, tom="alerta", **kwargs)

    def erro(self, titulo: str, texto: str = "", **kwargs) -> None:
        kwargs.setdefault("segundos", 9)
        self.mostrar(titulo, texto, tom="erro", **kwargs)

    def trabalhando(self, titulo: str, texto: str = "") -> tk.Toplevel | None:
        """Aviso que dura o que a tarefa durar, com um girador no lugar do selo.

        Sem prazo de propósito: quem abriu é quem fecha. Um aviso que some
        sozinho depois de alguns segundos deixaria a tela muda no meio de uma
        transmissão — e é exatamente aí que a pessoa quer ver alguma coisa se
        mexendo.
        """
        if not self.raiz.winfo_exists():
            return None
        try:
            janela = self._desenhar(titulo, texto, "info", girando=True)
        except tk.TclError:
            return None
        self._abertas.append(janela)
        self._reposicionar()
        return janela

    def mostrar(self, titulo: str, texto: str = "", *, tom: str = "info",
                segundos: float = 4.5) -> tk.Toplevel | None:
        if not self.raiz.winfo_exists():
            return None
        try:
            janela = self._desenhar(titulo, texto, tom)
        except tk.TclError:
            # Sem canto onde aparecer (janela fechando, tela sem gerenciador),
            # o aviso simplesmente não sai. Não é motivo para derrubar a ação
            # que o disparou.
            return None
        self._abertas.append(janela)
        self._reposicionar()
        janela.after(int(segundos * 1000), lambda: self.fechar(janela))
        return janela

    def fechar(self, janela: tk.Toplevel) -> None:
        if janela in self._abertas:
            self._abertas.remove(janela)
        try:
            janela.destroy()
        except tk.TclError:
            pass
        self._reposicionar()

    def limpar(self) -> None:
        for janela in list(self._abertas):
            self.fechar(janela)

    # -- Desenho --------------------------------------------------------- #

    def _desenhar(self, titulo: str, texto: str, tom: str,
                  *, girando: bool = False) -> tk.Toplevel:
        cor, fundo = cores_do_tom(tom)
        janela = tk.Toplevel(self.raiz)
        janela.overrideredirect(True)          # sem barra de título
        # Sem transient de propósito: no Windows, uma janela que é transient E
        # overrideredirect simplesmente não é desenhada — fica mapeada, no
        # lugar certo, com alfa 0.97, e invisível. Foi assim que os avisos
        # sumiram na primeira montagem. O overrideredirect já a tira da barra
        # de tarefas, que era o motivo de usar transient.
        janela.configure(bg=BORDER)
        try:
            janela.attributes("-topmost", True)
            janela.attributes("-alpha", 0.0)   # entra desbotado e acende
        except tk.TclError:
            pass

        corpo = tk.Frame(janela, bg=SURFACE)
        corpo.pack(padx=1, pady=1, fill="both", expand=True)
        tk.Frame(corpo, bg=cor, width=4).pack(side="left", fill="y")

        dentro = tk.Frame(corpo, bg=SURFACE, padx=E3, pady=E3)
        dentro.pack(side="left", fill="both", expand=True)
        topo = tk.Frame(dentro, bg=SURFACE)
        topo.pack(fill="x")
        if girando:
            girador = Girador(topo, fundo=SURFACE, cor=cor, lado=16)
            girador.pack(side="left")
            girador.girar()
        else:
            marca = {"sucesso": "✓", "erro": "!", "alerta": "!",
                     "info": "i"}.get(tom, "i")
            pilula(topo, marca, cor=cor, fundo_pilula=fundo,
                   fundo=SURFACE).pack(side="left")
        tk.Label(topo, text=titulo, font=CORPO_FORTE, fg=INK, bg=SURFACE,
                 anchor="w", justify="left",
                 wraplength=self.LARGURA - 90).pack(side="left", padx=(E2, 0))
        tk.Label(topo, text="✕", font=MICRO, fg=INK_3, bg=SURFACE,
                 cursor="hand2").pack(side="right")
        if texto:
            tk.Label(dentro, text=texto, font=PEQUENO, fg=INK_2, bg=SURFACE,
                     anchor="w", justify="left",
                     wraplength=self.LARGURA - 44).pack(anchor="w", pady=(E1, 0))

        # Clicar em qualquer parte fecha — inclusive no ✕, que é só o desenho.
        for widget in (janela, corpo, dentro, topo, *topo.winfo_children(),
                       *dentro.winfo_children()):
            widget.bind("<Button-1>", lambda _e, j=janela: self.fechar(j))
        janela.update_idletasks()
        janela.lift()
        self._acender(janela, 0.0)
        return janela

    def _acender(self, janela: tk.Toplevel, alfa: float) -> None:
        if not janela.winfo_exists():
            return
        try:
            janela.attributes("-alpha", min(alfa, 1.0))
        except tk.TclError:
            return
        if alfa < 1.0:
            janela.after(16, lambda: self._acender(janela, alfa + 0.15))

    def _reposicionar(self) -> None:
        """Empilha os avisos a partir do canto inferior direito da janela."""
        # Sai cedo no caso comum: isto roda a cada <Configure> da janela, ou
        # seja, dezenas de vezes por segundo enquanto alguém a redimensiona.
        if not self._abertas or not self.raiz.winfo_exists():
            return
        # Janela ainda não medida (largura 1) mandaria os avisos para o canto
        # superior esquerdo da tela. Espera o Tk terminar de montar.
        if self.raiz.winfo_width() <= 1:
            self.raiz.after_idle(self._reposicionar)
            return
        try:
            direita = self.raiz.winfo_rootx() + self.raiz.winfo_width()
            base = self.raiz.winfo_rooty() + self.raiz.winfo_height()
        except tk.TclError:
            return
        deslocamento = self.FOLGA
        for janela in reversed(self._abertas):     # o mais novo fica embaixo
            if not janela.winfo_exists():
                continue
            try:
                janela.update_idletasks()
                altura = janela.winfo_reqheight()
                x = direita - self.LARGURA - self.FOLGA
                y = base - deslocamento - altura
                janela.geometry(f"{self.LARGURA}x{altura}+{int(x)}+{int(y)}")
                deslocamento += altura + self.ESPACO
            except tk.TclError:
                continue


# --------------------------------------------------------------------------- #
# Botões com estado de trabalho
# --------------------------------------------------------------------------- #

class BotaoOcupado:
    """Guarda o texto de um botão para devolvê-lo quando o trabalho termina.

    Sem isto, cada chamada de rede repetia o mesmo par de linhas — e bastava um
    caminho de erro esquecer de restaurar para o botão ficar "Emitindo…" para
    sempre, sem que ninguém conseguisse clicar de novo.
    """

    def __init__(self, botao: ttk.Button) -> None:
        self.botao = botao
        self._texto = str(botao.cget("text"))

    def trabalhando(self, texto: str) -> None:
        try:
            self.botao.configure(text=texto, state="disabled")
        except tk.TclError:
            pass

    def pronto(self) -> None:
        try:
            self.botao.configure(text=self._texto, state="normal")
        except tk.TclError:
            pass


def ocupar(botao: ttk.Button, texto: str) -> BotaoOcupado:
    """Põe o botão em estado de trabalho e devolve quem sabe desfazer isso."""
    estado = BotaoOcupado(botao)
    estado.trabalhando(texto)
    return estado

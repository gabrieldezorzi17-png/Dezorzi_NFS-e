"""A marca Dezorzi® dentro do programa: cores, monograma e assinatura.

O monograma é **desenhado por fórmula**, não carregado de um arquivo de imagem.
Dois motivos práticos: o programa continua sendo só biblioteca padrão e arquivos
.py soltos, e o desenho sai nítido em qualquer tamanho — o ícone de 32 px da
barra de tarefas e o selo de 96 px da tela de entrada são renderizados cada um
no seu tamanho real, em vez de esticar uma imagem pequena.

Se existir ``assets/logo.png``, ele tem prioridade sobre o desenho. É assim que
se troca o traçado daqui pelo arquivo oficial da marca, sem mexer em código.

As cores da marca vivem só aqui e são usadas com parcimônia: o programa continua
com a paleta dele (``ui.py``), e o verde-petróleo e o dourado aparecem no
monograma, na assinatura e em um filete. Marca discreta é marca que não briga
com a informação da tela.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

import paths

# --------------------------------------------------------------------------- #
# Identidade
# --------------------------------------------------------------------------- #
NOME = "Dezorzi"
REGISTRADA = "®"
ASSINATURA = f"{NOME}{REGISTRADA}"

PETROLEO = "#245f66"        # verde-petróleo do monograma
PETROLEO_CLARO = "#2f7c85"
OURO = "#c3a059"            # dourado dos vazados
OURO_CLARO = "#d8bd85"
FUNDO = "#ffffff"           # o miolo da marca é branco, não vazado

# O miolo branco é parte da marca, não transparência: sobre a barra lateral
# escura, um miolo vazado deixaria o D em azul-marinho e a leitura inverteria.
# Como placa branca, a marca se aplica sobre qualquer fundo sem se desfigurar.

ARQUIVO = paths.ASSETS_DIR / "logo.png"

# --------------------------------------------------------------------------- #
# Geometria do monograma
# --------------------------------------------------------------------------- #
# Tudo é descrito numa caixa de 129 x 100 unidades e depois escalado para o
# tamanho pedido. Manter a geometria em unidades (e não em pixels) é o que
# permite desenhar o mesmo símbolo com 16 px e com 300 px sem serrilhar.
U_LARGURA = 129.0
U_ALTURA = 100.0
_BORDA = 12.0               # espessura da moldura e dos traços

# Barriga do D: semicircunferência que encosta na moldura de cima e de baixo,
# de modo que a lateral esquerda da moldura faz as vezes de haste da letra.
_D_CENTRO_X, _D_RAIO_X, _D_RAIO_Y = 34.0, 34.0, 50.0
_D_VAZIO_X, _D_VAZIO_Y = 22.0, 38.0

# Diagonal do Z: as barras de cima e de baixo são a própria moldura; só a
# diagonal é desenhada. x0(y) é a borda esquerda da diagonal na altura y.
_Z_LARGURA = 26.0                       # espessura medida na horizontal
_Z_TOPO_X = U_LARGURA - _Z_LARGURA      # começa colada na quina de cima à direita
_Z_INCLINACAO = 0.55        # quanto anda para a esquerda a cada unidade descida

# Folga branca entre a diagonal e o D. Sem ela as duas letras se encostam na
# altura do meio e o símbolo vira uma mancha só.
_FOLGA = 4.5

# Cunha dourada sob a barra de cima, encaixada na curva do D.
_CUNHA = ((58.0, _BORDA), (78.0, _BORDA), (58.0, 42.0))


def _dentro_da_moldura(x: float, y: float) -> bool:
    return not (_BORDA <= x <= U_LARGURA - _BORDA and _BORDA <= y <= U_ALTURA - _BORDA)


def _dentro_do_d(x: float, y: float) -> bool:
    """Traço do D: a área da barriga menos o vazado interno."""
    if x <= _D_CENTRO_X:
        corpo = 0.0 <= y <= U_ALTURA
    else:
        corpo = ((x - _D_CENTRO_X) / _D_RAIO_X) ** 2 + ((y - 50.0) / _D_RAIO_Y) ** 2 <= 1.0
    if not corpo:
        return False
    if _BORDA <= x <= _D_CENTRO_X and _BORDA <= y <= U_ALTURA - _BORDA:
        return False
    if x > _D_CENTRO_X:
        vazio = ((x - _D_CENTRO_X) / _D_VAZIO_X) ** 2 + ((y - 50.0) / _D_VAZIO_Y) ** 2 <= 1.0
        if vazio:
            return False
    return True


def _borda_da_diagonal(y: float) -> float:
    return _Z_TOPO_X - (y - _BORDA) * _Z_INCLINACAO


def _dentro_da_diagonal(x: float, y: float) -> bool:
    if not _BORDA <= y <= U_ALTURA - _BORDA:
        return False
    inicio = _borda_da_diagonal(y)
    return inicio <= x <= inicio + _Z_LARGURA


def _na_folga(x: float, y: float) -> bool:
    """Faixa branca em volta da diagonal, que abre caminho por cima do D.

    Vale só na altura do miolo: nas barras de cima e de baixo a diagonal tem de
    emendar com a moldura, e a folga ali abriria um talho branco no meio delas.
    """
    if not _BORDA <= y <= U_ALTURA - _BORDA:
        return False
    inicio = _borda_da_diagonal(y)
    return inicio - _FOLGA <= x <= inicio + _Z_LARGURA + _FOLGA


def _no_triangulo(x: float, y: float, pontos) -> bool:
    (ax, ay), (bx, by), (cx, cy) = pontos
    d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if d == 0:
        return False
    u = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / d
    v = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / d
    return u >= 0 and v >= 0 and u + v <= 1


def _no_ouro(x: float, y: float) -> bool:
    """Os dois vazados dourados: o grande, embaixo à direita, e a cunha do topo.

    O grande avança até a borda direita de propósito — é ele que interrompe a
    moldura naquele trecho, como no logotipo.
    """
    if _BORDA <= y <= U_ALTURA - _BORDA:
        if x >= _borda_da_diagonal(y) + _Z_LARGURA:
            return True
    return _no_triangulo(x, y, _CUNHA)


def cor_em(x: float, y: float) -> str | None:
    """Cor do símbolo no ponto (x, y), ou None onde ele é vazado.

    A ordem das perguntas é a ordem em que um desenhista pintaria: moldura,
    dourado por cima (é ele que corta a moldura à direita), e o traçado do
    D e do Z por último, que ficam acima de tudo.
    """
    if not (0.0 <= x <= U_LARGURA and 0.0 <= y <= U_ALTURA):
        return None
    # As barras de cima e de baixo e a lateral esquerda são petróleo em toda a
    # extensão — decidir isso de saída poupa um terço do desenho.
    if y <= _BORDA or y >= U_ALTURA - _BORDA or x <= _BORDA:
        return PETROLEO
    if _dentro_da_diagonal(x, y):
        return PETROLEO
    if _dentro_do_d(x, y):
        # A folga vale só contra o D: onde a diagonal encontra as barras de
        # cima e de baixo elas têm de emendar sem risco branco no meio.
        return FUNDO if _na_folga(x, y) else PETROLEO
    if _no_ouro(x, y):
        return OURO
    if _dentro_da_moldura(x, y):
        return PETROLEO
    return FUNDO


# --------------------------------------------------------------------------- #
# Rasterização
# --------------------------------------------------------------------------- #
_AMOSTRAS = 3   # 3x3 pontos por pixel: suaviza a curva do D e a diagonal


def _rgb(cor: str) -> tuple[int, int, int]:
    return int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)


# A marca tem três cores. Converter hexadecimal nove vezes por pixel era o
# grosso do tempo de desenho; aqui a conversão já vem pronta.
_TINTAS = {cor: _rgb(cor) for cor in (PETROLEO, OURO, FUNDO)}


_pixels_cache: dict[tuple[int, int], list[list[tuple[int, int, int]]]] = {}


def amostrar(largura: int, altura: int) -> list[list[tuple[int, int, int]]]:
    """A marca em pixels, com as bordas suavizadas.

    Cada pixel é a média de 3x3 pontos. Como toda a caixa tem cor — o miolo é
    branco, não vazio — a média já entrega o degradê certo na curva do D e nas
    beiradas da diagonal, sem precisar saber sobre que fundo a marca vai cair.
    """
    if (largura, altura) in _pixels_cache:
        return _pixels_cache[(largura, altura)]

    passo_x, passo_y = U_LARGURA / largura, U_ALTURA / altura
    sub = 1.0 / (_AMOSTRAS + 1)
    total = _AMOSTRAS * _AMOSTRAS
    tintas, branco, ponto = _TINTAS, _TINTAS[FUNDO], cor_em
    linhas: list[list[tuple[int, int, int]]] = []
    for py in range(altura):
        ys = [(py + j * sub) * passo_y for j in range(1, _AMOSTRAS + 1)]
        linha: list[tuple[int, int, int]] = []
        for px in range(largura):
            r = g = b = 0
            for i in range(1, _AMOSTRAS + 1):
                x = (px + i * sub) * passo_x
                for y in ys:
                    pr, pg, pb = tintas.get(ponto(x, y), branco)
                    r += pr
                    g += pg
                    b += pb
            linha.append((r // total, g // total, b // total))
        linhas.append(linha)
    _pixels_cache[(largura, altura)] = linhas
    return linhas


def imagem(altura: int, pai: tk.Misc | None = None) -> tk.PhotoImage:
    """O monograma como imagem do Tk, desenhado no tamanho exato pedido.

    Desenhar no tamanho final, em vez de esticar uma imagem pronta, é o que
    mantém a curva do D limpa tanto no selo de 96 px quanto no de 22 px.

    A imagem em si não é guardada de propósito: uma ``PhotoImage`` pertence ao
    interpretador Tk que a criou, e reaproveitar uma de outra janela dá
    ``image "pyimageN" doesn't exist``. O que se guarda são os pixels
    calculados — a parte cara —, e montar a imagem a partir deles é rápido.
    """
    do_arquivo = _do_arquivo(altura, pai)
    if do_arquivo is not None:
        return do_arquivo

    largura = max(1, round(altura * U_LARGURA / U_ALTURA))
    foto = tk.PhotoImage(master=pai, width=largura, height=altura)
    # Uma chamada por linha: montar a linha inteira como texto e entregar de uma
    # vez é ordens de grandeza mais rápido que pintar pixel a pixel.
    for py, linha in enumerate(amostrar(largura, altura)):
        foto.put("{" + " ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in linha) + "}",
                 to=(0, py))
    return foto


def _do_arquivo(altura: int, pai: tk.Misc | None = None) -> tk.PhotoImage | None:
    """Usa ``assets/logo.png`` quando ele existe, reduzido para caber na altura.

    O Tk só reduz por divisão inteira, então o resultado é aproximado — o
    arquivo oficial deve ser exportado grande (uns 600 px de altura) para que a
    redução caia bem nos tamanhos usados.
    """
    if not ARQUIVO.exists():
        return None
    try:
        original = tk.PhotoImage(master=pai, file=str(ARQUIVO))
    except tk.TclError:
        return None
    fator = max(1, round(original.height() / altura))
    return original.subsample(fator, fator) if fator > 1 else original


# --------------------------------------------------------------------------- #
# Arquivo PNG
def esquecer() -> None:
    """Descarta os pixels já calculados.

    Não há mais por onde trocar o logotipo pela tela — mas a suíte troca o
    `logo.png` entre um teste e outro, e sem limpar o cache o segundo teste
    mediria os pixels do primeiro.
    """
    _pixels_cache.clear()


# --------------------------------------------------------------------------- #
def png(altura: int = 512) -> bytes:
    """O monograma como arquivo PNG, escrito na mão.

    Serve para exportar a marca sem depender de nenhuma biblioteca de imagem —
    para o ícone do atalho, para um papel timbrado, para o que for.
    """
    import struct
    import zlib

    largura = max(1, round(altura * U_LARGURA / U_ALTURA))
    linhas = bytearray()
    for linha in amostrar(largura, altura):
        linhas.append(0)  # filtro "sem filtro" no começo de cada linha
        for r, g, b in linha:
            linhas.extend((r, g, b))

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))

    cabecalho = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", cabecalho)
            + bloco(b"IDAT", zlib.compress(bytes(linhas), 9))
            + bloco(b"IEND", b""))


def icone(lado: int = 56, pai: tk.Misc | None = None) -> tk.PhotoImage:
    """A marca centrada num quadrado, para o ícone da janela.

    O símbolo é mais largo que alto; num ícone quadrado ele precisa de folga em
    cima e embaixo, senão o Windows estica e entorta o desenho.
    """
    altura = max(1, round(lado * 0.62))
    largura = max(1, round(altura * U_LARGURA / U_ALTURA))
    foto = tk.PhotoImage(master=pai, width=lado, height=lado)
    foto.put(FUNDO, to=(0, 0, lado, lado))
    topo, esquerda = (lado - altura) // 2, (lado - largura) // 2
    for py, linha in enumerate(amostrar(largura, altura)):
        foto.put("{" + " ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in linha) + "}",
                 to=(esquerda, topo + py))
    return foto


# --------------------------------------------------------------------------- #
# Componentes de tela
# --------------------------------------------------------------------------- #
def selo(pai: tk.Widget, altura: int, fundo: str) -> tk.Label:
    """O monograma como etiqueta, pronto para empacotar."""
    imagem_ = imagem(altura, pai)
    etiqueta = tk.Label(pai, image=imagem_, bg=fundo, bd=0, highlightthickness=0)
    etiqueta.imagem = imagem_   # o Tk descarta a imagem se ninguém a segurar
    return etiqueta


def png_quadrado(lado: int) -> bytes:
    """A marca centrada num PNG quadrado, com o fundo branco preenchendo o resto."""
    import struct
    import zlib

    altura = max(1, round(lado * 0.62))
    largura = max(1, round(altura * U_LARGURA / U_ALTURA))
    topo, esquerda = (lado - altura) // 2, (lado - largura) // 2
    marca_ = amostrar(largura, altura)
    branco = _TINTAS[FUNDO]

    linhas = bytearray()
    for y in range(lado):
        linhas.append(0)
        dentro_y = topo <= y < topo + altura
        for x in range(lado):
            if dentro_y and esquerda <= x < esquerda + largura:
                r, g, b = marca_[y - topo][x - esquerda]
            else:
                r, g, b = branco
            linhas.extend((r, g, b))

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 2, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(bytes(linhas), 9))
            + bloco(b"IEND", b""))


def ico(lados: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)) -> bytes:
    """O ícone do Windows, com uma imagem para cada tamanho.

    Um .ico é um índice de imagens. Guardar vários tamanhos, cada um desenhado
    no seu, evita que o Windows encolha o de 256 para 16 e transforme o D e o Z
    numa mancha. As imagens vão em PNG, que o Windows aceita desde o Vista.
    """
    import struct

    imagens = [png_quadrado(lado) for lado in lados]
    cabecalho = struct.pack("<HHH", 0, 1, len(imagens))   # reservado, tipo 1 = ícone
    deslocamento = len(cabecalho) + 16 * len(imagens)
    indice = bytearray()
    for lado, dados in zip(lados, imagens):
        indice.extend(struct.pack(
            "<BBBBHHII",
            0 if lado >= 256 else lado,   # 0 quer dizer 256 no formato
            0 if lado >= 256 else lado,
            0, 0, 1, 24, len(dados), deslocamento,
        ))
        deslocamento += len(dados)
    return cabecalho + bytes(indice) + b"".join(imagens)


def salvar_ico(destino: Path | str) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(ico())
    return destino


def icone_do_windows(destino: Path | str) -> tuple[Path, str]:
    """O .ico do executável, do logotipo do usuário quando ele existe.

    Devolve (caminho, de_onde_veio) — "logotipo" ou "monograma".

    `ico()` desenha o monograma, e é o certo quando não há logotipo. Mas quem
    instalou o próprio PNG espera vê-lo no atalho da área de trabalho e na
    barra de tarefas, não só dentro do programa: o ícone é a marca no lugar
    onde ela mais aparece.

    Ler um PNG qualquer à mão — filtros, entrelaçamento, paleta — é trabalho
    demais para o ganho, então isto usa Pillow. E usa **só aqui**, na hora de
    compilar: o programa em si continua sem essa dependência, e sem Pillow
    instalado o ícone volta a ser o monograma em vez de a compilação falhar.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if ARQUIVO.exists():
        try:
            from PIL import Image
        except ImportError:
            pass
        else:
            with Image.open(ARQUIVO) as original:
                imagem = original.convert("RGBA")
                # Quadrado, com o logotipo centrado: ícone não-quadrado o
                # Windows estica, e a marca sai deformada no atalho.
                lado = max(imagem.size)
                tela = Image.new("RGBA", (lado, lado), (255, 255, 255, 0))
                tela.paste(imagem, ((lado - imagem.width) // 2,
                                    (lado - imagem.height) // 2), imagem)
                tela.save(destino, format="ICO",
                          sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
            return destino, "logotipo"
    salvar_ico(destino)
    return destino, "monograma"

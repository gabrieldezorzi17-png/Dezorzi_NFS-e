"""Prepara as duas variantes do logotipo a partir do arquivo original.

POR QUE DUAS
------------
MEDIDO pela fórmula de contraste das WCAG, com o arquivo que veio:

    metade grafite sobre a barra do tema escuro (#10141f)   2,14:1
    metade dourada sobre o branco do tema claro             2,02:1

Cada tema apaga uma das duas metades. A saída que as marcas sérias usam é ter
duas versões — a positiva e a negativa — em vez de uma placa branca por baixo,
que num programa de fundo escuro parece adesivo colado.

    logo.png                    a arte como veio: dourado e grafite
    logo-para-fundo-escuro.png  a mesma, com o grafite clareado para prata

O QUE ESTE ARQUIVO FAZ
----------------------
1. recorta a margem branca do original;
2. tira o fundo, com alfa de verdade — o recorte vem da distância até o
   branco, com um degrau que mata o ruído de compressão antes que ele vire
   uma névoa cinza dentro do losango;
3. grava em 672 px, que divide exato por 32, 42, 48, 56 e 84 — os tamanhos
   que o programa usa. O Tk só reduz por divisão inteira, e sobra vira
   serrilhado.

Rodar de novo só é preciso quando o arquivo da marca mudar.
"""
from pathlib import Path

from PIL import Image, ImageChops

import sys

ASSETS = Path(__file__).resolve().parents[1] / "assets"
LADO = 672
FOLGA = 0.015          # a ponta do losango não pode encostar na borda
RUIDO = 8              # abaixo disto é compressão, não desenho


def recortar(im: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Devolve (marca, alfa), já sem a margem e sem o fundo branco."""
    branco = Image.new("RGB", im.size, (255, 255, 255))
    distancia = ImageChops.difference(im, branco).convert("L")
    caixa = distancia.point(lambda v: 255 if v > 12 else 0).getbbox()
    marca = im.crop(caixa)
    # Degrau: some com o ruído e mantém a rampa de antisserrilhado da borda.
    alfa = distancia.crop(caixa).point(
        lambda v: 0 if v <= RUIDO else min(255, (v - RUIDO) * 14))
    return marca, alfa


def quadrar(marca: Image.Image, alfa: Image.Image) -> tuple[Image.Image, Image.Image]:
    lado = max(marca.size)
    folga = round(lado * FOLGA)
    tela = Image.new("RGB", (lado + 2 * folga, lado + 2 * folga), (255, 255, 255))
    mascara = Image.new("L", tela.size, 0)
    canto = ((tela.width - marca.width) // 2, (tela.height - marca.height) // 2)
    tela.paste(marca, canto)
    mascara.paste(alfa, canto)
    return tela, mascara


def clarear_o_grafite(pixel: tuple[int, int, int]) -> tuple[int, int, int]:
    """A metade grafite vira prata; a dourada não se toca.

    Cinza é o que tem pouca diferença entre os canais. O dourado tem muita —
    é o que separa as duas metades sem precisar saber onde uma acaba.
    """
    r, g, b = pixel
    if max(r, g, b) - min(r, g, b) >= 34 or r >= 190:
        return pixel
    # Mantém o degradê do original, subindo a faixa toda para o claro.
    claro = round(150 + r * 0.62)
    return (min(255, claro), min(255, claro + 2), min(255, claro + 6))


def gravar(rgb: Image.Image, alfa: Image.Image, nome: str) -> Path:
    imagem = rgb.convert("RGBA")
    imagem.putalpha(alfa)
    final = imagem.resize((LADO, LADO), Image.LANCZOS)
    destino = ASSETS / nome
    final.save(destino, "PNG", optimize=True)
    print(f"  {nome}: {LADO}x{LADO}, {destino.stat().st_size // 1024} KB")
    return destino


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python ferramentas/preparar_logotipo.py <arquivo da marca>")
        return 2
    origem = Path(sys.argv[1])
    if not origem.is_file():
        print(f"não achei o original: {origem}")
        return 1
    original = Image.open(origem).convert("RGB")
    marca, alfa = recortar(original)
    tela, mascara = quadrar(marca, alfa)
    print(f"original {original.size} -> marca {marca.size}")

    gravar(tela, mascara, "logo.png")

    clara = Image.new("RGB", tela.size)
    clara.putdata([clarear_o_grafite(p) for p in tela.getdata()])
    gravar(clara, mascara, "logo-para-fundo-escuro.png")

    for divisor in (32, 42, 48, 56, 84):
        assert LADO % divisor == 0, f"{LADO} não divide por {divisor}"
    print(f"  divide exato por 32, 42, 48, 56 e 84")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

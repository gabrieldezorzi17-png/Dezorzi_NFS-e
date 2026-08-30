"""A tag que está sendo publicada bate com a versão do código?

    python .github/workflows/conferir_versao.py v1.1.0

Esquecer de subir `VERSAO_ATUAL` antes de criar a tag é a falha mais fácil de
cometer aqui, e a que menos dá sinal: a compilação passa, a Release sai com o
arquivo certo, e nenhuma máquina atualiza — porque o anúncio continua dizendo
a versão de antes. Este passo transforma isso em erro na hora de publicar.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import updater  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: conferir_versao.py <tag>", file=sys.stderr)
        return 2
    tag = sys.argv[1].lstrip("vV")
    if tag != updater.VERSAO_ATUAL:
        print(f"::error::A tag diz {tag} e o updater.py diz "
              f"{updater.VERSAO_ATUAL}.")
        print("::error::Publicar assim faria a Release anunciar a versão "
              "errada, e nenhuma máquina atualizaria.")
        print("::error::Suba VERSAO_ATUAL em updater.py e crie a tag de novo.")
        return 1
    print(f"tag {tag} confere com updater.VERSAO_ATUAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

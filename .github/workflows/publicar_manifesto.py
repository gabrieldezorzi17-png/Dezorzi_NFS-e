"""Preenche o `version.json` com o endereço de download e confere tudo.

Roda na nuvem, depois de compilar. Precisa de duas variáveis de ambiente:

    REPOSITORIO   dono/repositorio
    TAG           v1.1.0

O campo `arquivo` fica em branco quando se compila na máquina, porque só quem
publica sabe para onde o arquivo vai. Aqui isso deixa de ser verdade: o
endereço da Release é previsível a partir do repositório e da tag. É o que
transforma "publicar" em "criar a tag".

Depois de preencher, confere as duas coisas de que o auto-atualizador depende
para aceitar a troca — a impressão digital sendo a do arquivo publicado, e o
endereço em https. Se algo não bater, é melhor a publicação falhar aqui do que
toda máquina recusar a atualização depois, uma por uma.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import urllib.parse

RAIZ = pathlib.Path(__file__).resolve().parents[2]
SAIDA = RAIZ / "executavel"


def impressao_digital(arquivo: pathlib.Path) -> str:
    digestor = hashlib.sha256()
    with arquivo.open("rb") as entrada:
        for pedaco in iter(lambda: entrada.read(1 << 20), b""):
            digestor.update(pedaco)
    return digestor.hexdigest()


def main() -> int:
    repositorio = os.environ.get("REPOSITORIO", "").strip()
    tag = os.environ.get("TAG", "").strip()
    if not repositorio or not tag:
        print("::error::faltam REPOSITORIO e TAG no ambiente", file=sys.stderr)
        return 2

    executaveis = sorted(SAIDA.glob("*.exe"))
    if len(executaveis) != 1:
        print(f"::error::esperava um .exe em {SAIDA}, achei {len(executaveis)}")
        return 1
    exe = executaveis[0]

    manifesto = SAIDA / "version.json"
    dados = json.loads(manifesto.read_text(encoding="utf-8"))
    # O nome vai codificado: "Dezorzi NFS-e.exe" tem espaço, e espaço em URL
    # quebra o download exatamente na hora em que ninguém está olhando.
    dados["arquivo"] = (f"https://github.com/{repositorio}/releases/download/"
                        f"{urllib.parse.quote(tag)}/{urllib.parse.quote(exe.name)}")
    dados.pop("_como_usar", None)

    calculada = impressao_digital(exe)
    if dados.get("sha256") != calculada:
        print("::error::o sha256 do version.json não é o do .exe compilado")
        print(f"::error::  publicado: {dados.get('sha256')}")
        print(f"::error::  do arquivo: {calculada}")
        return 1
    if not dados["arquivo"].startswith("https://"):
        print("::error::o endereço do .exe não ficou em https")
        return 1

    manifesto.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(f"{exe.name}  versão {dados['versao']}  {calculada[:16]}…")
    print(f"endereço: {dados['arquivo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

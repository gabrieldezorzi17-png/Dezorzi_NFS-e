"""Prepara a pasta do programa na primeira abertura.

Existe por causa do executável de arquivo único. Ali não há pasta nenhuma ao
lado do .exe — e o programa precisa de duas coisas para funcionar:

* arquivos que ele **lê**: o modelo de emissão, o modelo de login, a lista de
  municípios e a identificação da versão do portal (no .env). Sem eles o
  programa abre e não consegue logar;
* pastas onde ele **grava**: as notas e os ajustes.

Os arquivos de leitura viajam dentro do executável. Na primeira abertura eles
são copiados para o lado dele, e a partir daí são arquivos comuns — dá para
abrir, conferir e editar o modelo sem gerar o executável de novo.

A cópia **nunca sobrescreve**. Quem já usa o programa tem alíquotas conferidas e
notas emitidas ali; uma atualização que passasse por cima disso apagaria
trabalho, e no caso das alíquotas sairia como imposto errado na próxima nota.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import paths

def _copiar(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if origem.is_dir():
        shutil.copytree(origem, destino)
    else:
        shutil.copy2(origem, destino)


def preparar() -> list[str]:
    """Cria o que falta ao lado do programa. Devolve o que foi criado.

    Copia **tudo** que veio embutido em ``config/``, em vez de seguir uma lista
    de arquivos. Lista é coisa que se esquece de atualizar: bastaria alguém
    acrescentar um arquivo de configuração novo e ele não chegaria ao
    executável — falha que só aparece na máquina do usuário.
    """
    criados: list[str] = []
    for pasta in (paths.CONFIG_DIR, paths.DATA_DIR):
        if not pasta.exists():
            pasta.mkdir(parents=True, exist_ok=True)
            criados.append(pasta.name + "/")

    if paths.EMBUTIDOS == paths.BASE_DIR:
        return criados        # rodando solto: os arquivos já estão no lugar

    embutido = paths.EMBUTIDOS / "config"
    if embutido.is_dir():
        for item in sorted(embutido.iterdir()):
            destino = paths.CONFIG_DIR / item.name
            if not destino.exists():
                _copiar(item, destino)
                criados.append(f"config/{item.name}")

    env = paths.EMBUTIDOS / ".env"
    if env.exists() and not paths.ENV_FILE.exists():
        _copiar(env, paths.ENV_FILE)
        criados.append(".env")
    return criados


def pasta_grava() -> bool:
    """A pasta do programa aceita escrita?

    Num pendrive protegido ou dentro de Arquivos de Programas, o programa abre
    e depois falha ao salvar a nota — bem depois de o usuário ter digitado
    tudo. Melhor descobrir na abertura.
    """
    teste = paths.BASE_DIR / ".escrita"
    try:
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
    except OSError:
        return False
    return True

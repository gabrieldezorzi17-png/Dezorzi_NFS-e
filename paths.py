"""Caminhos do projeto, sempre resolvidos a partir do programa — nunca do CWD.

Um atalho do Windows pode iniciar o programa em qualquer diretório. Com
caminhos relativos, isso criava silenciosamente uma base de dados vazia e
ignorava o .env. Tudo aqui é absoluto.

Empacotado com o PyInstaller, a origem muda: ``__file__`` passa a apontar para
dentro do pacote — uma pasta de onde não se deve gravar, e que no modo arquivo
único é temporária e some a cada execução. As notas iriam para o lixo sem
ninguém perceber. Por isso, empacotado, tudo se mede a partir do executável.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _arquivo_unico() -> bool:
    """É o executável de arquivo único, e não o de pasta?

    No arquivo único o PyInstaller descompacta o programa numa pasta
    temporária, então ``sys._MEIPASS`` fica longe do .exe. No de pasta ele é o
    ``_internal/`` que está do lado.
    """
    interno = getattr(sys, "_MEIPASS", "")
    if not interno:
        return False
    return Path(interno).parent != Path(sys.executable).resolve().parent


def _pasta_do_usuario() -> Path:
    """A pasta de dados do usuário no Windows — %LOCALAPPDATA%."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Dezorzi NFS-e"


# Nome da subpasta onde o instalador põe o programa. Ela é trocada INTEIRA a
# cada atualização — nada que seja do usuário pode morar aí dentro.
PASTA_DO_PROGRAMA = "app"
# Arquivo que o empacotador põe dentro da carga. É o que distingue uma pasta
# instalada de uma cópia solta — ver `_instalado`.
CARIMBO_DA_VERSAO = "versao.txt"


def _instalado() -> bool:
    """O executável está numa pasta que o instalador criou?

    Reconhecido pela FORMA, não pelo endereço: uma pasta chamada `app` com o
    carimbo de versão dentro. Só o instalador produz isso.

    Pelo endereço não serve mais desde que o assistente passou a perguntar
    onde instalar — quem escolhe `D:\\Programas` continua instalado, e a
    regra tem de valer ali igual. E a forma é específica o bastante para não
    confundir com uma cópia solta da pasta, que não tem o carimbo.
    """
    if not getattr(sys, "frozen", False):
        return False
    ao_lado = Path(sys.executable).resolve().parent
    return (ao_lado.name.lower() == PASTA_DO_PROGRAMA
            and (ao_lado / CARIMBO_DA_VERSAO).is_file())


def _raiz() -> Path:
    """A pasta do programa: onde ficam o .env, o config/ e as notas.

    Rodando solto, é a pasta do código. Como executável, depende do formato:

    - **instalado**: uma pasta acima do .exe. O instalador põe o programa em
      `%LOCALAPPDATA%/Dezorzi NFS-e/app/` e troca essa pasta inteira a cada
      atualização; o `.env` e as notas ficam do lado de fora, intactos.
    - **pasta** (cópia solta): ao lado do .exe, que é o ponto desse formato —
      o config/ e as notas ficam à vista, para abrir e copiar.
    - **arquivo único**: em %LOCALAPPDATA%. Antes era ao lado do .exe também,
      e isso obrigava quem recebe o programa a se importar com ONDE ele fica:
      largado na Área de Trabalho, o programa criava `config/`, `data/` e
      `.env` na Área de Trabalho da pessoa. Agora o .exe pode ficar em
      qualquer lugar — inclusive ser movido depois — que os dados continuam
      onde estão.

    Instalação que já existe não se move: havendo `data/` ou `.env` ao lado do
    .exe, é ali que o programa continua. Trocar o lugar debaixo de quem já usa
    seria fazer as notas sumirem da tela sem explicação.
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent
    ao_lado = Path(sys.executable).resolve().parent
    if _instalado():
        # Uma pasta acima: `app/` é substituída inteira a cada atualização, e
        # o que é do usuário não pode ir junto.
        return ao_lado.parent
    if not _arquivo_unico():
        return ao_lado
    if (ao_lado / "data").is_dir() or (ao_lado / ".env").is_file():
        return ao_lado
    return _pasta_do_usuario()


def _embutidos() -> Path:
    """Onde estão os arquivos que vieram dentro do executável (só leitura).

    No executável de arquivo único, tudo é descompactado numa pasta temporária
    cujo caminho o PyInstaller deixa em ``sys._MEIPASS``. É de lá que saem as
    cópias iniciais do modelo de emissão e do .env (ver ``instalacao.py``).
    Rodando solto, não há nada embutido: os arquivos já estão na pasta.
    """
    if _instalado():
        # No formato pasta a semente viaja ao lado do .exe, não dentro do
        # `_internal` — é de lá que sai a primeira cópia do config/ e do .env.
        return Path(sys.executable).resolve().parent
    interno = getattr(sys, "_MEIPASS", None)
    return Path(interno).resolve() if interno else _raiz()


# Permite mover os dados para fora da pasta do programa (ex.: para tirar as
# notas de dentro do OneDrive) definindo NFSE_HOME.
BASE_DIR = _raiz()
EMBUTIDOS = _embutidos()
HOME_DIR = Path(os.environ["NFSE_HOME"]).expanduser().resolve() if os.environ.get("NFSE_HOME") else BASE_DIR

ENV_FILE = BASE_DIR / ".env"
STATIC_DIR = BASE_DIR / "static"
ASSETS_DIR = BASE_DIR / "assets"   # logotipo e afins acompanham o programa
CONFIG_DIR = HOME_DIR / "config"
DATA_DIR = HOME_DIR / "data"
REQUEST_TEMPLATE = CONFIG_DIR / "request_template.json"
TEMPLATE_EXAMPLE = BASE_DIR / "config" / "request_template.example.json"

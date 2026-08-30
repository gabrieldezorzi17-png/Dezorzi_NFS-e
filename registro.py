"""Diário do programa, em ``data/registro.txt``.

Existe por um motivo específico: quando o programa roda como executável, numa
máquina que não é a de quem o escreveu, uma falha não deixa rastro nenhum. O
usuário descreve o que viu, e a descrição raramente distingue "a janela não
abriu" de "a janela abriu e os botões não liberaram" — que têm causas
completamente diferentes.

Aqui ficam os marcos do que importa: emissão, abertura do layout de impressão,
chegada do PDF, e qualquer erro. É texto simples, para poder ser aberto no
Bloco de Notas e mandado por WhatsApp.

**Nunca entra dado sigiloso.** Sem senha, sem cookie, sem corpo de requisição —
o arquivo é feito para ser compartilhado quando algo dá errado.
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime

import paths

LIMITE_BYTES = 512 * 1024      # meio mega; passando disso, recomeça
_trava = threading.Lock()


def _arquivo():
    return paths.DATA_DIR / "registro.txt"


def escrever(marca: str, mensagem: str = "") -> None:
    """Anota um marco. Nunca estoura: registro que quebra o programa é pior."""
    try:
        with _trava:
            alvo = _arquivo()
            alvo.parent.mkdir(parents=True, exist_ok=True)
            if alvo.exists() and alvo.stat().st_size > LIMITE_BYTES:
                alvo.write_text("", encoding="utf-8")
            agora = datetime.now().strftime("%d/%m %H:%M:%S")
            linha = f"{agora}  {marca}"
            if mensagem:
                linha += f"  |  {' '.join(str(mensagem).split())[:400]}"
            with alvo.open("a", encoding="utf-8") as saida:
                saida.write(linha + "\n")
    except Exception:
        pass


def falha(marca: str, exc: BaseException) -> None:
    """Anota um erro com o rastro completo — é o que permite achar a causa."""
    escrever(marca, f"{type(exc).__name__}: {exc}")
    try:
        with _trava, _arquivo().open("a", encoding="utf-8") as saida:
            saida.write(traceback.format_exc() + "\n")
    except Exception:
        pass

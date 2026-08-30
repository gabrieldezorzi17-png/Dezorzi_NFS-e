"""Impressão do DANFSe — descoberta de impressoras e envio para a fila.

O layout de impressão da nota é o próprio PDF que o portal gera: ele já é o
documento oficial, com o brasão, o código de verificação e o QR. Nada é
redesenhado aqui — redesenhar produziria um papel parecido com a nota, que não
é a nota. Este módulo só cuida de levá-lo até a impressora.

O botão "Imprimir" do portal não serve: ele reenvia o formulário com
``imprime=1`` e o servidor responde com redirect para ``erros.jsp``. Testado em
15/08/2026 — por isso a impressão acontece deste lado.

Windows tem duas formas de imprimir um arquivo pelo shell, e ambas dependem do
leitor de PDF instalado ter registrado o verbo:

* ``print``   — manda para a impressora padrão
* ``printto`` — manda para uma impressora específica

Quando o verbo não existe (alguns leitores registram só ``open``), o erro é
convertido em recado que diz o que fazer, em vez de estourar na cara do usuário.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


class ImpressaoIndisponivel(RuntimeError):
    """O sistema não soube imprimir o arquivo sozinho."""


def _registro():
    try:
        import winreg
    except ImportError:  # não é Windows
        return None
    return winreg


def impressora_padrao() -> str:
    """Nome da impressora padrão do Windows, ou string vazia."""
    winreg = _registro()
    if winreg is None:
        return ""
    try:
        chave = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\Windows",
        )
        with chave:
            valor, _ = winreg.QueryValueEx(chave, "Device")
    except OSError:
        return ""
    # O valor vem como "Nome da impressora,winspool,Ne00:".
    return str(valor).split(",", 1)[0].strip()


def impressoras() -> list[str]:
    """Impressoras conhecidas do sistema, a padrão em primeiro lugar.

    Lidas do registro em vez de chamar PowerShell: é instantâneo e não abre
    processo — a janela de impressão precisa aparecer junto com a nota.
    """
    winreg = _registro()
    nomes: list[str] = []
    if winreg is not None:
        locais = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Devices"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Print\Printers"),
        )
        for raiz, caminho in locais:
            try:
                chave = winreg.OpenKey(raiz, caminho)
            except OSError:
                continue
            with chave:
                try:
                    total = winreg.QueryInfoKey(chave)[0 if "Printers" in caminho else 1]
                except OSError:
                    continue
                ler = winreg.EnumKey if "Printers" in caminho else (
                    lambda k, i: winreg.EnumValue(k, i)[0]
                )
                for indice in range(total):
                    try:
                        nome = str(ler(chave, indice)).strip()
                    except OSError:
                        break
                    if nome and nome not in nomes:
                        nomes.append(nome)

    padrao = impressora_padrao()
    if padrao:
        # A padrão vai para o topo — é a que o usuário quer em 9 de 10 vezes.
        nomes = [padrao] + [nome for nome in nomes if nome != padrao]
    return nomes


def imprimir(caminho: str | Path, impressora: str = "") -> str:
    """Manda o PDF para a impressora. Devolve o nome da impressora usada.

    Sem ``impressora``, usa a padrão do Windows.
    """
    arquivo = Path(caminho)
    if not arquivo.exists():
        raise ImpressaoIndisponivel(f"o arquivo do PDF não está mais em {arquivo}")
    if sys.platform != "win32" or not hasattr(os, "startfile"):
        raise ImpressaoIndisponivel(
            "impressão automática só está implementada no Windows; "
            "abra o PDF e imprima pelo leitor"
        )

    escolhida = impressora.strip()
    try:
        if escolhida:
            # O ShellExecute espera o nome entre aspas neste verbo.
            os.startfile(str(arquivo), "printto", f'"{escolhida}"')  # noqa: S606
        else:
            os.startfile(str(arquivo), "print")  # noqa: S606
    except OSError as exc:
        raise ImpressaoIndisponivel(
            f"o leitor de PDF instalado não aceitou o comando de impressão "
            f"({exc.strerror or exc}).\n\n"
            f"Use 'Abrir PDF' e imprima pelo próprio leitor."
        ) from exc
    return escolhida or impressora_padrao() or "impressora padrão"

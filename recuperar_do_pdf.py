"""Reconstrói o histórico de notas a partir dos PDFs guardados.

    python recuperar_do_pdf.py              mostra o que daria para recuperar
    python recuperar_do_pdf.py --gravar     grava os que faltam em data/

POR QUE ISTO EXISTE
-------------------
Um teste da suíte apagava os arquivos de `data/` — `unlink`, que não passa
pela Lixeira do Windows. O índice local das notas se perdeu. As notas em si
não: elas estão no portal da prefeitura, que é o registro que vale, e o PDF
de cada uma continua em `data/pdf/`.

O QUE É CERTO E O QUE É APROXIMADO
----------------------------------
O nome do arquivo — ``nfse-<número>-<código>.pdf`` — traz o número da nota e
o código de verificação. Esses dois são exatos, e são justamente o que abre a
nota no visualizador da prefeitura. Com eles, "Abrir no portal" volta a
funcionar.

O resto (tomador, valor, serviço) é lido de dentro do PDF, que é o desenho da
prefeitura e pode mudar de formato. Por isso cada registro recuperado sai
marcado, e o que não for reconhecido fica em branco em vez de ser inventado.

Nada é sobrescrito: nota já presente em `data/` é pulada.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

import paths

NOME_DO_PDF = re.compile(r"^nfse-(?P<numero>[^-]+)-(?P<codigo>[^.]+)\.pdf$", re.I)
CNPJ = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
CPF = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")
DATA_HORA = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$")
DATA = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
DINHEIRO = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")
SERVICO = re.compile(r"^(\d{2}\.\d{2})\s*/\s*(\S+)\s*-\s*(.+)$")


def texto_do_pdf(caminho: Path) -> list[str]:
    """Os trechos de texto do PDF, na ordem em que ele os desenha.

    Sem biblioteca externa: os fluxos do PDF são zlib, e o texto sai dos
    operadores ``Tj``. Basta para ler uma nota fiscal, que é um formulário
    fixo — não serviria para um PDF qualquer.
    """
    bruto = caminho.read_bytes()
    montado = ""
    for fluxo in re.findall(rb"stream\r?\n(.*?)endstream", bruto, re.S):
        try:
            montado += zlib.decompress(fluxo.strip()).decode("latin-1", "ignore")
        except zlib.error:
            continue
    pedacos = []
    for achado in re.findall(r"\((.*?)\)\s*Tj", montado):
        # O PDF escapa parênteses; e o texto vem em cp1252.
        limpo = achado.replace(chr(92) + "(", "(").replace(chr(92) + ")", ")")
        limpo = limpo.encode("latin-1", "ignore").decode("cp1252", "ignore").strip()
        if limpo:
            pedacos.append(limpo)
    return pedacos


def _depois_de(pedacos: list[str], marco: str, salto: int) -> str:
    """O trecho que vem `salto` posições depois de um rótulo do formulário.

    Âncora de rótulo, e não posição fixa: a descrição do serviço tem quantas
    linhas quiser, e tudo que vem depois dela anda junto.
    """
    for indice, pedaco in enumerate(pedacos):
        if pedaco.startswith(marco):
            alvo = indice + salto
            return pedacos[alvo] if 0 <= alvo < len(pedacos) else ""
    return ""


def ler_nota(caminho: Path) -> dict:
    """O que dá para saber desta nota. Campo não reconhecido fica vazio.

    Só entra o que sai de um rótulo do formulário. Chutar tomador ou valor
    numa nota fiscal é pior que deixar em branco: o branco se vê, o palpite
    errado passa por verdade.
    """
    achado = NOME_DO_PDF.match(caminho.name)
    dados: dict = {
        "arquivo": caminho.name,
        "numero": achado.group("numero") if achado else "",
        "codigo": achado.group("codigo") if achado else "",
        "prestador": "", "prestador_documento": "", "prestador_inscricao": "",
        "tomador": "", "documento": "", "valor": "", "iss": "",
        "codigo_servico": "", "descricao": "", "emitida_em": "", "competencia": "",
        "confere": False,
    }
    pedacos = texto_do_pdf(caminho)
    if not pedacos:
        return dados

    # O cabeçalho da prefeitura é o marco: dali em diante o formulário
    # imprime os valores sempre na mesma ordem.
    cabecalho = next((i for i, p in enumerate(pedacos)
                      if p.startswith("SECRETARIA DE FINAN")), None)
    if cabecalho is not None:
        def apos(salto: int) -> str:
            alvo = cabecalho + salto
            return pedacos[alvo] if alvo < len(pedacos) else ""

        # Conferência: o que o PDF diz tem de bater com o nome do arquivo.
        dados["confere"] = (apos(1) == dados["numero"] and apos(4) == dados["codigo"])
        dados["emitida_em"] = apos(2) if DATA_HORA.fullmatch(apos(2)) else ""
        dados["competencia"] = apos(3) if DATA.fullmatch(apos(3)) else ""
        dados["prestador_documento"] = apos(5) if CNPJ.fullmatch(apos(5)) else ""
        dados["prestador_inscricao"] = apos(6) if apos(6).isdigit() else ""
        # Nome que é só dígitos é inscrição municipal caída no lugar
        # errado — em branco vale mais que um número fazendo as vezes de
        # razão social.
        nome = apos(11)
        dados["tomador"] = "" if nome.replace(".", "").isdigit() else nome

    # "0-Nenhum" é o campo de desconto: o valor do serviço vem duas posições
    # antes dele, com o desconto no meio.
    valor = _depois_de(pedacos, "0-Nenhum", -2)
    if DINHEIRO.fullmatch(valor):
        dados["valor"] = valor

    # A razão social do prestador vem logo antes do ISS, e este antes de
    # "Natureza Operação". Varia de nota para nota: são vários logins.
    dados["prestador"] = _depois_de(pedacos, "Natureza Opera", -2)
    iss = _depois_de(pedacos, "Natureza Opera", -1)
    if DINHEIRO.fullmatch(iss):
        dados["iss"] = iss

    # O CNPJ do tomador vem depois da natureza da operação.
    documento = _depois_de(pedacos, "1-Tributa", 1)
    if CNPJ.fullmatch(documento) or CPF.fullmatch(documento):
        dados["documento"] = documento

    for pedaco in pedacos:
        servico = SERVICO.match(pedaco)
        if servico:
            dados["codigo_servico"] = servico.group(2)
            dados["descricao"] = servico.group(3).strip()
            break
    return dados


def numeros_ja_gravados() -> set[str]:
    presentes = set()
    for arquivo in paths.DATA_DIR.glob("*.json"):
        try:
            item = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        numero = str((item.get("nota") or {}).get("numero") or "")
        if numero:
            presentes.add(numero)
    return presentes


def montar_registro(dados: dict) -> dict:
    """O registro no formato que o programa guarda."""
    agora = datetime.now(timezone.utc).isoformat()
    competencia = ""
    if dados["competencia"]:
        dia, mes, ano = dados["competencia"].split("/")
        competencia = f"{ano}-{int(mes):02d}-{int(dia):02d}"
    return {
        "id": str(uuid.uuid4()),
        "status": "submitted",
        "created_at": competencia or agora[:10],
        "updated_at": agora,
        # Marca o que veio daqui: quem olhar o arquivo precisa saber que
        # estes campos foram lidos de um PDF, não gravados na emissão.
        "recuperado_do_pdf": dados["arquivo"],
        "nota": {"numero": dados["numero"], "codigo_verificacao": dados["codigo"]},
        "payload": {
            "competencia": competencia,
            # O prestador é o que faltava para separar as notas de cada login.
            "prestador": {"razao_social": dados["prestador"],
                          "inscricao": dados["prestador_inscricao"]},
            "tomador": {"nome": dados["tomador"], "documento": dados["documento"]},
            "servico": {"descricao": dados["descricao"], "valor": dados["valor"],
                        "codigo": dados["codigo_servico"], "iss": dados["iss"]},
        },
    }


def main() -> None:
    gravar = "--gravar" in sys.argv
    pasta = paths.DATA_DIR / "pdf"
    if not pasta.exists():
        print("Não há pasta de PDFs em", pasta)
        return

    presentes = numeros_ja_gravados()
    achados = [ler_nota(p) for p in sorted(pasta.glob("*.pdf"))]
    achados.sort(key=lambda d: int(d["numero"]) if d["numero"].isdigit() else 0,
                 reverse=True)

    print(f"{len(achados)} PDF(s) em {pasta}\n")
    largura = "{:<6} {:<10} {:<30} {:<24} {:>9}  {}"
    print(largura.format("Nº", "VERIFIC.", "PRESTADOR", "TOMADOR", "VALOR", "SITUAÇÃO"))
    novos = []
    for dados in achados:
        ja_tem = dados["numero"] in presentes
        if ja_tem:
            situacao = "já está na lista"
        elif not dados["confere"]:
            situacao = "NÃO CONFERE — pulada"
        else:
            situacao = "pode recuperar"
        print(largura.format(dados["numero"] or "?", dados["codigo"][:10],
                             (dados["prestador"] or "—")[:30],
                             (dados["tomador"] or "—")[:24],
                             dados["valor"] or "—", situacao))
        if not ja_tem and dados["confere"]:
            novos.append(dados)

    if not novos:
        print("\nNada a recuperar: todas já estão na lista.")
        return
    if not gravar:
        print(f"\n{len(novos)} nota(s) podem voltar para a lista.")
        print("Nada foi gravado. Para gravar:  python recuperar_do_pdf.py --gravar")
        return

    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for dados in novos:
        registro = montar_registro(dados)
        alvo = paths.DATA_DIR / f"{registro['id']}.json"
        alvo.write_text(json.dumps(registro, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\n{len(novos)} nota(s) gravadas em {paths.DATA_DIR}")
    print("Abra o programa em Notas — 'Abrir no portal' já funciona nelas.")


if __name__ == "__main__":
    main()

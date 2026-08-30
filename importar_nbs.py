"""Converte a planilha de correlação NBS para ``config/nbs_por_item.json``.

    python importar_nbs.py "caminho/Tabela-Correlacao-NBS.xlsx"

A planilha amarra cada item da LC 116 aos NBS que lhe cabem e, para cada NBS,
ao indicador de operação e à classificação tributária. É o que permite ao
programa oferecer 55 opções em vez de 675, e preencher sozinho o que só tem
uma alternativa.

COMO A PLANILHA SE LÊ
---------------------
Ela é uma tabela para o olho humano, não um arquivo de dados: célula vazia
significa "repete a de cima". A leitura respeita isso.

* uma linha **com NBS** começa um NBS novo;
* uma linha **sem NBS**, mas com indicador ou classificação, acrescenta mais
  uma opção ao NBS anterior — é assim que o item 14.05 dá quatro indicadores
  ao mesmo NBS;
* o que está em branco herda o último valor preenchido acima, dentro do item.
  No item 16.02 o indicador ``60101`` vale até o 21º NBS e ``70100`` do 22º em
  diante, embora só apareça escrito duas vezes.

A leitura é feita com biblioteca padrão — um ``.xlsx`` é um zip com XML —,
para o programa seguir sem dependências.

CONFERÊNCIA
-----------
Ao final, os códigos extraídos são comparados com o que o portal aceita. Uma
planilha que trouxesse um código desconhecido faria a nota ser recusada lá na
frente, com HTTP 500 e sem explicação; melhor descobrir aqui.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import paths

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
ABA = "tabela geral"
DESTINO = paths.CONFIG_DIR / "nbs_por_item.json"

# Colunas da planilha, na ordem em que aparecem.
ITEM, DESC_ITEM, NBS, DESC_NBS, ONEROSA, EXTERIOR, INDOP, LOCAL, CLASSE, DESC_CLASSE = range(10)


def _coluna(referencia: str) -> int:
    letras = "".join(c for c in referencia if c.isalpha())
    numero = 0
    for letra in letras:
        numero = numero * 26 + (ord(letra) - 64)
    return numero - 1


def ler_aba(caminho: Path, aba: str) -> list[list[str]]:
    """As linhas da aba, como listas de texto. Célula vazia vira string vazia."""
    arquivo = zipfile.ZipFile(caminho)
    textos = ["".join(t.text or "" for t in si.iter(NS + "t"))
              for si in ET.fromstring(arquivo.read("xl/sharedStrings.xml")).iter(NS + "si")]
    livro = ET.fromstring(arquivo.read("xl/workbook.xml"))
    nomes = [s.get("name") for s in livro.iter(NS + "sheet")]
    if aba not in nomes:
        raise SystemExit(f"a planilha não tem a aba {aba!r}; tem {nomes}")
    folha = ET.fromstring(arquivo.read(f"xl/worksheets/sheet{nomes.index(aba) + 1}.xml"))

    linhas = []
    for linha in folha.iter(NS + "row"):
        celulas: dict[int, str] = {}
        for c in linha.iter(NS + "c"):
            v = c.find(NS + "v")
            if v is None or v.text is None:
                continue
            texto = textos[int(v.text)] if c.get("t") == "s" else v.text
            if texto.strip():
                celulas[_coluna(c.get("r", "A1"))] = texto.strip()
        if celulas:
            linhas.append([celulas.get(i, "") for i in range(max(celulas) + 1)])
    return linhas


def _limpo(valor: str) -> str:
    """Tira o ``.0`` que o Excel põe em código guardado como número."""
    valor = valor.strip()
    return valor[:-2] if valor.endswith(".0") else valor


def converter(linhas: list[list[str]]) -> dict:
    itens: dict[str, dict] = {}
    item = nbs = None
    indop = classe = None
    for bruta in linhas[1:]:                      # a primeira linha é o cabeçalho
        linha = bruta + [""] * (10 - len(bruta))
        if linha[ITEM]:
            item = linha[ITEM]
            itens[item] = {"descricao": linha[DESC_ITEM], "nbs": {}}
            indop = classe = nbs = None
        if item is None:
            continue
        if linha[INDOP]:
            indop = {"codigo": _limpo(linha[INDOP]), "descricao": linha[LOCAL]}
        if linha[CLASSE]:
            classe = {"codigo": _limpo(linha[CLASSE]), "descricao": linha[DESC_CLASSE]}
        if linha[NBS]:
            nbs = linha[NBS]
            itens[item]["nbs"].setdefault(nbs, {
                "descricao": linha[DESC_NBS], "indop": [], "classificacao": [],
                "onerosa": linha[ONEROSA], "exterior": linha[EXTERIOR],
            })
        if nbs is None:
            continue
        alvo = itens[item]["nbs"][nbs]
        for chave, valor in (("indop", indop), ("classificacao", classe)):
            if valor and valor["codigo"] not in [x["codigo"] for x in alvo[chave]]:
                alvo[chave].append(valor)
    return itens


def conferir(itens: dict) -> list[str]:
    """Compara com o que o portal aceita. Devolve os avisos encontrados."""
    import reforma

    avisos = []
    try:
        aceitos = {
            "indop": {p["codigo"] for p in reforma.opcoes("indicador_operacao")},
            "classificacao": {p["codigo"] for p in reforma.opcoes("classificacao_tributaria")},
            "nbs": {p["codigo"] for p in reforma.opcoes("nbs")},
        }
    except Exception as exc:
        return [f"não deu para conferir com o portal ({exc})"]

    for campo in ("indop", "classificacao"):
        usados = {x["codigo"] for v in itens.values()
                  for d in v["nbs"].values() for x in d[campo]}
        fora = sorted(usados - aceitos[campo])
        if fora:
            avisos.append(f"{campo}: o portal não conhece {fora}")
    fora_nbs = sorted({n for v in itens.values() for n in v["nbs"]} - aceitos["nbs"])
    if fora_nbs:
        avisos.append(f"NBS que o portal não conhece: {fora_nbs[:8]} ({len(fora_nbs)} no total)")
    sem_indop = [n for v in itens.values() for n, d in v["nbs"].items() if not d["indop"]]
    if sem_indop:
        avisos.append(f"{len(sem_indop)} NBS ficaram sem indicador de operação")
    return avisos


def main(caminho: str) -> None:
    itens = converter(ler_aba(Path(caminho), ABA))
    total = sum(len(v["nbs"]) for v in itens.values())
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps(itens, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"itens da LC 116 : {len(itens)}")
    print(f"NBS             : {total}")
    print(f"gravado em      : {DESTINO}")
    avisos = conferir(itens)
    print("\nconferência com o portal:")
    for aviso in avisos or ["  tudo dentro do que o portal aceita"]:
        print(f"  {aviso}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])

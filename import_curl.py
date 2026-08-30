"""Converte um comando cURL capturado no navegador em modelo de requisição.

Uso:
    python import_curl.py emitir.txt --map servico.valor=1,00 --map tomador.documento=11222333000181
    python import_curl.py login.txt --login

No navegador: F12 → aba Rede → faça a operação → clique com o botão direito na
chamada → "Copiar como cURL (bash)" → cole num arquivo .txt e rode o comando.

O que a ferramenta faz por você:

* separa segredos (Cookie, permutação GWT, Authorization) para o .env, deixando
  o modelo livre de credenciais e seguro para guardar;
* remove cabeçalhos que quebram a automação — Accept-Encoding em especial, que
  faria o portal responder comprimido sem que o programa saiba descomprimir;
* troca os valores fiscais da captura por marcadores {{campo}}.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from decimal import Decimal
from typing import Any

import paths

# Cabeçalhos que o cliente HTTP calcula sozinho ou que atrapalham a automação.
DROP_HEADERS = {
    "accept-encoding",   # urllib não descomprime gzip/br automaticamente
    "content-length",    # recalculado a cada envio
    "host",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade-insecure-requests",
    "priority",
}
DROP_PREFIXES = ("sec-ch-", "sec-fetch-", "if-")

SECRET_HEADERS = {
    "cookie": "NFSE_COOKIE",
    "authorization": "NFSE_AUTHORIZATION",
    "x-gwt-permutation": "NFSE_GWT_PERMUTATION",
}


def normalize_command(text: str) -> str:
    """Aceita as variações de 'Copiar como cURL' do Windows e do Linux.

    O formato cmd do Chrome escapa com acento circunflexo: ^" para aspas, ^| para
    barra vertical, ^$ para cifrão. Sem desfazer isso, o corpo GWT-RPC chega com
    ^| no lugar dos delimitadores e nada é reconhecido.
    """
    text = text.replace("curl.exe", "curl").strip()
    formato_cmd = "^" in text
    # Continuação de linha: ^ (cmd), ` (PowerShell) e \ (bash) no fim da linha.
    text = re.sub(r"[\^`\\]\r?\n\s*", " ", text)
    text = re.sub(r"\r?\n", " ", text)
    if formato_cmd:
        # Fora isso, o ^ apenas escapa o caractere seguinte.
        text = re.sub(r"\^(.)", r"\1", text)
        text = text.replace('""', '\\"')
    return text


def split_commands(text: str) -> list[str]:
    """Separa uma captura com vários curl em comandos individuais.

    O Chrome exporta a aba inteira de uma vez, ligando os comandos por ';' (bash)
    ou '&' (cmd). Sem separar, os cabeçalhos de todas as chamadas se misturam e
    o último --data-raw vence — gerando um modelo que não corresponde a nada.
    """
    text = normalize_command(text)
    commands = []
    for chunk in re.split(r"[;&]\s*(?=curl\s)", text):
        position = chunk.find("curl ")
        if position >= 0:
            commands.append(chunk[position:].strip())
    return commands


def detectar_cobertura(body: str, ccm: str) -> dict[str, str]:
    """Descobre a que caso a captura pertence, lendo o próprio corpo.

    O código de serviço e o CNPJ do tomador têm formato inequívoco, então saem
    do corpo sem depender de posição — que muda de captura para captura, já que
    a tabela de strings do GWT é deduplicada por resposta. O CCM do prestador
    não dá para distinguir de outros números, por isso vem por parâmetro.
    """
    cobre: dict[str, str] = {"prestador.ccm": ccm.strip()}
    split = split_gwt(body)
    tabela = split[1] if split else [body]

    codigos = [t for t in tabela if re.fullmatch(r"\d+\.\d+/\d+/\d+", t)]
    if len(set(codigos)) == 1:
        cobre["servico.codigo"] = codigos[0]

    documentos = [t for t in tabela if re.fullmatch(r"\d{14}|\d{11}", t) and t != ccm.strip()]
    if len(set(documentos)) == 1:
        cobre["tomador.documento"] = documentos[0]
    return cobre


def _decimal(texto: str) -> Decimal:
    limpo = str(texto).strip().replace("R$", "").replace(" ", "")
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    return Decimal(limpo)


def detectar_posicoes(body: str, valor: str, aliquota: str, descricao: str,
                      competencia: str) -> tuple[dict[int, str], list[str]]:
    """Descobre em que posição da tabela está cada valor fiscal.

    Você informa o que digitou na nota que capturou; a função procura esses
    valores (e os derivados que o portal calcula) na tabela de strings e diz a
    posição de cada um. É o que evita ter de contar índices à mão, e o que
    torna a captura de uma empresa nova quase automática.
    """
    split = split_gwt(body)
    if split is None:
        return {}, ["o corpo não está no formato GWT-RPC"]
    _, tabela, _ = split

    bruto = _decimal(valor)
    taxa = _decimal(aliquota)
    iss = (bruto * taxa / Decimal(100)).quantize(Decimal("0.01"))
    alvos = {
        "servico.valor": f"{bruto:.2f}",
        "servico.iss": f"{iss:.2f}",
        "servico.valor_liquido": f"{bruto - iss:.2f}",
        "servico.aliquota_fracao": f"{taxa / 100:.4f}",
        "competencia": competencia.strip(),
        "servico.descricao": descricao.strip(),
    }

    codigos = [t for t in tabela if re.fullmatch(r"\d+\.\d+/\d+/\d+", t)]
    if len(set(codigos)) == 1:
        alvos["servico.codigo"] = codigos[0]
        alvos["servico.codigo_item"] = codigos[0].split("/", 1)[0]

    posicoes: dict[int, str] = {}
    avisos: list[str] = []
    for campo, procurado in alvos.items():
        if not procurado:
            continue
        achados = [i for i, texto in enumerate(tabela, 1) if texto == procurado]
        if not achados:
            avisos.append(f"{campo}: não achei {procurado!r} na tabela")
        elif len(achados) > 1:
            avisos.append(
                f"{campo}: {procurado!r} aparece nas posições {achados} — "
                f"informe --map-index manualmente para este campo"
            )
        else:
            posicoes[achados[0]] = campo
    return posicoes, avisos


def gwt_method(body: str) -> str:
    """Nome do método remoto — é a 4ª entrada da tabela de strings."""
    split = split_gwt(body)
    if split is None:
        return ""
    _, table, _ = split
    return table[3] if len(table) > 3 else ""


def parse_curl(text: str) -> dict[str, Any]:
    """Interpreta UM comando curl já normalizado."""
    tokens = shlex.split(text)
    if not tokens or tokens[0] != "curl":
        raise SystemExit("o trecho não começa com um comando curl")

    url = ""
    method = ""
    headers: dict[str, str] = {}
    body = ""
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--url" and index + 1 < len(tokens):
            index += 1
            url = tokens[index]
        elif token in ("-H", "--header") and index + 1 < len(tokens):
            index += 1
            name, _, value = tokens[index].partition(":")
            headers[name.strip()] = value.strip()
        elif token in ("-X", "--request") and index + 1 < len(tokens):
            index += 1
            method = tokens[index].upper()
        elif token in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii") and index + 1 < len(tokens):
            index += 1
            body = tokens[index]
        elif token in ("-b", "--cookie") and index + 1 < len(tokens):
            index += 1
            headers["Cookie"] = tokens[index]
        elif token in ("--compressed", "-i", "-s", "-k", "-L", "--location", "-v"):
            pass
        elif token.startswith("-"):
            # Opção desconhecida com valor (ex.: --user-agent "x")
            if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
                index += 1
        elif not url:
            url = token
        index += 1

    if not url:
        raise SystemExit("não encontrei a URL no comando curl")
    return {
        "method": method or ("POST" if body else "GET"),
        "url": url,
        "headers": headers,
        "body": body,
    }


def clean_headers(headers: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Separa os cabeçalhos úteis dos segredos que vão para o .env."""
    kept: dict[str, str] = {}
    secrets: dict[str, str] = {}
    for name, value in headers.items():
        lowered = name.lower()
        if lowered in DROP_HEADERS or lowered.startswith(DROP_PREFIXES):
            continue
        if lowered in SECRET_HEADERS:
            variable = SECRET_HEADERS[lowered]
            secrets[variable] = value
            kept[name] = f"{{{{env:{variable}}}}}"
            continue
        kept[name] = value
    return kept, secrets


def split_gwt(body: str) -> tuple[list[str], list[str], list[str]] | None:
    """Separa um corpo GWT-RPC em cabeçalho, tabela de strings e índices.

    Formato: versao|flags|qtd|string1|...|stringN|indices...
    """
    parts = body.split("|")
    if len(parts) < 4 or not parts[2].isdigit():
        return None
    total = int(parts[2])
    if len(parts) < 3 + total:
        return None
    return parts[:3], parts[3:3 + total], parts[3 + total:]


def list_gwt_table(body: str) -> None:
    split = split_gwt(body)
    if split is None:
        print("O corpo não está no formato GWT-RPC; use --map em vez de --map-index.")
        return
    _, table, indices = split
    print(f"\nTabela de strings ({len(table)} entradas, {len(indices)} índices no payload):")
    for number, value in enumerate(table, 1):
        print(f"  {number:>3}: {value!r}")


def apply_index_mapping(body: str, mapping: list[str]) -> tuple[str, list[str]]:
    """Troca entradas da tabela de strings pelo número da posição.

    Mais seguro que a troca literal: '1.00' pode aparecer em vários lugares do
    corpo, mas a posição 48 é uma só.
    """
    warnings: list[str] = []
    split = split_gwt(body)
    if split is None:
        return body, ["--map-index ignorado: o corpo não está no formato GWT-RPC"]
    header, table, indices = split
    for pair in mapping:
        raw_position, _, field = pair.partition("=")
        raw_position, field = raw_position.strip(), field.strip()
        if not raw_position.isdigit() or not field:
            warnings.append(f"ignorado: --map-index {pair!r} não está no formato numero=campo")
            continue
        position = int(raw_position)
        if not 1 <= position <= len(table):
            warnings.append(f"ignorado: posição {position} fora da tabela (1..{len(table)})")
            continue
        warnings.append(f"posição {position}: {table[position - 1]!r} -> {{{{{field}}}}}")
        table[position - 1] = f"{{{{{field}}}}}"
    return "|".join(header + table + indices), warnings


def apply_mapping(body: str, mapping: list[str]) -> tuple[str, list[str]]:
    """Troca valores literais da captura por marcadores {{campo}}."""
    warnings: list[str] = []
    for pair in mapping:
        field, _, literal = pair.partition("=")
        field, literal = field.strip(), literal.strip()
        if not field or not literal:
            warnings.append(f"ignorado: --map {pair!r} não está no formato campo=valor")
            continue
        occurrences = body.count(literal)
        if occurrences == 0:
            warnings.append(f"'{literal}' (campo {field}) não aparece no corpo capturado")
            continue
        if occurrences > 1:
            warnings.append(f"'{literal}' aparece {occurrences}x no corpo; confira se todas devem virar {field}")
        body = body.replace(literal, f"{{{{{field}}}}}")
    return body, warnings


def credentials_mapping(body: str, user: str, password: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    for literal, variable in ((user, "NFSE_USUARIO"), (password, "NFSE_SENHA")):
        if not literal:
            continue
        if literal not in body:
            warnings.append(f"não encontrei o valor informado para {variable} no corpo capturado")
            continue
        body = body.replace(literal, f"{{{{env:{variable}|url}}}}")
    return body, warnings


def main() -> int:
    # O console do Windows costuma usar cp1252; sem isto, um acento na saída
    # derruba a ferramenta com UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Gera modelos de requisição a partir de um cURL capturado.")
    parser.add_argument("arquivo", nargs="?", help="arquivo com o comando curl (ou '-' para ler da entrada padrão)")
    parser.add_argument("--login", action="store_true", help="gera config/login_template.json")
    parser.add_argument("--map", action="append", default=[], metavar="CAMPO=VALOR",
                        help="troca um valor da captura por um marcador, ex.: servico.valor=1,00")
    parser.add_argument("--map-index", action="append", default=[], metavar="POSICAO=CAMPO",
                        help="troca uma posição da tabela GWT-RPC, ex.: 48=servico.valor")
    parser.add_argument("--listar", action="store_true",
                        help="apenas mostra a tabela de strings do corpo, sem gravar nada")
    parser.add_argument("--comando", type=int, metavar="N",
                        help="escolhe o N-ésimo curl quando a captura tem vários")
    parser.add_argument("--conter", metavar="TEXTO",
                        help="escolhe o curl cujo corpo contém TEXTO, ex.: emitirNfs")
    parser.add_argument("--usuario", default="", help="valor do usuário na captura de login")
    parser.add_argument("--senha", default="", help="valor da senha na captura de login")
    parser.add_argument("--forcar", action="store_true", help="sobrescreve o modelo existente")
    parser.add_argument("--empresa", metavar="CCM",
                        help="CCM da empresa logada na captura; gera o bloco 'cobre'")
    parser.add_argument("--valor", metavar="X", help="valor que você digitou na nota capturada")
    parser.add_argument("--aliquota", metavar="X", help="alíquota da nota capturada, em %%")
    parser.add_argument("--descricao", metavar="TEXTO", help="descrição exata da nota capturada")
    parser.add_argument("--competencia", metavar="AAAA-MM-DD", help="data da nota capturada")
    parser.add_argument("--nome", metavar="ARQUIVO",
                        help="nome do modelo em config/templates/ (ex.: acme-pintura)")
    args = parser.parse_args()

    if not args.arquivo or args.arquivo == "-":
        print("Cole o comando curl e finalize com Ctrl+Z + Enter (Windows):")
        text = sys.stdin.read()
    else:
        text = Path(args.arquivo).read_text(encoding="utf-8")

    commands = split_commands(text)
    if not commands:
        raise SystemExit("não encontrei nenhum comando curl no arquivo")

    if len(commands) > 1 and args.comando is None and not args.conter:
        print(f"A captura tem {len(commands)} requisições. Escolha uma com "
              f"--comando N ou --conter NOME:\n")
        for number, command in enumerate(commands, 1):
            corpo = parse_curl(command)["body"]
            metodo = gwt_method(corpo) or "(sem corpo GWT-RPC)"
            print(f"  {number:>3}. {metodo}")
        return 1

    if args.conter:
        encontrados = [c for c in commands if args.conter in c]
        if not encontrados:
            raise SystemExit(f"nenhuma requisição contém {args.conter!r}")
        if len(encontrados) > 1:
            print(f"AVISO: {len(encontrados)} requisições contêm {args.conter!r}; usando a primeira.")
        escolhido = encontrados[0]
    elif args.comando is not None:
        if not 1 <= args.comando <= len(commands):
            raise SystemExit(f"--comando deve estar entre 1 e {len(commands)}")
        escolhido = commands[args.comando - 1]
    else:
        escolhido = commands[0]

    parsed = parse_curl(escolhido)
    headers, secrets = clean_headers(parsed["headers"])
    body = parsed["body"]
    # A cobertura sai do corpo ORIGINAL: depois do --map-index os valores já
    # viraram marcadores e não haveria mais o que detectar.
    corpo_original = body
    warnings: list[str] = []

    if args.listar:
        list_gwt_table(body)
        return 0

    if args.login:
        body, notes = credentials_mapping(body, args.usuario, args.senha)
        warnings.extend(notes)
    if args.valor and args.aliquota:
        posicoes, avisos = detectar_posicoes(
            corpo_original, args.valor, args.aliquota,
            args.descricao or "", args.competencia or "",
        )
        if posicoes:
            print("\nPosições detectadas na tabela:")
            for numero in sorted(posicoes):
                print(f"  {numero:>3} = {posicoes[numero]}")
            args.map_index = [f"{n}={campo}" for n, campo in posicoes.items()] + list(args.map_index)
        warnings.extend(avisos)

    if args.map_index:
        body, notes = apply_index_mapping(body, args.map_index)
        warnings.extend(notes)
    if args.map:
        body, notes = apply_mapping(body, args.map)
        warnings.extend(notes)

    template: dict[str, Any] = {
        "method": parsed["method"],
        "url": parsed["url"],
        "headers": headers,
        "body": body,
    }
    if args.empresa:
        cobre = detectar_cobertura(corpo_original, args.empresa)
        template = {"cobre": cobre, **template}
    if args.login:
        template["escape"] = "raw"
        template["success"] = {"status": [200, 302], "body_not_contains": "senha inv"}
        template["probe"] = {"url": parsed["url"], "status": [200], "body_contains": ""}

    if args.login:
        destination = paths.CONFIG_DIR / "login_template.json"
    elif args.nome or args.empresa:
        nome = args.nome or f"empresa-{args.empresa}"
        destination = paths.CONFIG_DIR / "templates" / f"{nome}.json"
    else:
        destination = paths.REQUEST_TEMPLATE
    if destination.exists() and not args.forcar:
        raise SystemExit(f"{destination} já existe. Use --forcar para sobrescrever.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Modelo gravado em {destination}")
    print(f"  método : {template['method']}")
    print(f"  url    : {template['url']}")
    print(f"  headers: {len(headers)} mantidos, {len(parsed['headers']) - len(headers)} descartados")
    print(f"  corpo  : {len(body)} caracteres")

    if secrets:
        print("\nAcrescente ao .env (os valores ficam FORA do modelo):")
        for variable, value in secrets.items():
            preview = value if len(value) <= 60 else f"{value[:57]}..."
            print(f"  {variable}={preview}")
    if args.login:
        print("\nAcrescente ao .env suas credenciais do portal:")
        print("  NFSE_USUARIO=")
        print("  NFSE_SENHA=")
        print("\nAjuste 'probe' no modelo para uma URL autenticada e um trecho que só")
        print("aparece quando a sessão está válida — é ela que dispara o relogin.")

    if args.empresa:
        print("\nEste modelo cobre:")
        for chave, valor in template["cobre"].items():
            print(f"  {chave:20} = {valor}")
        faltando = [c for c in ("servico.codigo", "tomador.documento") if c not in template["cobre"]]
        if faltando:
            print(f"  AVISO: não consegui deduzir {', '.join(faltando)} — complete à mão.")

    markers = sorted(set(re.findall(r"{{\s*([^{}]+?)\s*}}", body)))
    print(f"\nMarcadores no corpo: {', '.join(markers) if markers else 'nenhum'}")
    if not args.login and not markers:
        print("AVISO: sem marcadores, toda nota sairia com os dados da captura original.")
        print("       Use --map campo=valor para os dados fiscais.")
    for note in warnings:
        print(f"AVISO: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Cliente HTTP configurável para o portal de NFS-e.

O modelo em config/request_template.json descreve a requisição que o portal
espera. Os valores do rascunho entram por marcadores {{campo}} e os segredos
por {{env:VARIAVEL}} — segredo nenhum é gravado no modelo.

Regra de ouro deste módulo: **nunca reenviar sozinho**. Uma retentativa
automática de emissão fiscal produz nota duplicada. Toda repetição é decisão
explícita do usuário.
"""
from __future__ import annotations

import json
import os
import re
import ssl
from datetime import date
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import config
import paths

TOKEN = re.compile(r"{{\s*([^{}]+?)\s*}}")
SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "proxy-authorization", "x-csrf-token"}
SECRET_PATTERN = re.compile(r"(JSESSIONID|SESSIONID|token|senha|password)=[^;&\s\"']+", re.IGNORECASE)
EXCERPT_LIMIT = 8_000
READ_LIMIT = 200_000


class NfseError(RuntimeError):
    """Falha de configuração, de montagem ou de comunicação com o portal."""


# --------------------------------------------------------------------------- #
# Escapes
# --------------------------------------------------------------------------- #

def escape_gwt(value: str) -> str:
    """Escapa um valor para a tabela de strings do GWT-RPC.

    O corpo GWT-RPC é delimitado por '|'. Um valor com esse caractere — algo
    tão comum quanto "usinagem | solda" na descrição — desalinha a tabela e a
    chamada falha. A convenção do GWT (ServerSerializationStreamWriter) é
    escapar '\\' como '\\\\', '|' como '\\!' e os caracteres de controle na
    forma '\\uXXXX'.
    """
    out = []
    for character in value:
        if character == "\\":
            out.append("\\\\")
        elif character == "|":
            out.append("\\!")
        elif character == "\x00":
            out.append("\\0")
        elif ord(character) < 0x20:
            out.append(f"\\u{ord(character):04x}")
        else:
            out.append(character)
    return "".join(out)


def escape_json(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


def _escaper(mode: str):
    if mode == "gwt":
        return escape_gwt
    if mode == "json":
        return escape_json
    if mode == "strict":
        def reject(value: str) -> str:
            if any(character in value for character in "|\\\r\n"):
                raise NfseError(f"valor com caractere não permitido pelo portal: {value!r}")
            return value

        return reject
    return lambda value: value


# --------------------------------------------------------------------------- #
# Montagem
# --------------------------------------------------------------------------- #

def _derived(payload: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta variações de formato dos campos numéricos e de data.

    O portal pode exigir 1234,56, 1.234,56 ou 123456; em vez de adivinhar, o
    modelo escolhe o marcador certo.
    """
    context = json.loads(json.dumps(payload))  # cópia; não altera o rascunho salvo
    servico = context.get("servico")
    if isinstance(servico, dict):
        for field in ("valor", "iss"):
            try:
                amount = Decimal(str(servico.get(field, "")))
            except (InvalidOperation, ArithmeticError):
                continue
            plain = f"{amount:.2f}"
            servico[field] = plain
            servico[f"{field}_virgula"] = plain.replace(".", ",")
            servico[f"{field}_br"] = f"{amount:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
            servico[f"{field}_centavos"] = str(int(amount * 100))
        # O portal de São Bernardo pede, além do valor, a base líquida e a
        # alíquota como fração — foi o que a captura da chamada emitirNfs mostrou.
        try:
            valor = Decimal(str(servico.get("valor", "")))
            iss = Decimal(str(servico.get("iss", "")))
            aliquota = Decimal(str(servico.get("aliquota", "")))
        except (InvalidOperation, ArithmeticError):
            pass
        else:
            # A fórmula do portal subtrai o ISS **retido**, não o ISS. Sem
            # retenção o líquido é o valor cheio; com ela, desconta.
            retido = iss if servico.get("iss_retido") else Decimal("0.00")
            servico["valor_liquido"] = f"{valor - retido:.2f}"
            servico["aliquota_fracao"] = f"{aliquota / 100:.4f}"
        # O corpo cita o código de duas formas: completo (14.05/107120/1581) e
        # só o item da lista de serviços (14.05).
        codigo = str(servico.get("codigo", ""))
        servico["codigo_item"] = codigo.split("/", 1)[0]
    tomador = context.get("tomador")
    if isinstance(tomador, dict):
        digits = re.sub(r"\D", "", str(tomador.get("documento", "")))
        tomador["documento"] = digits
        tomador["documento_tipo"] = "CPF" if len(digits) == 11 else "CNPJ"
        if len(digits) == 11:
            tomador["documento_formatado"] = f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
        elif len(digits) == 14:
            tomador["documento_formatado"] = f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    try:
        competencia = date.fromisoformat(str(context.get("competencia", "")))
    except ValueError:
        pass
    else:
        context["competencia_br"] = competencia.strftime("%d/%m/%Y")
        context["competencia_mes"] = competencia.strftime("%m/%Y")
        context["competencia_ano"] = competencia.strftime("%Y")
    return context


def _lookup(expression: str, source: dict[str, Any]) -> str:
    if expression.startswith("env:"):
        name = expression[4:].strip()
        value = os.getenv(name)
        if not value:
            raise NfseError(
                f"a variável {name} não está definida no .env — sem ela o portal "
                f"recusa a requisição com um erro genérico"
            )
        return value
    value: Any = source
    for key in expression.split("."):
        if not isinstance(value, dict) or key not in value:
            raise NfseError(f"campo ausente no rascunho: {expression}")
        value = value[key]
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


FILTERS = {
    "url": quote,
    "json": escape_json,
    "gwt": escape_gwt,
    "raw": lambda value: value,
    "digits": lambda value: re.sub(r"\D", "", value),
    "upper": str.upper,
}


def _render(value: Any, source: dict[str, Any], escape) -> Any:
    if isinstance(value, dict):
        return {key: _render(item, source, escape) for key, item in value.items()}
    if isinstance(value, list):
        return [_render(item, source, escape) for item in value]
    if not isinstance(value, str):
        return value

    def substitute(match: re.Match[str]) -> str:
        # Sintaxe: {{campo}} ou {{campo|filtro}} — ex.: {{env:NFSE_SENHA|url}}
        expression, _, filter_name = match.group(1).partition("|")
        expression = expression.strip()
        filter_name = filter_name.strip().lower()
        found = _lookup(expression, source)
        if filter_name:
            if filter_name not in FILTERS:
                raise NfseError(f"filtro desconhecido no modelo: {filter_name!r}")
            return FILTERS[filter_name](found)
        # Sem filtro explícito: segredos entram literais (já estão no formato do
        # portal) e valores do rascunho passam pelo escape do corpo.
        return found if expression.startswith("env:") else escape(found)

    return TOKEN.sub(substitute, value)


def render_text(value: Any, source: dict[str, Any] | None = None) -> str:
    """Resolve marcadores num texto solto (critérios de sucesso, sondagens…)."""
    if not isinstance(value, str) or not value:
        return ""
    return _render(value, source or {}, _escaper("raw"))


def load_template() -> dict[str, Any]:
    if not paths.REQUEST_TEMPLATE.exists():
        raise NfseError(
            "config/request_template.json não existe. Gere-o com "
            "'python import_curl.py' a partir da chamada emitirNfs capturada no navegador."
        )
    try:
        template = json.loads(paths.REQUEST_TEMPLATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NfseError(f"modelo de requisição com JSON inválido: {exc}") from exc
    if not isinstance(template, dict):
        raise NfseError("o modelo de requisição deve ser um objeto JSON")
    return template


def check_url(url: str, hosts: set[str] | None = None) -> str:
    permitidos = hosts or {config.allowed_host()}
    parsed = urlsplit(str(url))
    if parsed.scheme != "https":
        raise NfseError("a URL do portal precisa usar https")
    if parsed.hostname is None or parsed.hostname.lower() not in permitidos:
        raise NfseError(
            f"por segurança, só é permitido acessar {', '.join(sorted(permitidos))} "
            f"(o modelo aponta para {parsed.hostname})"
        )
    return url


def check_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, dict):
        raise NfseError("headers do modelo devem ser um objeto JSON")
    checked: dict[str, str] = {}
    for key, value in headers.items():
        name, text = str(key), str(value)
        if any(character in name or character in text for character in "\r\n"):
            raise NfseError(f"quebra de linha no cabeçalho {name!r}: requisição recusada")
        try:
            text.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise NfseError(f"o cabeçalho {name!r} tem caractere fora do padrão HTTP") from exc
        checked[name] = text
    return checked


def default_escape(headers: Any) -> str:
    """Escolhe o escape pelo Content-Type declarado no modelo."""
    content_type = ""
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == "content-type":
                content_type = str(value).lower()
    if "gwt-rpc" in content_type:
        return "gwt"
    if "json" in content_type:
        return "json"
    return "strict"


def build_request(
    template: dict[str, Any],
    source: dict[str, Any],
    *,
    method_default: str = "POST",
    allowed_methods: tuple[str, ...] = ("POST", "PUT"),
    hosts: set[str] | None = None,
) -> dict[str, Any]:
    """Renderiza um modelo (emissão ou login) numa requisição pronta e conferida."""
    mode = str(template.get("escape", default_escape(template.get("headers")))).lower()
    rendered = _render(
        {
            "method": template.get("method", method_default),
            "url": template.get("url", ""),
            "headers": template.get("headers", {}),
            "body": template.get("body", ""),
        },
        source,
        _escaper(mode),
    )
    method = str(rendered["method"]).upper()
    if method not in allowed_methods:
        raise NfseError(f"método {method} não permitido aqui (esperado: {', '.join(allowed_methods)})")
    return {
        "method": method,
        "url": check_url(rendered["url"], hosts),
        "headers": check_headers(rendered["headers"]),
        "body": rendered["body"],
        "escape": mode,
    }


def build(payload: dict[str, Any], *, session_active: bool = False) -> dict[str, Any]:
    """Monta a requisição de emissão para este rascunho.

    O modelo é escolhido pelo caso (empresa logada + tomador + serviço), porque
    o corpo capturado carrega prestador e tomador embutidos. Sem modelo que
    cubra o caso, a emissão para aqui — usar o corpo de outra empresa geraria
    nota no CNPJ errado.

    Com `session_active`, o cabeçalho Cookie do modelo é descartado: quem manda
    o cookie é o cookie jar da sessão autenticada, e exigir NFSE_COOKIE no .env
    faria a montagem falhar justamente quando o login automático está ativo.
    """
    import templates

    try:
        template = templates.escolher(payload)
    except templates.SemModelo as exc:
        raise NfseError(str(exc)) from exc
    missing = [key for key in ("method", "url", "headers", "body") if key not in template]
    if missing:
        raise NfseError(f"o modelo precisa das chaves: {', '.join(missing)}")
    if session_active and isinstance(template.get("headers"), dict):
        template = dict(template)
        template["headers"] = {
            key: value for key, value in template["headers"].items() if key.lower() != "cookie"
        }

    # O corpo capturado traz o prestador de quem gravou. Trocar por quem está
    # logado é o que faz uma captura servir a várias empresas — sem isso a
    # nota sairia com a razão social da empresa errada.
    # Substituição do prestador é OPCIONAL: o portal identifica o emitente pela
    # sessão, então o corpo capturado funciona como está. Quem cadastrar os
    # dados em config/empresas.json ganha um corpo coerente com quem está
    # logado; quem não cadastrar, emite igual — decide o portal.
    # O corpo capturado traz prestador e tomador embutidos. Ambos são
    # consultados no portal e substituídos aqui — é o que faz uma única
    # captura servir a qualquer empresa e qualquer cliente.
    if session_active:
        template = dict(template)

        posicoes = template.get("prestador_posicoes")
        if isinstance(posicoes, dict) and posicoes:
            import prestador

            try:
                dados = prestador.do_portal()
            except NfseError:
                dados = prestador.cadastrado()
            if dados:
                template["body"] = prestador.aplicar(template["body"], posicoes, dados=dados)

        posicoes = template.get("tomador_posicoes")
        if isinstance(posicoes, dict) and posicoes:
            import tomador as tomador_portal

            informado = payload.get("tomador") or {}
            documento = informado.get("documento", "")
            try:
                dados = tomador_portal.consultar(documento)
            except tomador_portal.NaoEncontrado:
                # O portal não conhece este CNPJ e devolve resposta vazia — não
                # há id interno para reaproveitar. Nesse caso valem os dados
                # digitados; sem eles, não há como montar o bloco do tomador.
                dados = tomador_portal.manual(informado)
                if not dados:
                    raise NfseError(
                        f"o portal não encontrou o tomador {documento} e os dados "
                        f"dele não foram informados. Preencha o endereço e a razão "
                        f"social do cliente, ou cadastre-o no portal."
                    ) from None
            template["body"] = tomador_portal.aplicar(template["body"], posicoes, dados)

            # Município do tomador: mesma mecânica do local da prestação, porque
            # a string do código divide entrada com outros campos do corpo.
            municipio = str(dados.get("municipio", "")).strip()
            indice_tomador = template.get("tomador_municipio_indice")
            if municipio and isinstance(indice_tomador, int):
                template["body"] = apontar_indice(
                    template["body"], indice_tomador, municipio
                )

    # Local da prestação. Vai por índice, não por marcador: o código do
    # município do serviço divide a mesma entrada da tabela com o do endereço
    # do tomador e o do tributo, e trocar a entrada mudaria os três.
    municipio = str((payload.get("servico") or {}).get("municipio", "")).strip()
    indices = template.get("servico_municipio_indices")
    if isinstance(template.get("servico_municipio_indice"), int):
        indices = list(indices or []) + [template["servico_municipio_indice"]]
    if municipio and indices:
        # São dois campos, não um: além do município do serviço, o bloco de
        # IBS/CBS carrega o mesmo código. A emissão que o portal aceitou tem os
        # dois apontando para o município da prestação.
        template = dict(template)
        for posicao in indices:
            template["body"] = apontar_indice(template["body"], int(posicao), municipio)
    # Quem recolhe o ISS. O corpo capturado veio de uma nota com retenção e
    # trazia "1" fixo aqui — o que fazia toda nota sair retida. Agora a marca
    # segue o rascunho, e o padrão é sem retenção.
    marcas = template.get("servico_iss_retido_marcas")
    indice_iss = template.get("servico_iss_retido_indice")
    if isinstance(indice_iss, int) and isinstance(marcas, dict):
        retido = bool((payload.get("servico") or {}).get("iss_retido"))
        template = dict(template)
        template["body"] = apontar_indice(
            template["body"], indice_iss,
            str(marcas["sim"] if retido else marcas["nao"]),
        )

    # Sem ISS, o segundo campo dele vai vazio — não "0.00".
    vazio = template.get("servico_iss_vazio_indice")
    if isinstance(vazio, int):
        try:
            sem_iss = Decimal(str((payload.get("servico") or {}).get("iss", "0"))) == 0
        except (InvalidOperation, ArithmeticError):
            sem_iss = False
        if sem_iss:
            template = dict(template)
            template["body"] = anular_indice(template["body"], vazio)

    if municipio and not indices:
        raise NfseError(
            "este modelo não sabe onde fica o município da prestação "
            "(falta 'servico_municipio_indice' no arquivo do modelo), "
            "então a nota não pode sair com local de prestação diferente"
        )

    # Cadastrar o tomador novo no portal. Vem antes da obra porque a janela é
    # contada no fluxo original; e a obra, quando entra, acrescenta um objeto
    # antes dela — daí o ajuste das retro-referências.
    cadastrar = template.get("tomador_cadastrar")
    quer_cadastrar = bool((payload.get("tomador") or {}).get("cadastrar"))
    obra_declarada = template.get("servico_obra")
    tem_obra = bool(str((payload.get("servico") or {}).get("obra", "")).strip()
                    and isinstance(obra_declarada, dict))
    if quer_cadastrar and isinstance(cadastrar, dict):
        template = dict(template)
        template["body"] = trocar_janela(
            template["body"],
            int(cadastrar["inicio"]),
            cadastrar["sim"],
            cadastrar.get("tipos") or {},
            # Sem pré-compensação: quem insere objeto é que ajusta as
            # retro-referências, e a obra entra depois desta janela.
        )

    # Reforma tributária (IBS/CBS). Depois do "cadastrar tomador", cuja janela
    # é contada no fluxo original, e antes da obra, que empurra tudo a partir
    # da posição 30. Os três de texto só trocam para onde o campo aponta; o
    # NBS ativa um objeto e acrescenta uma posição, por isso vem por último
    # aqui dentro.
    reforma_declarada = template.get("servico_reforma")
    if isinstance(reforma_declarada, dict):
        servico_payload = payload.get("servico") or {}
        template = dict(template)
        for chave in ("classificacao_tributaria", "situacao_tributaria",
                      "indicador_operacao"):
            declaracao = reforma_declarada.get(chave)
            valor = str(servico_payload.get(chave, "")).strip()
            if valor and isinstance(declaracao, dict):
                template["body"] = apontar_indice(
                    template["body"], int(declaracao["indice"]), valor)
        nbs_declarado = reforma_declarada.get("nbs")
        nbs = str(servico_payload.get("nbs", "")).strip()
        if nbs and isinstance(nbs_declarado, dict):
            template["body"] = inserir_inteiro(
                template["body"], int(nbs_declarado["indice"]),
                str(nbs_declarado["tipo"]), nbs)

    # Código da Obra, por último e não por acaso: ativar o objeto da construção
    # civil **acrescenta** campos ao fluxo, empurrando tudo que vem depois. O
    # município é ajustado antes justamente porque o índice dele (70) vale no
    # fluxo original; feito na ordem inversa, ele cairia na casa errada.
    obra = str((payload.get("servico") or {}).get("obra", "")).strip()
    declaracao = template.get("servico_obra")
    if obra and isinstance(declaracao, dict):
        modelo_campos = declaracao.get("campos") or ["obra"]
        campos = [obra if campo == "obra" else campo for campo in modelo_campos]
        template = dict(template)
        template["body"] = inserir_objeto(
            template["body"],
            int(declaracao["indice"]),
            str(declaracao["tipo"]),
            campos,
        )

    return build_request(template, _derived(payload))


def placeholders() -> list[str]:
    """Marcadores citados no modelo — usado pelo diagnóstico da configuração."""
    if not paths.REQUEST_TEMPLATE.exists():
        return []
    return sorted(set(TOKEN.findall(paths.REQUEST_TEMPLATE.read_text(encoding="utf-8"))))


GWT_TABELA = re.compile(r'\[(?:\s*"(?:[^"\\]|\\.)*"\s*,?)+\]')
GWT_ERRO = ("MensagemRetorno", "ListaMensagemRetorno")


def gwt_strings(resposta: str) -> list[str]:
    """Tabela de strings de uma resposta GWT-RPC (o último vetor JSON)."""
    vetores = GWT_TABELA.findall(resposta or "")
    if not vetores:
        return []
    try:
        return json.loads(vetores[-1])
    except json.JSONDecodeError:
        return []


def gwt_tokens(resposta: str) -> tuple[list[str], list[str]]:
    """Os índices crus de uma resposta GWT-RPC, em ordem de leitura, e a tabela.

    Cru de propósito: um número pode ser referência à tabela **ou** um inteiro.
    O código IBGE de São Paulo é 35 e existe uma string na posição 35 — resolver
    às cegas trocaria o código do estado pelo nome de outro. Quem chama sabe o
    que espera em cada campo e decide.
    """
    texto = resposta or ""
    if "[" not in texto or "]" not in texto:
        return [], []
    corpo = texto[texto.find("[") + 1: texto.rfind("]")]
    try:
        abre = corpo.index("[")
        fecha = corpo.rindex("]")
        tabela = json.loads(corpo[abre:fecha + 1])
    except (ValueError, json.JSONDecodeError):
        return [], []
    indices = [parte.strip() for parte in corpo[:abre].rstrip(", ").split(",") if parte.strip()]
    return list(reversed(indices)), [str(item) for item in tabela]


def apontar_indice(corpo: str, posicao: int, valor: str) -> str:
    """Faz o campo na posição indicada apontar para um novo valor.

    Diferente de trocar a string na tabela: a tabela é **desduplicada**, então
    uma mesma string serve a vários campos. O código de São Bernardo aparece em
    cinco lugares do corpo — município do serviço, do tributo, do endereço do
    tomador… Trocar a string mudaria todos, e o endereço do cliente sairia
    noutra cidade.

    Aqui a string nova entra no fim da tabela (o que não desloca nenhuma
    posição existente) e só o campo pedido passa a apontar para ela.
    """
    partes = corpo.split("|")
    if len(partes) < 4 or not partes[2].isdigit():
        raise NfseError("corpo GWT-RPC inesperado ao ajustar um campo")
    total = int(partes[2])
    cabecalho, tabela, fluxo = partes[:3], partes[3:3 + total], partes[3 + total:]
    if not 0 <= posicao < len(fluxo):
        raise NfseError(f"posição {posicao} fora do corpo (tem {len(fluxo)} campos)")

    escapado = escape_gwt(str(valor))
    if escapado in tabela:
        alvo = tabela.index(escapado) + 1  # já existe: reaproveita, como o GWT faz
    else:
        tabela = tabela + [escapado]
        alvo = len(tabela)
    fluxo = list(fluxo)
    fluxo[posicao] = str(alvo)
    return "|".join([cabecalho[0], cabecalho[1], str(len(tabela))] + tabela + fluxo)


ALFABETO_GWT = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789$_"


def long_gwt(valor: int) -> str:
    """Codifica um inteiro no formato de ``long`` do GWT-RPC.

    É base 64 com alfabeto próprio e dígito mais significativo primeiro.
    Conferido contra a captura do portal: 48708 → ``L5E``.
    """
    valor = int(valor)
    if valor == 0:
        return "A"
    negativo = valor < 0
    valor = abs(valor)
    digitos = []
    while valor:
        digitos.append(ALFABETO_GWT[valor % 64])
        valor //= 64
    return ("-" if negativo else "") + "".join(reversed(digitos))


def long_gwt_para_int(texto: str) -> int:
    """Decodifica um ``long`` do GWT-RPC. Inverso de :func:`long_gwt`."""
    # Na resposta o long vem entre aspas simples ('LrB'); no pedido, sem elas.
    texto = str(texto).strip().strip("'\"")
    negativo = texto.startswith("-")
    if negativo:
        texto = texto[1:]
    valor = 0
    for caractere in texto:
        posicao = ALFABETO_GWT.find(caractere)
        if posicao < 0:
            raise NfseError(f"long GWT inválido: {texto!r}")
        valor = valor * 64 + posicao
    return -valor if negativo else valor


def inserir_objeto(corpo: str, posicao: int, tipo: str, campos: list[str | None]) -> str:
    """Preenche um campo de objeto que estava vazio, com seus subcampos.

    No GWT-RPC, um objeto ausente é um único ``0`` no fluxo. Presente, ele vira
    a referência ao nome da classe **seguida dos campos dele**, inline. Ou seja:
    ativar um objeto não troca um campo, **acrescenta** campos — e é por isso
    que ``apontar_indice`` não serve aqui.

    Foi assim que o Código da Obra apareceu na captura do portal: onde o corpo
    sem obra tem um ``0``, o corpo com obra tem ``TcDadosConstrucaoCivil``
    seguido de quatro campos. Os dois campos vazios seguintes, irmãos do objeto,
    continuam no lugar depois deles.

    ``campos`` descreve o conteúdo: um texto vira valor, ``None`` vira vazio.
    """
    partes = corpo.split("|")
    if len(partes) < 4 or not partes[2].isdigit():
        raise NfseError("corpo GWT-RPC inesperado ao inserir um objeto")
    total = int(partes[2])
    tabela = list(partes[3:3 + total])
    fluxo = list(partes[3 + total:])
    if not 0 <= posicao < len(fluxo):
        raise NfseError(f"posição {posicao} fora do corpo (tem {len(fluxo)} campos)")
    if fluxo[posicao] != "0":
        raise NfseError(
            f"o campo {posicao} já está preenchido (vale {fluxo[posicao]}) — "
            f"inserir aqui sobrescreveria outro dado"
        )

    def referencia(valor: str) -> str:
        escapado = escape_gwt(valor)
        if escapado not in tabela:
            tabela.append(escapado)
        return str(tabela.index(escapado) + 1)

    fluxo[posicao] = referencia(tipo)
    novos = ["0" if campo is None else referencia(str(campo)) for campo in campos]
    fluxo[posicao + 1:posicao + 1] = novos

    # As retro-referências que vêm depois contam objetos, e acabou de entrar
    # mais um: cada uma recua uma casa. Antes isso era compensado à mão dentro
    # da janela do "cadastrar tomador", o que deixava o caso obra-sem-cadastro
    # com a referência apontando para o objeto errado.
    for i in range(posicao + 1 + len(novos), len(fluxo)):
        if fluxo[i].startswith("-") and fluxo[i][1:].isdigit():
            fluxo[i] = str(int(fluxo[i]) - 1)
    return "|".join(partes[:2] + [str(len(tabela))] + tabela + fluxo)


def inserir_inteiro(corpo: str, posicao: int, tipo: str, valor: str) -> str:
    """Preenche um campo numérico que estava vazio — o NBS, na prática.

    Um ``Integer`` do GWT não vai na tabela de strings: o fluxo recebe a
    referência ao nome da classe e, logo depois, **o número cru**. Foi assim que
    o NBS apareceu na captura do portal — ``1.0401.23.00`` viaja como
    ``104012300``, sem os pontos, ao lado de ``java.lang.Integer``.

    Por isso ``apontar_indice`` não serve (poria o número na tabela) nem
    ``inserir_objeto`` (idem para os campos).

    Ativar o objeto **acrescenta** uma posição ao fluxo, e as retro-referências
    que vêm depois contam objetos — cada uma precisa recuar uma casa. Sem esse
    ajuste, o corpo cita o objeto errado e o portal responde HTTP 500 sem
    explicar.
    """
    partes = corpo.split("|")
    if len(partes) < 4 or not partes[2].isdigit():
        raise NfseError("corpo GWT-RPC inesperado ao inserir um número")
    total = int(partes[2])
    tabela = list(partes[3:3 + total])
    fluxo = list(partes[3 + total:])
    if not 0 <= posicao < len(fluxo):
        raise NfseError(f"posição {posicao} fora do corpo (tem {len(fluxo)} campos)")
    if fluxo[posicao] != "0":
        raise NfseError(
            f"o campo {posicao} já está preenchido (vale {fluxo[posicao]}) — "
            f"inserir aqui sobrescreveria outro dado"
        )
    digitos = re.sub(r"\D", "", str(valor))
    if not digitos:
        raise NfseError("o número a inserir não tem dígito nenhum")

    if tipo not in tabela:
        tabela.append(tipo)
    fluxo[posicao] = str(tabela.index(tipo) + 1)
    fluxo.insert(posicao + 1, digitos)

    for i in range(posicao + 2, len(fluxo)):
        if fluxo[i].startswith("-") and fluxo[i][1:].isdigit():
            fluxo[i] = str(int(fluxo[i]) - 1)
    return "|".join(partes[:2] + [str(len(tabela))] + tabela + fluxo)


def trocar_janela(corpo: str, inicio: int, tokens: list, tipos: dict,
                  ajuste_retro: int = 0) -> str:
    """Reescreve um trecho do fluxo, resolvendo os nomes de classe.

    Serve a campos cuja diferença não é o valor de um só campo: o GWT escreve
    ``Boolean.TRUE``/``FALSE`` uma vez e, nas repetições, uma **retro-referência**
    (número negativo) ao objeto já escrito. Ligar um desses booleanos muda,
    portanto, quem é objeto e quem é referência — a janela inteira troca de
    arranjo, mantendo o mesmo tamanho.

    ``ajuste_retro`` desloca as retro-referências quando outro objeto foi
    inserido antes no corpo (a obra, por exemplo), porque elas contam objetos.
    """
    partes = corpo.split("|")
    if len(partes) < 4 or not partes[2].isdigit():
        raise NfseError("corpo GWT-RPC inesperado ao trocar uma janela")
    total = int(partes[2])
    tabela = list(partes[3:3 + total])
    fluxo = list(partes[3 + total:])
    if inicio < 0 or inicio + len(tokens) > len(fluxo):
        raise NfseError(
            f"janela {inicio}..{inicio + len(tokens)} fora do corpo "
            f"(tem {len(fluxo)} campos)"
        )

    resolvidos = []
    for token in tokens:
        texto = str(token)
        if texto.startswith("@"):
            classe = tipos.get(texto)
            if not classe:
                raise NfseError(f"tipo {texto} não declarado no modelo")
            if classe not in tabela:
                tabela.append(classe)
            resolvidos.append(str(tabela.index(classe) + 1))
        elif texto.startswith("-") and ajuste_retro:
            resolvidos.append(str(int(texto) - ajuste_retro))
        else:
            resolvidos.append(texto)

    fluxo[inicio:inicio + len(resolvidos)] = resolvidos
    return "|".join(partes[:2] + [str(len(tabela))] + tabela + fluxo)


def anular_indice(corpo: str, posicao: int) -> str:
    """Esvazia um campo do corpo — o portal manda vazio, não zero.

    Nem todo campo sem valor é ``0.00``: no bloco de valores, o segundo campo
    do ISS vem **vazio** quando não há imposto. Foi assim na emissão que o
    portal aceitou.
    """
    partes = corpo.split("|")
    if len(partes) < 4 or not partes[2].isdigit():
        raise NfseError("corpo GWT-RPC inesperado ao esvaziar um campo")
    total = int(partes[2])
    fluxo = list(partes[3 + total:])
    if not 0 <= posicao < len(fluxo):
        raise NfseError(f"posição {posicao} fora do corpo")
    fluxo[posicao] = "0"
    return "|".join(partes[:3 + total] + fluxo)


def gwt_booleano(resposta: str) -> bool:
    """Lê um Boolean devolvido pelo GWT-RPC.

    O corpo é ``//OK[<valor>,<tipo>,[tabela],0,7]`` e o cliente lê de trás para
    frente: primeiro a classe, depois o valor. ``1`` é verdadeiro.
    """
    tokens, _ = gwt_tokens(resposta)
    return len(tokens) > 1 and tokens[1] == "1"


def gwt_fluxo(resposta: str) -> list[str | None]:
    """Os campos de uma resposta GWT-RPC na ordem em que o objeto os declara.

    Diferença essencial para ``gwt_strings``: aqui **campo vazio ocupa lugar**.
    A tabela de strings só guarda o que tem valor, então um campo nulo some e
    todos os seguintes andam uma casa — foi assim que o nome fantasia de uma
    empresa passou a ser lido como razão social, e a nota saiu com o nome
    errado. No fluxo, nulo vira ``None`` e as posições param de escorregar.

    O GWT escreve a resposta de trás para frente (o cliente lê desempilhando),
    por isso a lista de índices é invertida aqui.

    Devolve, para cada campo: o texto, ou ``None`` para vazio. Os marcadores de
    tipo (``br.eicon...``, ``java.lang...``) viram ``None`` também — são
    estrutura, não dado.
    """
    texto = resposta or ""
    if "[" not in texto or "]" not in texto:
        return []
    inicio = texto.find("[")
    fim = texto.rfind("]")
    corpo = texto[inicio + 1: fim]
    try:
        abre = corpo.index("[")
        fecha = corpo.rindex("]")
        tabela = json.loads(corpo[abre:fecha + 1])
    except (ValueError, json.JSONDecodeError):
        return []
    indices = [parte.strip() for parte in corpo[:abre].rstrip(", ").split(",") if parte.strip()]

    fluxo: list[str | None] = []
    for token in reversed(indices):
        try:
            posicao = int(token)
        except ValueError:
            fluxo.append(None)  # long/date codificados em base64 do GWT
            continue
        if posicao <= 0 or posicao > len(tabela):
            fluxo.append(None)  # inteiro comum, não referência à tabela
            continue
        valor = str(tabela[posicao - 1])
        # Nome de classe é estrutura. O marcador rO0AB… também não é dado.
        estrutural = ("/" in valor and "." in valor.split("/")[0]) or valor.startswith("rO0AB")
        fluxo.append(None if estrutural else valor)
    return fluxo


def _resumir_resposta(texto: str) -> str:
    """Descreve, em uma linha, o que o portal mandou no lugar do GWT-RPC.

    Sem isto o usuário fica com "não respondeu no formato GWT-RPC" e nada mais.
    Página de login, erro do servidor e resposta vazia dão a mesma frase e
    pedem providências diferentes.
    """
    if not texto.strip():
        return "o portal devolveu uma resposta vazia"
    limpo = " ".join(re.sub(r"<[^>]+>", " ", texto).split())
    if not limpo:
        return f"veio conteúdo não textual ({len(texto)} caracteres)"
    baixo = limpo.lower()
    if "login" in baixo or "senha" in baixo or "autentic" in baixo:
        pista = "parece a tela de login — a sessão caiu; entre de novo"
    elif "erro" in baixo or "error" in baixo or "exception" in baixo:
        pista = "o servidor da prefeitura acusou erro"
    else:
        pista = "conteúdo inesperado"
    return f"{pista}. O portal respondeu: “{limpo[:220]}”"


def avaliar_resposta(resposta: str) -> tuple[bool, list[str]]:
    """Diz se o portal aceitou a nota e devolve as mensagens que ele deu.

    O status HTTP não serve para isso: **o GWT-RPC responde 200 mesmo quando a
    operação falha**. Foi assim que uma nota recusada por falta do Código da
    Obra ficou registrada como emitida. O que distingue é o corpo:

    * ``//EX[...]`` — exceção no servidor;
    * ``//OK[...]`` contendo ``ListaMensagemRetorno`` — a chamada funcionou, mas
      o portal recusou a nota e explicou o motivo;
    * ``//OK[...]`` sem isso — nota aceita.
    """
    texto = resposta or ""
    if texto.startswith("//EX"):
        return False, [t for t in gwt_strings(texto) if not t.startswith(("br.", "java."))]
    if not texto.startswith("//OK"):
        # Dizer só "não respondeu no formato GWT-RPC" não permite agir: pode
        # ser página de login, erro do servidor ou resposta vazia, e cada uma
        # pede uma providência diferente. O trecho do que veio resolve isso.
        return False, ["o portal não respondeu no formato GWT-RPC; "
                       "a sessão pode ter expirado", _resumir_resposta(texto)]

    tabela = gwt_strings(texto)
    if not any(marca in item for item in tabela for marca in GWT_ERRO):
        return True, []
    mensagens = [
        item for item in tabela
        if not item.startswith(("br.", "java.")) and len(item.strip()) > 3
    ]
    return False, mensagens or ["o portal recusou a nota sem detalhar o motivo"]


VERIFICACAO = re.compile(r"^(?=.*[A-Z])[A-Z0-9]{7,12}$")
EMITIDA_EM = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def identificar_nota(resposta: str) -> dict[str, str]:
    """Número, código de verificação e data da nota que o portal acabou de emitir.

    O código de verificação é uma sequência de maiúsculas e dígitos — às vezes
    só letras (``BWRUOXEBN``), às vezes misturado (``TOVIPASW8``) — e o número
    da nota vem na entrada seguinte. Vale a **primeira** ocorrência: nomes de
    bairro em maiúsculas casariam com o padrão, mas aparecem depois.

    Não achando, os campos simplesmente não entram. Num controle fiscal, ficar
    sem o número é melhor do que registrar um número inventado.
    """
    tabela = gwt_strings(resposta)
    dados: dict[str, str] = {}
    for indice, texto in enumerate(tabela):
        if EMITIDA_EM.match(texto) and "emitida_em" not in dados:
            dados["emitida_em"] = texto
            continue
        if "codigo_verificacao" in dados or not VERIFICACAO.match(texto):
            continue
        seguinte = tabela[indice + 1] if indice + 1 < len(tabela) else ""
        if seguinte.isdigit() and len(seguinte) <= 9:
            dados["codigo_verificacao"] = texto
            dados["numero"] = seguinte
    return dados


def redact(text: str) -> str:
    return SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[oculto]", text)


def safe_preview(request: dict[str, Any]) -> dict[str, Any]:
    """Versão da requisição segura para exibir na tela ou gravar em disco."""
    body = str(request.get("body", ""))
    return {
        "method": request["method"],
        "url": request["url"],
        "headers": {
            key: "[oculto]" if key.lower() in SENSITIVE_HEADERS else value
            for key, value in request["headers"].items()
        },
        "body_preview": redact(body[:EXCERPT_LIMIT]),
        "body_bytes": len(body.encode("utf-8")),
    }


# --------------------------------------------------------------------------- #
# Transmissão
# --------------------------------------------------------------------------- #

def ssl_context() -> ssl.SSLContext:
    """Contexto TLS compatível com o servidor antigo do portal.

    O portal roda Apache-Coyote/JBoss 5. O OpenSSL 3 recusa a conexão por dois
    motivos, ambos confirmados por teste direto contra o servidor:

    * ele não implementa a renegociação segura da RFC 5746 — sem
      OP_LEGACY_SERVER_CONNECT o handshake morre com UNEXPECTED_EOF;
    * suas cifras ficam abaixo do nível de segurança padrão do OpenSSL 3, o
      que exige SECLEVEL=1.

    Com os dois, a conexão fecha em TLS 1.2. **A verificação do certificado
    continua ligada**: o que se relaxa é a negociação, não a autenticidade do
    servidor. Defina NFSE_TLS_ESTRITO=true para voltar ao padrão do Python.
    """
    context = ssl.create_default_context()
    if config.flag("NFSE_TLS_ESTRITO"):
        return context
    context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    context.set_ciphers("DEFAULT@SECLEVEL=1")
    return context


class NoRedirect(HTTPRedirectHandler):
    """Bloqueia redirecionamentos.

    No portal, um 302 quase sempre é a tela de login: a sessão expirou. Seguir
    o redirect transformaria o POST em GET e devolveria 200 de uma página que
    não emitiu nada — o pior desfecho possível, um falso sucesso.
    """

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _store_response(text: str) -> dict[str, Any]:
    mode = config.response_storage()
    if mode == "none":
        return {"response_stored": "none"}
    clean = redact(text)
    if mode == "full":
        return {"response_stored": "full", "response": clean}
    return {
        "response_stored": "excerpt",
        "response": clean[:EXCERPT_LIMIT],
        "response_truncated": len(clean) > EXCERPT_LIMIT,
    }


def send(request: dict[str, Any], opener: Any = None) -> dict[str, Any]:
    """Transmite a requisição uma única vez e descreve o que o portal respondeu.

    `opener` permite reaproveitar a sessão autenticada (session.py). Quando ele
    é informado, o cookie vem do cookie jar e o cabeçalho Cookie do modelo é
    descartado, para não misturar uma sessão velha do .env com a atual.
    """
    body = request["body"]
    # GWT-RPC serializa o corpo como texto; json.dumps aqui acrescentaria aspas
    # e quebraria a chamada.
    data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = dict(request["headers"])
    if opener is not None:
        headers = {key: value for key, value in headers.items() if key.lower() != "cookie"}
    http_request = Request(request["url"], data=data, headers=headers, method=request["method"])
    opener = opener or build_opener(HTTPSHandler(context=ssl_context()), NoRedirect)
    try:
        with opener.open(http_request, timeout=config.timeout()) as response:
            text = response.read(READ_LIMIT).decode("utf-8", errors="replace")
            return {
                "http_status": response.status,
                "content_type": response.headers.get_content_type(),
                **_store_response(text),
            }
    except HTTPError as exc:
        text = exc.read(READ_LIMIT).decode("utf-8", errors="replace")
        if 300 <= exc.code < 400:
            raise NfseError(
                f"o portal respondeu {exc.code} (redirecionamento) — a sessão provavelmente "
                f"expirou. Capture uma requisição nova e atualize NFSE_COOKIE no .env."
            )
        return {
            "http_status": exc.code,
            "error": f"o portal retornou HTTP {exc.code}",
            "content_type": exc.headers.get_content_type() if exc.headers else "",
            **_store_response(text),
        }
    except URLError as exc:
        raise NfseError(f"falha de conexão com o portal: {exc.reason}") from exc
    except (TimeoutError, HTTPException, OSError) as exc:
        raise NfseError(f"falha de comunicação com o portal: {exc}") from exc
    except (ValueError, UnicodeError) as exc:
        raise NfseError(f"requisição inválida: {exc}") from exc

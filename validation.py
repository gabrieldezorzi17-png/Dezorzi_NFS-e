"""Validação e normalização dos dados fiscais.

Nada é gravado nem transmitido sem passar por aqui: um erro de digitação em
valor ou documento vira uma nota fiscal errada, e nota errada se corrige com
cancelamento e retrabalho.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import config

UFS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}
MAX_VALOR = Decimal("99999999.99")
CENT = Decimal("0.01")


class ValidationError(ValueError):
    """Erro de preenchimento, com o campo responsável."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _check_digit(digits: str, weights: list[int]) -> str:
    total = sum(int(digit) * weight for digit, weight in zip(digits, weights))
    rest = total % 11
    return "0" if rest < 2 else str(11 - rest)


def normalize_document(raw: str, field: str = "documento") -> str:
    """Devolve CPF ou CNPJ apenas com dígitos, conferindo os verificadores."""
    digits = _digits(raw)
    if not digits:
        raise ValidationError(field, "informe o CPF ou CNPJ do tomador")
    if len(digits) not in (11, 14):
        raise ValidationError(field, "o documento deve ter 11 dígitos (CPF) ou 14 (CNPJ)")
    if digits == digits[0] * len(digits):
        raise ValidationError(field, "documento inválido: todos os dígitos são iguais")
    if len(digits) == 11:
        first = _check_digit(digits[:9], list(range(10, 1, -1)))
        second = _check_digit(digits[:10], list(range(11, 1, -1)))
        expected = first + second
    else:
        weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        first = _check_digit(digits[:12], weights)
        second = _check_digit(digits[:13], [6] + weights)
        expected = first + second
    if digits[-2:] != expected:
        kind = "CPF" if len(digits) == 11 else "CNPJ"
        raise ValidationError(field, f"{kind} inválido: dígitos verificadores não conferem")
    return digits


def format_document(digits: str) -> str:
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return digits


def format_money(value: Any) -> str:
    """Formata para exibição em pt-BR. O armazenamento continua em 1234.56."""
    try:
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ArithmeticError, TypeError):
        return str(value or "—")
    return f"{amount:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def normalize_money(raw: str, field: str = "valor") -> Decimal:
    """Aceita 1234.56, 1234,56 e 1.234,56; devolve Decimal com 2 casas."""
    # \u00a0 é o espaço não-quebrável que aparece em valores copiados de páginas web.
    text = str(raw or "").strip().replace("R$", "").replace(" ", "").replace("\u00a0", "")
    if not text:
        raise ValidationError(field, "informe o valor")
    if "," in text:
        # Formato brasileiro: ponto é separador de milhar.
        text = text.replace(".", "").replace(",", ".")
    try:
        value = Decimal(text).quantize(CENT)
    except (InvalidOperation, ArithmeticError) as exc:
        raise ValidationError(field, f"valor inválido: {raw!r}") from exc
    if value <= 0:
        raise ValidationError(field, "o valor deve ser maior que zero")
    if value > MAX_VALOR:
        raise ValidationError(field, "valor acima do limite aceito; confira a digitação")
    return value


def normalize_rate(raw: str, field: str = "aliquota") -> Decimal:
    text = str(raw or "").strip().replace("%", "").replace(" ", "").replace(",", ".")
    if not text:
        raise ValidationError(field, "informe a alíquota")
    try:
        value = Decimal(text).quantize(Decimal("0.0001"))
    except (InvalidOperation, ArithmeticError) as exc:
        raise ValidationError(field, f"alíquota inválida: {raw!r}") from exc
    if not 0 <= value <= 100:
        raise ValidationError(field, "a alíquota deve estar entre 0 e 100")
    return value


def normalize_date(raw: str, field: str = "competencia") -> date:
    text = str(raw or "").strip()
    if not text:
        raise ValidationError(field, "informe a competência")
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y-%m", "%m/%Y"):
        try:
            parsed = datetime.strptime(text, pattern).date()
        except ValueError:
            continue
        if parsed.year < 2000:
            raise ValidationError(field, "competência anterior a 2000; confira a data")
        if parsed > date.today() + timedelta(days=31):
            raise ValidationError(field, "competência muito à frente da data atual")
        return parsed
    raise ValidationError(field, "data inválida; use o formato AAAA-MM-DD ou DD/MM/AAAA")


def clean_text(raw: str, field: str, *, max_length: int = 500, required: bool = True,
               espacos: str = "normalizar") -> str:
    """Remove caracteres de controle e trata os espaços.

    Quebra de linha em campo de texto vira injeção de cabeçalho HTTP ou corpo
    GWT-RPC corrompido mais adiante, então some já na entrada. Isso vale para
    todo campo e não é negociável.

    Espaço repetido e quebra de linha, ao contrário, não têm risco: o corpo do
    portal é GWT-RPC e ``escape_gwt`` já converte a quebra em ``\\u000a``, como
    o próprio GWT faz. Por isso são dois modos:

    * ``normalizar`` — junta os espaços repetidos e transforma quebra de linha
      em espaço. É o certo para nome, logradouro, bairro: ali o texto é de uma
      linha só e espaço duplo é engano de digitação.
    * ``preservar`` — mantém espaçamento **e quebras de linha**. É o certo para
      a descrição do serviço, que é o texto que sai impresso na nota: o usuário
      alinha a chave PIX com espaços e separa os itens em linhas, e achatar
      tudo numa linha só entrega uma nota diferente da que ele escreveu.

    Nos dois modos as pontas são aparadas e os demais caracteres de controle
    somem — só a quebra de linha é poupada, e só no modo ``preservar``.
    """
    text = unicodedata.normalize("NFC", str(raw or ""))
    if espacos == "preservar":
        # \r\n e \r viram \n: o portal e o Tk usam a forma de uma linha só.
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
        text = "".join(character for character in text
                       if character == "\n" or unicodedata.category(character) != "Cc")
        text = text.strip()
    else:
        text = "".join(" " if character in "\r\n\t" else character for character in text)
        text = "".join(character for character in text
                       if unicodedata.category(character) != "Cc")
        text = re.sub(r"\s{2,}", " ", text).strip()
    if required and not text:
        raise ValidationError(field, "campo obrigatório")
    if len(text) > max_length:
        raise ValidationError(field, f"texto acima de {max_length} caracteres")
    return text


def normalize_uf(raw: str, field: str = "uf") -> str:
    uf = str(raw or "").strip().upper()
    if uf not in UFS:
        raise ValidationError(field, "UF inválida; use a sigla de duas letras")
    return uf


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normaliza um rascunho completo ou explica exatamente o que está errado.

    Três campos são preenchidos sozinhos quando vêm vazios:

    * **nome do tomador** — o portal resolve pelo CNPJ, então o formulário não
      pergunta; aqui ele fica em branco e a tela mostra o documento formatado;
    * **competência** — é sempre o dia da emissão;
    * **alíquota** — é uma propriedade do código de serviço, não da nota; vem
      de NFSE_ALIQUOTA no .env.
    """
    if not isinstance(payload, dict):
        raise ValidationError("payload", "o rascunho deve ser um objeto JSON")
    tomador = payload.get("tomador") if isinstance(payload.get("tomador"), dict) else {}
    servico = payload.get("servico") if isinstance(payload.get("servico"), dict) else {}

    # Quem emitiu. Opcional de propósito: rascunho gravado antes desta versão
    # não tem o bloco, e uma nota que já existe não pode virar erro de
    # validação agora. Sem ele, a lista mostra "não registrado" — que é a
    # verdade — em vez de atribuir a nota à empresa errada.
    prestador = payload.get("prestador") if isinstance(payload.get("prestador"), dict) else {}
    prestador_final: dict[str, str] = {}
    for campo, limite in (("inscricao", 20), ("razao_social", 150), ("usuario", 60)):
        valor_prestador = clean_text(prestador.get(campo, ""), f"prestador.{campo}",
                                     max_length=limite, required=False)
        if valor_prestador:
            prestador_final[campo] = valor_prestador

    documento = normalize_document(tomador.get("documento", ""), "tomador.documento")
    nome = clean_text(tomador.get("nome", ""), "tomador.nome", max_length=150, required=False)
    # Dados digitados quando o portal não conhece o CNPJ. Todos opcionais aqui:
    # quem cobra os obrigatórios é tomador.manual(), que sabe quais são.
    manuais = {}
    for campo, limite in (("razao_social", 150), ("logradouro", 120), ("numero", 15),
                          ("complemento", 60), ("bairro", 80), ("email", 120)):
        valor = clean_text(tomador.get(campo, ""), f"tomador.{campo}",
                           max_length=limite, required=False)
        if valor:
            manuais[campo] = valor
    cep_tomador = re.sub(r"\D", "", str(tomador.get("cep", "")))
    if cep_tomador:
        if len(cep_tomador) != 8:
            raise ValidationError("tomador.cep", "o CEP precisa ter 8 dígitos")
        manuais["cep"] = cep_tomador
    municipio_tomador = normalize_municipio(tomador.get("municipio", ""), "tomador.municipio")
    if municipio_tomador:
        manuais["municipio"] = municipio_tomador
    # Cadastrar o cliente no portal só faz sentido para quem ele ainda não
    # conhece; com o tomador já cadastrado o campo nem chega até aqui.
    if manuais and tomador.get("cadastrar"):
        manuais["cadastrar"] = True
    # A descrição é o único campo em que o usuário compõe o texto que sai
    # impresso na nota — o espaçamento dele é intencional e fica de pé.
    descricao = clean_text(servico.get("descricao", ""), "servico.descricao",
                           max_length=2000, espacos="preservar")
    codigo = clean_text(servico.get("codigo", ""), "servico.codigo", max_length=40)
    valor = normalize_money(servico.get("valor", ""), "servico.valor")
    aliquota = normalize_rate(
        servico.get("aliquota") or config.aliquota_do_servico(codigo),
        "servico.aliquota",
    )
    competencia = normalize_date(payload.get("competencia") or date.today().isoformat(), "competencia")
    municipio = normalize_municipio(servico.get("municipio", ""))
    obra = clean_text(servico.get("obra", ""), "servico.obra",
                      max_length=40, required=False)

    # Reforma tributária (IBS/CBS). O CST não vem da tabela de correlação e
    # tem 000 — tributação integral — como padrão; os outros três saem do NBS.
    from reforma import CST_PADRAO

    nbs = normalize_codigo_reforma(servico.get("nbs"), "servico.nbs", "o NBS")
    indicador = normalize_codigo_reforma(
        servico.get("indicador_operacao"), "servico.indicador_operacao",
        "o código indicador da operação")
    classificacao = normalize_codigo_reforma(
        servico.get("classificacao_tributaria"), "servico.classificacao_tributaria",
        "a classificação tributária")
    situacao = normalize_codigo_reforma(
        servico.get("situacao_tributaria"), "servico.situacao_tributaria",
        "a situação tributária (CST-IBS/CBS)", padrao=CST_PADRAO)

    # ISS devido a São Bernardo. Serviço prestado noutro município não gera
    # ISS aqui, e o portal **recalcula e compara**: mandar o imposto assim
    # mesmo faz o valor líquido não fechar e a nota é recusada com E181
    # ("Valor líquido de NFSe informada incorretamente").
    iss = Decimal("0.00") if municipio else (valor * aliquota / Decimal(100)).quantize(CENT)
    # Quem recolhe o ISS. O padrão é o prestador — reter é a exceção, e sair
    # retido sem ninguém pedir troca o responsável pelo imposto na nota.
    # Fora do município não há ISS aqui, logo não há o que reter.
    iss_retido = bool(servico.get("iss_retido")) and not municipio
    servico_final = {
        "descricao": descricao,
        "codigo": codigo,
        "valor": f"{valor:.2f}",
        "aliquota": f"{aliquota:.4f}".rstrip("0").rstrip("."),
        "iss": f"{iss:.2f}",
        "iss_retido": iss_retido,
        "nbs": nbs,
        "indicador_operacao": indicador,
        "classificacao_tributaria": classificacao,
        "situacao_tributaria": situacao,
    }
    # Só entra quando o serviço foi prestado fora do município. Ausente, o
    # corpo mantém o código de São Bernardo que veio da captura.
    if municipio:
        servico_final["municipio"] = municipio
    if obra:
        servico_final["obra"] = obra
    validado = {
        "tomador": {"documento": documento, "nome": nome, **manuais},
        "servico": servico_final,
        "competencia": competencia.isoformat(),
    }
    if prestador_final:
        validado["prestador"] = prestador_final
    return validado


def normalize_codigo_reforma(value: Any, field: str, oque: str,
                             *, padrao: str = "") -> str:
    """Um dos códigos da reforma: só dígitos e pontos, obrigatório.

    Obrigatório porque a prefeitura passou a exigi-los em 24/08/2026 e não
    recusa a nota com mensagem quando faltam — o servidor lança exceção e
    responde HTTP 500 sem dizer o motivo. Barrar aqui troca um erro
    indecifrável por um recado que diz o que fazer.
    """
    texto = str(value or padrao).strip()
    if not texto:
        raise ValidationError(
            field,
            f"{oque} é obrigatório desde a reforma tributária — escolha na tela de emissão",
        )
    if not re.fullmatch(r"[\d.]+", texto):
        raise ValidationError(field, f"{oque} deve conter apenas dígitos e pontos")
    return texto


def normalize_municipio(value: Any, field: str = "servico.municipio") -> str:
    """Código IBGE do município da prestação: sete dígitos, ou vazio.

    Sete dígitos porque é o formato do IBGE (UF + município), e é o que o
    portal registra como local da prestação. Um código curto ou inventado sai
    daqui como erro, não como nota emitida na cidade errada.
    """
    texto = re.sub(r"\D", "", str(value or ""))
    if not texto:
        return ""
    if len(texto) != 7:
        raise ValidationError(
            field, "o código IBGE do município precisa ter 7 dígitos (ex.: 3548708)"
        )
    return texto

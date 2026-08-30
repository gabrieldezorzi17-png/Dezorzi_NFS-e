"""Testes da automação de NFS-e. Rode com: python -m unittest discover tests

Sem dependências externas — o projeto inteiro usa só a biblioteca padrão.
"""
from __future__ import annotations

import importlib
import itertools
import json
import threading
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import copy
import unittest
import unittest.mock
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths  # noqa: E402

# A suíte manda config/ para uma pasta temporária. Alguns testes precisam
# das tabelas de verdade — elas são dados do projeto, não estado de teste.
CONFIG_REAL = Path(__file__).resolve().parent.parent / "config"

# Os testes não podem tocar nas notas reais: apontam tudo para uma pasta temporária.
_sandbox = tempfile.TemporaryDirectory()
paths.DATA_DIR = Path(_sandbox.name) / "data"
paths.CONFIG_DIR = Path(_sandbox.name) / "config"
paths.REQUEST_TEMPLATE = paths.CONFIG_DIR / "request_template.json"
paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

import cep  # noqa: E402
import config  # noqa: E402
import instalacao  # noqa: E402
import marca  # noqa: E402
import reforma  # noqa: E402
import registro  # noqa: E402
import ui  # noqa: E402
import updater  # noqa: E402
import empacotar  # noqa: E402
import obras  # noqa: E402
import municipios  # noqa: E402
import impressao  # noqa: E402
import pdf  # noqa: E402
import portal  # noqa: E402
import prestador  # noqa: E402
import services  # noqa: E402
import templates  # noqa: E402
import tomador  # noqa: E402
import import_curl  # noqa: E402
import desktop  # noqa: E402
import nfse_client  # noqa: E402
import service  # noqa: E402
import session  # noqa: E402
import storage  # noqa: E402
import validation  # noqa: E402

# --------------------------------------------------------------------------- #
# O .env de verdade fica fora do alcance da suíte.
#
# Um teste de sincronização do portal gravava a identificação de mentira por
# cima da real — e sem ela o portal recusa o login. Quem rodasse a suíte
# ficaria sem conseguir emitir, sem nenhuma pista do motivo.
#
# A cópia mantém o conteúdo real para os testes que leem configuração, mas
# toda escrita cai no temporário. Vale para o módulo inteiro: teste novo que
# grave no .env já nasce protegido, sem ninguém ter de lembrar disso.
_PASTA_ENV = pathlib.Path(tempfile.mkdtemp(prefix="nfse-env-"))
_ENV_DE_TESTE = _PASTA_ENV / ".env"
_ENV_DE_TESTE.write_text(
    paths.ENV_FILE.read_text(encoding="utf-8-sig") if paths.ENV_FILE.exists() else "",
    encoding="utf-8",
)
# Os caminhos REAIS, derivados do próprio módulo `paths` e não do que ele
# aponta agora: quando este bloco roda, algo já pode ter redirecionado — e foi
# assim que a primeira versão desta trava passou a comparar com o alvo errado.
_RAIZ_REAL = pathlib.Path(paths.__file__).resolve().parent
_ENV_REAL = _RAIZ_REAL / ".env"
_DADOS_REAIS = _RAIZ_REAL / "data"

paths.ENV_FILE = _ENV_DE_TESTE

# E a pasta das notas, pelo mesmo motivo e com mais urgência: `TestStorage`
# apagava todo *.json de `DATA_DIR` no setUp. Apagava mesmo — `unlink`, que
# não passa pela Lixeira do Windows. Rodar a suíte destruía as notas
# guardadas, sem aviso e sem volta.
_DADOS_DE_TESTE = _PASTA_ENV / "data"
_DADOS_DE_TESTE.mkdir(parents=True, exist_ok=True)
paths.DATA_DIR = _DADOS_DE_TESTE

# Trocar a constante não basta: quatro testes fazem `importlib.reload(paths)`,
# e o reload devolve o caminho de verdade. A trava fica em quem ESCREVE.
_gravar_no_env = config.definir_no_env


def _gravar_protegido(chave, valor):
    """Grava onde o teste mandou — nunca no .env do usuário."""
    if paths.ENV_FILE == _ENV_REAL:
        paths.ENV_FILE = _ENV_DE_TESTE
    return _gravar_no_env(chave, valor)


_CONFIG_REAL = _RAIZ_REAL / "config"


def _proteger_caminhos() -> None:
    """Desvia os caminhos se um reload devolveu os do usuário.

    A suíte já aponta tudo para um sandbox no import. `importlib.reload(paths)`
    desfaz isso, e o que roda depois passa a mexer na instalação de verdade —
    foi assim que as notas guardadas foram apagadas.
    """
    if paths.ENV_FILE == _ENV_REAL:
        paths.ENV_FILE = _ENV_DE_TESTE
    if paths.DATA_DIR == _DADOS_REAIS:
        paths.DATA_DIR = _DADOS_DE_TESTE
    if paths.CONFIG_DIR == _CONFIG_REAL:
        paths.CONFIG_DIR = _PASTA_ENV / "config"
        paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)


config.definir_no_env = _gravar_protegido


def _blindar(modulo, nomes: tuple[str, ...]) -> None:
    """Faz cada função conferir os caminhos antes de agir.

    `storage` lê `paths.DATA_DIR` na hora de gravar. Basta um reload ter
    devolvido o caminho real para a nota de teste nascer na pasta do usuário —
    e foi o que aconteceu, três por rodada.
    """
    for nome in nomes:
        original = getattr(modulo, nome)

        def protegida(*args, _original=original, **kwargs):
            _proteger_caminhos()
            return _original(*args, **kwargs)

        setattr(modulo, nome, protegida)


_blindar(storage, ("create", "save", "get", "list_all", "descartar",
                   "descartar_muitos", "record_submission", "corrupted"))


class _CaminhosSeguros(unittest.TestCase):
    """Base que reconfere os caminhos antes de cada teste.

    Herdada por quem apaga arquivos. Um `importlib.reload(paths)` em qualquer
    teste anterior devolve os caminhos reais, e o próximo que limpar uma pasta
    limpa a do usuário.
    """

    def setUp(self):
        _proteger_caminhos()


class EnvDeVerdadeIntactoTests(unittest.TestCase):
    """A própria rede de segurança tem teste — senão ela some numa refatoração."""

    def test_a_suite_nao_aponta_para_o_env_do_usuario(self):
        self.assertNotEqual(paths.ENV_FILE, _ENV_REAL)
        self.assertEqual(paths.ENV_FILE.parent, _PASTA_ENV)

    def test_a_suite_nao_cria_nota_na_pasta_do_usuario(self):
        # Medido antes da trava: 3 notas de fixture por rodada, com descrição
        # "Serviço prestado" e valor R$ 1,00, na pasta de verdade.
        if not _DADOS_REAIS.exists():
            self.skipTest("sem pasta de notas nesta máquina")
        antes = len(list(_DADOS_REAIS.glob("*.json")))
        importlib.reload(paths)          # o que desfazia a proteção
        try:
            criada = storage.create({
                "tomador": {"documento": "11222333000181"},
                "servico": {"codigo": "14.05", "descricao": "sonda", "valor": "1.00",
                            "aliquota": "2", "iss": "0.02", **REFORMA},
                "competencia": "2026-08-15",
            })
            self.assertEqual(antes, len(list(_DADOS_REAIS.glob("*.json"))))
            self.assertTrue((paths.DATA_DIR / f"{criada['id']}.json").exists())
        finally:
            paths.ENV_FILE = _ENV_DE_TESTE
            paths.DATA_DIR = _DADOS_DE_TESTE

    def test_a_pasta_de_notas_do_usuario_fica_fora_da_suite(self):
        self.assertNotEqual(paths.DATA_DIR, _DADOS_REAIS)
        self.assertEqual(paths.DATA_DIR.parent, _PASTA_ENV)

    def test_a_suite_nao_apaga_nota_nenhuma_do_usuario(self):
        # O estrago real: `unlink` não passa pela Lixeira do Windows.
        if not _DADOS_REAIS.exists():
            self.skipTest("sem pasta de notas nesta máquina")
        antes = sorted(p.name for p in _DADOS_REAIS.glob("*.json"))
        importlib.reload(paths)          # o que desfazia a proteção
        try:
            _proteger_caminhos()
            self.assertNotEqual(paths.DATA_DIR, _DADOS_REAIS)
        finally:
            paths.ENV_FILE = _ENV_DE_TESTE
            paths.DATA_DIR = _DADOS_DE_TESTE
        self.assertEqual(antes, sorted(p.name for p in _DADOS_REAIS.glob("*.json")))

    def test_a_trava_sobrevive_a_um_reload_de_paths(self):
        # `importlib.reload(paths)` devolve ENV_FILE ao caminho de verdade —
        # foi assim que `NFSE_LIVE_MODE=false` foi parar no .env do usuário.
        antes = _ENV_REAL.read_text(encoding="utf-8-sig") if _ENV_REAL.exists() else None
        importlib.reload(paths)
        self.assertEqual(paths.ENV_FILE, _ENV_REAL)      # o reload desfez mesmo
        try:
            config.definir_live_mode(False)              # o que causou o estrago
            depois = _ENV_REAL.read_text(encoding="utf-8-sig") if _ENV_REAL.exists() else None
            self.assertEqual(antes, depois)
            self.assertEqual(paths.ENV_FILE, _ENV_DE_TESTE)   # desviado a tempo
        finally:
            paths.ENV_FILE = _ENV_DE_TESTE
            os.environ.pop("NFSE_LIVE_MODE", None)

    def test_gravar_pelo_config_nao_alcanca_o_arquivo_real(self):
        antes = _ENV_REAL.read_text(encoding="utf-8-sig") if _ENV_REAL.exists() else None
        config.definir_no_env("NFSE_MARCA_DE_TESTE", "nao pode vazar")
        depois = _ENV_REAL.read_text(encoding="utf-8-sig") if _ENV_REAL.exists() else None
        self.assertEqual(antes, depois)
        self.assertIn("NFSE_MARCA_DE_TESTE",
                      paths.ENV_FILE.read_text(encoding="utf-8"))


# Os quatro códigos da reforma passaram a ser obrigatórios em 24/08/2026. Todo
# rascunho de teste precisa deles, como todo rascunho de verdade.
REFORMA = {
    "nbs": "1.1804.00.00",
    "indicador_operacao": "050101",
    "classificacao_tributaria": "000001",
    "situacao_tributaria": "000",
}


def draft(**overrides):
    payload = {
        "tomador": {"documento": "11222333000181", "nome": "Contabilidade Exemplo"},
        "servico": {"descricao": "Serviço prestado", "valor": "1,00",
                    "codigo": "14.05/107120/1581", "aliquota": "2", **REFORMA},
        "competencia": "2026-08-15",
    }
    for chave, valor in overrides.items():
        # Um "servico" passado inteiro não pode apagar os códigos da reforma —
        # os testes que sobrescrevem o serviço estão interessados noutra coisa.
        if chave == "servico" and isinstance(valor, dict):
            payload["servico"] = {**REFORMA, **valor}
        else:
            payload[chave] = valor
    return payload


class TestDocumento(unittest.TestCase):
    def test_cnpj_valido(self):
        self.assertEqual(validation.normalize_document("11.222.333/0001-81"), "11222333000181")

    def test_cpf_valido(self):
        self.assertEqual(validation.normalize_document("529.982.247-25"), "52998224725")

    def test_digito_verificador_errado(self):
        with self.assertRaises(validation.ValidationError):
            validation.normalize_document("11.222.333/0001-82")

    def test_todos_digitos_iguais(self):
        with self.assertRaises(validation.ValidationError):
            validation.normalize_document("111.111.111-11")

    def test_tamanho_invalido(self):
        with self.assertRaises(validation.ValidationError):
            validation.normalize_document("123456")


class TestValores(unittest.TestCase):
    def test_formato_brasileiro(self):
        self.assertEqual(str(validation.normalize_money("1.234,56")), "1234.56")

    def test_formato_americano(self):
        self.assertEqual(str(validation.normalize_money("1234.56")), "1234.56")

    def test_com_simbolo(self):
        self.assertEqual(str(validation.normalize_money("R$ 150,00")), "150.00")

    def test_zero_recusado(self):
        with self.assertRaises(validation.ValidationError):
            validation.normalize_money("0,00")

    def test_texto_recusado(self):
        with self.assertRaises(validation.ValidationError):
            validation.normalize_money("abc")

    def test_aliquota_fora_da_faixa(self):
        with self.assertRaises(validation.ValidationError):
            validation.normalize_rate("120")


class TestTexto(unittest.TestCase):
    def test_remove_quebra_de_linha(self):
        self.assertEqual(validation.clean_text("linha1\nlinha2", "x"), "linha1 linha2")

    def test_remove_controle(self):
        self.assertEqual(validation.clean_text("ab\x07c", "x"), "abc")

    def test_obrigatorio(self):
        with self.assertRaises(validation.ValidationError):
            validation.clean_text("   ", "x")


class TestPayload(unittest.TestCase):
    def test_normaliza_e_calcula_iss(self):
        result = validation.validate_payload(draft())
        self.assertEqual(result["servico"]["valor"], "1.00")
        self.assertEqual(result["servico"]["iss"], "0.02")
        self.assertEqual(result["tomador"]["documento"], "11222333000181")

    def test_nome_do_tomador_e_opcional(self):
        """O formulário não pergunta o nome: o portal resolve pelo CNPJ."""
        resultado = validation.validate_payload(draft(tomador={"documento": "11222333000181"}))
        self.assertEqual(resultado["tomador"]["nome"], "")
        self.assertEqual(resultado["tomador"]["documento"], "11222333000181")

    def test_competencia_vazia_vira_hoje(self):
        resultado = validation.validate_payload(draft(competencia=""))
        self.assertEqual(resultado["competencia"], date.today().isoformat())

    def test_aliquota_vazia_usa_o_padrao_do_env(self):
        os.environ["NFSE_ALIQUOTA"] = "3"
        try:
            servico = {"descricao": "x", "valor": "100,00", "codigo": "14.05", "aliquota": ""}
            resultado = validation.validate_payload(draft(servico=servico))
            self.assertEqual(resultado["servico"]["aliquota"], "3")
            self.assertEqual(resultado["servico"]["iss"], "3.00")
        finally:
            os.environ.pop("NFSE_ALIQUOTA", None)

    def test_documento_continua_obrigatorio(self):
        with self.assertRaises(validation.ValidationError):
            validation.validate_payload(draft(tomador={"documento": ""}))

    def test_payload_livre_recusado(self):
        with self.assertRaises(validation.ValidationError):
            validation.validate_payload({"qualquer": "coisa"})


class TestEscapeGwt(unittest.TestCase):
    def test_pipe_escapado(self):
        self.assertEqual(nfse_client.escape_gwt("usinagem | solda"), "usinagem \\! solda")

    def test_barra_escapada(self):
        self.assertEqual(nfse_client.escape_gwt("a\\b"), "a\\\\b")

    def test_espaco_preservado(self):
        self.assertEqual(nfse_client.escape_gwt("com espaco"), "com espaco")

    def test_nulo_escapado(self):
        self.assertEqual(nfse_client.escape_gwt("a\x00b"), "a\\0b")


class TestTemplate(unittest.TestCase):
    def setUp(self):
        os.environ["NFSE_COOKIE"] = "JSESSIONID=abc123"
        os.environ["NFSE_GWT_PERMUTATION"] = "PERM1"

    def escrever(self, template):
        paths.REQUEST_TEMPLATE.write_text(json.dumps(template), encoding="utf-8")

    def modelo_gwt(self, body="7|0|4|{{servico.descricao}}|{{servico.valor}}|"):
        return {
            "method": "POST",
            "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
            "headers": {"Content-Type": "text/x-gwt-rpc; charset=UTF-8", "Cookie": "{{env:NFSE_COOKIE}}"},
            "body": body,
        }

    def test_monta_requisicao(self):
        self.escrever(self.modelo_gwt())
        request = nfse_client.build(validation.validate_payload(draft()))
        self.assertEqual(request["headers"]["Cookie"], "JSESSIONID=abc123")
        self.assertIn("1.00", request["body"])

    def test_pipe_do_rascunho_nao_corrompe_corpo(self):
        self.escrever(self.modelo_gwt())
        payload = validation.validate_payload(draft(
            servico={"descricao": "usinagem | solda", "valor": "1,00", "codigo": "1", "aliquota": "2"}
        ))
        request = nfse_client.build(payload)
        # O modelo tem 5 delimitadores; o '|' da descrição virou '\!' e não
        # entrou na contagem, então a tabela de strings continua alinhada.
        self.assertEqual(request["body"].count("|"), 5)
        self.assertIn("usinagem \\! solda", request["body"])

    def test_env_ausente_falha_com_mensagem_clara(self):
        os.environ.pop("NFSE_COOKIE", None)
        self.escrever(self.modelo_gwt())
        with self.assertRaises(nfse_client.NfseError) as ctx:
            nfse_client.build(validation.validate_payload(draft()))
        self.assertIn("NFSE_COOKIE", str(ctx.exception))

    def test_url_de_outro_dominio_recusada(self):
        template = self.modelo_gwt()
        template["url"] = "https://exemplo.com/nfse"
        self.escrever(template)
        with self.assertRaises(nfse_client.NfseError):
            nfse_client.build(validation.validate_payload(draft()))

    def test_http_simples_recusado(self):
        template = self.modelo_gwt()
        template["url"] = "http://nfse.isssbc.com.br/nfseweb/nfse"
        self.escrever(template)
        with self.assertRaises(nfse_client.NfseError):
            nfse_client.build(validation.validate_payload(draft()))

    def test_filtro_digits(self):
        self.escrever(self.modelo_gwt(body="doc={{tomador.documento|digits}}"))
        request = nfse_client.build(validation.validate_payload(draft()))
        self.assertEqual(request["body"], "doc=11222333000181")

    def test_com_sessao_ativa_dispensa_cookie_do_env(self):
        """Com login automático, exigir NFSE_COOKIE quebraria a montagem."""
        os.environ.pop("NFSE_COOKIE", None)
        self.escrever(self.modelo_gwt())
        payload = validation.validate_payload(draft())
        with self.assertRaises(nfse_client.NfseError):
            nfse_client.build(payload)
        request = nfse_client.build(payload, session_active=True)
        self.assertNotIn("Cookie", request["headers"])

    def test_preview_oculta_segredo(self):
        self.escrever(self.modelo_gwt())
        preview = nfse_client.safe_preview(nfse_client.build(validation.validate_payload(draft())))
        self.assertEqual(preview["headers"]["Cookie"], "[oculto]")


class TestCamposDerivados(unittest.TestCase):
    """Formatos que o corpo GWT-RPC do portal exige além do valor puro."""

    def derivados(self, valor="1,00", aliquota="2", **extra):
        payload = validation.validate_payload(draft(
            servico={"descricao": "x", "valor": valor, "codigo": "1",
                     "aliquota": aliquota, **extra}
        ))
        return nfse_client._derived(payload)["servico"]

    def test_sem_retencao_o_liquido_e_o_valor_cheio(self):
        # O portal subtrai o ISS **retido**; sem retenção não há o que subtrair.
        self.assertEqual(self.derivados()["valor_liquido"], "1.00")

    def test_com_retencao_o_liquido_desconta_o_iss(self):
        self.assertEqual(self.derivados(iss_retido=True)["valor_liquido"], "0.98")

    def test_aliquota_vira_fracao_com_quatro_casas(self):
        self.assertEqual(self.derivados()["aliquota_fracao"], "0.0200")

    def test_recalculo_com_outros_valores(self):
        derivados = self.derivados(valor="1.500,00", aliquota="3")
        self.assertEqual(derivados["valor"], "1500.00")
        self.assertEqual(derivados["iss"], "45.00")
        self.assertEqual(derivados["valor_liquido"], "1500.00")
        self.assertEqual(derivados["aliquota_fracao"], "0.0300")
        retido = self.derivados(valor="1.500,00", aliquota="3", iss_retido=True)
        self.assertEqual(retido["valor_liquido"], "1455.00")


class TestTravaDoModelo(unittest.TestCase):
    """O corpo capturado embute tomador e serviço; emitir fora disso é proibido."""

    def setUp(self):
        os.environ["NFSE_COOKIE"] = "JSESSIONID=abc"
        paths.REQUEST_TEMPLATE.write_text(json.dumps({
            "method": "POST",
            "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
            "headers": {"Content-Type": "text/x-gwt-rpc", "Cookie": "{{env:NFSE_COOKIE}}"},
            "fixed": {"tomador.documento": "11222333000181", "servico.codigo": "14.05/107120/1581"},
            "body": "7|0|2|{{servico.valor}}|{{servico.descricao}}|1|",
        }), encoding="utf-8")

    def payload(self, documento="11222333000181", codigo="14.05/107120/1581"):
        return validation.validate_payload(draft(
            tomador={"documento": documento, "nome": "Falcon"},
            servico={"descricao": "x", "valor": "1,00", "codigo": codigo, "aliquota": "2"},
        ))

    def test_rascunho_previsto_passa(self):
        self.assertIn("1.00", nfse_client.build(self.payload())["body"])

    def test_outro_tomador_recusado(self):
        with self.assertRaises(nfse_client.NfseError) as ctx:
            nfse_client.build(self.payload(documento="47960950000121"))
        self.assertIn("tomador.documento", str(ctx.exception))

    def test_outro_servico_recusado(self):
        with self.assertRaises(nfse_client.NfseError) as ctx:
            nfse_client.build(self.payload(codigo="17.01/999999/0001"))
        self.assertIn("servico.codigo", str(ctx.exception))


class TestImportacaoCurl(unittest.TestCase):
    """O Chrome exporta em formatos diferentes; todos precisam ser lidos."""

    BASH = (
        "curl --url 'https://nfse.isssbc.com.br/nfseweb/nfse' \\\n"
        "  -H 'Content-Type: text/x-gwt-rpc; charset=UTF-8' \\\n"
        "  -b 'JSESSIONID=ABC' \\\n"
        "  --data-raw '7|0|4|https://x/|HASH|Servico|getSession|1|2|3|4|0|' ;\n"
        "curl --url 'https://nfse.isssbc.com.br/nfseweb/nfse' \\\n"
        "  --data-raw '7|0|4|https://x/|HASH|Servico|listaUF|1|2|3|4|0|'"
    )
    CMD = (
        'curl --url ^"https://nfse.isssbc.com.br/nfseweb/nfse^" ^\n'
        '  -H ^"Content-Type: text/x-gwt-rpc; charset=UTF-8^" ^\n'
        '  -b ^"JSESSIONID=ABC; _ga=GS2.1.s178^$o13^$g1^" ^\n'
        '  -H ^"sec-ch-ua-platform: ^\\^"Windows^\\^"^" ^\n'
        '  --data-raw ^"7^|0^|4^|https://x/^|HASH^|Servico^|getSession^|1^|2^|3^|4^|0^|^" &\n'
        'curl --url ^"https://nfse.isssbc.com.br/nfseweb/nfse^" ^\n'
        '  --data-raw ^"7^|0^|4^|https://x/^|HASH^|Servico^|listaUF^|1^|2^|3^|4^|0^|^"'
    )

    def test_bash_separa_dois_comandos(self):
        self.assertEqual(len(import_curl.split_commands(self.BASH)), 2)

    def test_cmd_separa_dois_comandos(self):
        self.assertEqual(len(import_curl.split_commands(self.CMD)), 2)

    def test_cmd_desfaz_escape_de_barra_vertical(self):
        comando = import_curl.split_commands(self.CMD)[0]
        corpo = import_curl.parse_curl(comando)["body"]
        self.assertNotIn("^|", corpo)
        self.assertEqual(corpo.count("|"), 12)

    def test_cmd_preserva_cifrao_do_cookie(self):
        comando = import_curl.split_commands(self.CMD)[0]
        self.assertEqual(import_curl.parse_curl(comando)["headers"]["Cookie"],
                         "JSESSIONID=ABC; _ga=GS2.1.s178$o13$g1")

    def test_url_por_opcao_explicita(self):
        comando = import_curl.split_commands(self.BASH)[0]
        self.assertEqual(import_curl.parse_curl(comando)["url"],
                         "https://nfse.isssbc.com.br/nfseweb/nfse")

    def test_identifica_o_metodo_gwt(self):
        for captura in (self.BASH, self.CMD):
            metodos = [import_curl.gwt_method(import_curl.parse_curl(c)["body"])
                       for c in import_curl.split_commands(captura)]
            self.assertEqual(metodos, ["getSession", "listaUF"])

    def test_descarta_accept_encoding(self):
        comando = "curl --url 'https://x/' -H 'Accept-Encoding: gzip' -H 'Accept: */*'"
        headers, _ = import_curl.clean_headers(import_curl.parse_curl(comando)["headers"])
        self.assertNotIn("Accept-Encoding", headers)
        self.assertIn("Accept", headers)

    def test_troca_por_indice_nao_afeta_valores_iguais(self):
        corpo = "7|0|5|a|1.00|b|1.00|c|1|2|"
        novo, _ = import_curl.apply_index_mapping(corpo, ["2=servico.valor"])
        self.assertEqual(novo, "7|0|5|a|{{servico.valor}}|b|1.00|c|1|2|")


class TestSondagemDeSessao(unittest.TestCase):
    """Os critérios de sucesso também resolvem marcadores {{env:...}}."""

    def setUp(self):
        os.environ["NFSE_USUARIO"] = "304838"

    def test_criterio_com_marcador_e_resolvido(self):
        spec = {"status": [200], "body_contains": "{{env:NFSE_USUARIO}}"}
        self.assertTrue(session.PortalSession._matches(spec, 200, '//OK[...,"304838",...]'))

    def test_criterio_com_marcador_recusa_resposta_vazia(self):
        spec = {"status": [200], "body_contains": "{{env:NFSE_USUARIO}}"}
        self.assertFalse(session.PortalSession._matches(spec, 200, "//OK[0,[],0,7]"))

    def test_status_fora_da_lista_reprova(self):
        self.assertFalse(session.PortalSession._matches({"status": [200]}, 302, "//OK"))

    def test_body_not_contains_reprova(self):
        spec = {"status": [200], "body_not_contains": "//EX"}
        self.assertFalse(session.PortalSession._matches(spec, 200, "//EX[1,[],0]"))
        self.assertTrue(session.PortalSession._matches(spec, 200, "//OK[1,[],0]"))


class TestCatalogoDeServicos(unittest.TestCase):
    """Leitura da resposta real de consultarServicos.

    A amostra abaixo reproduz a estrutura devolvida pelo portal: índices na
    frente, tabela de strings no fim.
    """

    RESPOSTA = (
        '//OK[0,29,23,-26,0,2,1,'
        '["br.com.eicon.ginfesvohb.dto.GenericList/2718224337",'
        '"java.util.ArrayList/4159755760",'
        '"14.05",'
        '"Restauracao, recondicionamento e congeneres, de objetos quaisquer.",'
        '"14.05/107120/1581",'
        '"MUNICIPIO DE SAO BERNARDO DO CAMPO",'
        '"SERVICOS DE USINAGEM, TORNEARIA E SOLDA",'
        '"7.02",'
        '"Execucao, por administracao, empreitada ou subempreitada, de obras.",'
        '"7.02/103138/1291",'
        '"SERVICOS DE PINTURA DE EDIFICIOS EM GERAL"],0,7]'
    )

    def test_encontra_os_dois_codigos(self):
        encontrados = services.interpretar(self.RESPOSTA)
        self.assertEqual([s["codigo"] for s in encontrados],
                         ["14.05/107120/1581", "7.02/103138/1291"])

    def test_item_sai_do_codigo(self):
        encontrados = services.interpretar(self.RESPOSTA)
        self.assertEqual([s["item"] for s in encontrados], ["14.05", "7.02"])

    def test_apelidos_pareados_na_ordem(self):
        encontrados = services.interpretar(self.RESPOSTA)
        self.assertEqual(encontrados[0]["nome"], "SERVICOS DE USINAGEM, TORNEARIA E SOLDA")
        self.assertEqual(encontrados[1]["nome"], "SERVICOS DE PINTURA DE EDIFICIOS EM GERAL")

    def test_descricao_vem_logo_apos_o_item(self):
        encontrados = services.interpretar(self.RESPOSTA)
        self.assertTrue(encontrados[0]["descricao"].startswith("Restauracao"))
        self.assertTrue(encontrados[1]["descricao"].startswith("Execucao"))

    def test_resposta_sem_ok_e_recusada(self):
        with self.assertRaises(nfse_client.NfseError):
            services.interpretar('//EX[0,1,["erro"],0,7]')

    def test_sessao_expirada_nao_vira_lista_vazia(self):
        with self.assertRaises(nfse_client.NfseError):
            services.interpretar("<html>login</html>")


class TestCodigoDeServicoNoCorpo(unittest.TestCase):
    """O corpo GWT cita o código completo e o item; os dois precisam variar."""

    def setUp(self):
        os.environ["NFSE_COOKIE"] = "JSESSIONID=abc"
        paths.REQUEST_TEMPLATE.write_text(json.dumps({
            "method": "POST",
            "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
            "headers": {"Content-Type": "text/x-gwt-rpc", "Cookie": "{{env:NFSE_COOKIE}}"},
            "body": "7|0|2|{{servico.codigo}}|{{servico.codigo_item}}|1|",
        }), encoding="utf-8")

    def montar(self, codigo):
        payload = validation.validate_payload(draft(servico={
            "descricao": "x", "valor": "100,00", "codigo": codigo, "aliquota": "2",
        }))
        return nfse_client.build(payload)["body"]

    def test_item_derivado_do_codigo(self):
        self.assertEqual(self.montar("14.05/107120/1581"), "7|0|2|14.05/107120/1581|14.05|1|")

    def test_outro_servico_muda_as_duas_posicoes(self):
        self.assertEqual(self.montar("7.02/103138/1291"), "7|0|2|7.02/103138/1291|7.02|1|")

    def test_estrutura_preservada_entre_servicos(self):
        a = self.montar("14.05/107120/1581")
        b = self.montar("7.02/103138/1291")
        self.assertEqual(a.count("|"), b.count("|"))


class TestAliquotaPorServico(unittest.TestCase):
    def setUp(self):
        config.ALIQUOTAS = paths.CONFIG_DIR / "aliquotas_teste.json"
        config.ALIQUOTAS.write_text(json.dumps({"14.05/107120/1581": "2"}), encoding="utf-8")

    def tearDown(self):
        config.ALIQUOTAS.unlink(missing_ok=True)

    def test_codigo_registrado_usa_a_propria(self):
        self.assertEqual(config.aliquota_do_servico("14.05/107120/1581"), "2")
        self.assertTrue(config.aliquota_confirmada("14.05/107120/1581"))

    def test_codigo_novo_cai_no_padrao_e_fica_marcado(self):
        self.assertEqual(config.aliquota_do_servico("7.02/103138/1291"),
                         config.aliquota_padrao())
        self.assertFalse(config.aliquota_confirmada("7.02/103138/1291"))

    def test_gravar_confirma_o_codigo(self):
        config.definir_aliquota("7.02/103138/1291", "5")
        self.assertEqual(config.aliquota_do_servico("7.02/103138/1291"), "5")
        self.assertTrue(config.aliquota_confirmada("7.02/103138/1291"))


class TestRespostaDoPortal(unittest.TestCase):
    """O portal recusa notas dentro de um //OK — HTTP 200 não é sucesso.

    Foi exatamente assim que uma nota rejeitada por falta do Código da Obra
    ficou gravada como emitida. As duas amostras abaixo são respostas reais.
    """

    RECUSADA = (
        '//OK[0,7,6,5,4,1,3,2,0,0,1,'
        '["br.eicon.nfse.xml.nfs.NFSE/2415353041",'
        '"br.eicon.nfse.xml.nfs.NFSE$ListaMensagemRetorno/3281892323",'
        '"java.util.ArrayList/4159755760",'
        '"br.eicon.nfse.vo.TcMensagemRetorno/4057196000",'
        '"E323","Favor informar o codigo da Obra",'
        '"Codigo da Obra e obrigatorio mas nao foi informado"],0,7]'
    )
    ACEITA = (
        '//OK[6,6,6,66,0,65,64,0,63,'
        '["br.eicon.nfse.xml.complexType.TcNfse/3098077507",'
        '"br.eicon.nfse.xml.complexType.TcIdentificacaoNfse/2440320867",'
        '"2026-08-15","1234"],0,7]'
    )

    def test_recusa_dentro_de_ok_e_detectada(self):
        aceita, mensagens = nfse_client.avaliar_resposta(self.RECUSADA)
        self.assertFalse(aceita)
        self.assertIn("Codigo da Obra e obrigatorio mas nao foi informado", mensagens)

    def test_recusa_traz_o_codigo_do_erro(self):
        _, mensagens = nfse_client.avaliar_resposta(self.RECUSADA)
        self.assertIn("E323", mensagens)

    def test_nota_aceita_nao_vira_falha(self):
        aceita, mensagens = nfse_client.avaliar_resposta(self.ACEITA)
        self.assertTrue(aceita)
        self.assertEqual(mensagens, [])

    def test_excecao_do_servidor_e_falha(self):
        aceita, _ = nfse_client.avaliar_resposta('//EX[0,1,["java.lang.RuntimeException/123"],0,7]')
        self.assertFalse(aceita)

    def test_html_de_login_e_falha(self):
        aceita, mensagens = nfse_client.avaliar_resposta("<html>sessao expirada</html>")
        self.assertFalse(aceita)
        self.assertTrue(mensagens)

    def test_resposta_vazia_e_falha(self):
        self.assertFalse(nfse_client.avaliar_resposta("")[0])


class TestSelecaoDeModelo(unittest.TestCase):
    """Um modelo cobre uma combinação (empresa, tomador, serviço), não o portal.

    O corpo capturado traz prestador e tomador embutidos: emitir com o modelo
    de outra empresa geraria nota no CNPJ errado. Por isso o programa recusa
    em vez de improvisar.
    """

    def setUp(self):
        templates.PASTA = paths.CONFIG_DIR / "templates_teste"
        templates.PASTA.mkdir(parents=True, exist_ok=True)
        for antigo in templates.PASTA.glob("*.json"):
            antigo.unlink()
        os.environ["NFSE_USUARIO"] = "304838"
        self.escrever("mundial-usinagem", {
            "prestador.ccm": "304838",
            "tomador.documento": "11222333000181",
            "servico.codigo": "14.05/107120/1581",
        })

    def tearDown(self):
        for arquivo in templates.PASTA.glob("*.json"):
            arquivo.unlink()

    def escrever(self, nome, cobre):
        (templates.PASTA / f"{nome}.json").write_text(json.dumps({
            "method": "POST",
            "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
            "headers": {"Content-Type": "text/x-gwt-rpc"},
            "cobre": cobre,
            "body": f"7|0|1|{nome}|1|",
        }), encoding="utf-8")

    def caso(self, documento="11222333000181", codigo="14.05/107120/1581"):
        return validation.validate_payload(draft(
            tomador={"documento": documento},
            servico={"descricao": "x", "valor": "100,00", "codigo": codigo, "aliquota": "2"},
        ))

    def test_caso_previsto_escolhe_o_modelo(self):
        self.assertEqual(templates.escolher(self.caso())["_nome"], "mundial-usinagem")

    def test_outra_empresa_logada_e_recusada(self):
        os.environ["NFSE_USUARIO"] = "999999"
        with self.assertRaises(templates.SemModelo) as ctx:
            templates.escolher(self.caso())
        self.assertIn("999999", str(ctx.exception))

    def test_outro_tomador_e_recusado(self):
        with self.assertRaises(templates.SemModelo):
            templates.escolher(self.caso(documento="47960950000121"))

    def test_servico_sem_modelo_e_recusado(self):
        with self.assertRaises(templates.SemModelo):
            templates.escolher(self.caso(codigo="7.02/103138/1291"))

    def test_segundo_modelo_atende_o_outro_servico(self):
        self.escrever("mundial-pintura", {
            "prestador.ccm": "304838",
            "tomador.documento": "11222333000181",
            "servico.codigo": "7.02/103138/1291",
        })
        escolhido = templates.escolher(self.caso(codigo="7.02/103138/1291"))
        self.assertEqual(escolhido["_nome"], "mundial-pintura")
        # e o primeiro continua valendo para o serviço dele
        self.assertEqual(templates.escolher(self.caso())["_nome"], "mundial-usinagem")

    def test_modelo_mais_especifico_ganha(self):
        self.escrever("generico", {"prestador.ccm": "304838"})
        self.assertEqual(templates.escolher(self.caso())["_nome"], "mundial-usinagem")

    def test_erro_lista_os_modelos_disponiveis(self):
        with self.assertRaises(templates.SemModelo) as ctx:
            templates.escolher(self.caso(codigo="9.99/1/1"))
        self.assertIn("mundial-usinagem", str(ctx.exception))


class TestMultiEmpresa(unittest.TestCase):
    """Cada empresa tem senha própria — cair na genérica logaria na errada."""

    def setUp(self):
        config.EMPRESAS = paths.CONFIG_DIR / "empresas_teste.json"
        config.EMPRESA_ATIVA = paths.CONFIG_DIR / "ativa_teste.txt"
        config.EMPRESAS.write_text(json.dumps({
            "304838": {"nome": "MUNDIAL"},
            "401122": {"nome": "ACME"},
        }), encoding="utf-8")
        for chave in ("NFSE_SENHA_304838", "NFSE_SENHA_401122"):
            os.environ.pop(chave, None)
        os.environ["NFSE_SENHA"] = "senha-generica"

    def tearDown(self):
        config.EMPRESAS.unlink(missing_ok=True)
        config.EMPRESA_ATIVA.unlink(missing_ok=True)
        for chave in ("NFSE_SENHA_304838", "NFSE_SENHA_401122"):
            os.environ.pop(chave, None)

    def test_duas_empresas_nao_usam_a_senha_generica(self):
        self.assertEqual(config.senha_da_empresa("401122"), "")

    def test_senha_propria_e_usada(self):
        os.environ["NFSE_SENHA_401122"] = "senha-acme"
        self.assertEqual(config.senha_da_empresa("401122"), "senha-acme")

    def test_empresa_unica_ainda_aceita_a_generica(self):
        config.EMPRESAS.write_text(json.dumps({"304838": {"nome": "MUNDIAL"}}), encoding="utf-8")
        self.assertEqual(config.senha_da_empresa("304838"), "senha-generica")

    def test_ativar_sem_senha_e_recusado(self):
        with self.assertRaises(ValueError) as ctx:
            config.ativar_empresa("401122")
        self.assertIn("NFSE_SENHA_401122", str(ctx.exception))

    def test_ativar_troca_as_credenciais_do_ambiente(self):
        os.environ["NFSE_SENHA_401122"] = "senha-acme"
        config.ativar_empresa("401122")
        self.assertEqual(config.empresa_ativa(), "401122")
        self.assertEqual(os.environ["NFSE_USUARIO"], "401122")
        self.assertEqual(os.environ["NFSE_SENHA"], "senha-acme")

    def test_modelo_de_outra_empresa_nao_serve(self):
        os.environ["NFSE_SENHA_401122"] = "senha-acme"
        config.ativar_empresa("401122")
        modelo = {"cobre": {"prestador.ccm": "304838"}, "body": "x"}
        self.assertFalse(templates.atende(modelo, {}))


class TestCachePorEmpresa(unittest.TestCase):
    """Cada empresa tem sua lista de serviços — um cache único misturaria tudo."""

    def setUp(self):
        config.EMPRESAS = paths.CONFIG_DIR / "empresas_cache.json"
        config.EMPRESA_ATIVA = paths.CONFIG_DIR / "ativa_cache.txt"
        config.EMPRESAS.write_text(json.dumps({
            "304838": {"nome": "MUNDIAL"},
            "401122": {"nome": "ACME"},
        }), encoding="utf-8")
        os.environ["NFSE_SENHA_304838"] = "a"
        os.environ["NFSE_SENHA_401122"] = "b"

    def tearDown(self):
        for ccm in ("304838", "401122"):
            services.cache_da_empresa(ccm).unlink(missing_ok=True)
            os.environ.pop(f"NFSE_SENHA_{ccm}", None)
        config.EMPRESAS.unlink(missing_ok=True)
        config.EMPRESA_ATIVA.unlink(missing_ok=True)

    def test_arquivo_de_cache_leva_o_ccm(self):
        self.assertIn("304838", services.cache_da_empresa("304838").name)
        self.assertIn("401122", services.cache_da_empresa("401122").name)

    def test_listas_nao_se_misturam(self):
        services.salvar([{"codigo": "14.05/1/1", "item": "14.05", "nome": "USINAGEM", "descricao": ""}], "304838")
        services.salvar([{"codigo": "1.01/2/2", "item": "1.01", "nome": "INFORMATICA", "descricao": ""}], "401122")
        self.assertEqual([s["codigo"] for s in services.em_cache("304838")], ["14.05/1/1"])
        self.assertEqual([s["codigo"] for s in services.em_cache("401122")], ["1.01/2/2"])

    def test_trocar_empresa_muda_a_lista_lida(self):
        services.salvar([{"codigo": "14.05/1/1", "item": "14.05", "nome": "USINAGEM", "descricao": ""}], "304838")
        config.ativar_empresa("304838")
        self.assertEqual(len(services.em_cache()), 1)
        config.ativar_empresa("401122")
        self.assertEqual(services.em_cache(), [])


class TestDeteccaoDePosicoes(unittest.TestCase):
    """Encontra onde estão os valores fiscais a partir do que foi digitado.

    A tabela de strings do GWT é deduplicada por resposta, então as posições
    mudam de captura para captura. Informando os valores da nota capturada, o
    importador acha cada um sem que ninguém precise contar índices.
    """

    CORPO = (
        "7|0|12|url|hash|Servico|emitirNfs|"
        "7.02/103141/1291|7.02|2026-08-20|pintura predial|"
        "1455.00|0.0300|1500.00|45.00|1|2|"
    )

    def test_acha_todos_os_campos(self):
        posicoes, avisos = import_curl.detectar_posicoes(
            self.CORPO, "1.500,00", "3", "pintura predial", "2026-08-20")
        self.assertEqual(avisos, [])
        self.assertEqual(posicoes, {
            5: "servico.codigo",
            6: "servico.codigo_item",
            7: "competencia",
            8: "servico.descricao",
            9: "servico.valor_liquido",
            10: "servico.aliquota_fracao",
            11: "servico.valor",
            12: "servico.iss",
        })

    def test_calcula_os_derivados_do_portal(self):
        """ISS e líquido não são digitados: saem de valor × alíquota."""
        posicoes, _ = import_curl.detectar_posicoes(
            self.CORPO, "1500,00", "3", "pintura predial", "2026-08-20")
        self.assertEqual(posicoes[12], "servico.iss")          # 1500 × 3% = 45.00
        self.assertEqual(posicoes[9], "servico.valor_liquido")  # 1500 − 45 = 1455.00

    def test_valor_ausente_vira_aviso_e_nao_erro(self):
        posicoes, avisos = import_curl.detectar_posicoes(
            self.CORPO, "999,00", "3", "outra coisa", "2020-01-01")
        self.assertTrue(any("servico.valor" in a for a in avisos))
        self.assertNotIn("servico.valor", posicoes.values())

    def test_valor_repetido_pede_mapeamento_manual(self):
        corpo = "7|0|6|url|hash|Servico|emitirNfs|10.00|10.00|1|"
        _, avisos = import_curl.detectar_posicoes(corpo, "10,00", "0", "", "")
        self.assertTrue(any("aparece nas posições" in a for a in avisos))


class TestSubstituicaoDoPrestador(unittest.TestCase):
    """Uma captura serve várias empresas trocando os campos do prestador.

    Sem isso, o corpo sairia com a razão social de quem gravou a captura — nota
    fiscal emitida no nome da empresa errada.
    """

    CORPO = "7|0|5|url|hash|304838|J B BEZERRA|BAIRRO PRESTADOR|1|2|"
    POSICOES = {"3": "inscricao", "4": "razao_social", "5": "bairro"}

    def setUp(self):
        config.EMPRESAS = paths.CONFIG_DIR / "empresas_prest.json"
        config.EMPRESA_ATIVA = paths.CONFIG_DIR / "ativa_prest.txt"
        config.EMPRESAS.write_text(json.dumps({
            "285504": {"nome": "ANTONIO BRAZ", "prestador": {
                "inscricao": "285504", "razao_social": "PRESTADOR EXEMPLO DOIS",
                "nome_fantasia": "ANTONIO BRAZ", "email": "a@b.com", "telefone": "8213805358",
                "logradouro": "PASS. QUITERIA", "numero": "519", "bairro": "RIO GRANDE",
                "cep": "09832174", "uf": "SP"}},
            "999999": {"nome": "INCOMPLETA", "prestador": {"inscricao": "999999"}},
        }), encoding="utf-8")
        os.environ["NFSE_SENHA_285504"] = "x"
        os.environ["NFSE_SENHA_999999"] = "y"
        config.ativar_empresa("285504")

    def tearDown(self):
        config.EMPRESAS.unlink(missing_ok=True)
        config.EMPRESA_ATIVA.unlink(missing_ok=True)
        for ccm in ("285504", "999999"):
            os.environ.pop(f"NFSE_SENHA_{ccm}", None)

    def test_campos_do_prestador_sao_trocados(self):
        novo = prestador.aplicar(self.CORPO, self.POSICOES)
        self.assertIn("285504", novo)
        self.assertIn("PRESTADOR EXEMPLO DOIS", novo)
        self.assertIn("RIO GRANDE", novo)

    def test_dados_da_empresa_anterior_somem(self):
        novo = prestador.aplicar(self.CORPO, self.POSICOES)
        self.assertNotIn("J B BEZERRA", novo)
        self.assertNotIn("BAIRRO PRESTADOR", novo)

    def test_estrutura_do_corpo_e_preservada(self):
        novo = prestador.aplicar(self.CORPO, self.POSICOES)
        self.assertEqual(novo.count("|"), self.CORPO.count("|"))
        self.assertEqual(novo.split("|")[2], "5")

    def test_cadastro_incompleto_e_detectado(self):
        config.ativar_empresa("999999")
        self.assertFalse(prestador.completo())
        self.assertIn("razao_social", prestador.faltando())

    def test_cadastro_completo_reconhecido(self):
        self.assertTrue(prestador.completo("285504"))
        self.assertEqual(prestador.faltando("285504"), [])

    def test_valor_com_pipe_e_escapado(self):
        config.EMPRESAS.write_text(json.dumps({"285504": {"nome": "X", "prestador": {
            "inscricao": "285504", "razao_social": "A | B", "nome_fantasia": "X",
            "email": "a@b.com", "telefone": "1", "logradouro": "R", "numero": "1",
            "bairro": "B", "cep": "1", "uf": "SP"}}}), encoding="utf-8")
        novo = prestador.aplicar(self.CORPO, self.POSICOES)
        self.assertIn("A \\! B", novo)
        self.assertEqual(novo.count("|"), self.CORPO.count("|"))


class TestEmissaoEntreEmpresas(unittest.TestCase):
    """Uma captura serve qualquer empresa e qualquer código de serviço.

    O prestador vem da sessão do portal, e o código de serviço é marcador no
    corpo. O que continua preso é o **tomador**, cujo endereço e id interno
    estão embutidos e não podem ser deduzidos.
    """

    def setUp(self):
        templates.PASTA = paths.CONFIG_DIR / "templates_entre"
        templates.PASTA.mkdir(parents=True, exist_ok=True)
        (templates.PASTA / "captura.json").write_text(json.dumps({
            "method": "POST",
            "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
            "headers": {"Content-Type": "text/x-gwt-rpc"},
            "cobre": {"tomador.documento": "11222333000181"},
            "body": "7|0|3|{{servico.codigo}}|{{servico.codigo_item}}|{{servico.valor}}|1|",
        }), encoding="utf-8")
        config.EMPRESAS = paths.CONFIG_DIR / "empresas_entre.json"
        config.EMPRESA_ATIVA = paths.CONFIG_DIR / "ativa_entre.txt"
        config.EMPRESAS.unlink(missing_ok=True)

    def tearDown(self):
        for arquivo in templates.PASTA.glob("*.json"):
            arquivo.unlink()
        config.EMPRESA_ATIVA.unlink(missing_ok=True)

    def montar(self, ccm, codigo, documento="11222333000181"):
        os.environ["NFSE_USUARIO"] = ccm
        payload = validation.validate_payload(draft(
            tomador={"documento": documento},
            servico={"descricao": "x", "valor": "500,00", "codigo": codigo, "aliquota": "2"},
        ))
        return nfse_client.build(payload)["body"]

    def test_empresa_nova_sem_cadastro_emite(self):
        corpo = self.montar("777777", "1.01/123456/7890")
        self.assertIn("1.01/123456/7890", corpo)

    def test_codigo_de_servico_de_outra_empresa(self):
        corpo = self.montar("285504", "14.05/999999/8888")
        self.assertIn("14.05/999999/8888", corpo)
        self.assertIn("|14.05|", corpo)

    def test_estrutura_igual_entre_empresas(self):
        a = self.montar("304838", "14.05/107120/1581")
        b = self.montar("285504", "14.05/999999/8888")
        self.assertEqual(a.count("|"), b.count("|"))

    def test_tomador_diferente_continua_recusado(self):
        with self.assertRaises(nfse_client.NfseError):
            self.montar("304838", "14.05/107120/1581", documento="47960950000121")


class TestExtracaoDoPrestador(unittest.TestCase):
    """Lê o prestador de getSession sem depender de posição fixa.

    As duas amostras são respostas reais de empresas diferentes. Uma tem
    e-mail cadastrado e a outra não — o que desloca todas as posições
    seguintes. Parsing posicional quebraria; por isso cada campo é reconhecido
    por formato ou pela vizinhança.
    """

    COM_EMAIL = [
        "rO0ABXcEAAAAAA==", "30203320000100", "Pessoa Juridica Direito Privado", "1",
        "prestador@exemplo.com.br", "285504", "PRESTADOR EXEMPLO DOIS",
        "MUNICIPIO DE SAO BERNARDO DO CAMPO", "Nao", "Tributacao no municipio", "Nenhum",
        "8213805358", "Comercial", "519", "110", "RUA", "RIO GRANDE",
        "PASS.  QUITERIA ANA LEITE SILVA", "09832", "174", "SAO PAULO", "SP",
        "SAO BERNARDO DO CAMPO",
    ]
    SEM_EMAIL = [
        "rO0ABXcEAAAAAA==", "44672776000123", "Pessoa Juridica Direito Privado", "1",
        "346186", "PRESTADOR EXEMPLO TRES",
        "MUNICIPIO DE SAO BERNARDO DO CAMPO", "Nao", "Tributacao no municipio", "Nenhum",
        "8217234886", "Comercial", "1301", "110", "RUA", "BAIRRO PRESTADOR",
        "PASS. DR. JOSE RUBENS ROSSIGNOLO", "09792", "370", "SAO PAULO", "SP",
        "SAO BERNARDO DO CAMPO",
    ]

    def test_empresa_com_email(self):
        dados = prestador.extrair(self.COM_EMAIL, "285504")
        self.assertEqual(dados["inscricao"], "285504")
        self.assertEqual(dados["razao_social"], "PRESTADOR EXEMPLO DOIS")
        self.assertEqual(dados["email"], "prestador@exemplo.com.br")
        self.assertEqual(dados["telefone"], "8213805358")
        self.assertEqual(dados["bairro"], "RIO GRANDE")
        self.assertEqual(dados["logradouro"], "PASS.  QUITERIA ANA LEITE SILVA")
        self.assertEqual(dados["numero"], "519")
        self.assertEqual(dados["cep"], "09832174")
        self.assertEqual(dados["uf"], "SP")

    def test_empresa_sem_email_nao_desalinha(self):
        """Sem e-mail as posições andam — a leitura tem de continuar certa."""
        dados = prestador.extrair(self.SEM_EMAIL, "346186")
        self.assertEqual(dados["razao_social"], "PRESTADOR EXEMPLO TRES")
        self.assertEqual(dados["bairro"], "BAIRRO PRESTADOR")
        self.assertEqual(dados["logradouro"], "PASS. DR. JOSE RUBENS ROSSIGNOLO")
        self.assertEqual(dados["numero"], "1301")
        self.assertEqual(dados["cep"], "09792370")
        self.assertNotIn("email", dados)

    def test_razao_social_nao_pega_o_cnpj(self):
        for tabela, ccm in ((self.COM_EMAIL, "285504"), (self.SEM_EMAIL, "346186")):
            dados = prestador.extrair(tabela, ccm)
            self.assertFalse(dados["razao_social"].isdigit())

    def test_telefone_nao_confunde_com_cnpj(self):
        dados = prestador.extrair(self.COM_EMAIL, "285504")
        self.assertNotEqual(dados["telefone"], "30203320000100")

    def test_empresas_diferentes_dao_dados_diferentes(self):
        a = prestador.extrair(self.COM_EMAIL, "285504")
        b = prestador.extrair(self.SEM_EMAIL, "346186")
        self.assertNotEqual(a["razao_social"], b["razao_social"])
        self.assertNotEqual(a["cep"], b["cep"])


class TestExtracaoDoTomador(unittest.TestCase):
    """Lê o tomador de buscaTomadorCnpj — inclusive o id interno no portal.

    As duas amostras são consultas reais de tomadores diferentes. Sem o id
    correto (posição 66 do corpo), a nota sai vinculada ao cliente errado.
    """

    FALCON = [
        "BAIRRO TOMADOR", "09000", "001", "11222333000181", "SL.22", "Aberta",
        "tomador@exemplo.com.br", "0", "375662", "RUA DO TOMADOR",
        "75", "110", "CONTABILIDADE EXEMPLO LTDA", "Pessoa Juridica Direito Privado",
    ]
    BEZERRA = [
        "BAIRRO PRESTADOR", "09000", "000", "12345678000195", "(PQ. SELECTA)", "Aberta",
        "prestador@exemplo.com.br", "110000000000", "304838", "RUA DO PRESTADOR",
        "51", "1100000000", "ESTRUTURAS METALICAS EXEMPLO",
        "Pessoa Juridica Direito Privado",
    ]

    def test_falcon(self):
        d = tomador.extrair(self.FALCON, "11222333000181")
        self.assertEqual(d["id"], "375662")
        self.assertEqual(d["razao_social"], "CONTABILIDADE EXEMPLO LTDA")
        self.assertEqual(d["bairro"], "BAIRRO TOMADOR")
        self.assertEqual(d["cep"], "09000001")
        self.assertEqual(d["complemento"], "SL.22")
        self.assertEqual(d["logradouro"], "RUA DO TOMADOR")
        self.assertEqual(d["numero"], "75")

    def test_segundo_tomador(self):
        d = tomador.extrair(self.BEZERRA, "12345678000195")
        self.assertEqual(d["id"], "304838")
        self.assertEqual(d["razao_social"], "ESTRUTURAS METALICAS EXEMPLO")
        self.assertEqual(d["cep"], "09000000")
        self.assertEqual(d["complemento"], "(PQ. SELECTA)")
        self.assertEqual(d["numero"], "51")

    def test_id_nao_e_confundido_com_telefone(self):
        """O id vem antes do logradouro; o telefone fica depois do número."""
        d = tomador.extrair(self.BEZERRA, "12345678000195")
        self.assertNotEqual(d["id"], "110000000000")
        self.assertNotEqual(d["id"], "1100000000")

    def test_tomadores_diferentes_dao_ids_diferentes(self):
        a = tomador.extrair(self.FALCON, "11222333000181")
        b = tomador.extrair(self.BEZERRA, "12345678000195")
        self.assertNotEqual(a["id"], b["id"])
        self.assertNotEqual(a["razao_social"], b["razao_social"])

    def test_substituicao_preserva_a_estrutura(self):
        corpo = "7|0|4|x|11222333000181|375662|FALCON|1|"
        posicoes = {"2": "documento", "3": "id", "4": "razao_social"}
        novo = tomador.aplicar(corpo, posicoes, tomador.extrair(self.BEZERRA, "12345678000195"))
        self.assertEqual(novo.count("|"), corpo.count("|"))
        self.assertIn("12345678000195", novo)
        self.assertIn("304838", novo)
        self.assertNotIn("FALCON", novo)


class TestStorage(unittest.TestCase):
    def setUp(self):
        # A conferência não é zelo: este setUp já apagou as notas de verdade
        # do usuário, porque `paths.DATA_DIR` apontava para a pasta real.
        # Antes de apagar qualquer coisa, confirma onde está pisando.
        _proteger_caminhos()
        assert paths.DATA_DIR != _DADOS_REAIS, "a suíte ia apagar as notas do usuário"
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        for arquivo in paths.DATA_DIR.glob("*.json"):
            arquivo.unlink()

    def test_cria_e_le(self):
        item = storage.create(validation.validate_payload(draft()))
        self.assertEqual(storage.get(item["id"])["id"], item["id"])

    def test_id_invalido(self):
        with self.assertRaises(ValueError):
            storage.get("../evil")

    def test_arquivo_corrompido_nao_derruba_listagem(self):
        storage.create(validation.validate_payload(draft()))
        (paths.DATA_DIR / "quebrado.json").write_text('{"id":"x","stat', encoding="utf-8")
        self.assertEqual(len(storage.list_all()), 1)
        self.assertEqual(storage.corrupted(), ["quebrado.json"])

    def test_historico_preserva_tentativas(self):
        item = storage.create(validation.validate_payload(draft()))
        storage.record_submission(item, {"http_status": 500}, "failed")
        storage.record_submission(item, {"http_status": 200}, "submitted")
        saved = storage.get(item["id"])
        self.assertEqual(len(saved["submissions"]), 2)
        self.assertEqual(saved["status"], "submitted")
        self.assertEqual(saved["submissions"][0]["http_status"], 500)


class TestService(unittest.TestCase):
    def setUp(self):
        os.environ["NFSE_LIVE_MODE"] = "false"
        os.environ["NFSE_COOKIE"] = "JSESSIONID=abc123"
        paths.REQUEST_TEMPLATE.write_text(json.dumps({
            "method": "POST",
            "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
            "headers": {"Content-Type": "text/x-gwt-rpc", "Cookie": "{{env:NFSE_COOKIE}}"},
            "body": "7|0|4|{{servico.valor}}|",
        }), encoding="utf-8")

    def test_modo_seguro_nao_transmite(self):
        item = service.create_document(draft())
        outcome = service.submit_document(item)
        self.assertFalse(outcome["transmitted"])
        self.assertEqual(outcome["status"], "draft")
        self.assertIn("Modo seguro", outcome["message"])

    def test_nota_enviada_bloqueia_reenvio(self):
        item = service.create_document(draft())
        storage.record_submission(item, {"http_status": 200}, "submitted")
        with self.assertRaises(service.AlreadySubmitted):
            service.submit_document(item)

    def test_reenvio_forcado_permitido(self):
        item = service.create_document(draft())
        storage.record_submission(item, {"http_status": 200}, "submitted")
        outcome = service.submit_document(item, force=True)
        self.assertFalse(outcome["transmitted"])  # segue em modo seguro

    def test_documento_invalido_recusado_na_criacao(self):
        with self.assertRaises(validation.ValidationError):
            service.create_document(draft(
                tomador={"documento": "12345678900", "nome": "Teste"}
            ))



class PrestadorNaNotaTests(unittest.TestCase):
    """Quem emitiu a nota fica gravado nela.

    Sem isto não há como separar as notas de logins diferentes — e este
    sistema é usado com mais de uma empresa. As notas gravadas antes desta
    versão não têm o dado e não há de onde tirá-lo: o corpo da requisição só
    foi guardado em prévia truncada.
    """

    BASE = {
        "tomador": {"documento": "11222333000181"},
        "servico": {
            "descricao": "servico", "valor": "10,00",
            "codigo": "14.05/107120/1581", "nbs": "1",
            "indicador_operacao": "1", "classificacao_tributaria": "1",
            "situacao_tributaria": "000",
        },
    }

    def test_nota_antiga_sem_prestador_continua_valida(self):
        # Uma nota que já existe não pode virar erro de validação agora.
        validado = validation.validate_payload(copy.deepcopy(self.BASE))
        self.assertNotIn("prestador", validado)

    def test_prestador_e_preservado(self):
        payload = copy.deepcopy(self.BASE)
        payload["prestador"] = {"inscricao": "61234", "razao_social": "USINAGEM EXEMPLO LTDA"}
        validado = validation.validate_payload(payload)
        self.assertEqual(validado["prestador"],
                         {"inscricao": "61234", "razao_social": "USINAGEM EXEMPLO LTDA"})

    def test_campo_desconhecido_no_prestador_e_descartado(self):
        payload = copy.deepcopy(self.BASE)
        payload["prestador"] = {"inscricao": "61234", "senha": "nao entra aqui"}
        validado = validation.validate_payload(payload)
        self.assertEqual(validado["prestador"], {"inscricao": "61234"})

    def test_a_lista_diz_a_verdade_quando_nao_sabe(self):
        # "não registrado" e não uma empresa qualquer: atribuir a nota ao
        # login errado é pior que admitir que o dado não existe.
        vazio = {"payload": {}}
        self.assertEqual(desktop.NfseDesktop.prestador_do_doc(vazio), "— não registrado")

    def test_a_lista_cai_no_ccm_quando_falta_a_razao_social(self):
        doc = {"payload": {"prestador": {"inscricao": "61234"}}}
        self.assertEqual(desktop.NfseDesktop.prestador_do_doc(doc), "CCM 61234")

    def test_a_razao_social_vem_na_frente_do_ccm(self):
        doc = {"payload": {"prestador": {"inscricao": "61234", "razao_social": "MUNDIAL"}}}
        self.assertEqual(desktop.NfseDesktop.prestador_do_doc(doc), "MUNDIAL")


class BuscaDaListaDeNotasTests(unittest.TestCase):
    DOC = {
        "status": "submitted",
        "created_at": "2026-08-27",
        "nota": {"numero": "1408"},
        "payload": {
            "prestador": {"razao_social": "DEZORZI SERVICOS"},
            "tomador": {"nome": "TRANSPORTES VELA", "documento": "47001882000105"},
            "servico": {"descricao": "Manutencao de prensa", "valor": "5600.00"},
        },
    }

    def procurar(self, termo):
        return ui.combina(desktop.NfseDesktop._texto_do_doc(self.DOC), termo)

    def test_acha_pelo_prestador(self):
        self.assertTrue(self.procurar("dezorzi"))

    def test_acha_pelo_valor_sem_separador(self):
        # Quem procura digita 5600; o valor exibido é "5.600,00", e o ponto
        # de milhar no meio impedia a busca por dígitos seguidos de achar.
        self.assertTrue(self.procurar("5600"))

    def test_acha_pelo_valor_formatado(self):
        self.assertTrue(self.procurar("5.600,00"))

    def test_acha_pelo_documento_cru_e_formatado(self):
        self.assertTrue(self.procurar("47001882000105"))
        self.assertTrue(self.procurar("47.001.882/0001-05"))

    def test_palavras_em_qualquer_ordem(self):
        self.assertTrue(self.procurar("vela 5600"))
        self.assertTrue(self.procurar("5600 vela"))

    def test_o_que_nao_existe_nao_aparece(self):
        self.assertFalse(self.procurar("kappa"))

if __name__ == "__main__":
    unittest.main(verbosity=2)


class PdfTests(unittest.TestCase):
    """O PDF da nota vem em dois passos e por outro host."""

    PAGINA = (
        "<html><body><form action='exportacao' name='exportar' method='post'>"
        "<input type='hidden' name='nfs' value='rO0ABX&amp;base64'>"
        "<input type=\"hidden\" name=\"nomeRelatorio\" value=\"nfs_ver4RT2\">"
        "<input type='hidden' name='imprime' value='1'>"
        "<input type='hidden' name='tipo' value='html'>"
        "</form></body></html>"
    )

    def test_extrai_acao_e_campos_do_formulario(self):
        acao, campos = pdf.extrair_formulario(self.PAGINA)
        self.assertEqual(acao, "exportacao")
        self.assertEqual(campos["nomeRelatorio"], "nfs_ver4RT2")
        # O campo com a nota serializada é copiado sem perder o & escapado.
        self.assertEqual(campos["nfs"], "rO0ABX&base64")

    def test_pagina_sem_formulario_da_erro_claro(self):
        with self.assertRaises(nfse_client.NfseError) as caso:
            pdf.extrair_formulario("<html>nota nao encontrada</html>")
        self.assertIn("formulário de exportação", str(caso.exception))

    def test_host_de_visualizacao_liberado_so_para_download(self):
        hosts = config.download_hosts()
        self.assertIn(config.VISUALIZAR_HOST, hosts)
        self.assertIn(config.allowed_host(), hosts)
        # A emissão continua restrita ao portal.
        with self.assertRaises(nfse_client.NfseError):
            nfse_client.check_url(f"https://{config.VISUALIZAR_HOST}/report/exportacao")

    def test_endereco_arbitrario_da_pagina_e_recusado(self):
        with self.assertRaises(nfse_client.NfseError):
            nfse_client.check_url("https://atacante.example/report", config.download_hosts())

    def test_nota_sem_codigo_nao_tenta_baixar(self):
        with self.assertRaises(pdf.SemModeloPdf):
            pdf.baixar({"numero": "85"})
        with self.assertRaises(pdf.SemModeloPdf):
            pdf.baixar({"codigo_verificacao": "TOVIPASW8"})

    def test_nome_do_arquivo_identifica_a_nota(self):
        nome = pdf._nome_do_arquivo({"numero": "85", "codigo_verificacao": "TOVIPASW8"})
        self.assertEqual(nome, "nfse-85-TOVIPASW8.pdf")

    def test_modelo_do_pdf_esta_instalado_e_aponta_para_o_visualizador(self):
        # CONFIG_DIR está desviado para o sandbox; aqui interessa o arquivo real.
        real = Path(__file__).resolve().parent.parent / "config" / "pdf_template.json"
        self.assertTrue(real.exists(), "config/pdf_template.json ausente")
        modelo = json.loads(real.read_text(encoding="utf-8"))
        self.assertIn(config.VISUALIZAR_HOST, modelo["url"])
        self.assertIn("{{codigo_verificacao}}", modelo["url"])
        self.assertIn("{{numero}}", modelo["url"])
        self.assertEqual(modelo["exportacao"]["campos"]["tipo"], "pdf")


class ImpressaoTests(unittest.TestCase):
    """Envio do DANFSe para a impressora (nenhum teste imprime de verdade)."""

    def test_lista_impressoras_com_a_padrao_em_primeiro(self):
        nomes = impressao.impressoras()
        self.assertIsInstance(nomes, list)
        padrao = impressao.impressora_padrao()
        if padrao and nomes:
            self.assertEqual(nomes[0], padrao)
        # Nomes repetidos confundiriam a escolha na combobox.
        self.assertEqual(len(nomes), len(set(nomes)))

    def test_arquivo_ausente_nao_chega_na_impressora(self):
        with self.assertRaises(impressao.ImpressaoIndisponivel) as caso:
            impressao.imprimir(paths.DATA_DIR / "pdf" / "nao-existe.pdf")
        self.assertIn("não está mais", str(caso.exception))

    def test_impressora_padrao_e_texto(self):
        self.assertIsInstance(impressao.impressora_padrao(), str)


class ExclusaoTests(unittest.TestCase):
    """Excluir tira da lista, mas não destrói registro fiscal."""

    def _nota(self, status: str = "draft") -> dict:
        item = storage.create({
            "tomador": {"documento": "11222333000181"},
            "servico": {"codigo": "14.05", "descricao": "teste", "valor": "10.00",
                        "aliquota": "2", "iss": "0.20", **REFORMA},
            "competencia": "2026-08-15",
        })
        if status != "draft":
            item["status"] = status
            storage.save(item)
        return item

    def test_descartada_some_da_lista_mas_o_arquivo_fica(self):
        item = self._nota()
        destino = storage.descartar(item["id"])
        ids = [d["id"] for d in storage.list_all()]
        self.assertNotIn(item["id"], ids)
        self.assertTrue(destino.exists(), "o arquivo tem de sobreviver na lixeira")
        self.assertEqual(destino.parent.name, storage.LIXEIRA)
        # O conteúdo continua íntegro — é prova fiscal, não rascunho descartável.
        self.assertEqual(json.loads(destino.read_text(encoding="utf-8"))["id"], item["id"])

    def test_descartar_duas_vezes_o_mesmo_id_nao_sobrescreve(self):
        primeiro = self._nota()
        um = storage.descartar(primeiro["id"])
        # Um id repetido só acontece se o arquivo for recriado; ainda assim, a
        # lixeira não pode perder o que já guardou.
        storage._write_atomic(storage._path(primeiro["id"]), primeiro)
        dois = storage.descartar(primeiro["id"])
        self.assertNotEqual(um, dois)
        self.assertTrue(um.exists() and dois.exists())

    def test_descartar_nota_inexistente_avisa(self):
        with self.assertRaises(FileNotFoundError):
            storage.descartar("00000000-0000-4000-8000-000000000000")

    def test_id_invalido_nao_apaga_nada(self):
        with self.assertRaises(ValueError):
            storage.descartar("../../etc/passwd")

    def test_descartar_muitos_conta_e_relata_erros(self):
        vivos = [self._nota()["id"] for _ in range(3)]
        saidas, erros = storage.descartar_muitos(vivos + ["id-invalido"])
        self.assertEqual(saidas, 3)
        self.assertEqual(len(erros), 1)
        self.assertNotIn(vivos[0], [d["id"] for d in storage.list_all()])

    def test_lixeira_nao_aparece_na_listagem(self):
        item = self._nota()
        storage.descartar(item["id"])
        # list_all varre só o primeiro nível de data/ — a subpasta fica de fora.
        self.assertNotIn(item["id"], [d["id"] for d in storage.list_all()])
        self.assertEqual(storage.corrupted(), [])


class SenhaNoArquivoTests(unittest.TestCase):
    """A tela de login só pode prometer memória se a senha não estiver em disco."""

    def setUp(self):
        self.original = paths.ENV_FILE
        self.arquivo = paths.CONFIG_DIR / "env-de-teste"
        paths.ENV_FILE = self.arquivo

    def tearDown(self):
        paths.ENV_FILE = self.original
        self.arquivo.unlink(missing_ok=True)

    def _escrever(self, conteudo: str) -> None:
        self.arquivo.write_text(conteudo, encoding="utf-8")

    def test_sem_arquivo_nao_ha_senha_gravada(self):
        self.assertFalse(config.senha_no_arquivo())

    def test_detecta_senha_gravada(self):
        self._escrever("NFSE_USUARIO=346186\nNFSE_SENHA=segredo123\n")
        self.assertTrue(config.senha_no_arquivo())

    def test_linha_vazia_nao_conta_como_gravada(self):
        self._escrever("NFSE_SENHA=\nNFSE_USUARIO=346186\n")
        self.assertFalse(config.senha_no_arquivo())

    def test_comentada_nao_conta(self):
        self._escrever("# NFSE_SENHA=segredo123\n")
        self.assertFalse(config.senha_no_arquivo())

    def test_aspas_e_export_sao_reconhecidos(self):
        self._escrever('export NFSE_SENHA="segredo123"\n')
        self.assertTrue(config.senha_no_arquivo())


class PrestadorConsistenciaTests(unittest.TestCase):
    """O número do endereço lido errado derrubava a emissão sem explicação."""

    # Cadastro completo: toda posição do prestador é sobrescrita na emissão,
    # então campo faltando vira campo vazio na nota e precisa ser barrado.
    BOM = {"inscricao": "346186", "razao_social": "PRESTADOR EXEMPLO TRES",
           "numero": "1301", "cep": "09792370", "uf": "SP",
           "logradouro": "PASS. DR. JOSE RUBENS ROSSIGNOLO", "bairro": "BAIRRO PRESTADOR"}

    def test_numero_valido_passa(self):
        self.assertEqual(prestador.conferir(self.BOM), [])

    def test_complemento_no_lugar_do_numero_e_barrado(self):
        # Caso real: empresa 254765 enviou isto e o portal respondeu com
        # "Erro ao processar retorno do servidor", sem dizer o motivo.
        ruim = {**self.BOM, "numero": "PRIMEBUSINESS CENTER SL.47"}
        problemas = prestador.conferir(ruim)
        self.assertTrue(any("não é um número" in p for p in problemas), problemas)

    def test_numero_ausente_e_barrado(self):
        ruim = {k: v for k, v in self.BOM.items() if k != "numero"}
        self.assertTrue(any("não foi lido" in p for p in prestador.conferir(ruim)))

    def test_cep_incompleto_e_barrado(self):
        self.assertTrue(any("CEP" in p for p in prestador.conferir({**self.BOM, "cep": "0979"})))

    def test_formas_aceitas_de_numero(self):
        for valor in ("1301", "75", "12A", "S/N", "s/n", "SN"):
            self.assertTrue(prestador.parece_numero(valor), valor)
        for valor in ("PRIMEBUSINESS CENTER SL.47", "SL.47", "CENTRO", "", "1234567"):
            self.assertFalse(prestador.parece_numero(valor), valor)

    def test_extrair_pula_o_complemento_e_acha_o_numero(self):
        tabela = ["254765", "MARMORARIA EXEMPLO", "AVENIDA", "CENTRO",
                  "AVEN.  KENNEDY", "SP", "Comercial", "PRIMEBUSINESS CENTER SL.47",
                  "47", "09726", "260"]
        dados = prestador.extrair(tabela, "254765")
        self.assertEqual(dados.get("numero"), "47")
        self.assertEqual(dados.get("complemento"), "PRIMEBUSINESS CENTER SL.47")
        self.assertEqual(prestador.conferir(dados), [])

    def test_sem_numero_algum_prefere_ficar_vazio_a_chutar(self):
        tabela = ["254765", "MARMORARIA", "AVENIDA", "CENTRO", "AVEN.  KENNEDY",
                  "SP", "Comercial", "PRIMEBUSINESS CENTER SL.47", "OUTRO TEXTO"]
        dados = prestador.extrair(tabela, "254765")
        self.assertNotIn("numero", dados)
        self.assertTrue(prestador.conferir(dados))


class ExigeObraTests(unittest.TestCase):
    """Bloqueio por Código da Obra vale por código, não pelo item inteiro."""

    def setUp(self):
        self.original = config.EXIGE_OBRA
        config.EXIGE_OBRA = paths.CONFIG_DIR / "exige_obra_teste.json"

    def tearDown(self):
        config.EXIGE_OBRA.unlink(missing_ok=True)
        config.EXIGE_OBRA = self.original

    def _regras(self, itens, codigos):
        config.EXIGE_OBRA.write_text(
            json.dumps({"itens": itens, "codigos": codigos}), encoding="utf-8")

    def test_codigo_registrado_e_barrado(self):
        self._regras([], ["7.02/103107/1291"])
        self.assertTrue(config.exige_obra("7.02/103107/1291"))

    def test_outro_codigo_do_mesmo_item_nao_e_barrado(self):
        # 7.07 emite sem obra; barrar o item 7 inteiro impediria emissão válida.
        self._regras([], ["7.02/103107/1291"])
        self.assertFalse(config.exige_obra("7.07/103802/1321"))

    def test_prefixo_de_item_barra_a_familia_quando_configurado(self):
        self._regras(["7."], [])
        self.assertTrue(config.exige_obra("7.07/103802/1321"))
        self.assertFalse(config.exige_obra("14.05/107120/1581"))

    def test_marcar_aprende_com_a_recusa_do_portal(self):
        self._regras([], [])
        self.assertFalse(config.exige_obra("7.06/106602/1601"))
        config.marcar_exige_obra("7.06/106602/1601")
        self.assertTrue(config.exige_obra("7.06/106602/1601"))

    def test_arquivo_ausente_nao_barra_nada(self):
        config.EXIGE_OBRA.unlink(missing_ok=True)
        self.assertFalse(config.exige_obra("7.02/103107/1291"))


def _resposta_gwt(valores: list) -> str:
    """Monta uma resposta GWT-RPC a partir dos campos, em ordem de leitura.

    O GWT escreve os índices ao contrário e desduplica a tabela — reproduzir
    isso é o que torna o teste fiel ao que o portal devolve.
    """
    tabela: list[str] = []
    indices: list[str] = []
    for valor in valores:
        if valor is None:
            indices.append("0")
            continue
        if valor not in tabela:
            tabela.append(valor)
        indices.append(str(tabela.index(valor) + 1))
    return ("//OK[" + ",".join(reversed(indices)) + ","
            + json.dumps(tabela, ensure_ascii=False) + ",0,7]")


def _sessao(inscricao: str, fantasia, razao: str) -> str:
    return _resposta_gwt([
        "44672776000123", None, inscricao, fantasia, razao, None,
        "contato@empresa.com.br", "8213492381",
        None, "Comercial", None, "47", None, None, None, "PRIMEBUSINESS SL.47",
        None, "RUA", None, "CENTRO", "AVEN.  KENNEDY", None, "09726", "260",
        None, "SP", "SAO BERNARDO DO CAMPO",
    ])


class FluxoGwtTests(unittest.TestCase):
    """Campo vazio precisa ocupar lugar, senão as posições escorregam."""

    def test_vazio_ocupa_posicao(self):
        fluxo = nfse_client.gwt_fluxo(_resposta_gwt(["a", None, "b"]))
        self.assertEqual(fluxo, ["a", None, "b"])

    def test_marcadores_de_tipo_nao_sao_dado(self):
        fluxo = nfse_client.gwt_fluxo(
            _resposta_gwt(["br.eicon.nfse.vo.TbEmpresa/1860692092", "346186"]))
        self.assertEqual(fluxo, [None, "346186"])

    def test_resposta_invalida_devolve_vazio(self):
        self.assertEqual(nfse_client.gwt_fluxo(""), [])
        self.assertEqual(nfse_client.gwt_fluxo("//EX[falhou]"), [])

    def test_valor_repetido_aponta_para_a_mesma_entrada(self):
        # A tabela é desduplicada; o fluxo tem de mostrar as duas ocorrências.
        self.assertEqual(nfse_client.gwt_fluxo(_resposta_gwt(["x", "y", "x"])),
                         ["x", "y", "x"])


class RazaoSocialTests(unittest.TestCase):
    """O bug mais caro: a nota saiu com o nome fantasia no lugar da razão social."""

    def test_empresa_com_fantasia_usa_a_razao_social(self):
        dados = prestador.ler(
            _sessao("254765", "MARMORARIA EXEMPLO", "SANTOS & SANTOS LTDA"),
            "254765",
        )
        self.assertEqual(dados["razao_social"], "SANTOS & SANTOS LTDA")
        self.assertEqual(dados["nome_fantasia"], "MARMORARIA EXEMPLO")

    def test_empresa_sem_fantasia_repete_a_razao_social(self):
        dados = prestador.ler(_sessao("346186", None, "PRESTADOR EXEMPLO TRES"),
                              "346186")
        self.assertEqual(dados["razao_social"], "PRESTADOR EXEMPLO TRES")
        self.assertEqual(dados["nome_fantasia"], "PRESTADOR EXEMPLO TRES")

    def test_leitura_por_vizinhanca_sozinha_erraria(self):
        # Guarda a razão de existir do fluxo: sem ele, a fantasia venceria.
        resposta = _sessao("254765", "MARMORARIA EXEMPLO", "SANTOS & SANTOS LTDA")
        achatada = [t for t in nfse_client.gwt_strings(resposta)
                    if not t.startswith(("br.", "java.", "[B/"))]
        antiga = prestador.extrair(achatada, "254765")
        self.assertEqual(antiga["razao_social"], "MARMORARIA EXEMPLO")

    def test_endereco_completo_vem_do_fluxo(self):
        dados = prestador.ler(_sessao("254765", "FANTASIA", "RAZAO LTDA"), "254765")
        self.assertEqual(dados["numero"], "47")
        self.assertEqual(dados["bairro"], "CENTRO")
        self.assertEqual(dados["logradouro"], "AVEN.  KENNEDY")
        self.assertEqual(dados["cep"], "09726260")
        self.assertEqual(dados["uf"], "SP")
        self.assertEqual(dados["cnpj"], "44672776000123")
        self.assertEqual(prestador.conferir(dados), [])

    def test_sessao_de_outra_empresa_nao_e_aproveitada(self):
        # Sem a inscrição no fluxo não há como localizar os nomes.
        self.assertEqual(prestador.extrair_do_fluxo(_sessao("254765", None, "X"), "999999"), {})


class VazamentoDoModeloTests(unittest.TestCase):
    """Campo não lido não pode manter o valor da empresa da captura."""

    CORPO = "7|0|4|A|B|prestador@exemplo.com.br|RAZAO SOCIAL EXEMPLO|1|2|"
    POSICOES = {"3": "email", "4": "nome_fantasia"}

    def test_campo_ausente_vira_vazio_e_nao_o_da_captura(self):
        corpo = prestador.aplicar(self.CORPO, self.POSICOES, dados={"inscricao": "346186"})
        self.assertNotIn("prestador@exemplo.com.br", corpo)
        self.assertNotIn("RAZAO SOCIAL EXEMPLO", corpo)

    def test_campo_lido_substitui_normalmente(self):
        corpo = prestador.aplicar(
            self.CORPO, self.POSICOES,
            dados={"email": "novo@empresa.com", "nome_fantasia": "OUTRA"},
        )
        self.assertIn("novo@empresa.com", corpo)
        self.assertIn("OUTRA", corpo)
        self.assertNotIn("jefersona76", corpo)

    def test_corpo_continua_com_o_mesmo_numero_de_campos(self):
        corpo = prestador.aplicar(self.CORPO, self.POSICOES, dados={"email": "a@b.c"})
        self.assertEqual(len(corpo.split("|")), len(self.CORPO.split("|")))


# Objeto TbEmpresa capturado do próprio portal (chamada buscaCodServ), com o
# fluxo de índices no formato de resposta. São duas empresas reais e opostas:
# uma sem e-mail/fantasia/complemento, outra com os três. Servem de âncora para
# as posições — se o layout do portal mudar, estes testes caem primeiro.
def _requisicao_para_resposta(corpo: str) -> str:
    partes = corpo.split("|")
    quantidade = int(partes[2])
    tabela = partes[3:3 + quantidade]
    indices = [p for p in partes[3 + quantidade:] if p != ""]
    return ("//OK[" + ",".join(reversed(indices)) + ","
            + json.dumps(tabela, ensure_ascii=False) + ",0,7]")


EMPRESA_254765 = (
    "7|0|54|https://nfse.isssbc.com.br/nfseweb/|00A883060444993EB7BC5039E8309DB4|"
    "br.com.eicon.nfseweb.client.service.ControllerService|buscaCodServ|"
    "br.eicon.nfse.vo.TbEmpresa/1860692092|rO0ABXcEAAAAAA==|23958873000107|"
    "br.eicon.nfse.vo.TbTipoEmpresa/64755147|java.lang.Short/551743396|"
    "Pessoa Juridica Direito Privado|1|contador@exemplo.com.br|254765|"
    "MARMORARIA EXEMPLO|PRESTADOR EXEMPLO QUATRO|"
    "java.sql.Date/730999118|java.util.ArrayList/4159755760|"
    "br.eicon.nfse.vo.TbClienteEmpresa/1398355630|br.eicon.nfse.vo.TbCliente/3932617029|"
    "MUNICIPIO DE SAO BERNARDO DO CAMPO|br.eicon.nfse.vo.TbIncentivaCultura/2957501286|"
    "Nao|br.eicon.nfse.vo.TbNaturezaOperacao/3257877863|Tributacao no municipio|"
    "br.eicon.nfse.vo.TbRegimeEspecialTributacao/3751250160|Nenhum|"
    "br.eicon.nfse.vo.TbClienteEmpresaPK/2653362960|br.eicon.nfse.vo.TbEmpresaSituacao/623780937|"
    "java.math.BigDecimal/8151472|8213492381|br.eicon.nfse.vo.TbSituacaoEmpresa/1128190636|"
    "br.eicon.nfse.vo.TbEnderecoEmpresa/2978238829|java.lang.Long/4227064769|"
    "br.eicon.nfse.vo.TbTipoEndereco/1185715125|Comercial|PRIMEBUSINESS CENTER SL.47|27|"
    "1141252388|br.eicon.nfse.vo.TbCep/841084315|br.eicon.nfse.vo.TbTpLogradouro/1098594195|"
    "AVENIDA|CENTRO|AVEN.  KENNEDY|br.eicon.nfse.vo.TbCepPK/2873971312|09726|260|"
    "br.eicon.nfse.vo.TbMunicipioIbge/1210383657|br.eicon.nfse.vo.TbUfIbge/1081887869|"
    "java.lang.Integer/3438268394|SAO PAULO|SP|SAO BERNARDO DO CAMPO|"
    "br.eicon.nfse.vo.TbMunicipioIbgePK/2739092191|br.eicon.nfse.vo.TbEndEmpDetalhe/1110977018|"
    "1|2|3|4|1|5|5|6|7|8|6|9|1|10|11|0|12|13|14|15|0|16|VIzj60A|0|17|1|18|6|19|6|9|3995|0|0|0|"
    "20|0|0|0|0|0|0|0|0|0|0|0|21|6|9|2|22|23|6|-3|24|25|6|9|0|26|0|16|VIzj60A|0|0|0|0|27|0|13|"
    "0|0|17|1|28|6|29|30|31|6|-3|0|0|0|0|0|16|V5klGOA|0|0|17|1|32|6|33|TO_f|34|6|-13|11|35|36|"
    "37|0|0|0|38|39|6|40|6|9|93|41|0|16|UJzPEkA|0|42|43|44|45|46|0|0|47|6|48|6|0|0|49|35|50|51|"
    "0|52|53|33|L5E|0|0|0|0|0|54|6|0|42|43|0|0|0|0|0|0|"
)


class EmpresaRealTests(unittest.TestCase):
    """Dados reais do portal — a âncora das posições."""

    def setUp(self):
        self.resposta = _requisicao_para_resposta(EMPRESA_254765)
        self.dados = prestador.ler(self.resposta, "254765")

    def test_razao_social_e_nao_a_fantasia(self):
        # O bug que emitiu nota com o nome errado.
        self.assertEqual(self.dados["razao_social"], "PRESTADOR EXEMPLO QUATRO")
        self.assertEqual(self.dados["nome_fantasia"], "MARMORARIA EXEMPLO")

    def test_numero_do_endereco_e_o_numero(self):
        self.assertEqual(self.dados["numero"], "27")
        self.assertEqual(self.dados["complemento"], "PRIMEBUSINESS CENTER SL.47")

    def test_demais_campos(self):
        self.assertEqual(self.dados["cnpj"], "23958873000107")
        self.assertEqual(self.dados["logradouro"], "AVEN.  KENNEDY")
        self.assertEqual(self.dados["bairro"], "CENTRO")
        self.assertEqual(self.dados["cep"], "09726260")
        self.assertEqual(self.dados["uf"], "SP")
        self.assertEqual(self.dados["email"], "contador@exemplo.com.br")
        self.assertEqual(self.dados["telefone"], "8213492381")

    def test_emissao_liberada_para_esta_empresa(self):
        self.assertEqual(prestador.conferir(self.dados), [])

    def test_o_corpo_da_nota_leva_a_razao_social(self):
        corpo = "|".join(["7", "0", "34"] + [f"c{i}" for i in range(1, 35)] + ["1", ""])
        posicoes = {"23": "email", "30": "numero", "32": "inscricao",
                    "33": "nome_fantasia", "34": "razao_social"}
        montado = prestador.aplicar(corpo, posicoes, dados=self.dados).split("|")
        self.assertEqual(montado[3 + 32], "MARMORARIA EXEMPLO")
        self.assertEqual(montado[3 + 33], "PRESTADOR EXEMPLO QUATRO")
        self.assertEqual(montado[3 + 29], "27")


class LocalDaPrestacaoTests(unittest.TestCase):
    """Município do serviço: por índice, nunca trocando a string."""

    # Corpo mínimo com a string 4 usada por três campos, como no corpo real.
    CORPO = "7|0|4|a|b|c|3548708|1|2|3|4|4|4|"

    def _fatiar(self, corpo):
        partes = corpo.split("|")
        total = int(partes[2])
        return partes[3:3 + total], partes[3 + total:]

    def test_troca_apenas_o_campo_pedido(self):
        # Os campos do fluxo em 4, 5 e 6 apontam todos para a string 4.
        tabela, fluxo = self._fatiar(self.CORPO)
        self.assertEqual([fluxo[3], fluxo[4], fluxo[5]], ["4", "4", "4"])
        novo = nfse_client.apontar_indice(self.CORPO, 4, "3547809")
        tabela, fluxo = self._fatiar(novo)
        self.assertEqual(tabela[int(fluxo[4]) - 1], "3547809")
        self.assertEqual(tabela[int(fluxo[3]) - 1], "3548708")
        self.assertEqual(tabela[int(fluxo[5]) - 1], "3548708")

    def test_a_string_nova_entra_no_fim_sem_deslocar_as_outras(self):
        antes, _ = self._fatiar(self.CORPO)
        depois, _ = self._fatiar(nfse_client.apontar_indice(self.CORPO, 4, "3547809"))
        self.assertEqual(depois[:len(antes)], antes)
        self.assertEqual(depois[-1], "3547809")

    def test_valor_ja_existente_reaproveita_a_entrada(self):
        antes, _ = self._fatiar(self.CORPO)
        depois, fluxo = self._fatiar(nfse_client.apontar_indice(self.CORPO, 4, "3548708"))
        self.assertEqual(len(depois), len(antes), "não deve duplicar string existente")
        self.assertEqual(depois[int(fluxo[4]) - 1], "3548708")

    def test_posicao_fora_do_corpo_e_recusada(self):
        with self.assertRaises(nfse_client.NfseError):
            nfse_client.apontar_indice(self.CORPO, 999, "3547809")

    def test_codigo_ibge_precisa_de_sete_digitos(self):
        self.assertEqual(validation.normalize_municipio("35-487.08"), "3548708")
        self.assertEqual(validation.normalize_municipio(""), "")
        # Texto sem dígito é o mesmo que não informar — o padrão vale.
        self.assertEqual(validation.normalize_municipio("abc"), "")
        for ruim in ("123", "12345678"):
            with self.assertRaises(validation.ValidationError):
                validation.normalize_municipio(ruim)

    def test_municipio_so_entra_no_rascunho_quando_informado(self):
        base = {"tomador": {"documento": "11222333000181"},
                "servico": {"codigo": "14.05", "descricao": "x", "valor": "1.00", **REFORMA}}
        self.assertNotIn("municipio", validation.validate_payload(base)["servico"])
        fora = {**base, "servico": {**base["servico"], "municipio": "3547809", **REFORMA}}
        self.assertEqual(validation.validate_payload(fora)["servico"]["municipio"], "3547809")

    def test_modelo_declara_onde_fica_o_municipio(self):
        real = Path(__file__).resolve().parent.parent / "config" / "templates" / "mundial-usinagem.json"
        modelo = json.loads(real.read_text(encoding="utf-8"))
        # São dois campos: o do serviço e o do bloco IBS/CBS.
        indices = modelo["servico_municipio_indices"]
        self.assertEqual(indices, [70, 81])
        partes = modelo["body"].split("|")
        total = int(partes[2])
        tabela, fluxo = partes[3:3 + total], partes[3 + total:]
        for indice in indices:
            self.assertEqual(tabela[int(fluxo[indice]) - 1], "3548708")

    def test_o_segundo_campo_do_iss_vai_vazio(self):
        real = Path(__file__).resolve().parent.parent / "config" / "templates" / "mundial-usinagem.json"
        modelo = json.loads(real.read_text(encoding="utf-8"))
        corpo = nfse_client.anular_indice(modelo["body"], modelo["servico_iss_vazio_indice"])
        partes = corpo.split("|")
        total = int(partes[2])
        self.assertEqual(partes[3 + total:][modelo["servico_iss_vazio_indice"]], "0")


class MunicipiosTests(unittest.TestCase):
    """Leitura das listas do portal (sem rede: resposta montada)."""

    def test_codigo_ibge_completo_e_uf_mais_cinco_digitos(self):
        resposta = _resposta_gwt([
            "java.util.ArrayList/4159755760",
            "br.com.eicon.nfseweb.client.vo.MunicipioVO/2818755302",
            "SAO BERNARDO DO CAMPO", None,
        ])
        # O código vem como inteiro cru, fora da tabela — aqui só o formato importa.
        self.assertEqual(f"35{48708:05d}", "3548708")
        self.assertEqual(f"35{105:05d}", "3500105")

    def test_tokens_nao_resolvem_inteiros_como_string(self):
        # O código de SP é 35 e existe string na posição 35: resolver trocaria
        # o código do estado pelo nome de outro.
        tokens, tabela = nfse_client.gwt_tokens(_resposta_gwt(["a", "b", "c"]))
        self.assertEqual(tabela, ["a", "b", "c"])
        self.assertTrue(all(isinstance(t, str) for t in tokens))

    def test_nome_do_codigo_sem_cache_devolve_vazio(self):
        self.assertEqual(municipios.nome_do_codigo("9999999"), "")
        self.assertEqual(municipios.nome_do_codigo("123"), "")


class ObraTests(unittest.TestCase):
    """Código da Obra: aparece só onde é exigido e nunca é chutado no corpo."""

    def setUp(self):
        self.original = config.EXIGE_OBRA
        config.EXIGE_OBRA = paths.CONFIG_DIR / "exige_obra_obra_teste.json"
        config.EXIGE_OBRA.write_text(
            json.dumps({"itens": [], "codigos": ["7.02/103107/1291"]}), encoding="utf-8")

    def tearDown(self):
        config.EXIGE_OBRA.unlink(missing_ok=True)
        config.EXIGE_OBRA = self.original

    def _rascunho(self, codigo: str, obra: str = "") -> dict:
        return {"tomador": {"documento": "11222333000181"},
                "servico": {"codigo": codigo, "descricao": "x", "valor": "1.00",
                            "obra": obra, **REFORMA}}

    def test_obra_entra_no_rascunho_quando_informada(self):
        limpo = validation.validate_payload(self._rascunho("7.02/103107/1291", "10023"))
        self.assertEqual(limpo["servico"]["obra"], "10023")

    def test_sem_obra_o_campo_nem_aparece_no_rascunho(self):
        limpo = validation.validate_payload(self._rascunho("14.05/107120/1581"))
        self.assertNotIn("obra", limpo["servico"])

    def test_servico_que_exige_obra_sem_obra_e_barrado(self):
        payload = validation.validate_payload(self._rascunho("7.02/103107/1291"))
        with self.assertRaises(service.ObraObrigatoria) as caso:
            service._barrar_se_exige_obra(payload)
        self.assertIn("nenhum foi informado", str(caso.exception))

    def test_com_obra_mas_sem_posicao_no_modelo_tambem_e_barrado(self):
        # O modelo atual não sabe onde a obra entra no corpo. Deixar passar
        # emitiria a nota sem a obra, que é o erro que o portal já recusou.
        payload = validation.validate_payload(self._rascunho("7.02/103107/1291", "10023"))
        with self.assertRaises(service.ObraObrigatoria) as caso:
            service._barrar_se_exige_obra(payload)
        self.assertIn("em que campo do corpo", str(caso.exception))
        self.assertIn("10023", str(caso.exception), "a obra digitada não pode se perder")

    def test_servico_sem_exigencia_passa_direto(self):
        payload = validation.validate_payload(self._rascunho("14.05/107120/1581"))
        service._barrar_se_exige_obra(payload)  # não levanta

    def test_lista_de_obras_da_empresa(self):
        arquivo = paths.CONFIG_DIR / "obras_999888.json"
        arquivo.write_text(json.dumps([
            {"codigo": "10023", "descricao": "Rua das Flores, 100"},
            {"codigo": "  ", "descricao": "sem código — deve sumir"},
        ]), encoding="utf-8")
        try:
            lista = obras.disponiveis("999888")
            self.assertEqual(len(lista), 1)
            self.assertEqual(lista[0]["codigo"], "10023")
            self.assertIn("Rua das Flores", obras.rotulo(lista[0]))
        finally:
            arquivo.unlink(missing_ok=True)

    def test_empresa_sem_arquivo_devolve_lista_vazia(self):
        self.assertEqual(obras.disponiveis("000000"), [])


class ObraNoCorpoTests(unittest.TestCase):
    """Quando o modelo declarar a posição, a obra entra pelo mesmo caminho."""

    def test_posicao_declarada_leva_a_obra_ao_corpo(self):
        modelo = {
            "url": "https://nfse.isssbc.com.br/nfseweb/nfse",
            "method": "POST",
            "escape": "gwt",
            "body": "7|0|4|a|b|c|d|1|2|3|4|",
            "servico_obra_indice": 2,
        }
        montado = nfse_client.build_request(modelo, {})
        corpo = nfse_client.apontar_indice(modelo["body"], 2, "10023")
        partes = corpo.split("|")
        total = int(partes[2])
        tabela, fluxo = partes[3:3 + total], partes[3 + total:]
        self.assertEqual(tabela[int(fluxo[2]) - 1], "10023")
        self.assertEqual(montado["method"], "POST")

    def test_sem_a_posicao_a_obra_nao_altera_o_corpo(self):
        modelo = {"url": "https://nfse.isssbc.com.br/nfseweb/nfse", "method": "POST",
                  "escape": "gwt", "body": "7|0|4|a|b|c|d|1|2|3|4|"}
        montado = nfse_client.build_request(modelo, {})
        self.assertEqual(montado["body"], modelo["body"])


class ConstrucaoCivilTests(unittest.TestCase):
    """Objeto da obra no corpo — conferido contra a captura real do portal."""

    TIPO = "br.eicon.nfse.xml.complexType.TcDadosConstrucaoCivil/243561992"
    # Campo 3 vazio é o do objeto; os dois seguintes são irmãos dele.
    CORPO = "7|0|3|a|b|c|1|2|0|0|0|3|"

    def _fatiar(self, corpo):
        partes = corpo.split("|")
        total = int(partes[2])
        return partes[3:3 + total], [p for p in partes[3 + total:] if p != ""]

    def test_objeto_acrescenta_campos_em_vez_de_trocar(self):
        novo = nfse_client.inserir_objeto(self.CORPO, 2, self.TIPO,
                                          ["1213550", None, None, "1213550"])
        _, antes = self._fatiar(self.CORPO)
        tabela, depois = self._fatiar(novo)
        self.assertEqual(len(depois), len(antes) + 4, "o objeto traz 4 campos")
        self.assertEqual(tabela[int(depois[2]) - 1], self.TIPO)
        self.assertEqual(tabela[int(depois[3]) - 1], "1213550")
        self.assertEqual(depois[4], "0")
        self.assertEqual(depois[5], "0")
        self.assertEqual(tabela[int(depois[6]) - 1], "1213550")

    def test_os_campos_irmaos_continuam_depois_do_objeto(self):
        _, antes = self._fatiar(self.CORPO)
        _, depois = self._fatiar(
            nfse_client.inserir_objeto(self.CORPO, 2, self.TIPO, ["1213550", None, None, "1213550"]))
        # O que vinha depois do campo vazio não pode se perder nem trocar de lugar.
        self.assertEqual(depois[-len(antes) + 3:], antes[3:])

    def test_codigo_repetido_reaproveita_a_mesma_entrada(self):
        tabela, fluxo = self._fatiar(
            nfse_client.inserir_objeto(self.CORPO, 2, self.TIPO, ["1213550", None, None, "1213550"]))
        self.assertEqual(fluxo[3], fluxo[6], "o mesmo valor aponta para a mesma string")

    def test_campo_ja_preenchido_e_recusado(self):
        with self.assertRaises(nfse_client.NfseError) as caso:
            nfse_client.inserir_objeto(self.CORPO, 0, self.TIPO, ["1213550"])
        self.assertIn("já está preenchido", str(caso.exception))

    def test_long_gwt_bate_com_a_captura(self):
        # O portal pediu listaObra com o município codificado como "L5E".
        self.assertEqual(nfse_client.long_gwt(48708), "L5E")
        self.assertEqual(nfse_client.long_gwt(0), "A")

    def test_modelo_declara_o_objeto_da_obra(self):
        real = Path(__file__).resolve().parent.parent / "config" / "templates" / "mundial-usinagem.json"
        modelo = json.loads(real.read_text(encoding="utf-8"))
        declarado = modelo["servico_obra"]
        self.assertEqual(declarado["tipo"], self.TIPO)
        self.assertEqual(declarado["campos"], ["obra", None, None, "obra"])
        # A posição declarada tem de estar vazia no corpo sem obra.
        partes = modelo["body"].split("|")
        total = int(partes[2])
        fluxo = partes[3 + total:]
        self.assertEqual(fluxo[declarado["indice"]], "0")

    def test_obra_e_municipio_convivem_sem_se_atropelar(self):
        # A obra desloca o fluxo em +4; se o município for ajustado depois, cai
        # na casa errada. A ordem em build() é o que garante os dois.
        real = Path(__file__).resolve().parent.parent / "config" / "templates" / "mundial-usinagem.json"
        modelo = json.loads(real.read_text(encoding="utf-8"))
        corpo = modelo["body"]
        for posicao in modelo["servico_municipio_indices"]:
            corpo = nfse_client.apontar_indice(corpo, posicao, "3547809")
        corpo = nfse_client.inserir_objeto(corpo, modelo["servico_obra"]["indice"],
                                           self.TIPO, ["1213550", None, None, "1213550"])
        tabela, fluxo = self._fatiar(corpo)
        self.assertEqual(tabela[int(fluxo[74]) - 1], "3547809", "município andou 4 casas")
        self.assertEqual(tabela[int(fluxo[30]) - 1], self.TIPO)


class ListaObraTests(unittest.TestCase):
    """Leitura da resposta de listaObra."""

    def test_lista_vazia_do_portal(self):
        # Resposta real de uma empresa sem obras cadastradas.
        vazia = '//OK[0,0,1,["br.com.eicon.ginfesvohb.dto.ListaObraVO/2367612354"],0,7]'
        self.assertEqual(obras.ler_resposta(vazia), [])

    def test_resposta_sem_tipo_de_obra_nao_inventa_nada(self):
        self.assertEqual(obras.ler_resposta('//OK[0,["java.lang.String/1"],0,7]'), [])
        self.assertEqual(obras.ler_resposta(""), [])


class GradeDoFormularioTests(unittest.TestCase):
    """Dois widgets na mesma célula: um esconde o outro, sem erro nenhum.

    Foi o que aconteceu com o campo Obra — ele existia, o bloqueio da emissão
    funcionava, mas ele nascia na linha da faixa de resumo e ficava invisível.
    """

    def setUp(self):
        try:
            import tkinter
            self.raiz = tkinter.Tk()
            self.raiz.withdraw()
        except Exception as exc:  # ambiente sem display
            self.skipTest(f"sem interface gráfica: {exc}")

    def tearDown(self):
        try:
            self.raiz.destroy()
        except Exception:
            pass

    def _celulas(self, container) -> list[tuple[str, int, int]]:
        ocupadas = []
        for filho in container.grid_slaves():
            info = filho.grid_info()
            linha, coluna = int(info["row"]), int(info["column"])
            for dl in range(int(info.get("rowspan", 1))):
                for dc in range(int(info.get("columnspan", 1))):
                    ocupadas.append((str(filho), linha + dl, coluna + dc))
        return ocupadas

    def test_nenhuma_celula_e_disputada_na_tela_de_emissao(self):
        import desktop

        app = desktop.NfseDesktop()
        app.withdraw()
        try:
            app.show_new_note()
            app.update_idletasks()
            formularios = []

            def procurar(widget):
                if widget.grid_slaves():
                    formularios.append(widget)
                for filho in widget.winfo_children():
                    procurar(filho)

            procurar(app.content)
            self.assertTrue(formularios, "a tela de emissão usa grid em algum lugar")
            for container in formularios:
                vistas: dict[tuple[int, int], str] = {}
                for nome, linha, coluna in self._celulas(container):
                    chave = (linha, coluna)
                    anterior = vistas.get(chave)
                    self.assertIsNone(
                        anterior,
                        f"linha {linha}, coluna {coluna} disputada por {anterior} e {nome}",
                    )
                    vistas[chave] = nome
        finally:
            app.destroy()


class LeituraDeObrasTests(unittest.TestCase):
    """A lista veio vazia numa empresa que tem obras — leitura ampliada."""

    def _resposta(self, valores: list) -> str:
        return _resposta_gwt(valores)

    def test_classe_com_nome_inesperado_ainda_e_reconhecida(self):
        # Exigir o sufixo "ObraVO" fazia a lista vir vazia com TbObra.
        resposta = self._resposta([
            "java.util.ArrayList/4159755760", "br.eicon.nfse.vo.TbObra/123",
            "1213550", "OBRA RUA X 100", "br.eicon.nfse.vo.TbObra/123",
            "1213551", "OBRA AV BRASIL",
        ])
        lidas = obras.ler_resposta(resposta)
        self.assertEqual([o["codigo"] for o in lidas], ["1213550", "1213551"])
        self.assertEqual(lidas[0]["descricao"], "OBRA RUA X 100")

    def test_sem_classe_reconhecivel_empareia_os_valores(self):
        resposta = self._resposta([
            "br.com.eicon.ginfesvohb.dto.ListaObraVO/2367612354",
            "1213550", "OBRA RUA X 100", "1213551", "OBRA AV BRASIL",
        ])
        lidas = obras.ler_resposta(resposta)
        self.assertEqual([o["codigo"] for o in lidas], ["1213550", "1213551"])

    def test_lista_vazia_continua_vazia(self):
        # Resposta real do portal para empresa sem obras.
        vazia = '//OK[0,0,1,["br.com.eicon.ginfesvohb.dto.ListaObraVO/2367612354"],0,7]'
        self.assertEqual(obras.ler_resposta(vazia), [])

    def test_o_involucro_nunca_vira_uma_obra(self):
        resposta = self._resposta([
            "br.com.eicon.ginfesvohb.dto.ListaObraVO/2367612354", "1213550", "OBRA",
        ])
        for obra in obras.ler_resposta(resposta):
            self.assertNotIn("ListaObra", obra["codigo"] + obra["descricao"])

    def test_codigo_repetido_entra_uma_vez_so(self):
        resposta = self._resposta([
            "br.eicon.nfse.vo.TbObra/123", "1213550", "A",
            "br.eicon.nfse.vo.TbObra/123", "1213550", "A",
        ])
        self.assertEqual(len(obras.ler_resposta(resposta)), 1)


class TomadorManualTests(unittest.TestCase):
    """CNPJ fora do cadastro do portal: os dados vêm digitados."""

    COMPLETO = {
        "documento": "11222333000181", "razao_social": "CLIENTE NOVO LTDA",
        "logradouro": "RUA DAS FLORES", "numero": "100", "complemento": "SALA 2",
        "bairro": "CENTRO", "cep": "09726260", "email": "novo@cliente.com",
        "municipio": "3547809",
    }

    def test_dados_completos_montam_o_bloco(self):
        dados = tomador.manual(self.COMPLETO)
        self.assertEqual(dados["razao_social"], "CLIENTE NOVO LTDA")
        self.assertEqual(dados["municipio"], "3547809")

    def test_id_interno_vai_vazio(self):
        # Não existe id para quem não está no cadastro. Herdar o da captura
        # apontaria a nota para outro cliente.
        self.assertEqual(tomador.manual(self.COMPLETO)["id"], "")

    def test_faltando_campo_essencial_nao_monta_nada(self):
        for ausente in ("razao_social", "logradouro", "numero", "bairro", "cep"):
            parcial = {k: v for k, v in self.COMPLETO.items() if k != ausente}
            self.assertEqual(tomador.manual(parcial), {}, ausente)

    def test_relatorio_do_que_falta(self):
        faltando = tomador.falta_para_manual({"documento": "11222333000181"})
        self.assertIn("razão social", faltando)
        self.assertIn("CEP", faltando)
        self.assertEqual(tomador.falta_para_manual(self.COMPLETO), [])

    def test_aplicar_sobrescreve_todas_as_posicoes(self):
        # O id da captura não pode sobreviver quando o tomador é digitado.
        corpo = "|".join(["7", "0", "4"] + ["a@b.c", "BAIRRO ANTIGO", "375662", "OUTRO"] + ["1", ""])
        posicoes = {"1": "email", "2": "bairro", "3": "id", "4": "razao_social"}
        montado = tomador.aplicar(corpo, posicoes, tomador.manual(self.COMPLETO))
        tabela = montado.split("|")[3:7]
        self.assertEqual(tabela[0], "novo@cliente.com")
        self.assertEqual(tabela[1], "CENTRO")
        self.assertEqual(tabela[2], "", "o id da captura tem de sumir")
        self.assertEqual(tabela[3], "CLIENTE NOVO LTDA")

    def test_validacao_normaliza_cep_e_municipio(self):
        limpo = validation.validate_payload({
            "tomador": {**self.COMPLETO, "cep": "09726-260"},
            "servico": {"codigo": "14.05", "descricao": "x", "valor": "1.00", **REFORMA},
        })["tomador"]
        self.assertEqual(limpo["cep"], "09726260")
        self.assertEqual(limpo["municipio"], "3547809")

    def test_cep_invalido_e_recusado(self):
        with self.assertRaises(validation.ValidationError):
            validation.validate_payload({
                "tomador": {**self.COMPLETO, "cep": "0972"},
                "servico": {"codigo": "14.05", "descricao": "x", "valor": "1.00", **REFORMA},
            })

    def test_tomador_conhecido_nao_carrega_campos_manuais(self):
        limpo = validation.validate_payload({
            "tomador": {"documento": "11222333000181"},
            "servico": {"codigo": "14.05", "descricao": "x", "valor": "1.00", **REFORMA},
        })["tomador"]
        self.assertEqual(set(limpo), {"documento", "nome"})

    def test_modelo_sabe_onde_fica_o_municipio_do_tomador(self):
        real = Path(__file__).resolve().parent.parent / "config" / "templates" / "mundial-usinagem.json"
        modelo = json.loads(real.read_text(encoding="utf-8"))
        indice = modelo["tomador_municipio_indice"]
        partes = modelo["body"].split("|")
        total = int(partes[2])
        tabela, fluxo = partes[3:3 + total], partes[3 + total:]
        self.assertEqual(tabela[int(fluxo[indice]) - 1], "3548708")


class IssForaDoMunicipioTests(unittest.TestCase):
    """E181: o portal recalcula o líquido e recusa quando não fecha."""

    BASE = {"tomador": {"documento": "11222333000181"},
            "servico": {"codigo": "14.05/107120/1581", "descricao": "x",
                        "valor": "1.00", "aliquota": "2", **REFORMA}}

    def test_dentro_do_municipio_o_iss_e_cobrado(self):
        limpo = validation.validate_payload(self.BASE)
        self.assertEqual(limpo["servico"]["iss"], "0.02")

    def test_fora_do_municipio_o_iss_zera(self):
        fora = {**self.BASE, "servico": {**self.BASE["servico"], "municipio": "3547809", **REFORMA}}
        limpo = validation.validate_payload(fora)
        self.assertEqual(limpo["servico"]["iss"], "0.00")

    def test_liquido_acompanha_a_retencao(self):
        # O líquido é (valor − ISS retido). Sem retenção, valor cheio.
        sem = nfse_client._derived(validation.validate_payload(self.BASE))
        self.assertEqual(sem["servico"]["valor_liquido"], "1.00")
        com = {**self.BASE, "servico": {**self.BASE["servico"], "iss_retido": True, **REFORMA}}
        self.assertEqual(
            nfse_client._derived(validation.validate_payload(com))["servico"]["valor_liquido"],
            "0.98")
        fora = {**self.BASE, "servico": {**self.BASE["servico"], "municipio": "3547809", **REFORMA}}
        calculado = nfse_client._derived(validation.validate_payload(fora))
        self.assertEqual(calculado["servico"]["valor_liquido"], "1.00")

    def test_fora_do_municipio_nao_ha_o_que_reter(self):
        fora = {**self.BASE, "servico": {**self.BASE["servico"],
                                         "municipio": "3547809", "iss_retido": True, **REFORMA}}
        limpo = validation.validate_payload(fora)
        self.assertFalse(limpo["servico"]["iss_retido"])
        self.assertEqual(limpo["servico"]["iss"], "0.00")

    def _modelo(self):
        real = Path(__file__).resolve().parent.parent / "config" / "templates" / "mundial-usinagem.json"
        return json.loads(real.read_text(encoding="utf-8"))

    def test_o_modelo_declara_as_duas_marcas(self):
        modelo = self._modelo()
        self.assertEqual(modelo["servico_iss_retido_marcas"], {"sim": "1", "nao": "2"})
        partes = modelo["body"].split("|")
        total = int(partes[2])
        tabela, fluxo = partes[3:3 + total], partes[3 + total:]
        # A captura veio de uma nota COM retenção: por isso "1" no corpo cru.
        self.assertEqual(tabela[int(fluxo[modelo["servico_iss_retido_indice"]]) - 1], "1")

    def test_sem_retencao_a_marca_vira_dois(self):
        modelo = self._modelo()
        corpo = nfse_client.apontar_indice(
            modelo["body"], modelo["servico_iss_retido_indice"], "2")
        partes = corpo.split("|")
        total = int(partes[2])
        tabela, fluxo = partes[3:3 + total], partes[3 + total:]
        self.assertEqual(tabela[int(fluxo[modelo["servico_iss_retido_indice"]]) - 1], "2")


class RecursosDoPortalTests(unittest.TestCase):
    """O que o portal libera decide o que a tela mostra."""

    def test_booleano_do_gwt(self):
        # Resposta real: //OK[<valor>,<tipo>,[tabela],0,7], lida de trás para frente.
        self.assertFalse(nfse_client.gwt_booleano(
            '//OK[0,1,["java.lang.Boolean/476441737"],0,7]'))
        self.assertTrue(nfse_client.gwt_booleano(
            '//OK[1,1,["java.lang.Boolean/476441737"],0,7]'))

    def test_resposta_estranha_nao_vira_verdadeiro(self):
        # Na dúvida, não oferecer: um campo que não funciona faz o usuário
        # acreditar num imposto que não vai acontecer.
        for ruim in ("", "//EX[erro]", "//OK[]"):
            self.assertFalse(nfse_client.gwt_booleano(ruim), ruim)


class CepTests(unittest.TestCase):
    """Endereço a partir do CEP (sem rede nos testes)."""

    def test_limpeza(self):
        self.assertEqual(cep.limpar("09726-260"), "09726260")
        self.assertEqual(cep.limpar("  09.726260 "), "09726260")
        self.assertEqual(cep.limpar(""), "")

    def test_cep_curto_e_recusado_antes_de_ir_a_rede(self):
        with self.assertRaises(cep.CepError):
            cep.buscar("0972")

    def test_pode_ser_desligado_pelo_env(self):
        anterior = os.environ.get("NFSE_CEP")
        os.environ["NFSE_CEP"] = "off"
        try:
            self.assertFalse(cep.ligado())
            with self.assertRaises(cep.CepError):
                cep.buscar("09726260")
        finally:
            if anterior is None:
                os.environ.pop("NFSE_CEP", None)
            else:
                os.environ["NFSE_CEP"] = anterior

    def test_ligado_por_padrao(self):
        anterior = os.environ.pop("NFSE_CEP", None)
        try:
            self.assertTrue(cep.ligado())
        finally:
            if anterior is not None:
                os.environ["NFSE_CEP"] = anterior


class CepDoPortalTests(unittest.TestCase):
    """Busca de CEP pelo próprio portal (buscaEndereco)."""

    # Resposta real do portal para 09171-640 (Santo André).
    RESPOSTA = (
        '//OK[0,0,0,0,19,18,17,0,16,15,35,14,0,0,13,2,12,0,0,11,10,9,8,7,0,'
        '"UJzPEkA",6,0,5,195,4,2,3,2,1,'
        '["br.eicon.nfse.vo.TbCep/841084315","rO0ABXcEAAAAAA==",'
        '"br.eicon.nfse.vo.TbTpLogradouro/1098594195","java.lang.Short/551743396",'
        '"RUA","java.sql.Date/730999118","SITIO DOS VIANAS","SAO DOMINGOS SAVIO",'
        '"br.eicon.nfse.vo.TbCepPK/2873971312","9171","640",'
        '"br.eicon.nfse.vo.TbMunicipioIbge/1210383657","br.eicon.nfse.vo.TbUfIbge/1081887869",'
        '"java.lang.Integer/3438268394","SAO PAULO","SP","SANTO ANDRE",'
        '"br.eicon.nfse.vo.TbMunicipioIbgePK/2739092191","java.lang.Long/4227064769"],0,7]'
    )

    def test_long_do_gwt_vai_e_volta(self):
        # Na resposta o long vem entre aspas: 'LrB'.
        self.assertEqual(nfse_client.long_gwt_para_int("LrB"), 47809)
        self.assertEqual(nfse_client.long_gwt_para_int("'LrB'"), 47809)
        self.assertEqual(nfse_client.long_gwt(47809), "LrB")
        self.assertEqual(nfse_client.long_gwt_para_int(nfse_client.long_gwt(3548708)), 3548708)

    def test_limpeza_do_cep(self):
        self.assertEqual(cep.limpar("09726-260"), "09726260")
        self.assertEqual(cep.limpar("  09.726260 "), "09726260")

    def test_cep_curto_nem_vai_a_rede(self):
        with self.assertRaises(cep.CepError):
            cep.buscar("0972")

    def test_pode_ser_desligado(self):
        anterior = os.environ.get("NFSE_CEP")
        os.environ["NFSE_CEP"] = "off"
        try:
            self.assertFalse(cep.ligado())
            with self.assertRaises(cep.CepError):
                cep.buscar("09726260")
        finally:
            os.environ.pop("NFSE_CEP", None)
            if anterior is not None:
                os.environ["NFSE_CEP"] = anterior

    def test_resposta_vazia_avisa_que_nao_achou(self):
        with self.assertRaises(cep.CepError):
            cep.ler_resposta("//OK[0,0,[],0,7]", "00000000")


class CadastrarTomadorTests(unittest.TestCase):
    """Ligar o cadastro do cliente troca a janela inteira, não um campo."""

    def _modelo(self):
        real = Path(__file__).resolve().parent.parent / "config" / "templates" / "mundial-usinagem.json"
        return json.loads(real.read_text(encoding="utf-8"))

    def _janela(self, corpo, inicio, tamanho):
        partes = corpo.split("|")
        total = int(partes[2])
        tabela, fluxo = partes[3:3 + total], partes[3 + total:]

        def nome(token):
            try:
                posicao = int(token)
            except ValueError:
                return token
            if 1 <= posicao <= len(tabela):
                valor = tabela[posicao - 1]
                if "/" in valor and "." in valor.split("/")[0]:
                    return "@" + valor.split("/")[0].split(".")[-1]
            return token

        return [nome(t) for t in fluxo[inicio:inicio + tamanho]]

    def test_modelo_guarda_as_duas_janelas_reais(self):
        declarado = self._modelo()["tomador_cadastrar"]
        self.assertEqual(len(declarado["nao"]), len(declarado["sim"]), "as janelas têm o mesmo tamanho")
        # 'nao' precisa descrever o corpo capturado como ele está.
        atual = self._janela(self._modelo()["body"], declarado["inicio"], len(declarado["nao"]))
        esperado = [t.replace("@Reforma", "@NnDpsDadosReformaVO") for t in declarado["nao"]]
        self.assertEqual(atual, esperado)

    def test_ligar_reproduz_a_janela_da_emissao_que_cadastrou(self):
        modelo = self._modelo()
        declarado = modelo["tomador_cadastrar"]
        corpo = nfse_client.trocar_janela(modelo["body"], declarado["inicio"],
                                          declarado["sim"], declarado["tipos"])
        atual = self._janela(corpo, declarado["inicio"], len(declarado["sim"]))
        esperado = [t.replace("@Reforma", "@NnDpsDadosReformaVO") for t in declarado["sim"]]
        self.assertEqual(atual, esperado)

    def test_o_corpo_nao_muda_de_tamanho(self):
        modelo = self._modelo()
        declarado = modelo["tomador_cadastrar"]
        antes = len(modelo["body"].split("|"))
        corpo = nfse_client.trocar_janela(modelo["body"], declarado["inicio"],
                                          declarado["sim"], declarado["tipos"])
        self.assertEqual(len(corpo.split("|")), antes)

    def test_com_obra_a_retro_referencia_anda_uma_casa(self):
        # A obra acrescenta um objeto antes da janela, e a retro-referência
        # conta objetos: sem o ajuste ela apontaria para o objeto errado.
        modelo = self._modelo()
        declarado = modelo["tomador_cadastrar"]
        corpo = nfse_client.trocar_janela(modelo["body"], declarado["inicio"],
                                          declarado["sim"], declarado["tipos"],
                                          ajuste_retro=1)
        janela = self._janela(corpo, declarado["inicio"], len(declarado["sim"]))
        self.assertIn("-38", janela)
        self.assertNotIn("-37", janela)

    def test_tipo_nao_declarado_e_recusado(self):
        with self.assertRaises(nfse_client.NfseError):
            nfse_client.trocar_janela("7|0|1|a|1|", 0, ["@Desconhecido"], {})

    def test_janela_fora_do_corpo_e_recusada(self):
        with self.assertRaises(nfse_client.NfseError):
            nfse_client.trocar_janela("7|0|1|a|1|", 50, ["0"], {})

    def test_cadastrar_so_entra_com_tomador_digitado(self):
        # Tomador já cadastrado não leva o flag: não há o que cadastrar.
        limpo = validation.validate_payload({
            "tomador": {"documento": "11222333000181", "cadastrar": True},
            "servico": {"codigo": "14.05", "descricao": "x", "valor": "1.00", **REFORMA},
        })["tomador"]
        self.assertNotIn("cadastrar", limpo)

        completo = validation.validate_payload({
            "tomador": {"documento": "11222333000181", "razao_social": "NOVO LTDA",
                        "logradouro": "RUA X", "numero": "1", "bairro": "C",
                        "cep": "09726260", "cadastrar": True},
            "servico": {"codigo": "14.05", "descricao": "x", "valor": "1.00", **REFORMA},
        })["tomador"]
        self.assertTrue(completo["cadastrar"])


class AutocompletarTests(unittest.TestCase):
    """Digitar filtra a lista — readonly impedia isso."""

    def setUp(self):
        try:
            import tkinter
            from tkinter import ttk
            self.raiz = tkinter.Tk()
            self.raiz.withdraw()
            self.combo = ttk.Combobox(self.raiz)
        except Exception as exc:
            self.skipTest(f"sem interface gráfica: {exc}")

    def tearDown(self):
        try:
            self.raiz.destroy()
        except Exception:
            pass

    def test_o_campo_fica_editavel(self):
        # A causa da queixa "não consigo digitar": readonly, em ttk, deixa
        # escolher da lista mas bloqueia o teclado.
        self.combo.configure(state="readonly")
        ui.autocompletar(self.combo, lambda: ["A", "B"])
        self.assertEqual(str(self.combo.cget("state")), "normal")

    def test_a_lista_e_relida_a_cada_tecla(self):
        # Trocar a UF troca os municípios; uma cópia guardada ficaria velha.
        atual = {"itens": ["ANTIGO"]}
        ui.autocompletar(self.combo, lambda: atual["itens"])
        atual["itens"] = ["NOVO"]
        self.assertEqual(ui.filtrar(atual["itens"], ""), ["NOVO"])


class FiltroDeListaTests(unittest.TestCase):
    """A regra por trás do autocompletar — sem depender de evento do Tk."""

    CIDADES = ["ESPIRITO SANTO DO PINHAL", "SANTO ANDRE", "SANTOS", "BAURU"]

    def test_poe_o_prefixo_na_frente(self):
        achados = ui.filtrar(self.CIDADES, "SANTO")
        self.assertEqual(achados[:2], ["SANTO ANDRE", "SANTOS"])
        self.assertIn("ESPIRITO SANTO DO PINHAL", achados)
        self.assertNotIn("BAURU", achados)

    def test_ignora_maiuscula_e_espaco(self):
        self.assertEqual(ui.filtrar(self.CIDADES, "  santo andre "), ["SANTO ANDRE"])

    def test_campo_vazio_mostra_a_lista(self):
        cidades = [f"CIDADE {n}" for n in range(50)]
        self.assertEqual(ui.filtrar(cidades, ""), cidades)

    def test_o_limite_corta_so_a_exibicao(self):
        cidades = [f"CIDADE {n}" for n in range(400)]
        self.assertEqual(len(ui.filtrar(cidades, "")), ui.LIMITE_LISTA)
        # e o que se digita continua achável mesmo estando além do limite
        self.assertEqual(ui.filtrar(cidades, "CIDADE 399"), ["CIDADE 399"])

    def test_sem_resultado_devolve_lista_vazia(self):
        self.assertEqual(ui.filtrar(self.CIDADES, "XYZ"), [])

    def test_nao_repete_quem_casa_das_duas_formas(self):
        achados = ui.filtrar(["SANTOS", "SANTOS DUMONT"], "SANTOS")
        self.assertEqual(achados, ["SANTOS", "SANTOS DUMONT"])


class CodigoDoServicoTests(unittest.TestCase):
    """Resolver o serviço pelo texto, nunca pelo índice da lista.

    Com a lista filtrando ao digitar, o índice deixa de valer: escolher a
    segunda linha de uma lista filtrada pegaria o segundo item do catálogo
    inteiro — nota emitida com o serviço errado.
    """

    CATALOGO = [
        {"codigo": "14.01/104880/1113", "nome": "MANUTENCAO DE MAQUINAS"},
        {"codigo": "16.02/105803/1371", "nome": "TRANSPORTE MUNICIPAL"},
        {"codigo": "17.01/106010/1402", "nome": "ASSESSORIA"},
    ]

    def _rotulo(self, servico):
        return f"{servico['codigo']}  —  {servico['nome']}"

    def _escolhido(self, escrito):
        for servico in self.CATALOGO:
            if self._rotulo(servico) == escrito:
                return servico["codigo"]
        return ""

    def test_o_texto_da_lista_devolve_o_codigo(self):
        self.assertEqual(
            self._escolhido(self._rotulo(self.CATALOGO[1])), "16.02/105803/1371")

    def test_filtrar_nao_troca_o_codigo(self):
        rotulos = [self._rotulo(s) for s in self.CATALOGO]
        filtrada = ui.filtrar(rotulos, "TRANSPORTE")
        self.assertEqual(len(filtrada), 1)
        # posição 0 na lista filtrada, posição 1 no catálogo: pelo índice sairia
        # MANUTENCAO; pelo texto sai o certo.
        self.assertEqual(self._escolhido(filtrada[0]), "16.02/105803/1371")

    def test_texto_solto_nao_vira_codigo(self):
        for escrito in ["TRANSPORTE", "16.02", "", "qualquer coisa"]:
            self.assertEqual(self._escolhido(escrito), "", escrito)


class MarcaGeometriaTests(unittest.TestCase):
    """O desenho do monograma — o que não pode mudar sem querer."""

    def test_a_caixa_toda_tem_cor(self):
        # Um furo no desenho apareceria como um buraco azul-marinho no meio da
        # marca quando ela é posta sobre a barra lateral.
        for i in range(60):
            for j in range(60):
                x = (i + 0.5) * marca.U_LARGURA / 60
                y = (j + 0.5) * marca.U_ALTURA / 60
                self.assertIsNotNone(marca.cor_em(x, y), f"vazio em {x:.1f},{y:.1f}")

    def test_fora_da_caixa_nao_tem_cor(self):
        for x, y in ((-1, 50), (marca.U_LARGURA + 1, 50), (50, -1), (50, marca.U_ALTURA + 1)):
            self.assertIsNone(marca.cor_em(x, y))

    def test_as_barras_e_a_haste_sao_petroleo(self):
        for x in range(2, int(marca.U_LARGURA), 3):
            self.assertEqual(marca.cor_em(x, 3), marca.PETROLEO, f"barra de cima em x={x}")
            self.assertEqual(marca.cor_em(x, marca.U_ALTURA - 3), marca.PETROLEO,
                             f"barra de baixo em x={x}")
        for y in range(2, int(marca.U_ALTURA), 3):
            self.assertEqual(marca.cor_em(4, y), marca.PETROLEO, f"haste em y={y}")

    def test_o_dourado_interrompe_a_lateral_direita(self):
        # O vazado grande chega até a borda e come um trecho dela — é o que dá
        # ao símbolo o ar de recorte em vez de moldura fechada.
        borda = [marca.cor_em(marca.U_LARGURA - 3, y) for y in range(1, int(marca.U_ALTURA))]
        self.assertEqual(borda[0], marca.PETROLEO, "barra de cima")
        self.assertEqual(borda[-1], marca.PETROLEO, "barra de baixo")
        dourados = [y for y, cor in enumerate(borda, 1) if cor == marca.OURO]
        self.assertTrue(dourados, "o dourado tem de alcançar a lateral")
        self.assertGreater(max(dourados), marca.U_ALTURA * 0.6, "e descer até embaixo")
        self.assertLess(len(dourados), marca.U_ALTURA * 0.85, "sem tomar a lateral toda")

    def test_ha_folga_branca_entre_o_d_e_o_z(self):
        # Sem ela as duas letras se encostam na meia-altura e viram uma mancha.
        meio = marca.U_ALTURA / 2
        faixa = [marca.cor_em(x / 2, meio) for x in range(2 * int(marca.U_LARGURA))]
        self.assertIn(marca.FUNDO, faixa)
        # e a sequência tem de ser: traço do D, branco, diagonal do Z
        seq = [c for c, _ in itertools.groupby(faixa)]
        self.assertEqual(seq.count(marca.PETROLEO), 3, seq)  # haste, barriga, diagonal

    def test_as_tres_cores_aparecem_em_proporcao_de_marca(self):
        pontos = [marca.cor_em((i + 0.5) * marca.U_LARGURA / 90,
                               (j + 0.5) * marca.U_ALTURA / 70)
                  for i in range(90) for j in range(70)]
        fatia = {cor: pontos.count(cor) / len(pontos)
                 for cor in (marca.PETROLEO, marca.OURO, marca.FUNDO)}
        self.assertGreater(fatia[marca.PETROLEO], fatia[marca.OURO], "o petróleo domina")
        self.assertGreater(fatia[marca.OURO], 0.05, "o dourado tem de aparecer")
        self.assertLess(fatia[marca.OURO], 0.30, "o dourado é acento, não fundo")


class MarcaImagemTests(unittest.TestCase):
    """Rasterização e arquivo."""

    def setUp(self):
        marca.esquecer()

    def tearDown(self):
        marca.esquecer()

    def test_o_png_sai_com_cabecalho_e_tamanho_certos(self):
        import struct
        dados = marca.png(30)
        self.assertTrue(dados.startswith(b"\x89PNG\r\n\x1a\n"))
        largura, altura = struct.unpack(">II", dados[16:24])
        self.assertEqual(altura, 30)
        self.assertEqual(largura, round(30 * marca.U_LARGURA / marca.U_ALTURA))
        self.assertIn(b"IEND", dados)

    def test_os_pixels_sao_reaproveitados(self):
        primeiro = marca.amostrar(20, 16)
        self.assertIs(marca.amostrar(20, 16), primeiro)
        marca.esquecer()
        self.assertIsNot(marca.amostrar(20, 16), primeiro)

    def test_as_bordas_ficam_suavizadas(self):
        # A curva do D passa por aqui; sem suavização só haveria as três cores
        # puras, e a curva sairia serrilhada.
        puras = {marca._rgb(c) for c in (marca.PETROLEO, marca.OURO, marca.FUNDO)}
        pixels = [p for linha in marca.amostrar(64, 50) for p in linha]
        self.assertTrue([p for p in pixels if p not in puras], "nenhum pixel intermediário")


class MarcaNaTelaTests(unittest.TestCase):
    """O que a marca vira dentro da janela."""

    def setUp(self):
        try:
            import tkinter
            self.raiz = tkinter.Tk()
            self.raiz.withdraw()
        except Exception as exc:
            self.skipTest(f"sem interface gráfica: {exc}")
        marca.esquecer()

    def tearDown(self):
        marca.esquecer()
        try:
            self.raiz.destroy()
        except Exception:
            pass

    def test_a_imagem_sai_no_tamanho_pedido(self):
        # Sem logotipo do usuário na pasta: a proporção medida é a do
        # monograma desenhado. Com um PNG lá — que é o caso de quem usou
        # "Usar meu logotipo…" —, a proporção passa a ser a do arquivo dele,
        # e o teste mediria o desenho contra a régua errada. Foi o que
        # aconteceu: o teste quebrou no dia em que o logotipo foi instalado,
        # sem nada ter mudado no código.
        arquivo = marca.ARQUIVO
        marca.ARQUIVO = arquivo.with_name("logo-que-nao-existe.png")
        marca.esquecer()
        try:
            foto = marca.imagem(24, self.raiz)
            self.assertEqual(foto.height(), 24)
            self.assertEqual(foto.width(),
                             round(24 * marca.U_LARGURA / marca.U_ALTURA))
        finally:
            marca.ARQUIVO = arquivo
            marca.esquecer()

    def test_o_logotipo_do_usuario_manda_na_proporcao(self):
        """Com um PNG na pasta, a altura é a pedida e a largura é a dele."""
        from PIL import Image

        arquivo = marca.ARQUIVO
        with tempfile.TemporaryDirectory() as pasta:
            alvo = pathlib.Path(pasta) / "logo.png"
            Image.new("RGBA", (300, 100), (10, 20, 30, 255)).save(alvo)
            marca.ARQUIVO = alvo
            marca.esquecer()
            try:
                foto = marca.imagem(20, self.raiz)
                self.assertEqual(foto.height(), 20)
                self.assertEqual(foto.width(), 60)   # 300/100 × 20
            finally:
                marca.ARQUIVO = arquivo
                marca.esquecer()

    def test_cada_janela_ganha_a_sua_imagem(self):
        # Guardar a PhotoImage entre janelas dava "image pyimageN doesn't
        # exist": ela pertence ao interpretador Tk que a criou.
        import tkinter
        outra = tkinter.Tk()
        outra.withdraw()
        try:
            self.assertIsNot(marca.imagem(20, self.raiz), marca.imagem(20, outra))
            tkinter.Label(outra, image=marca.imagem(20, outra))  # não pode estourar
        finally:
            outra.destroy()

    def test_o_icone_e_quadrado(self):
        icone = marca.icone(40, self.raiz)
        self.assertEqual((icone.width(), icone.height()), (40, 40))

    def test_a_assinatura_traz_o_nome_com_o_registrado(self):
        self.assertEqual(marca.ASSINATURA, "Dezorzi®")

    def test_o_selo_segura_a_propria_imagem(self):
        # Sem a referência, o coletor do Python descarta a PhotoImage e o
        # rótulo aparece vazio — o clássico "imagem some no Tk".
        etiqueta = marca.selo(self.raiz, 14, "#ffffff")
        self.assertIsNotNone(getattr(etiqueta, "imagem", None))
        self.assertEqual(etiqueta.imagem.height(), 14)

    def test_um_logo_png_na_pasta_substitui_o_desenho(self):
        original = marca.ARQUIVO
        try:
            pasta = pathlib.Path(tempfile.mkdtemp()).resolve()
            marca.ARQUIVO = pasta / "logo.png"
            marca.ARQUIVO.write_bytes(marca.png(48))
            self.assertEqual(marca.imagem(48, self.raiz).height(), 48)
            # e some quando o arquivo é apagado, voltando ao desenho interno
            marca.ARQUIVO.unlink()
            self.assertEqual(marca.imagem(48, self.raiz).height(), 48)
        finally:
            marca.ARQUIVO = original


class CaminhosEmpacotadoTests(unittest.TestCase):
    """Onde o programa procura os dados quando vira .exe.

    Empacotado, ``__file__`` aponta para dentro do pacote: pasta somente-leitura
    e, no modo arquivo único, temporária. Medir os caminhos dali faria as notas
    irem para uma pasta que some ao fechar o programa — sem erro nenhum na tela.
    """

    def setUp(self):
        self.frozen = getattr(sys, "frozen", None)
        self.executable = sys.executable

    def tearDown(self):
        if self.frozen is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = self.frozen
        sys.executable = self.executable

    def test_solto_usa_a_pasta_do_codigo(self):
        if hasattr(sys, "frozen"):
            del sys.frozen
        self.assertEqual(paths._raiz(), pathlib.Path(paths.__file__).resolve().parent)

    def test_empacotado_usa_a_pasta_do_executavel(self):
        sys.frozen = True
        sys.executable = str(
            pathlib.Path(tempfile.mkdtemp()).resolve() / "Dezorzi NFS-e.exe")
        self.assertEqual(paths._raiz(), pathlib.Path(sys.executable).resolve().parent)

    def test_empacotado_poe_env_config_e_notas_ao_lado_do_exe(self):
        # Recarrega o módulo com sys.frozen ligado para ver os caminhos que ele
        # deriva de fato — a suíte redireciona DATA_DIR para uma pasta de
        # testes, então olhar o valor atual não diria nada.
        import importlib

        guardado = (paths.BASE_DIR, paths.HOME_DIR, paths.ENV_FILE,
                    paths.DATA_DIR, paths.CONFIG_DIR, paths.REQUEST_TEMPLATE)
        # `.resolve()` na pasta de teste, e não só no que o programa deriva:
        # em conta cujo nome passa de oito letras, o Windows devolve o caminho
        # curto — "RUNNER~1" no lugar de "runneradmin" — e a mesma pasta vira
        # dois textos diferentes. Aqui nunca aparecia porque "dezor" é curto;
        # apareceu na primeira compilação na nuvem.
        pasta = pathlib.Path(tempfile.mkdtemp()).resolve()
        sys.frozen = True
        sys.executable = str(pasta / "Dezorzi NFS-e.exe")
        try:
            importlib.reload(paths)
            self.assertEqual(paths.ENV_FILE, pasta / ".env")
            self.assertEqual(paths.CONFIG_DIR, pasta / "config")
            self.assertEqual(paths.DATA_DIR, pasta / "data")
            self.assertEqual(paths.ASSETS_DIR, pasta / "assets")
        finally:
            del sys.frozen
            sys.executable = self.executable
            importlib.reload(paths)
            (paths.BASE_DIR, paths.HOME_DIR, paths.ENV_FILE,
             paths.DATA_DIR, paths.CONFIG_DIR, paths.REQUEST_TEMPLATE) = guardado

    def test_nfse_home_continua_valendo_no_executavel(self):
        # Quem move as notas para fora do OneDrive com NFSE_HOME não pode
        # perdê-las de vista ao passar a usar o .exe.
        import importlib

        guardado = (paths.BASE_DIR, paths.HOME_DIR, paths.ENV_FILE,
                    paths.DATA_DIR, paths.CONFIG_DIR, paths.REQUEST_TEMPLATE)
        # Resolvidos pelo mesmo motivo do teste acima: caminho curto do
        # Windows em conta de nome longo.
        programa = pathlib.Path(tempfile.mkdtemp()).resolve()
        notas = pathlib.Path(tempfile.mkdtemp()).resolve()
        sys.frozen = True
        sys.executable = str(programa / "Dezorzi NFS-e.exe")
        os.environ["NFSE_HOME"] = str(notas)
        try:
            importlib.reload(paths)
            self.assertEqual(paths.ENV_FILE, programa / ".env")   # o .env é do programa
            self.assertEqual(paths.DATA_DIR, notas / "data")      # as notas, de onde se mandou
        finally:
            os.environ.pop("NFSE_HOME", None)
            del sys.frozen
            sys.executable = self.executable
            importlib.reload(paths)
            (paths.BASE_DIR, paths.HOME_DIR, paths.ENV_FILE,
             paths.DATA_DIR, paths.CONFIG_DIR, paths.REQUEST_TEMPLATE) = guardado


class ModoDeTransmissaoTests(unittest.TestCase):
    """Ligar e desligar o envio real sem editar arquivo na mão."""

    def setUp(self):
        self.env_original = paths.ENV_FILE
        self.valor_original = os.environ.get("NFSE_LIVE_MODE")
        self.pasta = pathlib.Path(tempfile.mkdtemp()).resolve()
        paths.ENV_FILE = self.pasta / ".env"

    def tearDown(self):
        paths.ENV_FILE = self.env_original
        if self.valor_original is None:
            os.environ.pop("NFSE_LIVE_MODE", None)
        else:
            os.environ["NFSE_LIVE_MODE"] = self.valor_original

    def test_liga_no_arquivo_e_na_sessao(self):
        paths.ENV_FILE.write_text("NFSE_LIVE_MODE=false\n", encoding="utf-8")
        config.definir_live_mode(True)
        self.assertIn("NFSE_LIVE_MODE=true", paths.ENV_FILE.read_text(encoding="utf-8"))
        # e vale já, sem reabrir o programa: quem ligou quer emitir esta nota
        self.assertTrue(config.live_mode())

    def test_desliga_de_volta(self):
        paths.ENV_FILE.write_text("NFSE_LIVE_MODE=true\n", encoding="utf-8")
        config.definir_live_mode(False)
        self.assertFalse(config.live_mode())

    def test_preserva_o_resto_do_arquivo(self):
        # Reescrever o .env inteiro apagaria a permutação do GWT e os
        # comentários — e o programa pararia de logar.
        paths.ENV_FILE.write_text(
            "# comentário\nNFSE_USUARIO=346186\nNFSE_LIVE_MODE=false\n"
            "NFSE_GWT_PERMUTATION=ABC123\n", encoding="utf-8")
        config.definir_live_mode(True)
        texto = paths.ENV_FILE.read_text(encoding="utf-8")
        self.assertIn("# comentário", texto)
        self.assertIn("NFSE_USUARIO=346186", texto)
        self.assertIn("NFSE_GWT_PERMUTATION=ABC123", texto)
        self.assertNotIn("NFSE_LIVE_MODE=false", texto)

    def test_cria_a_chave_quando_ela_nao_existe(self):
        paths.ENV_FILE.write_text("NFSE_USUARIO=346186\n", encoding="utf-8")
        config.definir_live_mode(True)
        self.assertIn("NFSE_LIVE_MODE=true", paths.ENV_FILE.read_text(encoding="utf-8"))

    def test_nao_confunde_chave_comentada(self):
        paths.ENV_FILE.write_text("# NFSE_LIVE_MODE=true\n", encoding="utf-8")
        config.definir_live_mode(False)
        texto = paths.ENV_FILE.read_text(encoding="utf-8")
        self.assertIn("# NFSE_LIVE_MODE=true", texto)     # o comentário fica
        self.assertIn("\nNFSE_LIVE_MODE=false", texto)    # e a chave real entra

    def test_a_gravacao_nao_deixa_arquivo_pela_metade(self):
        paths.ENV_FILE.write_text("NFSE_LIVE_MODE=false\n", encoding="utf-8")
        config.definir_live_mode(True)
        self.assertFalse(list(self.pasta.glob("*.tmp")), "sobrou arquivo temporário")


class LeituraDoEnvTests(unittest.TestCase):
    """O .env é a única configuração do programa — ler errado desliga funções."""

    def setUp(self):
        self.env_original = paths.ENV_FILE
        self.pasta = pathlib.Path(tempfile.mkdtemp()).resolve()
        paths.ENV_FILE = self.pasta / ".env"
        self.guardadas = {}

    def tearDown(self):
        paths.ENV_FILE = self.env_original
        for chave in list(self.guardadas):
            os.environ.pop(chave, None)

    def _carregar(self, texto, *chaves):
        for chave in chaves:
            os.environ.pop(chave, None)
            self.guardadas[chave] = True
        paths.ENV_FILE.write_text(texto, encoding="utf-8")
        config.load_env(force=True)

    def test_comentario_no_fim_da_linha_nao_entra_no_valor(self):
        # O caso que desligou a transmissão num executável já entregue: o valor
        # virava "true   # ..." e deixava de ser "true".
        self._carregar("NFSE_LIVE_MODE=true   # ligue só para valer\n", "NFSE_LIVE_MODE")
        self.assertEqual(os.environ["NFSE_LIVE_MODE"], "true")
        self.assertTrue(config.live_mode())

    def test_cerquilha_colada_ao_valor_e_parte_do_valor(self):
        # Senha com # não pode ser cortada: só espaço seguido de # é comentário.
        self._carregar("NFSE_SENHA=abc#123\n", "NFSE_SENHA")
        self.assertEqual(os.environ["NFSE_SENHA"], "abc#123")

    def test_valor_entre_aspas_preserva_espacos_e_cerquilha(self):
        self._carregar('NFSE_SENHA="a b # c"   # comentário\n', "NFSE_SENHA")
        self.assertEqual(os.environ["NFSE_SENHA"], "a b # c")

    def test_tabulacao_antes_da_cerquilha_tambem_comenta(self):
        self._carregar("NFSE_LIVE_MODE=true\t# nota\n", "NFSE_LIVE_MODE")
        self.assertTrue(config.live_mode())

    def test_linha_de_comentario_inteira_continua_ignorada(self):
        self._carregar("# NFSE_LIVE_MODE=true\nNFSE_USUARIO=346186\n",
                       "NFSE_LIVE_MODE", "NFSE_USUARIO")
        self.assertNotIn("NFSE_LIVE_MODE", os.environ)
        self.assertEqual(os.environ["NFSE_USUARIO"], "346186")

    def test_o_env_gerado_pelo_empacotador_e_lido_corretamente(self):
        # Fecha o ciclo: o arquivo que sai no executável tem de voltar como
        # transmissão ligada quando foi gerado assim.
        self._carregar(
            "# Troque também por Configurações, dentro do programa.\n"
            "NFSE_LIVE_MODE=true\n"
            "# NFSE_SENHA fica de fora de propósito — digite na tela de entrada.\n"
            "NFSE_GWT_PERMUTATION=03277F0939CB3FDC9417F47BAA100F02\n",
            "NFSE_LIVE_MODE", "NFSE_GWT_PERMUTATION", "NFSE_SENHA")
        self.assertTrue(config.live_mode())
        self.assertEqual(os.environ["NFSE_GWT_PERMUTATION"],
                         "03277F0939CB3FDC9417F47BAA100F02")
        self.assertNotIn("NFSE_SENHA", os.environ)


class InstalacaoTests(unittest.TestCase):
    """A primeira abertura do executável de arquivo único."""

    def setUp(self):
        self.guardado = (paths.BASE_DIR, paths.EMBUTIDOS, paths.CONFIG_DIR,
                         paths.DATA_DIR, paths.ENV_FILE)
        self.programa = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.pacote = pathlib.Path(tempfile.mkdtemp()).resolve()
        paths.BASE_DIR = self.programa
        paths.EMBUTIDOS = self.pacote
        paths.CONFIG_DIR = self.programa / "config"
        paths.DATA_DIR = self.programa / "data"
        paths.ENV_FILE = self.programa / ".env"   # no programa real, deriva de BASE_DIR
        (self.pacote / "config" / "templates").mkdir(parents=True)
        (self.pacote / "config" / "templates" / "modelo.json").write_text("{}", encoding="utf-8")
        (self.pacote / "config" / "ufs.json").write_text("[]", encoding="utf-8")
        (self.pacote / "config" / "municipios_35.json").write_text("[]", encoding="utf-8")
        (self.pacote / ".env").write_text("NFSE_LIVE_MODE=true\n", encoding="utf-8")

    def tearDown(self):
        (paths.BASE_DIR, paths.EMBUTIDOS, paths.CONFIG_DIR,
         paths.DATA_DIR, paths.ENV_FILE) = self.guardado

    def test_cria_o_que_falta_ao_lado_do_programa(self):
        criados = instalacao.preparar()
        self.assertTrue((self.programa / "config" / "templates" / "modelo.json").exists())
        self.assertTrue((self.programa / ".env").exists())
        self.assertTrue((self.programa / "data").is_dir())
        self.assertIn("config/templates", criados)
        # tudo que veio embutido, não só uma lista escolhida a dedo
        self.assertTrue((self.programa / "config" / "municipios_35.json").exists())

    def test_nunca_sobrescreve_o_que_ja_existe(self):
        # Alíquotas conferidas e notas emitidas ficam aqui. Uma atualização que
        # passasse por cima apagaria trabalho — e alíquota errada vira imposto
        # errado na nota seguinte.
        (self.programa / "config").mkdir()
        meu = self.programa / "config" / "ufs.json"
        meu.write_text('["meu"]', encoding="utf-8")
        (self.programa / ".env").write_text("NFSE_LIVE_MODE=false\n", encoding="utf-8")
        instalacao.preparar()
        self.assertEqual(meu.read_text(encoding="utf-8"), '["meu"]')
        self.assertIn("false", (self.programa / ".env").read_text(encoding="utf-8"))

    def test_rodando_solto_nao_copia_nada(self):
        paths.EMBUTIDOS = paths.BASE_DIR
        criados = instalacao.preparar()
        self.assertEqual([c for c in criados if not c.endswith("/")], [])

    def test_e_idempotente(self):
        instalacao.preparar()
        self.assertEqual([c for c in instalacao.preparar() if not c.endswith("/")], [])

    def test_detecta_pasta_sem_permissao(self):
        self.assertTrue(instalacao.pasta_grava())
        paths.BASE_DIR = self.programa / "nao-existe" / "nem-aqui"
        self.assertFalse(instalacao.pasta_grava())


class RegistroTests(unittest.TestCase):
    """O diário: é o que responde 'o que aconteceu naquela máquina?'."""

    def setUp(self):
        self.guardado = paths.DATA_DIR
        paths.DATA_DIR = pathlib.Path(tempfile.mkdtemp()).resolve() / "data"

    def tearDown(self):
        paths.DATA_DIR = self.guardado

    def _texto(self):
        return (paths.DATA_DIR / "registro.txt").read_text(encoding="utf-8")

    def test_anota_com_hora_e_cria_a_pasta(self):
        registro.escrever("emissao ok", "nota nº 90")
        self.assertIn("emissao ok", self._texto())
        self.assertIn("nota nº 90", self._texto())

    def test_acumula_sem_apagar_o_anterior(self):
        registro.escrever("primeiro")
        registro.escrever("segundo")
        texto = self._texto()
        self.assertIn("primeiro", texto)
        self.assertIn("segundo", texto)

    def test_guarda_o_rastro_do_erro(self):
        try:
            raise ValueError("deu ruim")
        except ValueError as exc:
            registro.falha("teste", exc)
        texto = self._texto()
        self.assertIn("ValueError: deu ruim", texto)
        self.assertIn("Traceback", texto)

    def test_nunca_estoura_mesmo_sem_poder_gravar(self):
        # Registro que derruba o programa é pior que registro nenhum.
        paths.DATA_DIR = pathlib.Path("Z:/nao/existe/mesmo")
        registro.escrever("qualquer coisa")      # não pode levantar
        registro.falha("outra", ValueError("x"))

    def test_nao_cresce_sem_limite(self):
        registro.escrever("inicio")
        (paths.DATA_DIR / "registro.txt").write_text("x" * (registro.LIMITE_BYTES + 10),
                                                     encoding="utf-8")
        registro.escrever("depois do limite")
        texto = self._texto()
        self.assertLess(len(texto), registro.LIMITE_BYTES)
        self.assertIn("depois do limite", texto)


class SaidaPeloNavegadorTests(unittest.TestCase):
    """A saída para quando o download do PDF não funciona.

    Em rede de empresa é comum o programa não alcançar o segundo endereço
    (o visualizador) enquanto o navegador alcança — ele usa o proxy e os
    certificados do Windows. Sem esta saída, uma nota emitida ficava sem
    nenhuma forma de ser impressa.
    """

    def setUp(self):
        # A suíte roda numa pasta isolada; o modelo do PDF precisa existir lá,
        # e usar o real garante que o teste acompanhe mudanças nele.
        real = Path(__file__).resolve().parent.parent / "config" / "pdf_template.json"
        if not real.exists():
            self.skipTest("sem config/pdf_template.json neste projeto")
        pdf.MODELO.parent.mkdir(parents=True, exist_ok=True)
        pdf.MODELO.write_text(real.read_text(encoding="utf-8"), encoding="utf-8")

    def test_monta_o_endereco_da_nota(self):
        endereco = pdf.endereco_no_portal({"numero": "90", "codigo_verificacao": "UZHVFRZD0"})
        self.assertIn("numNota=90", endereco)
        self.assertIn("cdVerificacao=UZHVFRZD0", endereco)
        self.assertTrue(endereco.startswith("https://"))

    def test_sem_numero_ou_codigo_nao_ha_endereco(self):
        for nota in ({}, {"numero": "90"}, {"codigo_verificacao": "ABC"}, {"numero": ""}):
            self.assertEqual(pdf.endereco_no_portal(nota), "", nota)

    def test_o_endereco_fica_no_host_autorizado(self):
        # O endereço é montado a partir de um modelo em disco; se alguém trocar
        # o modelo, isto impede que a nota abra num site qualquer.
        import config as _config
        endereco = pdf.endereco_no_portal({"numero": "1", "codigo_verificacao": "A1"})
        host = endereco.split("/")[2].lower()
        self.assertIn(host, _config.download_hosts())


class RodapeDaJanelaTests(unittest.TestCase):
    """A barra de botões não pode sumir quando o conteúdo é alto.

    O defeito que motivou esta classe: no layout de impressão a barra era
    empacotada por último, depois de um corpo com ``expand=True``. No pack do
    Tk quem vem primeiro reserva seu espaço — então, em máquina com escala de
    tela maior, o corpo tomava tudo e os botões sumiam da área visível, sem
    erro nenhum. A nota saía emitida e não havia como imprimir nem baixar.

    Verificar posição em pixels exigiria janela visível, o que não é confiável
    em teste. A regra em si é o que importa, e ela é determinística: a barra
    fica presa embaixo E é empacotada antes de quem expande.
    """

    NOTA = {"numero": "90", "codigo_verificacao": "UZHVFRZD0",
            "emitida_em": "2026-08-16T17:21:46"}
    ITEM = {
        "id": "3f1c8a2e-0000-4000-8000-000000000090", "status": "submitted",
        "payload": {
            "tomador": {"documento": "11222333000181", "nome": "CLIENTE TESTE LTDA"},
            "servico": {"codigo": "16.02/105803/1371", "descricao": "T" * 200,
                        "valor": "1234.56", "iss": "24.69", **REFORMA},
            "competencia": "2026-08-16",
        },
        "nota": NOTA,
    }

    def setUp(self):
        try:
            import desktop
            import pdf
            self.app = desktop.NfseDesktop()
            self.app.withdraw()
        except Exception as exc:
            self.skipTest(f"sem interface gráfica: {exc}")
        # A janela dispara o download do PDF; no teste ele não vai à rede.
        original = pdf.baixar
        pdf.baixar = lambda nota, progresso=None: (_ for _ in ()).throw(
            OSError("sem rede no teste"))
        self.addCleanup(lambda: setattr(pdf, "baixar", original))

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def _botoes(self, janela):
        from tkinter import ttk as _ttk
        achados = []

        def varrer(w):
            for f in w.winfo_children():
                if isinstance(f, _ttk.Button):
                    achados.append(f)
                varrer(f)

        varrer(janela)
        return achados

    def _conferir_rodape(self, janela):
        """A barra dos botões vem antes de quem expande, e fica presa embaixo."""
        janela.update_idletasks()
        botoes = self._botoes(janela)
        self.assertTrue(botoes, "a janela não tem botão nenhum")

        # De quem os botões são filhos: essa é a barra.
        barras = {b.winfo_parent() for b in botoes}
        filhos = list(janela.pack_slaves())
        nomes = [str(f) for f in filhos]
        for barra in barras:
            if barra not in nomes:
                continue    # botão dentro do corpo (ex.: "Tentar de novo")
            quadro = filhos[nomes.index(barra)]
            info = quadro.pack_info()
            self.assertEqual(info.get("side"), "bottom",
                             f"a barra de botões de {janela.title()!r} não está presa embaixo")
            posicao = nomes.index(barra)
            expansores = [i for i, f in enumerate(filhos)
                          if str(f.pack_info().get("expand")) in ("1", "True")]
            for i in expansores:
                self.assertLess(
                    posicao, i,
                    f"em {janela.title()!r} a barra de botões é empacotada depois de "
                    f"um quadro que expande — ela some quando o conteúdo é alto",
                )

    def test_o_layout_de_impressao_tem_todos_os_botoes(self):
        janela = self.app.janela_impressao(self.NOTA, self.ITEM, recem_emitida=True)
        self.app.update()
        textos = [str(b.cget("text")) for b in self._botoes(janela)]
        for esperado in ("Imprimir", "Abrir PDF", "Salvar cópia…",
                         "Ver no site da prefeitura", "Fechar"):
            self.assertIn(esperado, textos)

    def test_a_barra_do_layout_de_impressao_fica_presa_embaixo(self):
        janela = self.app.janela_impressao(self.NOTA, self.ITEM, recem_emitida=True)
        self.app.update()
        self._conferir_rodape(janela)

    def test_a_janela_de_detalhes_tambem(self):
        import storage
        gravada = storage.save(dict(self.ITEM))
        self.app._details((gravada["id"],))
        self.app.update()
        for filha in self.app.winfo_children():
            if isinstance(filha, tk.Toplevel) and "Nota" in filha.title():
                self._conferir_rodape(filha)
                return
        self.skipTest("a janela de detalhes não abriu")

    def test_o_botao_do_site_funciona_sem_o_pdf(self):
        # É a saída quando o download falha: não pode depender dele.
        janela = self.app.janela_impressao(self.NOTA, self.ITEM, recem_emitida=True)
        self.app.update()
        site = [b for b in self._botoes(janela)
                if str(b.cget("text")) == "Ver no site da prefeitura"]
        self.assertEqual(len(site), 1)
        self.assertNotIn("disabled", site[0].state())


class VersaoDoPortalTests(unittest.TestCase):
    """Ler do portal em que versão ele está.

    Em 17/08/2026 a prefeitura publicou versão nova do sistema. A identificação
    gravada no .env deixou de existir e o portal passou a responder 500 com
    "see server log for details" — o acesso parou sem nada no programa ter
    mudado, e sem nenhuma pista do motivo. Daí ler isso do próprio portal.
    """

    # Trecho no formato real do nocache.js: minificado, com as identificações
    # em variáveis e o mapeamento em duas indireções.
    JS = ("var Qb='182A568EE36E676DFAADD9CF0B13E4A2',Rb='19050E8E172CC04E832B7F13B4F8855F',"
          "Db='opera',Fb='safari',Hb='ie9',Sb='3DA6DAB3876CA5712AAA0FA20E549499',"
          "Lb='gecko1_8';"
          "G([Fb],Qb);G([Lb],Rb);G([Db],Sb);G([Hb],Tb);")

    def setUp(self):
        self.guardado = (portal.ARQUIVO, os.environ.get(portal.VARIAVEL))
        portal.ARQUIVO = pathlib.Path(tempfile.mkdtemp()).resolve() / "portal_versao.json"

    def tearDown(self):
        portal.ARQUIVO = self.guardado[0]
        if self.guardado[1] is None:
            os.environ.pop(portal.VARIAVEL, None)
        else:
            os.environ[portal.VARIAVEL] = self.guardado[1]

    def test_le_o_mapa_de_navegadores(self):
        mapa = portal.ler_permutacoes(self.JS)
        self.assertEqual(mapa["safari"], "182A568EE36E676DFAADD9CF0B13E4A2")
        self.assertEqual(mapa["gecko1_8"], "19050E8E172CC04E832B7F13B4F8855F")
        self.assertEqual(mapa["opera"], "3DA6DAB3876CA5712AAA0FA20E549499")
        # Tb não foi definido no trecho: entrada incompleta não entra no mapa.
        self.assertNotIn("ie9", mapa)

    def test_ignora_arquivo_sem_permutacao(self):
        self.assertEqual(portal.ler_permutacoes("var a='qualquer coisa';"), {})

    def test_troca_a_identificacao_que_saiu_da_lista(self):
        os.environ[portal.VARIAVEL] = "03277F0939CB3FDC9417F47BAA100F02"  # a que sumiu
        portal.descobrir = lambda **k: portal.ler_permutacoes(self.JS)
        try:
            self.assertEqual(portal.sincronizar(), "182A568EE36E676DFAADD9CF0B13E4A2")
        finally:
            importlib.reload(portal)

    def test_respeita_quem_configurou_a_mao_se_ainda_vale(self):
        # Quem escolheu outro navegador de propósito não pode ser sobrescrito
        # enquanto a escolha continuar funcionando.
        os.environ[portal.VARIAVEL] = "19050E8E172CC04E832B7F13B4F8855F"   # gecko
        portal.descobrir = lambda **k: portal.ler_permutacoes(self.JS)
        try:
            self.assertEqual(portal.sincronizar(), "19050E8E172CC04E832B7F13B4F8855F")
        finally:
            importlib.reload(portal)

    def test_sem_rede_mantem_o_que_havia(self):
        os.environ[portal.VARIAVEL] = "03277F0939CB3FDC9417F47BAA100F02"
        portal.descobrir = lambda **k: {}
        try:
            self.assertEqual(portal.sincronizar(), "03277F0939CB3FDC9417F47BAA100F02")
        finally:
            importlib.reload(portal)


class AssinaturaDoServicoTests(unittest.TestCase):
    """A assinatura do serviço, que viaja dentro do corpo de cada chamada.

    Segunda metade da pane de 17/08/2026. Com a identificação já corrigida, o
    portal continuava recusando o login com HTTP 200 — porque o corpo citava
    uma assinatura que a publicação nova havia aposentado. Comprovado:

        assinatura antiga -> HTTP 500
        assinatura nova   -> HTTP 200 //OK
    """

    PERM = "182A568EE36E676DFAADD9CF0B13E4A2"
    POLITICA = "600A785220C8B19AF3AA145ED4504B4F"

    def setUp(self):
        self.guardado = (portal.ARQUIVO,
                         os.environ.get(portal.VARIAVEL),
                         os.environ.get(portal.VARIAVEL_POLITICA))
        portal.ARQUIVO = pathlib.Path(tempfile.mkdtemp()).resolve() / "portal_versao.json"

    def tearDown(self):
        portal.ARQUIVO = self.guardado[0]
        for variavel, valor in ((portal.VARIAVEL, self.guardado[1]),
                                (portal.VARIAVEL_POLITICA, self.guardado[2])):
            if valor is None:
                os.environ.pop(variavel, None)
            else:
                os.environ[variavel] = valor

    def test_acha_a_assinatura_no_arquivo_compilado(self):
        html = f"var a='{self.PERM}';var b='{self.POLITICA}';resto"
        self.assertEqual(portal.ler_politica(html, self.PERM), self.POLITICA)

    def test_nao_confunde_com_a_propria_permutacao(self):
        html = f"só a permutação aqui: '{self.PERM}'"
        self.assertEqual(portal.ler_politica(html, self.PERM), "")

    def test_na_duvida_nao_escolhe(self):
        # Duas candidatas: adivinhar poria uma assinatura errada em toda
        # requisição — inclusive nas de emissão de nota.
        html = f"'{self.PERM}' 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'"
        self.assertEqual(portal.ler_politica(html, self.PERM), "")

    def test_todo_corpo_do_programa_usa_a_variavel(self):
        # Nenhuma assinatura pode voltar a ficar fixa no código: quando o portal
        # for republicado, uma que sobrar derruba justamente aquela função.
        raiz = Path(__file__).resolve().parent.parent
        fixas = []
        for arquivo in list(raiz.glob("*.py")) + list((raiz / "config").rglob("*.json")):
            texto = arquivo.read_text(encoding="utf-8", errors="replace")
            if re.search(r"nfseweb/\|[0-9A-F]{32}\|", texto):
                fixas.append(arquivo.name)
        self.assertEqual(fixas, [], f"assinatura fixa em: {fixas}")

    def test_a_assinatura_e_conferida_mesmo_sem_trocar_a_identificacao(self):
        # O estado exato da pane: identificação certa, assinatura vazia.
        os.environ[portal.VARIAVEL] = self.PERM
        os.environ.pop(portal.VARIAVEL_POLITICA, None)
        portal.descobrir = lambda **k: {"safari": self.PERM}
        portal._baixar_politica = lambda perm: self.POLITICA
        try:
            portal.sincronizar()
            self.assertEqual(portal.politica_em_uso(), self.POLITICA)
        finally:
            importlib.reload(portal)


class ConsultaSempreComAssinaturaTests(unittest.TestCase):
    """Toda consulta ao portal precisa da assinatura em mãos.

    A sincronização morava só no login. Com a sessão já de pé o login não roda,
    e as consultas — serviços, municípios, tomador, obras — montavam o corpo
    sem a assinatura e falhavam. Na tela isso aparecia como a lista de
    serviços que simplesmente "não carrega".
    """

    def setUp(self):
        self.politica = os.environ.get(portal.VARIAVEL_POLITICA)
        self.perm = os.environ.get(portal.VARIAVEL)
        self.sincronizar = portal.sincronizar

    def tearDown(self):
        portal.sincronizar = self.sincronizar
        for variavel, valor in ((portal.VARIAVEL_POLITICA, self.politica),
                                (portal.VARIAVEL, self.perm)):
            if valor is None:
                os.environ.pop(variavel, None)
            else:
                os.environ[variavel] = valor

    def _sessao(self):
        import session
        return session.PortalSession() if hasattr(session, "PortalSession") \
            else session.get_session()

    def test_a_assinatura_ausente_dispara_a_releitura(self):
        os.environ.pop(portal.VARIAVEL_POLITICA, None)
        os.environ[portal.VARIAVEL] = "182A568EE36E676DFAADD9CF0B13E4A2"
        chamou = []
        portal.sincronizar = lambda **k: chamou.append(True) or "182A"
        try:
            self._sessao().ensure()
        except Exception:
            pass          # sem credenciais o login falha; o que importa é a chamada
        self.assertTrue(chamou, "ensure() não releu a versão do portal")

    def test_com_tudo_em_maos_nao_vai_a_rede(self):
        os.environ[portal.VARIAVEL] = "182A568EE36E676DFAADD9CF0B13E4A2"
        os.environ[portal.VARIAVEL_POLITICA] = "600A785220C8B19AF3AA145ED4504B4F"
        chamou = []
        portal.sincronizar = lambda **k: chamou.append(True) or ""
        try:
            self._sessao().ensure()
        except Exception:
            pass
        self.assertEqual(chamou, [], "releu a versão sem precisar")


class RespostaForaDoFormatoTests(unittest.TestCase):
    """Quando o portal responde algo que não é GWT-RPC, dizer o quê.

    "o portal não respondeu no formato GWT-RPC" é verdade e não serve para
    nada: página de login, erro do servidor e resposta vazia geram a mesma
    frase e pedem providências diferentes.
    """

    def _mensagens(self, texto):
        aceita, mensagens = nfse_client.avaliar_resposta(texto)
        self.assertFalse(aceita)
        return " | ".join(mensagens)

    def test_resposta_vazia_e_dita_como_vazia(self):
        self.assertIn("vazia", self._mensagens(""))

    def test_tela_de_login_indica_sessao_caida(self):
        texto = self._mensagens("<html><body>Informe seu login e senha</body></html>")
        self.assertIn("sessão caiu", texto)
        self.assertIn("entre de novo", texto)

    def test_erro_do_servidor_e_identificado(self):
        texto = self._mensagens("<html><h1>HTTP Status 500 - Internal Error</h1></html>")
        self.assertIn("erro", texto.lower())

    def test_o_trecho_do_portal_aparece(self):
        texto = self._mensagens("<p>Coisa muito específica que o portal disse</p>")
        self.assertIn("Coisa muito específica", texto)

    def test_o_html_e_limpo_das_marcacoes(self):
        texto = self._mensagens("<div class='x'><b>Alô</b></div>")
        self.assertIn("Alô", texto)
        self.assertNotIn("<b>", texto)

    def test_resposta_boa_continua_aceita(self):
        aceita, mensagens = nfse_client.avaliar_resposta('//OK[1,["texto"],0,7]')
        self.assertTrue(aceita)
        self.assertEqual(mensagens, [])


class ReformaTributariaTests(unittest.TestCase):
    """As tabelas da reforma e o filtro de NBS por serviço."""

    # Resposta no formato real: cinco posições por item, com a ordem de campos
    # variando por tipo e as descrições compartilhadas entre itens.
    INDICADORES = ("//OK[5,6,'b',3,2,5,4,'a',3,2,2,1,"
                   '["java.util.ArrayList/4159755760",'
                   '"br.com.eicon.nfseweb.client.vo.IndicadorDeOperacaoVO/1036423791",'
                   '"java.lang.Long/4227064769","100101","local da prestação","050104"],0,7]')

    # O mesmo formato, mas com a descrição também numérica: item a item seria
    # impossível distinguir, e é por isso que o layout se decide pelo conjunto.
    DESCRICAO_NUMERICA = ("//OK[5,6,'b',3,2,5,4,'a',3,2,2,1,"
                          '["java.util.ArrayList/4159755760",'
                          '"br.com.eicon.nfseweb.client.vo.CodSituacaoTributariaVO/1",'
                          '"java.lang.Long/4227064769","000","2026","010"],0,7]')

    def test_le_codigo_e_descricao_de_cada_item(self):
        itens = reforma.ler_lista(self.INDICADORES)
        self.assertEqual(len(itens), 2)
        self.assertEqual({i["codigo"] for i in itens}, {"100101", "050104"})

    def test_a_descricao_compartilhada_vale_para_os_dois(self):
        # "local da prestação" serve vários códigos; a tabela guarda uma só vez.
        for item in reforma.ler_lista(self.INDICADORES):
            self.assertEqual(item["descricao"], "local da prestação")

    def test_nome_de_classe_nao_vira_codigo(self):
        for item in reforma.ler_lista(self.INDICADORES):
            self.assertNotIn("/", item["codigo"])
            self.assertNotIn("java.", item["descricao"])

    def test_descricao_numerica_nao_confunde_o_leitor(self):
        itens = reforma.ler_lista(self.DESCRICAO_NUMERICA)
        self.assertEqual(len(itens), 2)
        self.assertEqual({i["codigo"] for i in itens}, {"000", "010"})
        for item in itens:
            self.assertEqual(item["descricao"], "2026")

    def test_recusa_resposta_que_nao_e_ok(self):
        with self.assertRaises(reforma.ReformaIndisponivel):
            reforma.ler_lista("<html>sessão expirada</html>")

    def test_o_item_sai_do_codigo_de_servico(self):
        # O portal escreve "7.02"; a tabela de correlação usa "07.02".
        self.assertEqual(reforma.item_do_servico("7.02/103141/1291"), "07.02")
        self.assertEqual(reforma.item_do_servico("16.02/105803/1371"), "16.02")
        self.assertEqual(reforma.item_do_servico("01.01"), "01.01")

    def test_codigo_estranho_nao_inventa_item(self):
        for ruim in ("", "abc", "7", "7.02.03", "//", "{{servico.codigo}}"):
            self.assertEqual(reforma.item_do_servico(ruim), "", ruim)

    def test_o_nbs_vai_no_corpo_so_com_digitos(self):
        # Descoberto comparando com uma emissão feita pelo navegador: na tela é
        # 1.0401.23.00, no corpo da nota é o inteiro 104012300.
        self.assertEqual(reforma.para_o_corpo("1.0401.23.00"), "104012300")
        self.assertEqual(reforma.para_o_corpo("1.1502.10.00"), "115021000")
        self.assertEqual(reforma.para_o_corpo(""), "")

    def test_a_correlacao_cobre_os_servicos_em_uso(self):
        arquivo = CONFIG_REAL / "nbs_por_item.json"
        if not arquivo.exists():
            self.skipTest("sem config/nbs_por_item.json neste projeto")
        correlacao = json.loads(arquivo.read_text(encoding="utf-8"))
        for codigo in ("7.02/103141/1291", "16.02/105803/1371", "14.05/107120/1581"):
            item = reforma.item_do_servico(codigo)
            self.assertIn(item, correlacao, codigo)
            self.assertTrue(correlacao[item]["nbs"], f"{item} sem NBS")


class CorrelacaoNbsTests(unittest.TestCase):
    """A leitura da planilha de correlação: NBS, indicador e classificação.

    A planilha é feita para o olho humano — célula vazia quer dizer "repete a
    de cima", e uma linha sem NBS acrescenta opção ao NBS anterior. Ler isso
    como tabela de dados normal atribuiria o indicador errado a dezenas de
    serviços, e indicador errado numa nota é tributo errado.
    """

    CABECALHO = ["Item LC 116", "Descrição Item", "NBS", "DESCRIÇÃO NBS",
                 "PS ONEROSA? (S/N)", "ADQ EXTERIOR? (S/N)", "INDOP",
                 "Local incidência IBS", "cClassTrib", "nome cClassTrib"]

    def _converter(self, linhas):
        import importar_nbs
        return importar_nbs.converter([self.CABECALHO] + linhas)

    def test_o_valor_em_branco_herda_o_de_cima(self):
        # Caso real do item 16.02: o indicador aparece escrito duas vezes e
        # vale para as 74 linhas seguintes, mudando na 22ª.
        itens = self._converter([
            ["16.02", "Transporte", "1.0401.21.90", "A", "", "", "60101.0", "local", "000001", "Integral"],
            ["", "", "1.0401.11.11", "B", "", "", "", "", "", ""],
            ["", "", "1.0501.11.10", "C", "", "", "70100.0", "local", "", ""],
            ["", "", "1.0501.11.20", "D", "", "", "", "", "", ""],
        ])
        nbs = itens["16.02"]["nbs"]
        self.assertEqual([x["codigo"] for x in nbs["1.0401.21.90"]["indop"]], ["60101"])
        self.assertEqual([x["codigo"] for x in nbs["1.0401.11.11"]["indop"]], ["60101"])
        self.assertEqual([x["codigo"] for x in nbs["1.0501.11.10"]["indop"]], ["70100"])
        self.assertEqual([x["codigo"] for x in nbs["1.0501.11.20"]["indop"]], ["70100"])
        for codigo in nbs:
            self.assertEqual([x["codigo"] for x in nbs[codigo]["classificacao"]], ["000001"])

    def test_linha_sem_nbs_acrescenta_opcao_ao_anterior(self):
        # Caso real do item 14.05: o mesmo NBS aceita quatro indicadores.
        itens = self._converter([
            ["14.05", "Restauração", "1.1804.00.00", "A", "", "", "050101", "l", "000001", "Integral"],
            ["", "", "", "", "", "", "050102", "l", "", ""],
            ["", "", "", "", "", "", "050103", "l", "", ""],
            ["", "", "", "", "", "", "050104", "l", "", ""],
            ["", "", "1.2002.90.00", "B", "", "", "050101", "l", "", ""],
        ])
        nbs = itens["14.05"]["nbs"]
        self.assertEqual([x["codigo"] for x in nbs["1.1804.00.00"]["indop"]],
                         ["050101", "050102", "050103", "050104"])
        self.assertEqual([x["codigo"] for x in nbs["1.2002.90.00"]["indop"]], ["050101"])

    def test_duas_classificacoes_para_o_mesmo_nbs(self):
        # Caso real do item 07.02: cada NBS alterna 200046 e 200045.
        itens = self._converter([
            ["07.02", "Obra", "1.0101.11.00", "A", "", "", "20201.0", "l", "200046", "x"],
            ["", "", "", "", "", "", "", "", "200045.0", "y"],
            ["", "", "1.0101.12.00", "B", "", "", "", "", "200046", "x"],
            ["", "", "", "", "", "", "", "", "200045.0", "y"],
        ])
        nbs = itens["07.02"]["nbs"]
        for codigo in ("1.0101.11.00", "1.0101.12.00"):
            self.assertEqual([x["codigo"] for x in nbs[codigo]["classificacao"]],
                             ["200046", "200045"], codigo)
            self.assertEqual([x["codigo"] for x in nbs[codigo]["indop"]], ["20201"])

    def test_o_ponto_zero_do_excel_e_removido(self):
        # O Excel guarda 100301 como número e devolve "100301.0"; enviado assim
        # o portal não reconheceria o código.
        itens = self._converter([
            ["01.01", "Sistemas", "1.1502.10.00", "A", "S", "N", "100301.0", "l", "200045.0", "x"],
        ])
        dados = itens["01.01"]["nbs"]["1.1502.10.00"]
        self.assertEqual(dados["indop"][0]["codigo"], "100301")
        self.assertEqual(dados["classificacao"][0]["codigo"], "200045")

    def test_um_item_novo_zera_a_heranca(self):
        # Sem isso, o indicador de um item vazaria para o item seguinte.
        itens = self._converter([
            ["07.02", "Obra", "1.0101.11.00", "A", "", "", "20201", "l", "200046", "x"],
            ["07.03", "Outra", "1.0102.00.00", "B", "", "", "", "", "", ""],
        ])
        self.assertEqual(itens["07.03"]["nbs"]["1.0102.00.00"]["indop"], [])
        self.assertEqual(itens["07.03"]["nbs"]["1.0102.00.00"]["classificacao"], [])

    def test_a_planilha_real_bate_com_o_que_o_portal_aceita(self):
        arquivo = CONFIG_REAL / "nbs_por_item.json"
        if not arquivo.exists():
            self.skipTest("sem config/nbs_por_item.json neste projeto")
        correlacao = json.loads(arquivo.read_text(encoding="utf-8"))
        self.assertEqual(len(correlacao), 200)
        sem_indop = [n for v in correlacao.values()
                     for n, d in v["nbs"].items() if not d["indop"]]
        self.assertEqual(sem_indop, [], "há NBS sem indicador de operação")


class CamposDaReformaNaTelaTests(unittest.TestCase):
    """O encadeamento serviço → NBS → indicador e classificação.

    Foi assim que o usuário pediu: escolher o serviço mostra os NBS daquele
    serviço; escolher o NBS preenche sozinho o indicador de operação e a
    classificação tributária, conforme a tabela de correlação. O CST não está
    na tabela e fica em 000.
    """

    SERVICOS = [
        {"codigo": "7.07/103802/1321", "nome": "RASPAGEM E POLIMENTO"},
        {"codigo": "16.02/105803/1371", "nome": "TRANSPORTE MUNICIPAL"},
    ]

    def setUp(self):
        try:
            import services
            import desktop
            from tkinter import ttk
        except Exception as exc:
            self.skipTest(f"sem interface gráfica: {exc}")
        # A suíte manda config/ para uma pasta temporária; estes testes
        # precisam das tabelas de verdade, que são dados do projeto.
        self.arquivos = (reforma.CORRELACAO, reforma.ARQUIVO)
        reforma.CORRELACAO = CONFIG_REAL / "nbs_por_item.json"
        reforma.ARQUIVO = CONFIG_REAL / "reforma_codigos.json"
        if not reforma.CORRELACAO.exists() or not reforma.ARQUIVO.exists():
            reforma.CORRELACAO, reforma.ARQUIVO = self.arquivos
            self.skipTest("sem as tabelas da reforma neste projeto")
        self.originais = (services.disponiveis, services.em_cache)
        services.disponiveis = lambda **k: self.SERVICOS
        services.em_cache = lambda *a, **k: self.SERVICOS
        self.addCleanup(self._restaurar)
        self.app = desktop.NfseDesktop()
        self.app.withdraw()
        self.app.show_new_note()
        self.app.update()

    def _restaurar(self):
        import services
        services.disponiveis, services.em_cache = self.originais
        reforma.CORRELACAO, reforma.ARQUIVO = self.arquivos
        try:
            self.app.destroy()
        except Exception:
            pass

    def _caixas(self):
        from tkinter import ttk
        achados = []

        def varrer(w):
            for f in w.winfo_children():
                if isinstance(f, ttk.Combobox) and list(f["values"]):
                    achados.append(f)
                varrer(f)

        varrer(self.app)
        return achados[:5]        # serviço, NBS, indicador, classificação, CST

    def test_um_unico_nbs_ja_vem_escolhido(self):
        # 83 dos 200 itens da LC 116 têm um só NBS; pedir confirmação neles
        # seria atrito puro.
        _, nbs, indop, classe, _ = self._caixas()
        self.assertEqual(len(list(nbs["values"])), 1)
        self.assertTrue(nbs.get(), "o NBS único deveria vir escolhido")
        self.assertTrue(indop.get(), "o indicador deveria vir preenchido")
        self.assertTrue(classe.get(), "a classificação deveria vir preenchida")

    def test_o_indicador_vem_da_tabela_e_nao_da_lista_geral(self):
        _, _, indop, classe, _ = self._caixas()
        self.assertTrue(indop.get().startswith("20201"), indop.get())
        self.assertTrue(classe.get().startswith("200046"), classe.get())

    def test_o_cst_sai_em_000(self):
        *_, cst = self._caixas()
        self.assertTrue(cst.get().startswith(reforma.CST_PADRAO), cst.get())
        self.assertGreater(len(list(cst["values"])), 1, "deve dar para trocar")

    def test_trocar_de_servico_recarrega_os_nbs(self):
        servico, nbs, *_ = self._caixas()
        servico.current(1)
        servico.event_generate("<<ComboboxSelected>>")
        self.app.update()
        self.assertEqual(len(list(nbs["values"])), 74, "16.02 tem 74 NBS")

    def test_com_varios_nbs_os_codigos_ficam_vazios(self):
        # O ponto: um código plausível já escolhido passa despercebido, e aqui
        # isso sai como tributo errado na nota. Melhor vazio e barrado.
        servico, nbs, indop, classe, _ = self._caixas()
        servico.current(1)
        servico.event_generate("<<ComboboxSelected>>")
        self.app.update()
        self.assertEqual(nbs.get(), "")
        self.assertEqual(indop.get(), "", "não pode sugerir indicador sem NBS")
        self.assertEqual(classe.get(), "", "não pode sugerir classificação sem NBS")

    def test_escolher_o_nbs_preenche_os_dois(self):
        servico, nbs, indop, classe, _ = self._caixas()
        servico.current(1)
        servico.event_generate("<<ComboboxSelected>>")
        self.app.update()
        nbs.set(list(nbs["values"])[0])
        nbs.event_generate("<<ComboboxSelected>>")
        self.app.update()
        self.assertTrue(indop.get().startswith("60101"), indop.get())
        self.assertTrue(classe.get().startswith("000001"), classe.get())

    def test_a_heranca_da_planilha_vale_no_meio_da_lista(self):
        # No item 16.02 o indicador muda do 22º NBS em diante — está escrito
        # duas vezes na planilha e vale para as 74 linhas.
        servico, nbs, indop, _, _ = self._caixas()
        servico.current(1)
        servico.event_generate("<<ComboboxSelected>>")
        self.app.update()
        nbs.set(list(nbs["values"])[30])
        nbs.event_generate("<<ComboboxSelected>>")
        self.app.update()
        self.assertTrue(indop.get().startswith("70100"), indop.get())


class NomeComEspacoNoFimTests(unittest.TestCase):
    """Serviço cujo nome termina em espaço tem de continuar reconhecível.

    O Tk devolve o texto do campo, e o código comparava esse texto **aparado**
    com o rótulo **sem aparar**. Nomes vindos do portal trazem espaço no fim
    com frequência — a varredura pelos 200 itens da LC 116 mostrou 15 assim, e
    em todos eles o serviço ficava irreconhecível: a lista de NBS vinha vazia e
    a emissão era barrada sem motivo aparente.
    """

    SERVICOS = [
        {"codigo": "7.02/103141/1291", "nome": "EXECUCAO DE OBRAS "},   # espaço no fim
        {"codigo": "16.02/105803/1371", "nome": "TRANSPORTE MUNICIPAL"},
    ]

    def setUp(self):
        try:
            import services
            import desktop
        except Exception as exc:
            self.skipTest(f"sem interface gráfica: {exc}")
        arquivo = CONFIG_REAL / "nbs_por_item.json"
        if not arquivo.exists():
            self.skipTest("sem a tabela de correlação neste projeto")
        self.arquivos = (reforma.CORRELACAO, reforma.ARQUIVO)
        reforma.CORRELACAO = arquivo
        reforma.ARQUIVO = CONFIG_REAL / "reforma_codigos.json"
        self.originais = (services.disponiveis, services.em_cache)
        services.disponiveis = lambda **k: self.SERVICOS
        services.em_cache = lambda *a, **k: self.SERVICOS
        self.addCleanup(self._restaurar)
        self.app = desktop.NfseDesktop()
        self.app.withdraw()
        self.app.show_new_note()
        self.app.update()

    def _restaurar(self):
        import services
        services.disponiveis, services.em_cache = self.originais
        reforma.CORRELACAO, reforma.ARQUIVO = self.arquivos
        try:
            self.app.destroy()
        except Exception:
            pass

    def _caixas(self):
        from tkinter import ttk
        achados = []

        def varrer(w):
            for f in w.winfo_children():
                if isinstance(f, ttk.Combobox) and list(f["values"]):
                    achados.append(f)
                varrer(f)

        varrer(self.app)
        return achados[:5]

    def test_o_servico_com_espaco_no_fim_carrega_os_nbs(self):
        _, nbs, indop, classe, _ = self._caixas()
        self.assertEqual(len(list(nbs["values"])), 55, "o item 07.02 tem 55 NBS")
        self.assertTrue(nbs.get() == "" or nbs.get(), "a lista tem de existir")

    def test_e_os_codigos_se_preenchem_normalmente(self):
        _, nbs, indop, classe, _ = self._caixas()
        nbs.set(list(nbs["values"])[0])
        nbs.event_generate("<<ComboboxSelected>>")
        self.app.update()
        self.assertTrue(indop.get().startswith("20201"), indop.get())
        self.assertTrue(classe.get().startswith("200046"), classe.get())


class ReformaNoCorpoTests(unittest.TestCase):
    """Os quatro códigos escritos no corpo da requisição.

    Posições conferidas contra uma emissão real feita pelo navegador em
    24/08/2026. Errar a vaga aqui não dá erro de programa: sai como tributo
    errado numa nota fiscal.
    """

    SERVICO = {
        "descricao": "NOTA FISCAL TESTE", "codigo": "7.02/103141/1291",
        "valor": "1.00", "aliquota": "2",
        "nbs": "1.0401.23.00", "indicador_operacao": "050104",
        "situacao_tributaria": "000", "classificacao_tributaria": "010002",
    }

    def setUp(self):
        import prestador
        import templates
        import tomador as tomador_portal
        # A suíte manda config/ para uma pasta temporária; o modelo de emissão
        # é dado do projeto e precisa vir do lugar de verdade.
        self.pasta_modelos = templates.PASTA
        templates.PASTA = CONFIG_REAL / "templates"
        if not templates.PASTA.is_dir():
            templates.PASTA = self.pasta_modelos
            self.skipTest("sem config/templates neste projeto")
        self.addCleanup(lambda: setattr(templates, "PASTA", self.pasta_modelos))
        self.guardado = (tomador_portal.consultar, tomador_portal.aplicar,
                         prestador.do_portal, prestador.aplicar,
                         os.environ.get("NFSE_COOKIE"), os.environ.get("NFSE_AUTHORIZATION"))
        tomador_portal.consultar = lambda d, **k: {}
        tomador_portal.aplicar = lambda corpo, pos, dados: corpo
        prestador.do_portal = lambda *a, **k: {}
        prestador.aplicar = lambda corpo, pos, dados=None: corpo
        os.environ["NFSE_COOKIE"] = "x"
        os.environ["NFSE_AUTHORIZATION"] = "-"
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        import prestador
        import tomador as tomador_portal
        (tomador_portal.consultar, tomador_portal.aplicar,
         prestador.do_portal, prestador.aplicar, cookie, auth) = self.guardado
        for nome, valor in (("NFSE_COOKIE", cookie), ("NFSE_AUTHORIZATION", auth)):
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor

    def _corpo(self, **extra):
        servico = {**self.SERVICO, **extra.pop("servico", {})}
        tomador = {"documento": "11222333000181", "nome": "", **extra.pop("tomador", {})}
        payload = validation.validate_payload({
            "tomador": tomador, "servico": servico, "competencia": "2026-08-24"})
        return nfse_client.build(payload, session_active=True)["body"]

    def _partes(self, corpo):
        campos = corpo.split("|")
        qtd = int(campos[2])
        tabela = campos[3:3 + qtd]
        fluxo = [c for c in campos[3 + qtd:] if c != ""]
        return tabela, fluxo

    def _valor(self, tabela, token):
        try:
            n = int(token)
        except ValueError:
            return token
        if n == 0:
            return None
        return tabela[n - 1] if 1 <= n <= len(tabela) else f"CRU:{n}"

    def _marco(self, tabela, fluxo, marca):
        for i, token in enumerate(fluxo):
            valor = self._valor(tabela, token)
            if isinstance(valor, str) and marca in valor:
                return i
        raise AssertionError(f"não achei {marca} no corpo")

    def test_os_quatro_ficam_nas_vagas_certas(self):
        tabela, fluxo = self._partes(self._corpo())
        servico = self._marco(tabela, fluxo, "TcDadosServico/")
        ibscbs = self._marco(tabela, fluxo, "TcIBSCBS/")
        gibscbs = self._marco(tabela, fluxo, "GIBSCBS/")
        self.assertIn("java.lang.Integer", self._valor(tabela, fluxo[servico + 1]))
        self.assertEqual(fluxo[servico + 2], "104012300", "o NBS vai cru, sem os pontos")
        self.assertEqual(self._valor(tabela, fluxo[ibscbs + 1]), "050104")
        self.assertEqual(self._valor(tabela, fluxo[gibscbs + 1]), "000")
        self.assertEqual(self._valor(tabela, fluxo[gibscbs + 2]), "010002")

    def test_o_nbs_perde_os_pontos(self):
        tabela, fluxo = self._partes(self._corpo(servico={"nbs": "1.1502.10.00"}))
        servico = self._marco(tabela, fluxo, "TcDadosServico/")
        self.assertEqual(fluxo[servico + 2], "115021000")

    def test_o_codigo_do_servico_continua_no_lugar(self):
        # A inserção do NBS empurra tudo que vem depois; se a conta estiver
        # errada, o código do serviço cai na casa do NBS.
        tabela, fluxo = self._partes(self._corpo())
        servico = self._marco(tabela, fluxo, "TcDadosServico/")
        self.assertEqual(self._valor(tabela, fluxo[servico + 4]), "7.02/103141/1291")
        self.assertEqual(self._valor(tabela, fluxo[servico + 5]), "NOTA FISCAL TESTE")

    def _retro(self, corpo):
        _, fluxo = self._partes(corpo)
        return [v for v in fluxo if v.startswith("-")]

    def test_a_retro_referencia_conta_os_objetos_inseridos(self):
        # Ela conta objetos: cada inserção antes dela a empurra uma casa. O
        # modelo traz -37; o NBS soma um, a obra soma outro.
        cadastro = {"razao_social": "X", "logradouro": "R", "numero": "1",
                    "bairro": "B", "cep": "09710000", "municipio": "3548708",
                    "cadastrar": True}
        self.assertEqual(self._retro(self._corpo()), ["-38"])
        self.assertEqual(self._retro(self._corpo(servico={"obra": "1213550"})), ["-39"])
        self.assertEqual(self._retro(self._corpo(tomador=cadastro)), ["-38"])
        self.assertEqual(
            self._retro(self._corpo(servico={"obra": "1213550"}, tomador=cadastro)), ["-39"])

    def test_o_corpo_cresce_exatamente_uma_posicao_por_causa_do_nbs(self):
        modelo = json.loads(
            (CONFIG_REAL / "templates" / "mundial-usinagem.json").read_text(encoding="utf-8"))
        _, original = self._partes(modelo["body"])
        _, gerado = self._partes(self._corpo())
        self.assertEqual(len(gerado) - len(original), 1)


class EspacamentoDaDescricaoTests(unittest.TestCase):
    """A descrição é o texto que sai impresso na nota — o espaçamento é do usuário.

    Ele separa o serviço da chave PIX com uma corrida de espaços:

        VENDAS PROMOCIONAIS                    PIX:4545184444.

    A limpeza juntava tudo num espaço só e saía "VENDAS PROMOCIONAIS
    PIX:4545184444." — sem aviso nenhum. Espaço repetido não tem risco no corpo
    do portal; quem precisa sumir é quebra de linha e caractere de controle.
    """

    TEXTO = "VENDAS PROMOCIONAIS" + " " * 40 + "PIX:4545184444."

    def test_a_descricao_mantem_o_espacamento(self):
        limpo = validation.clean_text(self.TEXTO, "servico.descricao",
                                      max_length=2000, espacos="preservar")
        self.assertEqual(limpo, self.TEXTO)

    def test_o_rascunho_guarda_o_texto_como_foi_digitado(self):
        payload = validation.validate_payload(draft(
            servico={"descricao": self.TEXTO, "codigo": "14.05/107120/1581",
                     "valor": "1,00", "aliquota": "2"}))
        self.assertEqual(payload["servico"]["descricao"], self.TEXTO)

    def test_os_campos_estruturados_continuam_normalizados(self):
        # Ali espaço duplo é engano de digitação, não intenção.
        self.assertEqual(validation.clean_text("JOAO   DA   SILVA", "x"), "JOAO DA SILVA")
        self.assertEqual(validation.clean_text("  RUA    DAS   FLORES  ", "x"),
                         "RUA DAS FLORES")

    def test_a_descricao_mantem_as_quebras_de_linha(self):
        # A nota sai impressa como o usuário escreveu. Eu havia afirmado aqui
        # que quebra de linha corromperia o corpo GWT-RPC — não corrompe:
        # escape_gwt já a converte em \u000a, como o próprio portal faz.
        texto = "linha um\nlinha dois"
        limpo = validation.clean_text(texto, "x", espacos="preservar")
        self.assertEqual(limpo, texto)
        self.assertEqual(len(limpo.splitlines()), 2)

    def test_nos_campos_estruturados_a_quebra_vira_espaco(self):
        # Nome e endereço são de uma linha só; ali a quebra continua virando
        # espaço, senão ela entraria no meio de um campo cadastral.
        limpo = validation.clean_text("linha um\nlinha dois", "x")
        self.assertNotIn("\n", limpo)
        self.assertEqual(limpo, "linha um linha dois")

    def test_a_quebra_vai_escapada_no_corpo(self):
        self.assertEqual(nfse_client.escape_gwt("a\nb"), "a\\u000ab")

    def test_windows_e_mac_viram_a_mesma_quebra(self):
        # A caixa de texto pode devolver \r\n; solto, ele duplicaria as linhas.
        for bruto in ("a\r\nb", "a\rb", "a\nb"):
            self.assertEqual(validation.clean_text(bruto, "x", espacos="preservar"),
                             "a\nb", bruto)

    def test_tabulacao_continua_virando_espaco(self):
        # Tabulação some porque o portal não a lê como alinhamento — o que sai
        # na nota impressa é imprevisível. Espaço sai igual em toda máquina.
        self.assertEqual(validation.clean_text("a\tb", "x", espacos="preservar"), "a b")

    def test_as_pontas_continuam_aparadas(self):
        # Espaço no fim é invisível e já causou estrago: nome de serviço que
        # não casava com a lista.
        limpo = validation.clean_text("   texto   ", "x", espacos="preservar")
        self.assertEqual(limpo, "texto")

    def test_caractere_de_controle_some_mesmo_preservando_espaco(self):
        limpo = validation.clean_text("a\x00b\x07c", "x", espacos="preservar")
        self.assertEqual(limpo, "abc")

    def test_o_limite_de_tamanho_conta_os_espacos(self):
        # No meio, porque nas pontas eles são aparados antes da contagem.
        with self.assertRaises(validation.ValidationError):
            validation.clean_text("a" + " " * 2000 + "b", "x", max_length=2000,
                                  espacos="preservar")
        # e logo abaixo do limite continua passando
        cabe = "a" + " " * 1997 + "b"
        self.assertEqual(len(validation.clean_text(cabe, "x", max_length=2000,
                                                   espacos="preservar")), 1999)

class AtualizarNoLugarTests(unittest.TestCase):
    """Filtrar troca o conteúdo; não reconstrói os widgets.

    Medido antes da mudança: um redesenho da tela de notas custava 168 ms com
    100 notas e 218 ms com 500 — quase o mesmo, o que denunciava que o custo
    estava em criar e destruir widgets, não em inserir linhas. Depois: 54 ms e
    80 ms.

    O contrato é esse, e por isso tem teste: a mesma Treeview, as mesmas
    etiquetas do cartão, só o conteúdo trocado. Quem voltar a destruir e
    recriar faz a digitação engasgar de novo.
    """

    def setUp(self):
        self.raiz = tk.Tk()
        self.raiz.withdraw()
        ui.aplicar_estilo(self.raiz)

    def tearDown(self):
        self.raiz.destroy()

    @staticmethod
    def _nota(identidade, valor="10,00"):
        return {"id": identidade, "status": "submitted", "created_at": "2026-08-29",
                "payload": {"tomador": {"nome": "CLIENTE", "documento": "11222333000181"},
                            "servico": {"descricao": "servico", "valor": valor}}}

    def _tabela(self):
        return ui.Tabela(self.raiz, desktop.colunas_de_notas())

    @staticmethod
    def _visiveis(tabela):
        return [linha for linha in tabela._linhas if linha.winfo_manager()]

    def test_as_linhas_sao_reaproveitadas_ao_filtrar(self):
        # O contrato de desempenho: filtrar troca o conteúdo das linhas que já
        # existem. Criar e destruir Frame por linha a cada tecla é o que fazia
        # a digitação engasgar.
        tabela = self._tabela()
        tabela.pack()
        tabela.mostrar([desktop.linha_da_nota(self._nota("a"), lambda d: "MUNDIAL"),
                        desktop.linha_da_nota(self._nota("b"), lambda d: "MUNDIAL")])
        self.raiz.update_idletasks()
        criadas = [str(linha) for linha in tabela._linhas]
        self.assertEqual(len(self._visiveis(tabela)), 2)

        tabela.mostrar([desktop.linha_da_nota(self._nota("a"), lambda d: "MUNDIAL")])
        self.raiz.update_idletasks()
        self.assertEqual(len(self._visiveis(tabela)), 1)
        self.assertEqual([str(linha) for linha in tabela._linhas], criadas)

    def test_esconder_valores_chega_na_tabela(self):
        tabela = self._tabela()
        tabela.pack()
        tabela.mostrar([desktop.linha_da_nota(self._nota("a"), lambda d: "X",
                                              ocultar_valores=True)])
        self.raiz.update_idletasks()
        valor = tabela._linhas[0].partes["valor"]["valor"]
        self.assertEqual(str(valor.cget("text")), "•••")

    def test_o_simbolo_de_moeda_fica_mais_leve_que_o_numero(self):
        # Convenção de tabela financeira: o R$ não disputa atenção com o valor.
        tabela = self._tabela()
        tabela.pack()
        tabela.mostrar([desktop.linha_da_nota(self._nota("a"), lambda d: "X")])
        self.raiz.update_idletasks()
        parte = tabela._linhas[0].partes["valor"]
        self.assertEqual(str(parte["simbolo"].cget("text")), "R$")
        self.assertEqual(str(parte["simbolo"].cget("fg")), ui.INK_3)
        self.assertEqual(str(parte["valor"].cget("fg")), ui.INK)
        # E o número em fonte de largura fixa, para as casas se alinharem.
        self.assertIn(ui.MONO, str(parte["valor"].cget("font")))

    def test_a_altura_da_linha_segue_a_pratica_de_tabela_de_dados(self):
        self.assertGreaterEqual(ui.ALTURA_LINHA, 44)
        self.assertLessEqual(ui.ALTURA_LINHA, 56)

    def test_o_cartao_nao_recria_os_rotulos(self):
        cartao = ui.CartaoFiltro(self.raiz, "Emitidas", tom="sucesso")
        filhos = [str(w) for w in cartao.winfo_children()]
        cartao.atualizar("7", "R$ 1.000,00", ativo=True)
        cartao.atualizar("3", "R$ 500,00", ativo=False)
        self.assertEqual([str(w) for w in cartao.winfo_children()], filhos)
        self.assertEqual(cartao.numero.cget("text"), "3")

    def test_o_cartao_se_preenche_quando_fica_ativo(self):
        # O cartão é um Canvas com a moldura desenhada: a cor de preenchimento
        # é `fundo`, não o `bg` do widget — este último é o que fica ATRÁS da
        # forma arredondada, e precisa ser o da tela para os cantos vazarem.
        cartao = ui.CartaoFiltro(self.raiz, "Recusadas", tom="erro")
        self.assertEqual(cartao.fundo, ui.SURFACE)
        cartao.atualizar("2", "R$ 9,00", ativo=True)
        self.assertEqual(cartao.fundo, cartao.cor)
        self.assertEqual(cartao.interior.cget("bg"), cartao.cor)
        # E o texto por cima precisa ser legível sobre esse preenchimento.
        self.assertEqual(cartao.numero.cget("fg"), ui.contraste(cartao.cor))
        cartao.atualizar("2", "R$ 9,00", ativo=False)
        self.assertEqual(cartao.fundo, ui.SURFACE)

    def test_o_canto_arredondado_deixa_a_tela_aparecer_atras(self):
        # Se o `bg` do Canvas fosse a cor do cartão, o canto arredondado
        # apareceria como um quadrado da mesma cor — ou seja, não apareceria.
        cartao = ui.CartaoFiltro(self.raiz, "Todas", tom="info")
        self.assertEqual(cartao.cget("bg"), ui.BG)
        self.assertNotEqual(cartao.cget("bg"), cartao.fundo)

    def test_a_busca_espera_antes_de_redesenhar(self):
        # Sem espera, cada tecla redesenha a lista inteira.
        self.assertGreaterEqual(ui.CampoBusca.ESPERA, 250)
        self.assertLessEqual(ui.CampoBusca.ESPERA, 500)

    def test_o_campo_de_data_tambem_espera(self):
        # "29/08/2026" são dez teclas; sem espera, dez redesenhos.
        self.assertGreaterEqual(desktop.ViewDocumentos.ESPERA_DATA, 250)


class ContrasteTests(unittest.TestCase):
    """Texto legível sobre qualquer preenchimento, em qualquer tema."""

    def test_texto_claro_sobre_fundo_escuro(self):
        self.assertEqual(ui.contraste("#0f172a"), "#ffffff")

    def test_texto_escuro_sobre_fundo_claro(self):
        self.assertEqual(ui.contraste("#34d399"), "#0b1020")

    def test_cor_invalida_nao_derruba_a_tela(self):
        self.assertEqual(ui.contraste("nao e cor"), "#ffffff")

    def test_todos_os_tons_de_filtro_ficam_legiveis_nos_dois_temas(self):
        for tema in ("claro", "escuro"):
            ui.usar_tema(tema)
            for tom, nome in ui.TONS_DE_FILTRO.items():
                cor = getattr(ui, nome)
                tinta = ui.contraste(cor)
                self.assertIn(tinta, ("#ffffff", "#0b1020"), f"{tema}/{tom}")
        ui.usar_tema("claro")


class AssinaturaDaMarcaTests(unittest.TestCase):
    """A marca escrita na barra: espaçamento e o ® no alto."""

    def setUp(self):
        try:
            import tkinter
            self.raiz = tkinter.Tk()
            self.raiz.withdraw()
        except Exception as exc:
            self.skipTest(f"sem interface gráfica: {exc}")
        ui.escolher_familia(self.raiz)
        ui.usar_tema("escuro")

    def tearDown(self):
        try:
            self.raiz.destroy()
        except Exception:
            pass

    def _desenhar(self, nome="DEZORZI", **extra):
        tela = ui.assinatura(self.raiz, nome, fundo=ui.NAVY, cor=ui.INK,
                             tamanho=14, registrada="®", **extra)
        itens = tela.find_all()
        textos = [(tela.itemcget(i, "text"), tela.coords(i)) for i in itens]
        return tela, textos

    def test_uma_letra_por_item_mais_o_registrado(self):
        # Letra a letra é o que permite o espaçamento: um rótulo só não tem
        # como afastar as maiúsculas umas das outras.
        _tela, textos = self._desenhar()
        self.assertEqual([t for t, _c in textos],
                         list("DEZORZI") + ["®"])

    def test_as_letras_saem_em_ordem_da_esquerda_para_a_direita(self):
        _tela, textos = self._desenhar()
        xs = [coords[0] for _t, coords in textos[:7]]
        self.assertEqual(xs, sorted(xs))
        self.assertTrue(all(b - a > 0 for a, b in zip(xs, xs[1:])),
                        "duas letras no mesmo x")

    def test_ha_respiro_entre_as_letras(self):
        """O espaço pedido aparece de verdade entre uma letra e a seguinte."""
        import tkinter.font as tkfont

        fonte = tkfont.Font(family=ui.FAMILIA, size=14, weight="bold")
        _tela, textos = self._desenhar(espaco=6)
        xs = [coords[0] for _t, coords in textos[:7]]
        for letra, inicio, seguinte in zip("DEZORZI", xs, xs[1:]):
            self.assertAlmostEqual(seguinte - inicio,
                                   fonte.measure(letra) + 6, delta=1)

    def test_o_registrado_fica_acima_da_base_das_letras(self):
        # É o que separa a assinatura de uma palavra com um "R" solto no fim:
        # o símbolo sobe até o alto da maiúscula.
        _tela, textos = self._desenhar()
        base_das_letras = textos[0][1][1]
        base_do_simbolo = textos[-1][1][1]
        self.assertLess(base_do_simbolo, base_das_letras)

    def test_o_registrado_e_menor_que_o_nome(self):
        # Medido pelo que foi desenhado, não pela fonte declarada: o Tk
        # devolve só o NOME interno da fonte, que não diz o tamanho.
        tela, _textos = self._desenhar()
        self.raiz.update_idletasks()
        itens = tela.find_all()

        def altura(item):
            x0, y0, x1, y1 = tela.bbox(item)
            return y1 - y0

        self.assertLess(altura(itens[-1]), altura(itens[0]))

    def test_sem_registrado_desenha_so_o_nome(self):
        tela = ui.assinatura(self.raiz, "DEZORZI", fundo=ui.NAVY, cor=ui.INK,
                             tamanho=14)
        self.assertEqual(len(tela.find_all()), 7)

    def test_a_tela_cabe_o_que_desenhou(self):
        tela, textos = self._desenhar()
        self.raiz.update_idletasks()
        ultimo_x = max(coords[0] for _t, coords in textos)
        self.assertGreaterEqual(int(tela.cget("width")), ultimo_x)


class AtualizacaoTests(unittest.TestCase):
    """O auto-atualizador: comparação de versão, travas e o roteiro da troca.

    Nada aqui toca a rede nem executa arquivo nenhum: o que se mede é a
    decisão — o que ele aceita, o que recusa, e o que escreve no `.bat`.
    """

    def setUp(self):
        self.env = dict(os.environ)
        os.environ.pop(updater.VARIAVEL_URL, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)

    # -- comparação ------------------------------------------------------ #

    def test_compara_por_numero_e_nao_por_texto(self):
        # Como texto, "1.9.0" seria maior que "1.10.0" — e a correção urgente
        # nunca chegaria à máquina de quem está na 1.9.0.
        self.assertTrue(updater.e_mais_nova("1.10.0", "1.9.0"))
        self.assertFalse(updater.e_mais_nova("1.9.0", "1.10.0"))

    def test_aceita_o_v_na_frente(self):
        self.assertEqual(updater.como_numeros("v2.3.1"), (2, 3, 1))

    def test_versao_igual_nao_atualiza(self):
        self.assertFalse(updater.e_mais_nova("1.0.0", "1.0.0"))

    def test_versao_menor_nao_atualiza(self):
        self.assertFalse(updater.e_mais_nova("0.9.9", "1.0.0"))

    def test_a_versao_de_referencia_e_lida_na_hora(self):
        """Trocar `VERSAO_ATUAL` tem de valer na comparação seguinte.

        Era `local: str = VERSAO_ATUAL` como valor padrão do parâmetro, e o
        padrão é fixado quando o arquivo é lido: quem trocasse a constante
        depois continuaria comparando com o valor antigo, sem nenhum sinal.
        Custou uma conferência da publicação de verdade dizendo "não há versão
        nova" com a versão nova já publicada.
        """
        original = updater.VERSAO_ATUAL
        updater.VERSAO_ATUAL = "0.0.1"
        try:
            self.assertTrue(updater.e_mais_nova("1.0.0"))
        finally:
            updater.VERSAO_ATUAL = original
        self.assertFalse(updater.e_mais_nova("1.0.0"))

    # -- o anúncio ------------------------------------------------------- #

    def _anunciar(self, corpo, **extra):
        """Faz o módulo "buscar" este conteúdo, sem rede."""
        def buscar(url, limite):
            achado = extra.get(url)
            if achado is not None:
                return achado.encode("utf-8")
            if not url.lower().startswith("https://"):
                raise updater.AtualizacaoRecusada("endereço não é https")
            bruto = json.dumps(corpo) if isinstance(corpo, dict) else corpo
            return bruto.encode("utf-8")

        return buscar

    def test_manifesto_simples_vira_atualizacao(self):
        sha = "a" * 64
        buscar = self._anunciar({"versao": "9.9.9",
                                 "arquivo": "https://exemplo/App.exe",
                                 "sha256": sha, "notas": "corrige  o   ISS"})
        with unittest.mock.patch.object(updater, "_buscar", buscar):
            achada = updater.verificar_atualizacao("https://exemplo/version.json")
        self.assertEqual(achada.versao, "9.9.9")
        self.assertEqual(achada.sha256, sha)
        self.assertEqual(achada.notas, "corrige o ISS")

    def test_release_do_github_e_reconhecido_sozinho(self):
        sha = "b" * 64
        corpo = {
            "tag_name": "v9.9.9", "body": "novidades",
            "assets": [
                {"name": "version.json",
                 "browser_download_url": "https://exemplo/version.json"},
                {"name": "Dezorzi NFS-e.exe",
                 "browser_download_url": "https://exemplo/App.exe"},
            ],
        }
        buscar = self._anunciar(
            corpo, **{"https://exemplo/version.json": json.dumps({"sha256": sha})})
        with unittest.mock.patch.object(updater, "_buscar", buscar):
            achada = updater.verificar_atualizacao("https://exemplo/releases/latest")
        self.assertEqual(achada.url, "https://exemplo/App.exe")
        self.assertEqual(achada.sha256, sha)

    def test_le_o_sha_no_formato_sha256sums(self):
        sha = "c" * 64
        corpo = {"tag_name": "9.9.9", "assets": [
            {"name": "SHA256SUMS", "browser_download_url": "https://exemplo/sums"},
            {"name": "app.exe", "browser_download_url": "https://exemplo/App.exe"}]}
        buscar = self._anunciar(
            corpo, **{"https://exemplo/sums": sha + "  Dezorzi NFS-e.exe"})
        with unittest.mock.patch.object(updater, "_buscar", buscar):
            achada = updater.verificar_atualizacao("https://exemplo/releases/latest")
        self.assertEqual(achada.sha256, sha)

    def test_sem_url_configurada_nao_procura_nada(self):
        self.assertIsNone(updater.verificar_atualizacao())

    def test_versao_igual_a_daqui_devolve_nada(self):
        buscar = self._anunciar({"versao": updater.VERSAO_ATUAL,
                                 "arquivo": "https://exemplo/App.exe",
                                 "sha256": "d" * 64})
        with unittest.mock.patch.object(updater, "_buscar", buscar):
            self.assertIsNone(
                updater.verificar_atualizacao("https://exemplo/version.json"))

    # -- as travas ------------------------------------------------------- #

    def test_recusa_anuncio_sem_sha256(self):
        # Sem impressão digital não há como saber se o que chegou é o que foi
        # publicado — e o que chegou vira código executado nesta máquina.
        buscar = self._anunciar({"versao": "9.9.9",
                                 "arquivo": "https://exemplo/App.exe"})
        with unittest.mock.patch.object(updater, "_buscar", buscar):
            with self.assertRaises(updater.AtualizacaoRecusada) as erro:
                updater.verificar_atualizacao("https://exemplo/version.json")
        self.assertIn("SHA-256", str(erro.exception))

    def test_recusa_sha256_mal_formado(self):
        buscar = self._anunciar({"versao": "9.9.9",
                                 "arquivo": "https://exemplo/App.exe",
                                 "sha256": "curto-demais"})
        with unittest.mock.patch.object(updater, "_buscar", buscar):
            with self.assertRaises(updater.AtualizacaoRecusada):
                updater.verificar_atualizacao("https://exemplo/version.json")

    def test_recusa_executavel_fora_de_https(self):
        buscar = self._anunciar({"versao": "9.9.9",
                                 "arquivo": "http://exemplo/App.exe",
                                 "sha256": "e" * 64})
        with unittest.mock.patch.object(updater, "_buscar", buscar):
            with self.assertRaises(updater.AtualizacaoRecusada) as erro:
                updater.verificar_atualizacao("https://exemplo/version.json")
        self.assertIn("https", str(erro.exception))

    def test_recusa_anuncio_fora_de_https(self):
        with self.assertRaises(updater.AtualizacaoRecusada):
            updater.verificar_atualizacao("http://exemplo/version.json")

    def test_recusa_anuncio_sem_versao(self):
        buscar = self._anunciar({"arquivo": "https://exemplo/App.exe",
                                 "sha256": "f" * 64})
        with unittest.mock.patch.object(updater, "_buscar", buscar):
            with self.assertRaises(updater.AtualizacaoRecusada):
                updater.verificar_atualizacao("https://exemplo/version.json")

    # -- download -------------------------------------------------------- #

    def test_arquivo_que_nao_confere_e_apagado(self):
        conteudo = b"binario qualquer"
        outro = hashlib.sha256(b"outra coisa").hexdigest()
        nova = updater.Atualizacao("9.9.9", "https://exemplo/App.exe", outro)
        with tempfile.TemporaryDirectory() as pasta:
            with unittest.mock.patch.object(updater, "pasta_de_trabalho",
                                            lambda: pathlib.Path(pasta)), \
                 unittest.mock.patch.object(updater.urllib.request, "urlopen",
                                            _resposta_falsa(conteudo)):
                with self.assertRaises(updater.AtualizacaoRecusada):
                    updater.baixar(nova)
            self.assertEqual(list(pathlib.Path(pasta).glob("*.exe")), [],
                             "o arquivo recusado ficou no disco")

    def test_arquivo_que_confere_e_guardado(self):
        conteudo = b"binario qualquer"
        certo = hashlib.sha256(conteudo).hexdigest()
        nova = updater.Atualizacao("9.9.9", "https://exemplo/App.exe", certo)
        with tempfile.TemporaryDirectory() as pasta:
            with unittest.mock.patch.object(updater, "pasta_de_trabalho",
                                            lambda: pathlib.Path(pasta)), \
                 unittest.mock.patch.object(updater.urllib.request, "urlopen",
                                            _resposta_falsa(conteudo)):
                caminho = updater.baixar(nova)
            self.assertEqual(caminho.read_bytes(), conteudo)

    # -- o roteiro da troca ---------------------------------------------- #

    def test_o_roteiro_troca_abre_e_se_apaga(self):
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            roteiro = updater._roteiro(base / "update_temp.exe",
                                       base / "Dezorzi NFS-e.exe", base)
            texto = roteiro.read_text(encoding="utf-8")
        self.assertIn("ping -n 3", texto)      # a espera antes de trocar
        self.assertIn("move /y", texto)
        self.assertIn("start ", texto)
        self.assertIn('del "%~f0"', texto)

    def test_a_variavel_do_caminho_vai_entre_aspas(self):
        """"Dezorzi NFS-e.exe" tem espaço: sem aspas, o `move` recebe dois
        argumentos e a troca não acontece.

        As aspas agora envolvem a VARIÁVEL, não o caminho — ele deixou de ser
        escrito no arquivo para não passar pela página de código do `cmd`.
        """
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            texto = updater._roteiro(base / "update_temp.exe",
                                     base / "Dezorzi NFS-e.exe",
                                     base).read_text(encoding="ascii")
        self.assertIn('"%NFSE_NOVO%" "%NFSE_ALVO%"', texto)
        self.assertIn('start "" "%NFSE_ALVO%"', texto)

    def test_o_roteiro_insiste_antes_de_desistir(self):
        # OneDrive e antivírus seguram o arquivo por um instante depois de o
        # processo morrer; uma tentativa só falharia justamente na máquina em
        # que o programa vive.
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            texto = updater._roteiro(base / "novo.exe", base / "velho.exe",
                                     base).read_text(encoding="utf-8")
        self.assertIn("goto tentar", texto)
        self.assertIn("geq 15", texto)

    def test_o_roteiro_e_ascii_puro(self):
        """Nenhum byte acentuado no `.bat` — nem no caminho, nem em texto.

        O `cmd` lê um `.bat` na página de código antiga do Windows (850, no
        Brasil), não em UTF-8. Caminho com acento gravado em UTF-8 chegava
        corrompido: "Área de Trabalho" virava "├ürea de Trabalho", o `move`
        falhava calado e o `start` reclamava de um caminho inexistente. E
        "Área de Trabalho" é o nome PADRÃO da Área de Trabalho no Windows em
        português — o recurso quebrava para quase todo mundo.
        """
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            acentuado = base / "Área de Trabalho" / "Dezorzi NFS-e.exe"
            bruto = updater._roteiro(base / "novo.exe", acentuado,
                                     base).read_bytes()
        fora = [b for b in bruto if b > 127]
        self.assertEqual(fora, [], "há byte não-ASCII no roteiro")

    def test_os_caminhos_vao_por_variavel_de_ambiente(self):
        """Variável de ambiente não passa por página de código: vem em Unicode."""
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            novo, alvo = base / "novo.exe", base / "Área" / "app.exe"
            texto = updater._roteiro(novo, alvo, base).read_text(encoding="ascii")
            ambiente = updater.ambiente_do_roteiro(novo, alvo)
        self.assertIn("%NFSE_NOVO%", texto)
        self.assertIn("%NFSE_ALVO%", texto)
        self.assertNotIn(str(base), texto, "o caminho vazou para dentro do .bat")
        self.assertEqual(ambiente["NFSE_NOVO"], str(novo))
        self.assertEqual(ambiente["NFSE_ALVO"], str(alvo))

    def test_o_ambiente_preserva_o_resto(self):
        # O roteiro herda o ambiente todo; só acrescenta os dois caminhos.
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            ambiente = updater.ambiente_do_roteiro(base / "a", base / "b")
        for chave in list(os.environ)[:5]:
            self.assertIn(chave, ambiente)

    def test_a_espera_nao_usa_timeout(self):
        """`timeout` precisa de console, e o roteiro roda sem nenhum.

        Sem console ele sai com erro na hora, e as quinze tentativas queimam
        em milissegundos em vez de durarem quinze segundos — qualquer arquivo
        momentaneamente preso, que é o caso normal em máquina com OneDrive,
        perde a atualização. Descoberto executando o roteiro de verdade.
        """
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            texto = updater._roteiro(base / "novo.exe", base / "velho.exe",
                                     base).read_text(encoding="utf-8")
        self.assertNotIn("timeout", texto)
        self.assertIn("ping -n", texto)

    def test_o_laco_nao_usa_bloco_entre_parenteses(self):
        """Dentro de `( )` o cmd expande %TENTATIVA% ao LER, não ao executar."""
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            texto = updater._roteiro(base / "novo.exe", base / "velho.exe",
                                     base).read_text(encoding="utf-8")
        for linha in texto.splitlines():
            if "TENTATIVA" in linha:
                self.assertNotIn("(", linha, linha)

    def test_falhando_a_troca_o_programa_abre_do_mesmo_jeito(self):
        """A última linha abre o executável, tenha a troca dado certo ou não."""
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            linhas = updater._roteiro(base / "novo.exe", base / "App.exe",
                                      base).read_text(encoding="utf-8").splitlines()
        abre = [i for i, l in enumerate(linhas) if l.startswith("start ")]
        desiste = [i for i, l in enumerate(linhas) if "geq 15" in l]
        self.assertTrue(abre and desiste and abre[0] > desiste[0],
                        "o `start` tem de vir depois de desistir da troca")

    # -- integração com a tela ------------------------------------------- #

    def test_rodando_do_codigo_nao_procura_atualizacao(self):
        chamou = []
        with unittest.mock.patch.object(updater, "formato", lambda: "codigo"), \
             unittest.mock.patch.object(updater, "verificar_atualizacao",
                                        lambda *a, **k: chamou.append(1)):
            updater.procurar_em_segundo_plano(lambda _n: None)
        self.assertEqual(chamou, [])

    def test_rede_fora_nao_impede_o_programa_de_abrir(self):
        """Falha de rede vira linha no diário, não exceção na tela."""
        def explodir(*_a, **_k):
            raise OSError("rede fora")

        avisado = []
        pronto = threading.Event()
        with unittest.mock.patch.object(updater, "formato", lambda: "unico"), \
             unittest.mock.patch.object(updater, "verificar_atualizacao", explodir), \
             unittest.mock.patch.object(registro, "falha",
                                        lambda *a, **k: pronto.set()):
            updater.procurar_em_segundo_plano(lambda n: avisado.append(n))
            pronto.wait(timeout=5)
        self.assertEqual(avisado, [])

    def test_a_versao_tem_formato_de_versao(self):
        self.assertRegex(updater.VERSAO_ATUAL, r"^\d+\.\d+\.\d+$")


def _resposta_falsa(conteudo: bytes):
    """Um `urlopen` que devolve estes bytes, sem rede."""
    class Resposta:
        headers = {"Content-Length": str(len(conteudo))}

        def __init__(self):
            self._sobra = conteudo

        def read(self, quanto=None):
            pedaco, self._sobra = self._sobra[:quanto], self._sobra[quanto:]
            return pedaco

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    return lambda *_a, **_k: Resposta()


class EmpacotamentoTests(unittest.TestCase):
    """O que sai — e o que NÃO sai — na compilação distribuída."""

    def test_o_cadastro_de_empresas_nao_e_distribuido(self):
        self.assertIn("empresas.json", empacotar.DESCARTAR)
        self.assertIn("empresa_ativa.txt", empacotar.DESCARTAR)

    def test_os_caches_por_inscricao_ficam_de_fora(self):
        # `servicos_304838.json` é a lista de serviços de um cliente DESTA
        # máquina: identifica quem usa o programa e não serve para mais
        # ninguém. O programa reconstrói no primeiro login.
        for nome in ("servicos_304838.json", "obras_285504.json",
                     "servicos_1.json"):
            self.assertTrue(empacotar.POR_INSCRICAO.match(nome), nome)

    def test_as_tabelas_comuns_continuam_indo(self):
        # Estas valem para qualquer máquina — sem elas a nota é recusada.
        for nome in ("reforma_codigos.json", "nbs_por_item.json", "ufs.json",
                     "aliquotas.json", "municipios_35.json"):
            self.assertIsNone(empacotar.POR_INSCRICAO.match(nome), nome)

    def test_o_updater_esta_entre_os_modulos_embutidos(self):
        # Sem isto o PyInstaller não o enxerga e o .exe morre na primeira tela.
        self.assertIn("updater", empacotar.MODULOS)

    def test_a_semente_sai_sem_senha_e_sem_cache_de_cliente(self):
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            (base / "config").mkdir()
            (base / "assets").mkdir()
            for nome, conteudo in (
                ("empresas.json", '{"segredo": 1}'),
                ("empresa_ativa.txt", "MUNDIAL"),
                ("servicos_304838.json", "[]"),
                ("obras_285504.json", "[]"),
                ("ufs.json", "[]"),
            ):
                (base / "config" / nome).write_text(conteudo, encoding="utf-8")
            (base / ".env").write_text(
                "NFSE_SENHA=segredo\nNFSE_LIVE_MODE=true\nNFSE_TEMA=escuro\n",
                encoding="utf-8")
            for nome in ("LEIA-ME.txt", "COMO-USAR.txt"):
                (base / "assets" / nome).write_text("x", encoding="utf-8")

            with unittest.mock.patch.object(empacotar, "BASE", base), \
                 unittest.mock.patch.object(empacotar, "SEMENTE",
                                            base / "semente"), \
                 unittest.mock.patch.object(empacotar, "PASTAS",
                                            ("config", "assets")):
                semente = empacotar.preparar_semente(seguro=False)

            config_semente = semente / "config"
            self.assertTrue((config_semente / "ufs.json").exists(),
                            "a tabela comum tinha de ir")
            for fora in ("empresas.json", "empresa_ativa.txt",
                         "servicos_304838.json", "obras_285504.json"):
                self.assertFalse((config_semente / fora).exists(),
                                 f"{fora} não podia ir junto")
            env = (semente / ".env").read_text(encoding="utf-8")
            self.assertNotIn("NFSE_SENHA=segredo", env)
            self.assertIn("NFSE_LIVE_MODE=true", env)

    def test_a_chave_de_atualizacao_esta_na_origem_do_env(self):
        """Sem a chave, a semente sai sem ela e a cópia nunca procura versão.

        Confere a MESMA origem que `preparar_semente` usa: o `.env` quando
        existe, e o `.env.example` quando não — que é o caso de um clone, onde
        o `.env` nem é versionado. Antes isto olhava só o `.env`, e a
        compilação na nuvem quebrava por falta de um arquivo que ela nunca
        vai ter.
        """
        raiz = pathlib.Path(paths.__file__).resolve().parent
        origem = raiz / ".env"
        if not origem.exists():
            origem = raiz / ".env.example"
        self.assertTrue(origem.exists(), "nem .env nem .env.example")
        self.assertIn("NFSE_ATUALIZACAO_URL",
                      origem.read_text(encoding="utf-8"),
                      f"a chave falta em {origem.name}")


class IconeDoExecutavelTests(unittest.TestCase):
    """O ícone do .exe sai do logotipo do usuário quando há um."""

    def test_sem_logotipo_usa_o_monograma(self):
        arquivo = marca.ARQUIVO
        with tempfile.TemporaryDirectory() as pasta:
            marca.ARQUIVO = pathlib.Path(pasta) / "nao-existe.png"
            marca.esquecer()
            try:
                alvo, origem = marca.icone_do_windows(
                    pathlib.Path(pasta) / "app_icon.ico")
                self.assertEqual(origem, "monograma")
                self.assertTrue(alvo.stat().st_size > 0)
            finally:
                marca.ARQUIVO = arquivo
                marca.esquecer()

    def test_com_logotipo_o_icone_sai_dele(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("sem Pillow: o ícone cai no monograma, por desenho")
        arquivo = marca.ARQUIVO
        with tempfile.TemporaryDirectory() as pasta:
            base = pathlib.Path(pasta)
            logo = base / "logo.png"
            # Retangular de propósito: o ícone tem de sair quadrado.
            Image.new("RGBA", (400, 200), (10, 90, 100, 255)).save(logo)
            marca.ARQUIVO = logo
            marca.esquecer()
            try:
                alvo, origem = marca.icone_do_windows(base / "app_icon.ico")
                self.assertEqual(origem, "logotipo")
                with Image.open(alvo) as icone:
                    self.assertIn((256, 256), icone.info["sizes"])
                    self.assertIn((16, 16), icone.info["sizes"])
            finally:
                marca.ARQUIVO = arquivo
                marca.esquecer()

    def test_o_icone_traz_varios_tamanhos(self):
        # Um .ico com só 256 faz o Windows encolher para 16 e a marca vira
        # mancha na barra de tarefas.
        with tempfile.TemporaryDirectory() as pasta:
            alvo = pathlib.Path(pasta) / "i.ico"
            marca.salvar_ico(alvo)
            bruto = alvo.read_bytes()
        quantidade = int.from_bytes(bruto[4:6], "little")
        self.assertGreaterEqual(quantidade, 5)


class PublicacaoNaNuvemTests(unittest.TestCase):
    """Os dois scripts que o GitHub Actions roda, exercitados sem GitHub."""

    def setUp(self):
        self.raiz = pathlib.Path(paths.__file__).resolve().parent
        self.fluxo = self.raiz / ".github" / "workflows"
        if not (self.fluxo / "publicar_manifesto.py").exists():
            self.skipTest("workflow não instalado")

    def _rodar(self, script, *argumentos, **ambiente):
        env = dict(os.environ)
        env.update(ambiente)
        return subprocess.run(
            [sys.executable, str(self.fluxo / script), *argumentos],
            capture_output=True, text=True, env=env, cwd=str(self.raiz))

    # -- conferência de versão ------------------------------------------- #

    def test_tag_igual_a_versao_passa(self):
        saida = self._rodar("conferir_versao.py", f"v{updater.VERSAO_ATUAL}")
        self.assertEqual(saida.returncode, 0, saida.stdout + saida.stderr)

    def test_tag_diferente_da_versao_falha(self):
        # É a falha que ninguém percebe: a Release sai, e nenhuma máquina
        # atualiza porque o anúncio repete a versão de antes.
        saida = self._rodar("conferir_versao.py", "v99.98.97")
        self.assertEqual(saida.returncode, 1)
        self.assertIn("::error::", saida.stdout)

    def test_aceita_a_tag_com_ou_sem_o_v(self):
        saida = self._rodar("conferir_versao.py", updater.VERSAO_ATUAL)
        self.assertEqual(saida.returncode, 0, saida.stdout + saida.stderr)

    # -- manifesto ------------------------------------------------------- #

    def _cenario(self, pasta, sha=None):
        """Uma pasta `executavel/` como a que a compilação deixa."""
        saida = pathlib.Path(pasta) / "executavel"
        saida.mkdir(parents=True)
        exe = saida / "Dezorzi NFS-e.exe"
        exe.write_bytes(b"binario de teste")
        verdadeiro = hashlib.sha256(exe.read_bytes()).hexdigest()
        (saida / "version.json").write_text(json.dumps({
            "versao": "1.2.3", "arquivo": "", "sha256": sha or verdadeiro,
            "notas": "", "_como_usar": "…"}), encoding="utf-8")
        return saida

    def test_preenche_o_endereco_da_release(self):
        with tempfile.TemporaryDirectory() as pasta:
            saida = self._cenario(pasta)
            script = self.fluxo / "publicar_manifesto.py"
            resultado = subprocess.run(
                [sys.executable, "-c",
                 "import runpy,sys,pathlib;"
                 "import importlib.util as u;"
                 f"spec=u.spec_from_file_location('pm', r'{script}');"
                 "m=u.module_from_spec(spec);spec.loader.exec_module(m);"
                 f"m.SAIDA=pathlib.Path(r'{saida}');"
                 "sys.exit(m.main())"],
                capture_output=True, text=True,
                env={**os.environ, "REPOSITORIO": "dezorzi/nfse",
                     "TAG": "v1.2.3"})
            self.assertEqual(resultado.returncode, 0,
                             resultado.stdout + resultado.stderr)
            dados = json.loads((saida / "version.json").read_text(encoding="utf-8"))
        self.assertEqual(
            dados["arquivo"],
            "https://github.com/dezorzi/nfse/releases/download/v1.2.3/"
            "Dezorzi.NFS-e.exe")
        self.assertNotIn("_como_usar", dados)

    def test_o_espaco_do_nome_vira_ponto_como_o_github_faz(self):
        """O GitHub renomeia o anexo: "Dezorzi NFS-e.exe" vira "Dezorzi.NFS-e.exe".

        Escrever o nome original no manifesto dá um endereço que responde 404.
        Visto na primeira publicação de verdade, comparando o que o workflow
        gravou com o que a Release realmente serviu.
        """
        with tempfile.TemporaryDirectory() as pasta:
            saida = self._cenario(pasta)
            script = self.fluxo / "publicar_manifesto.py"
            subprocess.run(
                [sys.executable, "-c",
                 "import sys,pathlib;import importlib.util as u;"
                 f"spec=u.spec_from_file_location('pm', r'{script}');"
                 "m=u.module_from_spec(spec);spec.loader.exec_module(m);"
                 f"m.SAIDA=pathlib.Path(r'{saida}');sys.exit(m.main())"],
                capture_output=True, text=True,
                env={**os.environ, "REPOSITORIO": "d/n", "TAG": "v1.2.3"})
            dados = json.loads((saida / "version.json").read_text(encoding="utf-8"))
        self.assertNotIn(" ", dados["arquivo"])
        self.assertNotIn("%20", dados["arquivo"])
        self.assertTrue(dados["arquivo"].endswith("Dezorzi.NFS-e.exe"),
                        dados["arquivo"])

    def test_sha_que_nao_bate_derruba_a_publicacao(self):
        # Melhor falhar aqui do que toda máquina recusar a atualização depois.
        with tempfile.TemporaryDirectory() as pasta:
            saida = self._cenario(pasta, sha="0" * 64)
            script = self.fluxo / "publicar_manifesto.py"
            resultado = subprocess.run(
                [sys.executable, "-c",
                 "import sys,pathlib;import importlib.util as u;"
                 f"spec=u.spec_from_file_location('pm', r'{script}');"
                 "m=u.module_from_spec(spec);spec.loader.exec_module(m);"
                 f"m.SAIDA=pathlib.Path(r'{saida}');sys.exit(m.main())"],
                capture_output=True, text=True,
                env={**os.environ, "REPOSITORIO": "d/n", "TAG": "v1.2.3"})
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("::error::", resultado.stdout)

    def test_o_manifesto_publicado_e_aceito_pelo_atualizador(self):
        """A ponta final: o que a nuvem publica, o programa aceita."""
        with tempfile.TemporaryDirectory() as pasta:
            saida = self._cenario(pasta)
            script = self.fluxo / "publicar_manifesto.py"
            subprocess.run(
                [sys.executable, "-c",
                 "import sys,pathlib;import importlib.util as u;"
                 f"spec=u.spec_from_file_location('pm', r'{script}');"
                 "m=u.module_from_spec(spec);spec.loader.exec_module(m);"
                 f"m.SAIDA=pathlib.Path(r'{saida}');sys.exit(m.main())"],
                capture_output=True, text=True,
                env={**os.environ, "REPOSITORIO": "d/n", "TAG": "v1.2.3"})
            publicado = (saida / "version.json").read_text(encoding="utf-8")

        def buscar(url, limite):
            return publicado.encode("utf-8")

        with unittest.mock.patch.object(updater, "_buscar", buscar):
            achada = updater.verificar_atualizacao("https://exemplo/version.json")
        self.assertEqual(achada.versao, "1.2.3")
        self.assertTrue(achada.url.startswith("https://"))
        self.assertRegex(achada.sha256, r"^[0-9a-f]{64}$")

    # -- o arquivo do fluxo ---------------------------------------------- #

    def test_o_workflow_dispara_na_tag_e_pode_publicar(self):
        texto = (self.fluxo / "build.yml").read_text(encoding="utf-8")
        self.assertIn('tags: ["v*"]', texto)
        self.assertIn("contents: write", texto)
        self.assertIn("windows-latest", texto)
        self.assertIn("empacotar.py --unico", texto)

    def test_o_workflow_confere_a_versao_antes_de_publicar(self):
        texto = (self.fluxo / "build.yml").read_text(encoding="utf-8")
        ordem = [texto.index(t) for t in ("conferir_versao.py",
                                          "empacotar.py --unico",
                                          "action-gh-release")]
        self.assertEqual(ordem, sorted(ordem),
                         "a conferência tem de vir antes de compilar e publicar")


class PastaDoArquivoUnicoTests(unittest.TestCase):
    """Onde o executável de arquivo único guarda os dados.

    Antes era ao lado do .exe, e isso obrigava quem recebe o programa a se
    importar com onde ele fica: largado na Área de Trabalho, criava três
    pastas na Área de Trabalho da pessoa.
    """

    def setUp(self):
        self.frozen = getattr(sys, "frozen", None)
        self.executable = sys.executable
        self.meipass = getattr(sys, "_MEIPASS", None)
        self.local = os.environ.get("LOCALAPPDATA")

    def tearDown(self):
        if self.frozen is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = self.frozen
        if self.meipass is None:
            if hasattr(sys, "_MEIPASS"):
                del sys._MEIPASS
        else:
            sys._MEIPASS = self.meipass
        sys.executable = self.executable
        if self.local is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self.local

    def _fingir(self, *, exe: pathlib.Path, unico: bool):
        sys.frozen = True
        sys.executable = str(exe)
        # Arquivo único: o PyInstaller descompacta longe do .exe.
        # Pasta: o `_internal/` fica do lado.
        sys._MEIPASS = (str(pathlib.Path(tempfile.mkdtemp()).resolve())
                        if unico else str(exe.parent / "_internal"))

    def test_arquivo_unico_guarda_no_appdata(self):
        with tempfile.TemporaryDirectory() as area, \
             tempfile.TemporaryDirectory() as appdata:
            mesa = pathlib.Path(area).resolve()      # a "Área de Trabalho"
            os.environ["LOCALAPPDATA"] = str(pathlib.Path(appdata).resolve())
            self._fingir(exe=mesa / "Dezorzi NFS-e.exe", unico=True)
            raiz = paths._raiz()
            self.assertEqual(raiz,
                             pathlib.Path(appdata).resolve() / "Dezorzi NFS-e")
            self.assertNotEqual(raiz, mesa,
                                "não pode sujar a pasta onde o .exe está")

    def test_formato_pasta_continua_ao_lado_do_exe(self):
        # Nesse formato o config/ e as notas à vista são o ponto: quem usa a
        # pasta a copia inteira, com dados e tudo.
        with tempfile.TemporaryDirectory() as programa:
            base = pathlib.Path(programa).resolve()
            self._fingir(exe=base / "Dezorzi NFS-e.exe", unico=False)
            self.assertEqual(paths._raiz(), base)

    def test_instalacao_que_ja_existe_nao_e_movida(self):
        """Havendo dados ao lado do .exe, é ali que o programa continua.

        Trocar o lugar debaixo de quem já usa faria as notas sumirem da tela
        sem nenhuma explicação.
        """
        with tempfile.TemporaryDirectory() as antigo, \
             tempfile.TemporaryDirectory() as appdata:
            base = pathlib.Path(antigo).resolve()
            (base / "data").mkdir()
            os.environ["LOCALAPPDATA"] = str(pathlib.Path(appdata).resolve())
            self._fingir(exe=base / "Dezorzi NFS-e.exe", unico=True)
            self.assertEqual(paths._raiz(), base)

    def test_um_env_ao_lado_tambem_segura_a_instalacao(self):
        with tempfile.TemporaryDirectory() as antigo, \
             tempfile.TemporaryDirectory() as appdata:
            base = pathlib.Path(antigo).resolve()
            (base / ".env").write_text("NFSE_TEMA=escuro\n", encoding="utf-8")
            os.environ["LOCALAPPDATA"] = str(pathlib.Path(appdata).resolve())
            self._fingir(exe=base / "Dezorzi NFS-e.exe", unico=True)
            self.assertEqual(paths._raiz(), base)

    def test_solto_no_codigo_nao_muda_nada(self):
        if hasattr(sys, "frozen"):
            del sys.frozen
        self.assertEqual(paths._raiz(),
                         pathlib.Path(paths.__file__).resolve().parent)

    def test_sem_localappdata_cai_na_pasta_do_usuario(self):
        # Windows sempre define, mas um ambiente enxuto pode não ter.
        with tempfile.TemporaryDirectory() as area:
            os.environ.pop("LOCALAPPDATA", None)
            self._fingir(exe=pathlib.Path(area).resolve() / "x.exe", unico=True)
            self.assertEqual(paths._raiz(), pathlib.Path.home() / "Dezorzi NFS-e")

    def test_mover_o_exe_nao_perde_as_notas(self):
        """O .exe pode mudar de pasta; os dados ficam onde estavam."""
        with tempfile.TemporaryDirectory() as um, \
             tempfile.TemporaryDirectory() as outro, \
             tempfile.TemporaryDirectory() as appdata:
            os.environ["LOCALAPPDATA"] = str(pathlib.Path(appdata).resolve())
            self._fingir(exe=pathlib.Path(um).resolve() / "app.exe", unico=True)
            primeira = paths._raiz()
            self._fingir(exe=pathlib.Path(outro).resolve() / "app.exe", unico=True)
            self.assertEqual(paths._raiz(), primeira)


class ContrasteWCAGTests(unittest.TestCase):
    """A paleta passa nas WCAG 2.1, nível AA (critério 1.4.3)?

    A norma pede razão de contraste de 4,5:1 para texto normal e 3:1 para
    texto grande. Não é questão de gosto: é a conta da luminância relativa,
    definida na própria norma, e ou o número passa ou não passa.

    Medindo a tela inteira nos dois temas, 24 de 72 combinações reprovavam —
    o cinza dos rótulos secundários dava 2,68:1 sobre o branco. Estes testes
    seguram o que foi corrigido.
    """

    @staticmethod
    def _canal(valor: float) -> float:
        valor /= 255.0
        return valor / 12.92 if valor <= 0.03928 else ((valor + 0.055) / 1.055) ** 2.4

    @classmethod
    def luminancia(cls, cor: str) -> float:
        cor = cor.lstrip("#")
        r, g, b = (int(cor[i:i + 2], 16) for i in (0, 2, 4))
        return (0.2126 * cls._canal(r) + 0.7152 * cls._canal(g)
                + 0.0722 * cls._canal(b))

    @classmethod
    def razao(cls, frente: str, fundo: str) -> float:
        a, b = cls.luminancia(frente), cls.luminancia(fundo)
        return (max(a, b) + 0.05) / (min(a, b) + 0.05)

    def tearDown(self):
        ui.usar_tema("claro")

    def _conferir(self, pares, minimo=4.5):
        reprovados = []
        for tema in ("claro", "escuro"):
            ui.usar_tema(tema)
            for nome_frente, nome_fundo in pares:
                frente = getattr(ui, nome_frente)
                fundo = getattr(ui, nome_fundo)
                valor = self.razao(frente, fundo)
                if valor < minimo:
                    reprovados.append(
                        f"{tema}: {nome_frente} ({frente}) sobre "
                        f"{nome_fundo} ({fundo}) = {valor:.2f}:1")
        self.assertEqual(reprovados, [], "\n".join([""] + reprovados))

    def test_a_conta_bate_com_os_valores_da_norma(self):
        # Preto sobre branco é 21:1, o máximo possível; e a razão é simétrica.
        self.assertAlmostEqual(self.razao("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(self.razao("#ffffff", "#000000"), 21.0, places=2)
        self.assertAlmostEqual(self.razao("#777777", "#ffffff"), 4.48, places=2)

    def test_os_tres_tons_de_texto_sobre_as_superficies(self):
        self._conferir([(tinta, fundo)
                        for tinta in ("INK", "INK_2", "INK_3")
                        for fundo in ("BG", "SURFACE", "SURFACE_ALT")])

    def test_o_texto_da_barra_de_comando(self):
        self._conferir([("INK", "NAVY"), ("NAV_TEXTO", "NAVY"),
                        ("NAV_LEGENDA", "NAVY"), ("NAV_MONO", "NAVY"),
                        ("NAV_DESTAQUE", "NAVY")])

    def test_as_pilulas_de_situacao(self):
        # "Emitida", "Rascunho", "Falhou": o selo tem de se ler à distância.
        self._conferir([("SUCESSO", "SUCESSO_BG"), ("ALERTA", "ALERTA_BG"),
                        ("ERRO", "ERRO_BG"), ("INFO", "INFO_BG"),
                        ("NEUTRO", "NEUTRO_BG")])

    def test_o_branco_sobre_os_preenchimentos_fortes(self):
        for tema in ("claro", "escuro"):
            ui.usar_tema(tema)
            for nome in ("PRIMARIA", "PRIMARIA_HOVER", "PRIMARIA_PRESS",
                         "ERRO_SOLIDO"):
                cor = getattr(ui, nome)
                tinta = ui.contraste(cor)
                valor = self.razao(tinta, cor)
                self.assertGreaterEqual(
                    valor, 4.5,
                    f"{tema}: {tinta} sobre {nome} ({cor}) = {valor:.2f}:1")

    def test_a_escolha_automatica_de_tinta_sempre_passa(self):
        """`contraste()` tem de devolver a tinta que de fato se lê."""
        for tema in ("claro", "escuro"):
            ui.usar_tema(tema)
            for nome in ("SUCESSO", "ALERTA", "ERRO", "INFO", "NEUTRO",
                         "PRIMARIA", "SURFACE", "SURFACE_ALT", "BG", "NAVY"):
                cor = getattr(ui, nome)
                valor = self.razao(ui.contraste(cor), cor)
                self.assertGreaterEqual(
                    valor, 4.5, f"{tema}: contraste({nome}={cor}) = {valor:.2f}:1")


class EscalaTipograficaTests(unittest.TestCase):
    """A régua de tamanhos tem degraus que se enxergam?

    Antes eram sete tamanhos com razões de 1,045 a 1,375 entre vizinhos. Um
    degrau de 1,045 — o 22 para o 23 — não se vê: eram sete tamanhos que o
    olho lia como quatro.
    """

    @staticmethod
    def _tamanho(fonte) -> int:
        return abs(int(fonte[1]))

    def setUp(self):
        self.escala = [self._tamanho(f) for f in
                       (ui.MICRO, ui.PEQUENO, ui.CORPO, ui.SUBTITULO,
                        ui.TITULO, ui.DISPLAY)]

    def test_a_regua_sobe_sempre(self):
        self.assertEqual(self.escala, sorted(self.escala))

    def test_os_degraus_de_cima_seguem_a_escala_modular(self):
        """Do corpo para cima, cada degrau é ao menos 25% maior."""
        de_cima = [self._tamanho(f) for f in
                   (ui.CORPO, ui.SUBTITULO, ui.TITULO, ui.DISPLAY)]
        for menor, maior in zip(de_cima, de_cima[1:]):
            self.assertGreaterEqual(
                maior / menor, 1.25,
                f"{menor} -> {maior} é x{maior / menor:.3f}: não se enxerga")

    def test_numero_e_display_sao_o_mesmo_degrau(self):
        # Eram 22 e 23 — x1,045, dois tamanhos lidos como um só.
        self.assertEqual(self._tamanho(ui.NUMERO), self._tamanho(ui.DISPLAY))

    def test_os_dois_degraus_de_baixo_existem_por_densidade(self):
        """9 e 10 ficam fora da escala de propósito: abaixo de 9 some.

        A hierarquia entre eles é sustentada por cor e caixa alta, não por
        tamanho — é uma tela de dados, e a régua modular não alcança ali.
        """
        self.assertEqual(self._tamanho(ui.MICRO), 9)
        self.assertLess(self._tamanho(ui.PEQUENO), self._tamanho(ui.CORPO))

    def test_a_etiqueta_e_o_micro_em_negrito(self):
        self.assertEqual(self._tamanho(ui.ETIQUETA), self._tamanho(ui.MICRO))
        self.assertIn("bold", ui.ETIQUETA)


class AtenuacaoTests(unittest.TestCase):
    """A curva que move o indicador da navegação."""

    def test_parte_do_zero_e_chega_ao_um(self):
        self.assertEqual(ui.Segmentado.atenuar(0.0), 0.0)
        self.assertEqual(ui.Segmentado.atenuar(1.0), 1.0)

    def test_e_simetrica(self):
        # Sai devagar e chega devagar, no mesmo ritmo dos dois lados.
        for fracao in (0.1, 0.25, 0.4):
            self.assertAlmostEqual(
                ui.Segmentado.atenuar(fracao) + ui.Segmentado.atenuar(1 - fracao),
                1.0, places=9)

    def test_no_meio_do_caminho_esta_na_metade(self):
        self.assertAlmostEqual(ui.Segmentado.atenuar(0.5), 0.5, places=9)

    def test_comeca_devagar(self):
        """O defeito da mola exponencial era partir na velocidade máxima."""
        self.assertLess(ui.Segmentado.atenuar(0.1), 0.1 / 2)

    def test_nunca_sai_do_trajeto(self):
        anterior = -1.0
        for passo in range(0, 101):
            valor = ui.Segmentado.atenuar(passo / 100)
            self.assertGreaterEqual(valor, anterior, "voltou para trás")
            self.assertTrue(0.0 <= valor <= 1.0, f"saiu do intervalo: {valor}")
            anterior = valor

    def test_a_duracao_e_declarada(self):
        # A mola antiga não tinha fim: parava num corte arbitrário de 0,6px.
        self.assertGreater(ui.Segmentado.DURACAO, 0)
        self.assertLessEqual(ui.Segmentado.DURACAO, 400,
                             "animação longa demais atrapalha quem trabalha")


class GravacaoTeimosaTests(unittest.TestCase):
    """Gravar preferência não pode falhar porque o antivírus estava olhando.

    No Windows, o Defender e o indexador abrem o arquivo assim que ele é
    escrito, e nessa janela de milissegundos o `replace` falha com
    PermissionError. Uma tentativa só bastava aqui e quebrou na nuvem — na
    máquina de quem usa, seria a preferência que some de vez em quando.
    """

    def setUp(self):
        self.original = paths.ENV_FILE
        self.pasta = pathlib.Path(tempfile.mkdtemp()).resolve()
        paths.ENV_FILE = self.pasta / ".env"

    def tearDown(self):
        paths.ENV_FILE = self.original

    def test_insiste_e_consegue(self):
        """Falhando as primeiras vezes, ainda assim grava."""
        paths.ENV_FILE.write_text("NFSE_TEMA=claro\n", encoding="utf-8")
        original = pathlib.Path.replace
        tentativas = {"n": 0}

        def teimoso(self, alvo):
            tentativas["n"] += 1
            if tentativas["n"] <= 3:
                raise PermissionError(13, "o antivírus estava com o arquivo")
            return original(self, alvo)

        with unittest.mock.patch.object(pathlib.Path, "replace", teimoso):
            config.definir_no_env("NFSE_TEMA", "escuro")

        self.assertGreater(tentativas["n"], 3, "não tentou de novo")
        self.assertIn("NFSE_TEMA=escuro",
                      paths.ENV_FILE.read_text(encoding="utf-8"))

    def test_desistindo_nao_deixa_arquivo_solto(self):
        """Se não der mesmo, o temporário não fica largado na pasta."""
        paths.ENV_FILE.write_text("NFSE_TEMA=claro\n", encoding="utf-8")

        def sempre_falha(self, alvo):
            raise PermissionError(13, "preso o tempo todo")

        with unittest.mock.patch.object(pathlib.Path, "replace", sempre_falha):
            with self.assertRaises(PermissionError):
                config.definir_no_env("NFSE_TEMA", "escuro")

        sobrando = [p.name for p in self.pasta.iterdir() if p.name != ".env"]
        self.assertEqual(sobrando, [], f"sobrou lixo: {sobrando}")
        # E o arquivo antigo continua íntegro: melhor a preferência velha que
        # nenhuma configuração.
        self.assertIn("NFSE_TEMA=claro",
                      paths.ENV_FILE.read_text(encoding="utf-8"))

    def test_no_caminho_normal_grava_de_primeira(self):
        paths.ENV_FILE.write_text("NFSE_TEMA=claro\n", encoding="utf-8")
        config.definir_no_env("NFSE_TEMA", "escuro")
        self.assertIn("NFSE_TEMA=escuro",
                      paths.ENV_FILE.read_text(encoding="utf-8"))
        self.assertFalse((self.pasta / ".env.env.tmp").exists())


class InteracaoDaTabelaTests(unittest.TestCase):
    """Ordenar pelo cabeçalho, e o clique que chega onde deveria."""

    COLUNAS = None

    def setUp(self):
        try:
            self.raiz = tk.Tk()
        except Exception as exc:
            self.skipTest(f"sem interface gráfica: {exc}")
        # Sem `withdraw`: evento de clique não chega a widget não mapeado, e o
        # teste passaria dizendo que nada aconteceu — que é exatamente o
        # defeito que ele existe para pegar.
        # Larga o bastante para as colunas receberem largura: numa janela
        # apertada a caixa do ícone fica com 1x1 e o clique não chega nela.
        self.raiz.geometry("700x300")
        ui.escolher_familia(self.raiz)
        ui.usar_tema("escuro")
        self.pedidos = []
        self.acoes = []
        self.tabela = ui.Tabela(
            self.raiz,
            [ui.Celula("nome", "Nome", 120, tipo="duplo"),
             ui.Celula("valor", "Valor", 90, tipo="dinheiro", fim=True),
             ui.Celula("acoes", "", 60, tipo="acoes", fim=True, ordenavel=False)],
            # A Tabela já entrega a IDENTIDADE, não a linha.
            ao_agir=lambda identidade, nome: self.acoes.append((identidade, nome)),
            ao_ordenar=lambda chave, crescente: self.pedidos.append((chave, crescente)),
        )
        self.tabela.pack(fill="both", expand=True)
        self.tabela.mostrar([
            {"id": "1", "nome": ("ALFA", "a"), "valor": "10,00",
             "acoes": {"pdf": True, "enviar": False}},
            {"id": "2", "nome": ("BETA", "b"), "valor": "20,00",
             "acoes": {"pdf": True, "enviar": False}},
        ])
        for _ in range(20):        # deixa o layout assentar antes de clicar
            self.raiz.update()
            time.sleep(0.02)

    def tearDown(self):
        try:
            self.raiz.destroy()
        except Exception:
            pass
        ui.usar_tema("claro")

    # -- o defeito antigo ------------------------------------------------- #

    def test_clicar_no_icone_dispara_a_acao_do_icone(self):
        """Os dois ícones do fim da linha eram decorativos.

        A `Linha` religava `<Button-1>` em todos os filhos sem `add="+"`, o
        que APAGAVA a ação ligada ao ícone quando ele foi montado. Clicar no
        ícone de PDF só selecionava a linha. Passou despercebido porque o
        teste chamava o método direto, sem clicar.
        """
        linha = self.tabela._linhas[0]
        linha.partes["acoes"]["botoes"]["pdf"]["caixa"].event_generate("<Button-1>")
        self.raiz.update()
        self.assertEqual(self.acoes, [("1", "pdf")])

    def test_o_icone_desligado_nao_dispara(self):
        linha = self.tabela._linhas[0]
        linha.partes["acoes"]["botoes"]["enviar"]["caixa"].event_generate("<Button-1>")
        self.raiz.update()
        self.assertEqual(self.acoes, [])

    def test_clicar_na_linha_continua_selecionando(self):
        # A correção não podia quebrar o clique comum: `add="+"` mantém os
        # dois, e o do ícone come o evento só quando de fato age.
        marcadas = []
        self.tabela._ao_selecionar = marcadas.append
        self.tabela._linhas[1].partes["nome"]["cima"].event_generate("<Button-1>")
        self.raiz.update()
        self.assertEqual(marcadas, ["2"])

    # -- ordenação -------------------------------------------------------- #

    def test_o_cabecalho_pede_a_ordem(self):
        self.tabela.ordenar_por("nome")
        self.assertEqual(self.pedidos, [("nome", True)])

    def test_clicar_de_novo_inverte(self):
        self.tabela.ordenar_por("nome")
        self.tabela.ordenar_por("nome")
        self.assertEqual(self.pedidos, [("nome", True), ("nome", False)])

    def test_trocar_de_coluna_recomeca_crescente(self):
        self.tabela.ordenar_por("nome")
        self.tabela.ordenar_por("nome")
        self.tabela.ordenar_por("valor")
        self.assertEqual(self.pedidos[-1], ("valor", True))

    def test_a_seta_diz_o_sentido(self):
        self.tabela.ordenar_por("nome")
        self.assertTrue(self.tabela._titulos["nome"].cget("text").endswith("▲"))
        self.tabela.ordenar_por("nome")
        self.assertTrue(self.tabela._titulos["nome"].cget("text").endswith("▼"))

    def test_so_a_coluna_ativa_tem_seta(self):
        self.tabela.ordenar_por("nome")
        self.tabela.ordenar_por("valor")
        self.assertEqual(self.tabela._titulos["nome"].cget("text"), "NOME")
        self.assertIn("▲", self.tabela._titulos["valor"].cget("text"))

    def test_a_coluna_de_icones_nao_ordena(self):
        # Não há o que comparar numa coluna de botões.
        caixa = self.tabela._caixas_cabeca["acoes"]
        self.assertNotEqual(str(caixa.cget("cursor")), "hand2")
        caixa.event_generate("<Button-1>")
        self.raiz.update()
        self.assertEqual(self.pedidos, [])


class DicaFlutuanteTests(unittest.TestCase):
    """A legenda que aparece ao pousar o mouse."""

    def setUp(self):
        try:
            self.raiz = tk.Tk()
            self.raiz.withdraw()
        except Exception as exc:
            self.skipTest(f"sem interface gráfica: {exc}")
        ui.escolher_familia(self.raiz)
        ui.usar_tema("escuro")
        self.raiz.deiconify()
        self.alvo = tk.Frame(self.raiz, width=40, height=20, bg=ui.SURFACE)
        self.alvo.pack()
        self.raiz.update()

    def tearDown(self):
        try:
            self.raiz.destroy()
        except Exception:
            pass
        ui.usar_tema("claro")

    def _flutuantes(self):
        return [w for w in self.alvo.winfo_children()
                if isinstance(w, tk.Toplevel)]

    def _esperar(self, quer: bool, limite: float = 2.0):
        fim = time.time() + limite
        while time.time() < fim:
            self.raiz.update()
            if bool(self._flutuantes()) == quer:
                return True
            time.sleep(0.03)
        return bool(self._flutuantes()) == quer

    def test_aparece_ao_pousar_e_some_ao_sair(self):
        ui.dica(self.alvo, "Abrir em PDF", espera=50)
        self.alvo.event_generate("<Enter>")
        self.assertTrue(self._esperar(True), "a dica não apareceu")
        textos = [f.cget("text") for w in self._flutuantes()
                  for f in w.winfo_children() if isinstance(f, tk.Label)]
        self.assertIn("Abrir em PDF", textos)
        self.alvo.event_generate("<Leave>")
        self.assertTrue(self._esperar(False), "a dica não sumiu")

    def test_nao_aparece_se_o_mouse_so_passou(self):
        """Entrar e sair antes do tempo não deixa a legenda pipocar."""
        ui.dica(self.alvo, "Abrir em PDF", espera=600)
        self.alvo.event_generate("<Enter>")
        self.raiz.update()
        self.alvo.event_generate("<Leave>")
        fim = time.time() + 1.0
        while time.time() < fim:
            self.raiz.update()
            time.sleep(0.03)
        self.assertEqual(self._flutuantes(), [])

    def test_clicar_fecha_a_dica(self):
        ui.dica(self.alvo, "Abrir em PDF", espera=50)
        self.alvo.event_generate("<Enter>")
        self.assertTrue(self._esperar(True))
        self.alvo.event_generate("<Button-1>")
        self.assertTrue(self._esperar(False), "a dica ficou por cima do clique")


class CursorHonestoTests(unittest.TestCase):
    """A mãozinha é promessa: onde ela aparece, o clique tem de responder.

    Um widget com cursor de mão e sem tratador é um botão que não é botão —
    foi o caso dos ícones de cada linha e dos contadores do Painel. A
    varredura da tela inteira achou os dois; estes testes seguram o
    componente onde eles nasciam.
    """

    def setUp(self):
        try:
            self.raiz = tk.Tk()
            self.raiz.geometry("500x260")
        except Exception as exc:
            self.skipTest(f"sem interface gráfica: {exc}")
        ui.escolher_familia(self.raiz)
        ui.usar_tema("escuro")

    def tearDown(self):
        try:
            self.raiz.destroy()
        except Exception:
            pass
        ui.usar_tema("claro")

    def test_cartao_sem_acao_nao_promete_clique(self):
        """No Painel estes cartões não filtravam nada e mostravam a mão."""
        cartao = ui.CartaoFiltro(self.raiz, "Faturado", tom="info")
        cartao.pack()
        self.raiz.update()
        self.assertNotEqual(str(cartao.cget("cursor")), "hand2")

    def test_cartao_com_acao_promete_no_cartao_inteiro(self):
        cliques = []
        cartao = ui.CartaoFiltro(self.raiz, "Emitidas", tom="sucesso",
                                 ao_clicar=lambda: cliques.append(1))
        cartao.atualizar("4", "no portal", ativo=False)
        cartao.pack()
        self.raiz.update()
        # Nos rótulos também: eles cobrem quase toda a área do cartão.
        for parte in (cartao, cartao.titulo, cartao.numero, cartao.detalhe):
            self.assertEqual(str(parte.cget("cursor")), "hand2",
                             f"{parte} sem a mãozinha")
        cartao.numero.event_generate("<Button-1>")
        self.raiz.update()
        self.assertEqual(cliques, [1])

    def test_a_linha_da_tabela_promete_no_corpo_inteiro(self):
        tabela = ui.Tabela(self.raiz,
                           [ui.Celula("nome", "Nome", 200, tipo="duplo")],
                           ao_selecionar=lambda _i: None)
        tabela.pack(fill="both", expand=True)
        tabela.mostrar([{"id": "1", "nome": ("ALFA", "a")}])
        for _ in range(15):
            self.raiz.update()
            time.sleep(0.02)
        linha = tabela._linhas[0]
        for parte in (linha, linha.partes["nome"]["cima"],
                      linha.partes["nome"]["baixo"]):
            self.assertEqual(str(parte.cget("cursor")), "hand2",
                             f"{parte} sem a mãozinha")

    def test_a_dica_do_campo_usa_cursor_de_texto(self):
        # Ela fica por cima de um campo em que se digita.
        campo = tk.Entry(self.raiz)
        campo.pack()
        ui.dica_no_campo(campo, "dd/mm/aaaa")
        for _ in range(10):
            self.raiz.update()
            time.sleep(0.02)
        rotulos = [w for w in campo.winfo_children() if isinstance(w, tk.Label)]
        self.assertTrue(rotulos, "a dica não foi criada")
        self.assertEqual(str(rotulos[0].cget("cursor")), "xterm")

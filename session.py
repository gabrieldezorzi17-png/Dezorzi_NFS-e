"""Sessão HTTP autenticada no portal — automação sem navegador.

Sem isto, o cookie JSESSIONID tinha de ser copiado do navegador a cada uso e a
emissão falhava assim que a sessão expirava. Aqui o programa faz login por HTTP,
guarda o cookie num cookie jar e renova a sessão sozinho quando ela cai.

Ordem deliberada das operações: **autenticar antes de emitir, nunca depois.**
Se a emissão falhar, o programa não repete o POST — quando não se sabe se o
portal processou a nota, reenviar é como emitir duas. A sessão é conferida
antes, justamente para que a emissão aconteça uma vez só.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

import config
import nfse_client
import portal
import paths

LOGIN_TEMPLATE = paths.CONFIG_DIR / "login_template.json"
CREDENTIAL_VARS = ("NFSE_USUARIO", "NFSE_SENHA")


class PortalSession:
    """Mantém o cookie da sessão e sabe reautenticar quando ele expira."""

    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        cookies = HTTPCookieProcessor(self.jar)
        # Emissão e sondagem não seguem redirect: um 302 é sinal de sessão
        # expirada e precisa ser visível, não seguido em silêncio.
        tls = HTTPSHandler(context=nfse_client.ssl_context())
        self.opener = build_opener(cookies, tls, nfse_client.NoRedirect)
        # O login, ao contrário, costuma redirecionar depois de autenticar.
        self.login_opener = build_opener(cookies, HTTPSHandler(context=nfse_client.ssl_context()))
        self._lock = threading.RLock()
        # Trava da retentativa de login: sem ela, um portal que recusa
        # por senha errada entraria em laço relendo a versão para sempre.
        self._relogado = False

    # ------------------------------------------------------------------ #
    # Configuração
    # ------------------------------------------------------------------ #

    @property
    def configured(self) -> bool:
        return LOGIN_TEMPLATE.exists()

    @property
    def usable(self) -> bool:
        """O login automático só é usado quando dá para executá-lo de fato.

        Com o modelo presente mas as credenciais em branco, insistir no login
        travaria a emissão. Neste caso o programa volta ao cookie do .env, que
        é o caminho manual — funciona, só expira mais rápido.
        """
        return self.configured and not self.missing_credentials()

    def _template(self) -> dict[str, Any]:
        try:
            template = json.loads(LOGIN_TEMPLATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise nfse_client.NfseError(f"login_template.json com JSON inválido: {exc}") from exc
        if not isinstance(template, dict):
            raise nfse_client.NfseError("login_template.json deve ser um objeto JSON")
        return template

    def missing_credentials(self) -> list[str]:
        if not self.configured:
            return []
        raw = LOGIN_TEMPLATE.read_text(encoding="utf-8")
        return [name for name in CREDENTIAL_VARS if f"env:{name}" in raw and not os.getenv(name)]

    def cookie_names(self) -> list[str]:
        return sorted(cookie.name for cookie in self.jar)

    # ------------------------------------------------------------------ #
    # Requisições
    # ------------------------------------------------------------------ #

    def _build(self, spec: dict[str, Any], *, method_default: str) -> dict[str, Any]:
        # O login não tem rascunho: só {{env:...}} é permitido como origem.
        return nfse_client.build_request(
            {"escape": "raw", **spec},
            {},
            method_default=method_default,
            allowed_methods=("GET", "POST", "PUT"),
        )

    def _call(self, request: dict[str, Any], opener: Any) -> tuple[int, str]:
        body = request["body"]
        data = body.encode("utf-8") if body else None
        http_request = Request(
            request["url"],
            data=data,
            headers=request["headers"],
            method=request["method"],
        )
        try:
            with opener.open(http_request, timeout=config.timeout()) as response:
                return response.status, response.read(nfse_client.READ_LIMIT).decode("utf-8", errors="replace")
        except HTTPError as exc:
            return exc.code, exc.read(nfse_client.READ_LIMIT).decode("utf-8", errors="replace")
        except URLError as exc:
            raise nfse_client.NfseError(f"falha de conexão com o portal: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise nfse_client.NfseError(f"falha de comunicação com o portal: {exc}") from exc

    @staticmethod
    def _matches(spec: dict[str, Any], status: int, text: str) -> bool:
        """Confere o resultado contra os critérios do modelo.

        Os critérios também passam por {{env:...}} — a sondagem procura o CCM
        na resposta, e ele mora no .env junto com as demais credenciais.
        """
        expected = spec.get("status") or [200]
        if status not in expected:
            return False
        required = nfse_client.render_text(spec.get("body_contains"))
        if required and required not in text:
            return False
        forbidden = nfse_client.render_text(spec.get("body_not_contains"))
        if forbidden and forbidden in text:
            return False
        return True

    # ------------------------------------------------------------------ #
    # Ciclo de vida da sessão
    # ------------------------------------------------------------------ #

    def consultar(self, spec: dict[str, Any]) -> str:
        """Executa uma chamada de leitura e devolve a resposta inteira.

        Separado de nfse_client.send: aquele é o caminho da emissão, que trunca
        o corpo para o histórico de auditoria. Uma consulta como a lista de
        serviços traz dezenas de KB e a informação útil fica no fim.
        """
        self.ensure()
        status, texto = self._call(self._build(spec, method_default="POST"), self.opener)
        if not 200 <= status < 300:
            raise nfse_client.NfseError(f"o portal respondeu HTTP {status} à consulta")
        return texto

    def probe(self) -> bool:
        """Confere se a sessão ainda vale, sem emitir nada."""
        template = self._template()
        spec = template.get("probe")
        if not isinstance(spec, dict) or not spec.get("url"):
            # Sem sondagem configurada, o melhor sinal disponível é ter cookie.
            return bool(self.cookie_names())
        request = self._build(spec, method_default="GET")
        status, text = self._call(request, self.opener)
        return self._matches(spec, status, text)

    def login(self) -> None:
        # Antes de qualquer coisa: conferir em que versão o portal está. Quando
        # a prefeitura publica versão nova, a identificação gravada deixa de
        # existir e o servidor responde 500 sem dizer por quê — o login
        # simplesmente para, e nada no programa mudou. Ver portal.py.
        try:
            portal.sincronizar()
        except Exception:
            pass    # sem rede, segue com o que estiver configurado

        template = self._template()
        missing = self.missing_credentials()
        if missing:
            raise nfse_client.NfseError(
                f"defina {', '.join(missing)} no .env para o login automático"
            )

        # O portal cria a sessão no primeiro acesso e só depois a autentica:
        # na captura, o POST de login já viajava com um JSESSIONID existente.
        # Sem essa visita inicial, o cookie jar estaria vazio na hora do login.
        bootstrap = template.get("bootstrap")
        if isinstance(bootstrap, dict) and bootstrap.get("url"):
            self._call(self._build(bootstrap, method_default="GET"), self.login_opener)

        request = self._build(template, method_default="POST")
        status, text = self._call(request, self.login_opener)
        success = template.get("success") or {"status": [200, 302]}
        if not self._matches(success, status, text):
            # Uma segunda chance, relendo a versão do portal: o cache tem
            # validade de dias, e a publicação nova pode ter saído hoje.
            if portal.sincronizar(forcar=True) and not self._relogado:
                self._relogado = True
                try:
                    return self.login()
                finally:
                    self._relogado = False
            raise nfse_client.NfseError(
                f"login recusado pelo portal (HTTP {status}). Confira usuário e senha; "
                f"se estiverem certos, o portal pode ter mudado — o programa já "
                f"tentou reler a versão dele (identificação {portal.em_uso()[:8]}…)."
            )
        if not self.cookie_names():
            raise nfse_client.NfseError("o portal não devolveu cookie de sessão no login")

    def ensure(self) -> None:
        """Garante sessão válida antes de qualquer emissão."""
        with self._lock:
            # A identificação e a assinatura do portal precisam estar em mãos
            # aqui, não só no login: quando a sessão já está de pé, o login não
            # roda — e toda consulta (serviços, municípios, tomador) montava o
            # corpo sem a assinatura e falhava. Na tela, isso aparecia como a
            # lista de serviços que "não carrega", sem dizer por quê.
            if not portal.politica_em_uso() or not portal.em_uso():
                try:
                    portal.sincronizar()
                except Exception:
                    pass
            if self.probe():
                return
            self.login()
            if not self.probe():
                raise nfse_client.NfseError(
                    "o login foi aceito mas a sessão não ficou válida; "
                    "capture o fluxo de login novamente"
                )

    def reset(self) -> None:
        self.jar.clear()

    def autenticar(self, usuario: str, senha: str) -> str:
        """Entra no portal com estas credenciais e devolve a razão social.

        A senha fica **só em memória**, no ambiente do processo — nada é
        gravado em disco. Fechar o programa esquece.

        Tudo que dependia da empresa anterior é descartado: cookie, dados do
        prestador e lista de serviços em memória. Sem isso, a primeira nota
        depois da troca sairia com dados de quem estava logado antes.
        """
        usuario = str(usuario).strip()
        senha = str(senha).strip()
        if not usuario or not senha:
            raise nfse_client.NfseError("informe usuário e senha")

        with self._lock:
            os.environ["NFSE_USUARIO"] = usuario
            os.environ["NFSE_SENHA"] = senha
            config.EMPRESA_ATIVA.unlink(missing_ok=True)
            self.reset()

            import prestador
            import recursos
            import tomador

            prestador.esquecer()
            tomador.esquecer()
            recursos.esquecer()

            self.login()
            if not self.probe():
                raise nfse_client.NfseError(
                    "o portal aceitou o login mas a sessão não ficou válida"
                )
            dados = prestador.do_portal(usuario, recarregar=True)
            return dados.get("razao_social") or usuario

    def encerrar(self) -> None:
        """Sai da empresa atual: apaga sessão, credenciais e dados em memória."""
        with self._lock:
            self.reset()
            os.environ.pop("NFSE_SENHA", None)
            import prestador
            import recursos
            import tomador

            prestador.esquecer()
            tomador.esquecer()
            recursos.esquecer()

    def trocar_empresa(self, ccm: str) -> None:
        """Passa a operar como outra empresa.

        O cookie jar é esvaziado de propósito: manter a sessão anterior faria a
        próxima emissão sair pela empresa errada, já que o portal identifica o
        prestador pela sessão.
        """
        with self._lock:
            config.ativar_empresa(ccm)
            self.reset()
            import prestador
            prestador.esquecer()


_session: PortalSession | None = None
_guard = threading.Lock()


def get_session() -> PortalSession:
    global _session
    with _guard:
        if _session is None:
            _session = PortalSession()
        return _session


def status() -> dict[str, Any]:
    portal = get_session()
    return {
        "login_configured": portal.configured,
        "login_usable": portal.usable,
        "missing_credentials": portal.missing_credentials(),
        "cookies": portal.cookie_names(),
    }

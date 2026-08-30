"""Servidor HTTP local que serve a interface web e a API de rascunhos.

O serviço escuta só em 127.0.0.1, mas isso não basta: qualquer página aberta no
navegador consegue disparar POST para localhost. Como um POST aqui pode emitir
nota fiscal, o servidor confere Host e Origin antes de aceitar escrita.
"""
from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import config
import nfse_client
import paths
import service
import storage
import validation

STATIC_FILES = {"/app.js": "app.js", "/styles.css": "styles.css",
                "/marca.svg": "marca.svg", "/tema.js": "tema.js"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def load_env() -> None:
    """Mantido por compatibilidade; a implementação vive em config."""
    config.load_env()
    config.aplicar_empresa_ativa()


def _allowed_hosts() -> set[str]:
    return LOCAL_HOSTS | {os.getenv("HOST", "127.0.0.1").strip().lower()}


class Api(BaseHTTPRequestHandler):
    server_version = "NfseAutomation/1.0"

    # ------------------------------------------------------------------ #
    # Infraestrutura
    # ------------------------------------------------------------------ #

    def log_message(self, fmt: str, *args: Any) -> None:
        # Só método, rota e status. Corpo, tokens e dados fiscais nunca vão ao log.
        route = urlsplit(self.path).path
        status = args[1] if len(args) > 1 else ""
        print(f"{self.address_string()} {self.command} {route} {status}")

    def _send(self, status: int, raw: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'none'",
        )
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass  # navegador fechou a aba no meio da resposta

    def _json(self, status: int, content: dict[str, Any]) -> None:
        self._send(status, json.dumps(content, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._json(404, {"error": "arquivo não encontrado"})
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith(("text/", "application/javascript")):
            content_type = f"{content_type}; charset=utf-8"
        self._send(200, path.read_bytes(), content_type)

    def _body(self) -> dict[str, Any]:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length inválido") from exc
        if size <= 0 or size > 200_000:
            raise ValueError("corpo ausente ou grande demais")
        value = json.loads(self.rfile.read(size))
        if not isinstance(value, dict):
            raise ValueError("o corpo deve ser um objeto JSON")
        return value

    def _same_origin(self) -> bool:
        """Rejeita escrita vinda de outra origem (CSRF / DNS rebinding)."""
        allowed = _allowed_hosts()
        host = urlsplit(f"//{self.headers.get('Host', '')}").hostname
        if host is not None and host.lower() not in allowed:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "null":
            origin_host = urlsplit(origin).hostname
            if origin_host is None or origin_host.lower() not in allowed:
                return False
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return False
        return True

    # ------------------------------------------------------------------ #
    # Rotas
    # ------------------------------------------------------------------ #

    def _route(self) -> str:
        return unquote(urlsplit(self.path).path).rstrip("/") or "/"

    def do_GET(self) -> None:
        self._handle(self._dispatch_get)

    def _dispatch_get(self) -> None:
        route = self._route()
        if route in ("/", "/index.html"):
            self._file(paths.STATIC_DIR / "index.html")
            return
        if route in STATIC_FILES:
            self._file(paths.STATIC_DIR / STATIC_FILES[route])
            return
        if route == "/health":
            self._json(200, {"status": "ok", "live_mode": config.live_mode()})
            return
        if route == "/config":
            self._json(200, service.describe_configuration())
            return
        if route == "/documents":
            self._json(200, {"documents": storage.list_all()})
            return
        # Antes do caso geral de /documents/{id}: senão "abc/pdf-url" seria
        # lido como o id "abc/pdf-url" e devolveria 404.
        if route.startswith("/documents/") and route.endswith("/pdf-url"):
            self._pdf_url(route.removeprefix("/documents/").removesuffix("/pdf-url"))
            return
        if route.startswith("/documents/"):
            self._get_document(route.removeprefix("/documents/"))
            return
        self._json(404, {"error": "rota não encontrada"})

    def _pdf_url(self, document_id: str) -> None:
        """O endereço da nota no visualizador da prefeitura.

        Serve para ver a nota sem baixar nada: a tela abre este endereço numa
        aba, e o navegador atravessa proxy e certificado do Windows — que é
        justamente onde o download automático costuma esbarrar.

        Só existe depois de o portal aceitar a nota: o endereço é montado com
        o número e o código de verificação, que é o que ele devolve.
        """
        import pdf

        item = storage.get(document_id)
        if item is None:
            self._json(404, {"error": "documento não encontrado"})
            return
        nota = item.get("nota") or {}
        endereco = pdf.endereco_no_portal(nota)
        if not endereco:
            self._json(409, {
                "error": "esta nota ainda não tem número e código de verificação",
                "pending": True,
            })
            return
        self._json(200, {"id": document_id, "url": endereco})

    def _get_document(self, document_id: str) -> None:
        item = storage.get(document_id)
        if item is None:
            self._json(404, {"error": "documento não encontrado"})
            return
        self._json(200, item)

    def do_POST(self) -> None:
        if not self._same_origin():
            self._json(403, {"error": "origem não autorizada"})
            return
        self._handle(self._dispatch_post)

    def _dispatch_post(self) -> None:
        route = self._route()
        if route == "/documents":
            self._json(201, service.create_document(self._body()))
            return
        if route.startswith("/documents/") and route.endswith("/submit"):
            self._submit(route.removeprefix("/documents/").removesuffix("/submit"))
            return
        if route.startswith("/documents/") and route.endswith("/preview"):
            self._preview(route.removeprefix("/documents/").removesuffix("/preview"))
            return
        self._json(404, {"error": "rota não encontrada"})

    def _submit(self, document_id: str) -> None:
        item = storage.get(document_id)
        if item is None:
            self._json(404, {"error": "documento não encontrado"})
            return
        outcome = service.submit_document(item)
        status = 200 if outcome["transmitted"] else 409
        self._json(
            status,
            {
                "id": document_id,
                "status": outcome["status"],
                "transmitted": outcome["transmitted"],
                "message": outcome["message"],
                "preview": outcome["preview"],
                "result": outcome["result"],
            },
        )

    def _preview(self, document_id: str) -> None:
        item = storage.get(document_id)
        if item is None:
            self._json(404, {"error": "documento não encontrado"})
            return
        self._json(200, {"id": document_id, "preview": service.dry_run(item["payload"])})

    # ------------------------------------------------------------------ #
    # Erros
    # ------------------------------------------------------------------ #

    def _handle(self, action) -> None:
        """Executa a rota traduzindo cada falha para o status HTTP correto."""
        try:
            action()
        except validation.ValidationError as exc:
            self._json(422, {"error": exc.message, "field": exc.field})
        except service.AlreadySubmitted as exc:
            self._json(409, {"error": str(exc), "already_submitted": True})
        except nfse_client.NfseError as exc:
            self._json(502, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except OSError as exc:
            self._json(500, {"error": f"falha ao acessar o disco: {exc}"})


def main() -> None:
    config.load_env()
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    state = "ATIVO — transmissões reais liberadas" if config.live_mode() else "SEGURO — transmissão bloqueada"
    print(f"Modo de envio: {state}")
    print(f"Servidor em http://{host}:{port}")
    ThreadingHTTPServer((host, port), Api).serve_forever()


if __name__ == "__main__":
    main()

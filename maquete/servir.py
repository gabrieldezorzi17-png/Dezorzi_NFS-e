"""Servidor de preview que declara UTF-8 — só para olhar a maquete."""
import http.server, functools
class ComAcento(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".html": "text/html; charset=utf-8"}
http.server.test(HandlerClass=ComAcento, port=8301, bind="127.0.0.1")

"""Testa login e sessão no portal, sem emitir nota nenhuma.

Execute com: python testar_conexao.py

Este script só faz chamadas de leitura (bootstrap, login e getSession). Ele nunca
chama emitirNfs — dá para rodar quantas vezes quiser sem risco fiscal.
"""
from __future__ import annotations

import sys

import config
import nfse_client
import service
import session


def linha(rotulo: str, valor: object) -> None:
    print(f"  {rotulo:.<32} {valor}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    config.load_env()
    config.aplicar_empresa_ativa()
    estado = service.describe_configuration()
    portal = session.get_session()

    print("\n=== Configuração ===")
    linha("modelo de emissão", "ok" if estado["template_exists"] else "ausente")
    linha("erro no modelo", estado["template_error"] or "nenhum")
    linha("modelo de login", "ok" if estado["login_configured"] else "ausente")
    linha("modo de envio", "ATIVO" if estado["live_mode"] else "SEGURO (não transmite)")
    linha("segredos faltando", ", ".join(estado["missing_secrets"]) or "nenhum")
    linha("credenciais faltando", ", ".join(estado["missing_credentials"]) or "nenhuma")

    if not portal.configured:
        print("\nSem config/login_template.json não há o que testar aqui.")
        return 1
    if portal.missing_credentials():
        print("\nPreencha NFSE_USUARIO e NFSE_SENHA no .env e rode de novo.")
        return 1

    print("\n=== Sessão ===")
    try:
        valida = portal.probe()
    except nfse_client.NfseError as exc:
        print(f"  FALHA na sondagem: {exc}")
        return 1
    linha("sessão já válida?", "sim" if valida else "não (vai tentar login)")

    if not valida:
        print("\n=== Login ===")
        try:
            portal.login()
        except nfse_client.NfseError as exc:
            print(f"  FALHA no login: {exc}")
            print("\n  Confira NFSE_USUARIO/NFSE_SENHA e o bloco 'success' do modelo.")
            return 1
        linha("login aceito", "sim")
        linha("cookies recebidos", ", ".join(portal.cookie_names()) or "nenhum")

        try:
            valida = portal.probe()
        except nfse_client.NfseError as exc:
            print(f"  FALHA na sondagem pós-login: {exc}")
            return 1
        linha("sessão válida após login", "sim" if valida else "NÃO")

    if not valida:
        print("\n  O login passou mas a sondagem não reconheceu a sessão.")
        print("  Ajuste 'probe.body_contains' em config/login_template.json:")
        print("  ele precisa ser um trecho que só aparece na resposta autenticada.")
        return 1

    print("\n=== Requisição de emissão (montada, NÃO enviada) ===")
    import storage

    rascunhos = [d for d in storage.list_all() if d.get("status") == "draft"]
    if not rascunhos:
        print("  Nenhum rascunho para montar. Crie um no aplicativo e rode de novo.")
    else:
        try:
            preview = service.dry_run(rascunhos[0]["payload"])
        except Exception as exc:
            print(f"  FALHA ao montar: {type(exc).__name__}: {exc}")
            return 1
        linha("método", preview["method"])
        linha("url", preview["url"])
        linha("bytes do corpo", preview["body_bytes"])
        print(f"\n  corpo (segredos ocultos):\n  {preview['body_preview'][:300]}...")

    if config.live_mode():
        print("\nTudo pronto. O modo de transmissão está ATIVO: o botão Emitir")
        print("no aplicativo vai gerar nota fiscal de verdade.")
    else:
        print("\nTudo pronto, mas em modo seguro. Para transmitir de verdade,")
        print("defina NFSE_LIVE_MODE=true no .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

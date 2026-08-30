"""Cadastra os dados do prestador da empresa logada.

Execute com: python cadastrar_empresa.py

O portal sugere o que dá para reconhecer com certeza (e-mail, telefone, CEP,
UF, inscrição). Razão social, endereço e bairro **você confirma**, porque
identificá-los na resposta do portal seria adivinhação — e adivinhar razão
social significa emitir nota fiscal com o nome errado.

Feito uma vez por empresa, a emissão passa a ser automática para ela.
"""
from __future__ import annotations

import json
import sys

import config
import nfse_client
import paths
import prestador

ROTULOS = {
    "inscricao": "Inscrição municipal (CCM)",
    "razao_social": "Razão social",
    "nome_fantasia": "Nome fantasia",
    "email": "E-mail",
    "telefone": "Telefone (só dígitos)",
    "logradouro": "Logradouro (como aparece na nota)",
    "numero": "Número",
    "bairro": "Bairro",
    "cep": "CEP (só dígitos)",
    "uf": "UF",
}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    config.load_env()
    ccm = config.aplicar_empresa_ativa()
    if not ccm:
        print("Defina NFSE_USUARIO no .env (ou escolha a empresa no aplicativo).")
        return 1

    empresas = config.empresas()
    nome = (empresas.get(ccm) or {}).get("nome", ccm)
    print(f"\nEmpresa logada: {nome} (CCM {ccm})")

    print("\nConsultando o portal…")
    try:
        sugerido, incertos = prestador.sugerir(ccm)
    except nfse_client.NfseError as exc:
        print(f"  falhou: {exc}")
        print("  Você pode preencher tudo à mão mesmo assim.")
        sugerido, incertos = {"inscricao": ccm}, [c for c in prestador.CAMPOS if c != "inscricao"]

    atual = prestador.cadastrado(ccm)
    print("\nConfirme cada campo (Enter aceita o valor entre colchetes):\n")

    dados: dict[str, str] = {}
    for campo in prestador.CAMPOS:
        padrao = atual.get(campo) or sugerido.get(campo, "")
        origem = ""
        if campo in sugerido and campo not in atual:
            origem = "  ← sugerido pelo portal"
        elif campo in incertos and not padrao:
            origem = "  ← o portal não permite deduzir; confira na nota"
        resposta = input(f"  {ROTULOS[campo]} [{padrao}]{origem}\n    > ").strip()
        valor = resposta or padrao
        if not valor:
            print("    (vazio — este campo é obrigatório)")
            return 1
        dados[campo] = valor

    registro = dict(empresas)
    registro.setdefault(ccm, {})
    registro[ccm] = {"nome": dados["razao_social"], "prestador": dados}
    config.EMPRESAS.parent.mkdir(parents=True, exist_ok=True)
    config.EMPRESAS.write_text(
        json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nGravado em {paths.CONFIG_DIR / 'empresas.json'}.")
    print("A partir de agora as notas desta empresa saem com estes dados.")
    print("\nConfira a primeira emissão no portal antes de emitir em série.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

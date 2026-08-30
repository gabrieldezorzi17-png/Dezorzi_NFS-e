"""Leitura do .env e das chaves de configuração usadas pelo programa."""
from __future__ import annotations

from typing import Any

import json
import os

import paths

PORTAL_URL = "https://nfse.isssbc.com.br/nfseweb/nfse"
PORTAL_HOST = "nfse.isssbc.com.br"

# Segredos que o modelo de requisição pode referenciar como {{env:NOME}}.
SECRET_VARS = ("NFSE_COOKIE", "NFSE_GWT_PERMUTATION", "NFSE_AUTHORIZATION")

_loaded = False


def load_env(*, force: bool = False) -> None:
    """Carrega o .env para o ambiente. Variáveis já definidas têm precedência."""
    global _loaded
    if _loaded and not force:
        return
    _loaded = True
    if not paths.ENV_FILE.exists():
        return
    for number, raw in enumerate(paths.ENV_FILE.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            print(f"[.env] linha {number} ignorada: falta '='")
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in ('"', "'"):
            # Aspas são delimitadores do arquivo, não parte do segredo. O que
            # vier depois do fechamento é comentário.
            fecha = value.find(value[0], 1)
            value = value[1:fecha] if fecha > 0 else value[1:]
        else:
            # Comentário no fim da linha. Sem isto, `NFSE_LIVE_MODE=true # nota`
            # vale "true # nota", que não é "true" — e a transmissão fica
            # desligada sem ninguém entender por quê. A convenção do formato é
            # espaço (ou tabulação) seguido de #, para não cortar um valor que
            # legitimamente contenha o caractere.
            for marcador in (" #", "\t#"):
                if marcador in value:
                    value = value.split(marcador, 1)[0].rstrip()
                    break
        if key:
            os.environ.setdefault(key, value)


def flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


def live_mode() -> bool:
    """True quando a transmissão real ao portal está liberada."""
    return flag("NFSE_LIVE_MODE")


def allowed_host() -> str:
    return os.getenv("NFSE_ALLOWED_HOST", PORTAL_HOST).strip().lower()


# O PDF da nota mora noutro host da mesma prefeitura.
VISUALIZAR_HOST = "visualizar.isssbc.com.br"


def download_hosts() -> set[str]:
    """Hosts autorizados a servir o PDF da nota.

    A emissão continua restrita ao portal; só o download aceita este segundo
    endereço, e ainda assim apenas os declarados aqui.
    """
    extras = os.getenv("NFSE_HOSTS_PDF", VISUALIZAR_HOST)
    return {allowed_host()} | {h.strip().lower() for h in extras.split(",") if h.strip()}


def timeout() -> float:
    try:
        return max(1.0, float(os.getenv("NFSE_TIMEOUT", "30")))
    except ValueError:
        return 30.0


ALIQUOTAS = paths.CONFIG_DIR / "aliquotas.json"
EMPRESAS = paths.CONFIG_DIR / "empresas.json"
EMPRESA_ATIVA = paths.CONFIG_DIR / "empresa_ativa.txt"


def empresas() -> dict[str, dict[str, str]]:
    """Empresas cadastradas, por CCM (que é o próprio usuário do portal).

    O arquivo guarda só o que não é segredo — CCM e nome. **A senha de cada uma
    fica no .env**, em ``NFSE_SENHA_<CCM>``, e nunca é gravada aqui.
    """
    try:
        dados = json.loads(EMPRESAS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    empresas: dict[str, dict[str, Any]] = {}
    for ccm, info in dados.items():
        if not isinstance(info, dict):
            continue
        registro: dict[str, Any] = {"nome": str(info.get("nome", ccm))}
        if isinstance(info.get("prestador"), dict):
            registro["prestador"] = info["prestador"]
        empresas[str(ccm)] = registro
    return empresas


def senha_da_empresa(ccm: str) -> str:
    """Senha desta empresa, de ``NFSE_SENHA_<CCM>`` no .env.

    O ``NFSE_SENHA`` genérico só vale quando há no máximo uma empresa
    cadastrada. Com duas ou mais, cair no genérico significaria tentar entrar
    numa empresa com a senha de outra — o login falharia, mas depois de o
    programa já ter trocado de contexto.
    """
    especifica = os.getenv(f"NFSE_SENHA_{str(ccm).strip()}")
    if especifica and especifica.strip():
        return especifica.strip()
    if len(empresas()) <= 1:
        return (os.getenv("NFSE_SENHA") or "").strip()
    return ""


def empresa_ativa() -> str:
    """CCM da empresa em uso. Sem escolha gravada, vale o NFSE_USUARIO do .env."""
    try:
        gravada = EMPRESA_ATIVA.read_text(encoding="utf-8").strip()
    except OSError:
        gravada = ""
    if gravada and (not empresas() or gravada in empresas()):
        return gravada
    return (os.getenv("NFSE_USUARIO") or "").strip()


def ativar_empresa(ccm: str) -> None:
    """Passa a operar como esta empresa.

    Grava a escolha e ajusta as variáveis que o modelo de login consome, para
    que a próxima autenticação use as credenciais certas.
    """
    ccm = str(ccm).strip()
    senha = senha_da_empresa(ccm)
    if not senha:
        raise ValueError(
            f"defina NFSE_SENHA_{ccm} no .env com a senha desta empresa"
        )
    EMPRESA_ATIVA.parent.mkdir(parents=True, exist_ok=True)
    EMPRESA_ATIVA.write_text(ccm, encoding="utf-8")
    os.environ["NFSE_USUARIO"] = ccm
    os.environ["NFSE_SENHA"] = senha


def aplicar_empresa_ativa() -> str:
    """Coloca as credenciais da empresa ativa no ambiente, se houver cadastro."""
    ccm = empresa_ativa()
    senha = senha_da_empresa(ccm)
    if ccm and senha:
        os.environ["NFSE_USUARIO"] = ccm
        os.environ["NFSE_SENHA"] = senha
    return ccm


def aliquota_padrao() -> str:
    """Alíquota usada quando o código de serviço não tem uma própria."""
    return os.getenv("NFSE_ALIQUOTA", "2").strip() or "2"


def aliquotas_por_codigo() -> dict[str, str]:
    """Alíquota de cada código de serviço, em config/aliquotas.json.

    Cada serviço tem a sua, e emitir com a errada gera nota com imposto errado
    — por isso a alíquota é gravada por código e não adivinhada da lista do
    portal, cujos números não conferiram com a nota realmente emitida.
    """
    try:
        dados = json.loads(ALIQUOTAS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in dados.items() if str(v).strip()}


EXIGE_OBRA = paths.CONFIG_DIR / "exige_obra.json"

# Nenhum item é bloqueado por prefixo. Dentro do mesmo item 7 convivem serviços
# que exigem obra (7.02, 7.06) e serviços que não exigem (7.07) — bloquear o
# item inteiro barraria emissão que funciona. Só entra aqui código com recusa
# registrada pelo portal.
_ITENS_COM_OBRA_PADRAO: list[str] = []


def _regras_obra() -> dict[str, list[str]]:
    try:
        dados = json.loads(EXIGE_OBRA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"itens": list(_ITENS_COM_OBRA_PADRAO), "codigos": []}
    if not isinstance(dados, dict):
        return {"itens": list(_ITENS_COM_OBRA_PADRAO), "codigos": []}
    return {
        "itens": [str(i) for i in dados.get("itens", _ITENS_COM_OBRA_PADRAO)],
        "codigos": [str(c) for c in dados.get("codigos", [])],
    }


def exige_obra(codigo: str) -> bool:
    """O serviço precisa de Código da Obra, que o modelo atual não sabe enviar?

    Existe para transformar uma recusa ambígua em bloqueio limpo. Quando o
    portal recusa por falta da obra, ele às vezes responde "Erro ao processar
    retorno do servidor — consulte se a nota foi emitida", e aí não dá para
    saber se houve nota. Barrar antes de transmitir elimina essa dúvida.
    """
    codigo = str(codigo).strip()
    if not codigo:
        return False
    regras = _regras_obra()
    if codigo in regras["codigos"]:
        return True
    item = codigo.split("/", 1)[0]
    return any(item.startswith(prefixo) for prefixo in regras["itens"])


def marcar_exige_obra(codigo: str) -> None:
    """Registra um código que o portal recusou por falta de obra.

    Assim o erro acontece no máximo uma vez por código: da segunda em diante o
    programa barra antes de transmitir.
    """
    codigo = str(codigo).strip()
    if not codigo or exige_obra(codigo):
        return
    regras = _regras_obra()
    regras["codigos"] = sorted({*regras["codigos"], codigo})
    EXIGE_OBRA.parent.mkdir(parents=True, exist_ok=True)
    EXIGE_OBRA.write_text(
        json.dumps(regras, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def aliquota_do_servico(codigo: str) -> str:
    """Alíquota do código informado; cai no padrão quando não há registro."""
    return aliquotas_por_codigo().get(str(codigo).strip()) or aliquota_padrao()


def aliquota_confirmada(codigo: str) -> bool:
    """True quando a alíquota daquele código foi conferida por uma emissão real.

    Sem isso o programa usaria o padrão em silêncio, e uma alíquota herdada de
    outro serviço sai como imposto errado numa nota fiscal.
    """
    return str(codigo).strip() in aliquotas_por_codigo()


def definir_aliquota(codigo: str, valor: str) -> None:
    tabela = aliquotas_por_codigo()
    tabela[str(codigo).strip()] = str(valor).strip()
    ALIQUOTAS.parent.mkdir(parents=True, exist_ok=True)
    ALIQUOTAS.write_text(json.dumps(tabela, ensure_ascii=False, indent=2), encoding="utf-8")


def response_storage() -> str:
    """Quanto da resposta do portal é gravado em disco: full, excerpt ou none."""
    mode = os.getenv("NFSE_STORE_RESPONSE", "excerpt").strip().lower()
    return mode if mode in ("full", "excerpt", "none") else "excerpt"


def definir_no_env(chave: str, valor: str) -> None:
    """Grava uma chave no .env, preservando o resto do arquivo.

    Reescreve só a linha da chave — comentários, ordem e as demais variáveis
    ficam como estavam. Se a chave não existir, entra no fim.

    A gravação é atômica (arquivo temporário e troca), porque o .env é lido na
    abertura do programa: um arquivo pela metade, depois de uma queda de
    energia, deixaria o programa sem configuração nenhuma.
    """
    linhas = []
    if paths.ENV_FILE.exists():
        linhas = paths.ENV_FILE.read_text(encoding="utf-8-sig").splitlines()

    escrito = False
    for indice, bruta in enumerate(linhas):
        limpa = bruta.strip().removeprefix("export ").lstrip()
        if limpa.startswith("#") or "=" not in limpa:
            continue
        if limpa.split("=", 1)[0].strip() == chave:
            linhas[indice] = f"{chave}={valor}"
            escrito = True
            break
    if not escrito:
        linhas.append(f"{chave}={valor}")

    temporario = paths.ENV_FILE.with_suffix(".env.tmp")
    temporario.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    temporario.replace(paths.ENV_FILE)


def definir_live_mode(ativo: bool) -> None:
    """Liga ou desliga a transmissão real, no arquivo e na sessão em curso.

    Os dois: o .env para a próxima abertura, e ``os.environ`` para valer agora —
    quem acabou de ligar quer emitir esta nota, não reabrir o programa.
    """
    valor = "true" if ativo else "false"
    os.environ["NFSE_LIVE_MODE"] = valor
    definir_no_env("NFSE_LIVE_MODE", valor)


TEMAS = ("claro", "escuro")


def tema() -> str:
    """Claro ou escuro. Vale para a próxima abertura também."""
    escolhido = (os.environ.get("NFSE_TEMA") or "").strip().lower()
    return escolhido if escolhido in TEMAS else "claro"


def definir_tema(nome: str) -> None:
    """Grava a escolha no .env e na sessão em curso."""
    nome = nome if nome in TEMAS else "claro"
    os.environ["NFSE_TEMA"] = nome
    definir_no_env("NFSE_TEMA", nome)


def senha_no_arquivo() -> bool:
    """A senha do portal está gravada no .env?

    O programa nunca a escreve — mas nada impede que ela tenha sido posta ali à
    mão, e a tela de login não pode prometer que a senha "só existe em memória"
    quando o campo veio preenchido do disco. Uma promessa falsa sobre onde mora
    um segredo é pior que nenhuma promessa.
    """
    if not paths.ENV_FILE.exists():
        return False
    try:
        linhas = paths.ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return False
    for bruta in linhas:
        linha = bruta.strip().removeprefix("export ").lstrip()
        if linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        if chave.strip() == "NFSE_SENHA":
            return bool(valor.strip().strip("\"'"))
    return False


def missing_secrets() -> list[str]:
    """Segredos citados no modelo de requisição que ainda não foram preenchidos."""
    if not paths.REQUEST_TEMPLATE.exists():
        return []
    raw = paths.REQUEST_TEMPLATE.read_text(encoding="utf-8")
    return [name for name in SECRET_VARS if f"env:{name}" in raw and not os.getenv(name)]

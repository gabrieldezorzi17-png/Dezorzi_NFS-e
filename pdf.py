"""Baixa o PDF (DANFSe) de uma nota já emitida.

O portal de visualização entrega o PDF em dois passos, e não em um:

1. ``consultarNota`` devolve **HTML** — a tela do visualizador, não o arquivo.
   Dentro dela vem um formulário ``exportar`` com o objeto da nota já
   serializado num campo oculto.
2. O botão "Exportar PDF" faz POST desse formulário em ``exportacao``, e é essa
   resposta que traz o ``%PDF``.

Por isso o segundo passo repete os campos ocultos que vieram do primeiro: eles
são o estado da nota e não há como remontá-los do lado de cá.

Duas diferenças em relação ao resto do programa, ambas deliberadas:

* **Não exige login.** O código de verificação já autoriza a leitura — é o
  mesmo endereço que o tomador usa para conferir a nota. Assim dá para rebaixar
  o PDF de uma nota antiga sem estar logado na empresa que a emitiu.
* **Segue redirect.** O POST de exportação termina noutro endereço (o arquivo
  gerado). Na emissão, seguir redirect esconderia sessão expirada e por isso é
  proibido; aqui, recusá-lo quebraria o download.

O endereço fica em ``config/pdf_template.json`` para que uma mudança de rota da
prefeitura seja edição de arquivo, não de código.
"""
from __future__ import annotations

import html as htmllib
import http.cookiejar
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

import config
import nfse_client
import paths

MODELO = paths.CONFIG_DIR / "pdf_template.json"
DESTINO = paths.DATA_DIR / "pdf"
LIMITE_HTML = 4_000_000
LIMITE_PDF = 30_000_000


class SemModeloPdf(RuntimeError):
    """Falta o modelo com o endereço do PDF no portal."""


def configurado() -> bool:
    return MODELO.exists()


def _modelo() -> dict[str, Any]:
    if not MODELO.exists():
        raise SemModeloPdf(
            "falta config/pdf_template.json com o endereço do PDF no portal.\n\n"
            "Copie config/pdf_template.example.json por cima dele."
        )
    try:
        dados = json.loads(MODELO.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SemModeloPdf(f"pdf_template.json com JSON inválido: {exc}") from exc
    if not isinstance(dados, dict) or not dados.get("url"):
        raise SemModeloPdf("pdf_template.json precisa da chave 'url'")
    return dados


def _contexto(nota: dict[str, str], modelo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dados disponíveis aos marcadores do modelo.

    O prestador só é buscado se o modelo realmente citar ``{{prestador.…}}``.
    O endereço do PDF em São Bernardo não cita: número e código de verificação
    bastam. Buscá-lo assim mesmo custava uma ida ao portal por download — e,
    pior, fazia o download depender da sessão, que tem trava própria: com o
    login ocupado, a janela ficava em "Buscando o PDF no portal…" sem fim,
    porque essa espera não tem tempo limite.
    """
    emitente: dict[str, Any] = {"inscricao": os.getenv("NFSE_USUARIO", "")}
    if modelo is not None and "prestador." in json.dumps(modelo, ensure_ascii=False):
        try:
            import prestador

            emitente = prestador.do_portal() or emitente
        except Exception:
            pass
    return {
        "numero": str(nota.get("numero", "")),
        "codigo_verificacao": str(nota.get("codigo_verificacao", "")),
        "relatorio": os.getenv("NFSE_PDF_RELATORIO", "nfs_ver4RT2"),
        "prestador": emitente,
    }


def _nome_do_arquivo(nota: dict[str, str]) -> str:
    numero = re.sub(r"\W", "", str(nota.get("numero", ""))) or "sem-numero"
    codigo = re.sub(r"\W", "", str(nota.get("codigo_verificacao", "")))
    return f"nfse-{numero}{'-' + codigo if codigo else ''}.pdf"


def _opener():
    """Opener próprio: segue redirect e guarda cookies só deste download."""
    return build_opener(
        HTTPCookieProcessor(http.cookiejar.CookieJar()),
        HTTPSHandler(context=nfse_client.ssl_context()),
    )


def _abrir(opener, url: str, *, dados: bytes | None, cabecalhos: dict[str, str], limite: int):
    pedido = Request(url, data=dados, headers=cabecalhos, method="POST" if dados else "GET")
    try:
        with opener.open(pedido, timeout=config.timeout()) as resposta:
            return resposta.read(limite), resposta.headers.get("Content-Type", "")
    except HTTPError as exc:
        raise nfse_client.NfseError(
            f"o portal de visualização respondeu HTTP {exc.code} ao pedir o PDF"
        ) from exc
    except URLError as exc:
        raise nfse_client.NfseError(f"falha de conexão ao baixar o PDF: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise nfse_client.NfseError(f"falha ao baixar o PDF: {exc}") from exc


def extrair_formulario(html: str, nome: str = "exportar") -> tuple[str, dict[str, str]]:
    """Lê a ação e os campos ocultos do formulário de exportação.

    Os campos são copiados em vez de reconstruídos porque um deles carrega a
    nota inteira serializada pelo servidor — remontá-la aqui seria adivinhação.
    """
    marcado = re.search(
        rf"<form[^>]*name=[\"']?{re.escape(nome)}[\"']?[^>]*>(.*?)</form>",
        html,
        re.S | re.I,
    )
    if not marcado:
        raise nfse_client.NfseError(
            "a página da nota não trouxe o formulário de exportação. "
            "Confira se o número e o código de verificação estão corretos."
        )
    inteiro = marcado.group(0)
    acao = re.search(r"<form[^>]*\saction=[\"']([^\"']*)[\"']", inteiro, re.I)
    campos: dict[str, str] = {}
    for tag in re.findall(r"<input[^>]*>", marcado.group(1), re.I):
        chave = re.search(r"\sname=[\"']?([^\"'\s>]+)", tag, re.I)
        if not chave:
            continue
        valor = re.search(r"\svalue=[\"']([^\"']*)[\"']", tag, re.I)
        campos[htmllib.unescape(chave.group(1))] = (
            htmllib.unescape(valor.group(1)) if valor else ""
        )
    return (acao.group(1) if acao else ""), campos


def endereco_no_portal(nota: dict[str, str]) -> str:
    """O endereço da nota no visualizador da prefeitura.

    Serve de saída quando o download automático não funciona — em rede de
    empresa é comum o programa não alcançar este segundo endereço enquanto o
    navegador alcança, porque ele usa o proxy e os certificados do Windows.
    Abrindo ali, dá para ver, salvar e imprimir a nota do mesmo jeito.
    """
    numero = str(nota.get("numero", "")).strip()
    codigo = str(nota.get("codigo_verificacao", "")).strip()
    if not numero or not codigo:
        return ""
    modelo = _modelo()
    endereco = nfse_client.build_request(
        {"escape": "url", "method": "GET",
         **{k: v for k, v in modelo.items() if k != "exportacao"}},
        _contexto(nota, modelo),
        method_default="GET",
        allowed_methods=("GET", "POST"),
        hosts=config.download_hosts(),
    )["url"]
    return endereco


def baixar(nota: dict[str, str], progresso: Any = None) -> Path:
    """Busca o PDF da nota e grava em data/pdf. Devolve o caminho.

    ``progresso`` recebe uma frase por etapa — o download tem dois passos e
    alguns segundos; sem sinal de vida, parece travado.
    """
    avisar = progresso if callable(progresso) else (lambda _texto: None)

    numero = str(nota.get("numero", "")).strip()
    codigo = str(nota.get("codigo_verificacao", "")).strip()
    if not numero or not codigo:
        raise SemModeloPdf(
            "esta nota não tem número e código de verificação registrados; "
            "não dá para localizar o PDF no portal"
        )

    modelo = _modelo()
    hosts = config.download_hosts()
    contexto = _contexto(nota, modelo)
    avisar(f"Abrindo a nota nº {numero} no portal de visualização…")

    # Passo 1 — a tela do visualizador.
    visualizador = nfse_client.build_request(
        {"escape": "url", "method": "GET", **{k: v for k, v in modelo.items() if k != "exportacao"}},
        contexto,
        method_default="GET",
        allowed_methods=("GET", "POST"),
        hosts=hosts,
    )
    opener = _opener()
    bruto, _ = _abrir(
        opener,
        visualizador["url"],
        dados=visualizador["body"].encode("utf-8") if visualizador.get("body") else None,
        cabecalhos=visualizador["headers"],
        limite=LIMITE_HTML,
    )
    if bruto.startswith(b"%PDF"):  # se um dia a rota passar a devolver o arquivo direto
        return _gravar(nota, bruto)

    html = bruto.decode("iso-8859-1", errors="replace")
    avisar("Gerando o PDF (Exportar PDF)…")

    # Passo 2 — o POST que o botão "Exportar PDF" faz.
    exportacao = modelo.get("exportacao") if isinstance(modelo.get("exportacao"), dict) else {}
    acao, campos = extrair_formulario(html, str(exportacao.get("formulario") or "exportar"))
    destino = urljoin(visualizador["url"], acao) if acao else str(exportacao.get("url") or "")
    if not destino:
        raise nfse_client.NfseError("o formulário de exportação não informou para onde enviar")
    # A página é conteúdo lido do portal, não instrução: o endereço que ela
    # aponta só é aceito se estiver na lista de hosts autorizados.
    nfse_client.check_url(destino, hosts)

    extras = exportacao.get("campos")
    campos.update({str(k): str(v) for k, v in extras.items()} if isinstance(extras, dict) else {})
    campos.setdefault("imprime", "0")
    campos.setdefault("tipo", "pdf")

    cabecalhos = dict(visualizador["headers"])
    cabecalhos["Content-Type"] = "application/x-www-form-urlencoded"
    cabecalhos["Referer"] = visualizador["url"]
    conteudo, tipo = _abrir(
        opener,
        destino,
        dados=urlencode(campos).encode("utf-8"),
        cabecalhos=cabecalhos,
        limite=LIMITE_PDF,
    )

    avisar("Gravando o arquivo…")
    if not conteudo.startswith(b"%PDF"):
        trecho = re.sub(r"<[^>]+>", " ", conteudo[:600].decode("iso-8859-1", errors="replace"))
        raise nfse_client.NfseError(
            f"o portal não devolveu um PDF (Content-Type: {tipo or 'desconhecido'}).\n\n"
            f"{' '.join(trecho.split())[:300]}"
        )
    return _gravar(nota, conteudo)


def _gravar(nota: dict[str, str], conteudo: bytes) -> Path:
    DESTINO.mkdir(parents=True, exist_ok=True)
    caminho = DESTINO / _nome_do_arquivo(nota)
    temporario = caminho.with_suffix(".pdf.tmp")
    temporario.write_bytes(conteudo)
    os.replace(temporario, caminho)
    return caminho


def ja_baixado(nota: dict[str, str]) -> Path | None:
    """O PDF desta nota já está gravado? Devolve o caminho, ou ``None``.

    Buscar de novo no portal o que já se tem custa alguns segundos e depende
    da rede — e o portal é justamente a parte que às vezes não responde. Vale
    principalmente para as notas antigas, cujo PDF ficou guardado.

    Confere os quatro primeiros bytes: um arquivo truncado por um download
    interrompido abriria no leitor como documento corrompido, o que é pior
    que baixar de novo.
    """
    numero = str(nota.get("numero", "")).strip()
    codigo = str(nota.get("codigo_verificacao", "")).strip()
    if not numero or not codigo:
        return None
    caminho = DESTINO / _nome_do_arquivo(nota)
    try:
        with open(caminho, "rb") as arquivo:
            if arquivo.read(4) == b"%PDF":
                return caminho
    except OSError:
        return None
    return None


def abrir(caminho: Any) -> None:
    """Abre o PDF no visualizador padrão do sistema."""
    os.startfile(str(caminho))  # noqa: S606 - Windows; é o app do próprio usuário

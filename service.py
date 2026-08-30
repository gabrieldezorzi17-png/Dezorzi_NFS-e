"""Regra de negócio da emissão — fonte única para o servidor e o desktop.

Antes, servidor e desktop tinham cópias da mesma lógica de envio, e só uma das
duas checava se a nota já havia sido transmitida. O resultado era emissão
duplicada pela interface web. Toda decisão sobre emitir mora aqui.
"""
from __future__ import annotations

import threading
from typing import Any

import config
import nfse_client
import paths
import session
import storage
import validation

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(document_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(document_id, threading.Lock())


class AlreadySubmitted(RuntimeError):
    """A nota já foi transmitida — emitir de novo geraria duplicidade."""


class ObraObrigatoria(RuntimeError):
    """O serviço exige Código da Obra e o modelo atual não sabe enviá-lo."""


class PrestadorIncompleto(RuntimeError):
    """Os dados lidos da sessão não servem para emitir."""


def _barrar_prestador_suspeito() -> None:
    """Confere o prestador lido do portal antes de montar a nota.

    O portal aceita a requisição e só então estoura, respondendo "Erro ao
    processar retorno do servidor na emissão da NFS-e. Consulte se a nota foi
    emitida." Nesse ponto já não se sabe se houve nota, e tanto repetir quanto
    desistir é arriscado. Conferir antes é o que evita chegar lá.
    """
    import prestador

    try:
        dados = prestador.do_portal()
    except nfse_client.NfseError:
        return  # sem sessão, quem reclama é o caminho normal de login
    problemas = prestador.conferir(dados)
    if not problemas:
        return
    raise PrestadorIncompleto(
        "Os dados da empresa lidos do portal não estão consistentes:\n\n• "
        + "\n• ".join(problemas)
        + "\n\nNada foi transmitido. Confira o endereço no cadastro do portal "
        "(Configurações mostra o que foi lido)."
    )


def _barrar_se_exige_obra(payload: dict[str, Any]) -> None:
    """Recusa antes de transmitir os serviços que pedem Código da Obra.

    Deixar seguir produzia o pior desfecho possível: o portal responde "Erro ao
    processar retorno do servidor na emissão da NFS-e. Consulte se a nota foi
    emitida", e a partir daí ninguém sabe se existe nota. Tentar de novo pode
    duplicar; não tentar pode deixar de emitir. Barrar aqui é a única saída sem
    ambiguidade.
    """
    servico = payload.get("servico") or {}
    codigo = str(servico.get("codigo", "")).strip()
    if not config.exige_obra(codigo):
        return

    obra = str(servico.get("obra", "")).strip()
    if not obra:
        raise ObraObrigatoria(
            f"O serviço {codigo} exige Código da Obra e nenhum foi informado.\n\n"
            f"Nada foi transmitido."
        )

    # A obra foi informada, mas o modelo precisa saber em que campo do corpo
    # ela entra. A captura veio de uma emissão de 14.05, que não usa obra —
    # essa posição não existe no corpo e não pode ser deduzida. Chutá-la
    # produziria nota com o valor no campo errado.
    import templates

    try:
        modelo = templates.escolher(payload)
    except Exception:
        modelo = {}
    if not isinstance(modelo.get("servico_obra"), dict):
        raise ObraObrigatoria(
            f"O serviço {codigo} exige Código da Obra, e o modelo ainda não sabe "
            f"em que campo do corpo essa informação entra.\n\n"
            f"Nada foi transmitido — a obra ({obra}) ficou guardada no rascunho.\n\n"
            f"Para liberar: emita uma nota deste serviço pelo portal, capture a "
            f"chamada emitirNfs (F12 → Rede → Copiar como cURL) e me mande."
        )


def create_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Valida e grava um rascunho. Levanta ValidationError se algo estiver errado."""
    return storage.create(validation.validate_payload(payload))


def submit_document(item: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Monta e transmite a nota, no máximo uma vez.

    Em modo seguro (NFSE_LIVE_MODE diferente de true) devolve a requisição
    preparada, sem tocar na rede. Nunca faz retentativa automática: repetir uma
    emissão é decisão do usuário.
    """
    document_id = str(item.get("id", ""))
    with _lock_for(document_id):
        current = storage.get(document_id) or item
        if current.get("status") == "submitted" and not force:
            raise AlreadySubmitted(
                f"a nota {document_id[:8]} já foi transmitida em "
                f"{current.get('last_submission', {}).get('at', 'data desconhecida')}"
            )

        payload = validation.validate_payload(current["payload"])
        if payload != current["payload"]:
            current["payload"] = payload
            storage.save(current)

        # Antes de montar qualquer coisa: duas recusas que evitam o desfecho
        # ambíguo em que o portal responde "consulte se a nota foi emitida".
        _barrar_se_exige_obra(payload)
        if config.live_mode():
            _barrar_prestador_suspeito()

        portal = session.get_session()
        # A versão do portal é conferida ANTES de montar o corpo. A assinatura
        # do serviço entra dentro da requisição; montada antes da conferência,
        # a nota sairia assinada com a versão velha — e o servidor responde a
        # isso com HTTP 500 "The call failed on the server", sem dizer o motivo.
        import portal as versao_do_portal
        try:
            versao_do_portal.sincronizar()
        except Exception:
            pass      # sem rede, vale o que estiver configurado

        request = nfse_client.build(payload, session_active=portal.usable)
        preview = nfse_client.safe_preview(request)

        if not config.live_mode():
            return {
                "transmitted": False,
                "status": current.get("status", "draft"),
                # A instrução aponta para a tela, não para o arquivo: numa
                # máquina onde o programa chegou como executável, "edite o .env"
                # é conselho que não se cumpre.
                "message": (
                    "Modo seguro: a requisição foi montada e validada, mas não foi enviada. "
                    "Para transmitir de verdade, vá em Configurações e clique em "
                    "“Ativar transmissão”."
                ),
                "preview": preview,
                "result": None,
                "document": current,
            }

        # Autenticação acontece ANTES da emissão. Se a sessão estiver caída, o
        # login renova aqui; depois do POST não há retentativa, porque não dá
        # para saber se o portal chegou a processar a nota.
        opener = None
        if portal.usable:
            portal.ensure()
            opener = portal.opener

        result = nfse_client.send(request, opener)
        http = int(result.get("http_status", 0))

        # HTTP 200 não significa nota emitida: o portal recusa dentro de um
        # //OK e explica o motivo na ListaMensagemRetorno.
        aceita, mensagens = nfse_client.avaliar_resposta(result.get("response", ""))
        status = "submitted" if 200 <= http < 300 and aceita else "failed"

        # O portal acabou de ensinar que este código pede obra: anota, para que
        # a próxima tentativa seja barrada antes de ir à rede.
        if not aceita and any("obra" in str(m).lower() for m in mensagens):
            config.marcar_exige_obra(str((payload.get("servico") or {}).get("codigo", "")))

        result["portal_aceitou"] = aceita
        if mensagens:
            result["portal_mensagens"] = mensagens

        identificacao = {}
        if aceita:
            identificacao = nfse_client.identificar_nota(result.get("response", ""))
            if identificacao:
                result["nota"] = identificacao
                current["nota"] = identificacao

        record = {"request": preview, **result}
        document = storage.record_submission(current, record, status)
        if status == "submitted":
            numero = identificacao.get("numero")
            message = (
                f"NFS-e nº {numero} emitida."
                if numero
                else f"Nota emitida. Portal respondeu HTTP {http}."
            )
        elif mensagens:
            # O status HTTP entra junto: recusa de regra e queda de sessão dão
            # mensagens parecidas, e o status separa uma da outra na hora.
            message = ("O portal recusou a nota (HTTP {}):\n\n• ".format(http)
                       + "\n• ".join(mensagens))
        else:
            message = f"Falha na emissão: HTTP {http}."
        return {
            "transmitted": True,
            "status": status,
            "message": message,
            "preview": preview,
            "result": result,
            "document": document,
        }


def describe_configuration() -> dict[str, Any]:
    """Diagnóstico do que ainda falta para conseguir emitir."""
    # O modelo pode vir de dois lugares: o request_template.json antigo, de uma
    # captura só, ou a pasta config/templates com um modelo por caso. Conferir
    # apenas o primeiro fazia o painel anunciar "modelo ausente" com a emissão
    # funcionando pela pasta — alarme falso, e alarme falso ensina a ignorar.
    import templates

    modelos = templates.carregar()
    template_exists = paths.REQUEST_TEMPLATE.exists() or bool(modelos)
    login = session.status()
    missing = config.missing_secrets()
    if login["login_usable"]:
        # Com login automático o cookie vem do cookie jar, não do .env.
        missing = [name for name in missing if name != "NFSE_COOKIE"]
    pending: list[str] = []
    if not template_exists:
        pending.append("Gerar config/request_template.json (python import_curl.py emitir.txt)")
    if not login["login_configured"]:
        pending.append(
            "Opcional para automação 100% HTTP: gerar config/login_template.json "
            "(python import_curl.py login.txt --login)"
        )
    if login["missing_credentials"]:
        pending.append(f"Preencher no .env: {', '.join(login['missing_credentials'])}")
    if missing:
        pending.append(f"Preencher no .env: {', '.join(missing)}")
    if not config.live_mode():
        pending.append("Definir NFSE_LIVE_MODE=true quando a integração estiver validada")

    template_error = ""
    if paths.REQUEST_TEMPLATE.exists():
        # Só o modelo único passa por aqui; os da pasta são validados um a um
        # em templates.carregar(), que descarta o quebrado sem derrubar o resto.
        try:
            nfse_client.load_template()
        except nfse_client.NfseError as exc:
            template_error = str(exc)

    defaults = template_defaults()
    return {
        "portal": config.PORTAL_URL,
        "live_mode": config.live_mode(),
        "aliquota": config.aliquota_padrao(),
        "codigo_servico": defaults.get("servico.codigo", ""),
        "documento_tomador": defaults.get("tomador.documento", ""),
        "template_exists": template_exists,
        "template_error": template_error,
        "templates": [str(modelo.get("_nome", "")) for modelo in modelos],
        "placeholders": nfse_client.placeholders(),
        "missing_secrets": missing,
        "response_storage": config.response_storage(),
        "data_dir": str(paths.DATA_DIR),
        "corrupted_files": storage.corrupted(),
        "login_configured": login["login_configured"],
        "missing_credentials": login["missing_credentials"],
        "pending": pending,
        "ready": template_exists and not missing and not template_error,
    }


def template_defaults() -> dict[str, str]:
    """O que o modelo capturado já fixa — usado para pré-preencher o formulário."""
    try:
        template = nfse_client.load_template()
    except nfse_client.NfseError:
        return {}
    fixed = template.get("fixed")
    return {str(k): str(v) for k, v in fixed.items()} if isinstance(fixed, dict) else {}


def dry_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Monta a requisição sem enviar — usado pelo botão 'Testar configuração'."""
    request = nfse_client.build(
        validation.validate_payload(payload),
        session_active=session.get_session().usable,
    )
    return nfse_client.safe_preview(request)

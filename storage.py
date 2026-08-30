"""Armazenamento local dos rascunhos e do histórico de transmissões.

Duas garantias que um arquivo fiscal precisa ter:

* escrita atômica — uma queda de energia no meio do save não pode deixar um
  JSON pela metade, porque isso derrubava a listagem inteira do programa;
* histórico append-only — cada tentativa de envio vira um registro novo, nunca
  sobrescreve a anterior. É a trilha de auditoria da nota.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paths

MAX_SUBMISSIONS = 50
_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_write_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(document_id: str) -> Path:
    if not _ID.match(str(document_id or "").strip().lower()):
        raise ValueError("id de documento inválido")
    return paths.DATA_DIR / f"{document_id}.json"


def _write_atomic(path: Path, item: dict[str, Any]) -> None:
    """Grava num temporário no mesmo diretório e troca — os.replace é atômico."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(item, ensure_ascii=False, indent=2)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with _write_lock:
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def create(payload: dict[str, Any]) -> dict[str, Any]:
    item = {
        "id": str(uuid.uuid4()),
        "status": "draft",
        "created_at": _now(),
        "updated_at": _now(),
        "payload": payload,
        "submissions": [],
    }
    _write_atomic(_path(item["id"]), item)
    return item


def get(document_id: str) -> dict[str, Any] | None:
    path = _path(document_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"arquivo da nota está corrompido: {path.name}") from exc


def save(item: dict[str, Any]) -> dict[str, Any]:
    item["updated_at"] = _now()
    _write_atomic(_path(item["id"]), item)
    return item


def record_submission(item: dict[str, Any], record: dict[str, Any], status: str) -> dict[str, Any]:
    """Acrescenta uma tentativa ao histórico e persiste, sem apagar as anteriores."""
    with _write_lock:
        history = item.get("submissions")
        if not isinstance(history, list):
            history = []
        entry = {"at": _now(), **record}
        history.append(entry)
        item["submissions"] = history[-MAX_SUBMISSIONS:]
        item["last_submission"] = entry
        item["status"] = status
        return save(item)


def list_all() -> list[dict[str, Any]]:
    """Lista as notas. Um arquivo ilegível é pulado, não derruba a listagem."""
    if not paths.DATA_DIR.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(paths.DATA_DIR.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"[storage] ignorando {path.name}: {exc}")
            continue
        if isinstance(item, dict) and item.get("id"):
            items.append(item)
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


LIXEIRA = "lixeira"


def descartar(document_id: str) -> Path:
    """Tira a nota da lista, guardando o arquivo em data/lixeira.

    Não apaga de verdade, e isso é deliberado: uma nota já emitida é registro
    fiscal, e a lista ficar limpa não pode significar a prova sumir. Excluir
    aqui some da tela; esvaziar a lixeira é um ato manual, fora do programa.

    A lixeira é subpasta de data/, e ``list_all`` varre só o primeiro nível —
    por isso o arquivo movido some da listagem sem nenhum filtro extra.
    """
    origem = _path(document_id)
    if not origem.exists():
        raise FileNotFoundError(f"a nota {document_id} não existe mais")
    destino_dir = paths.DATA_DIR / LIXEIRA
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / origem.name
    # Descartar duas vezes o mesmo id não pode estourar por nome repetido.
    contador = 1
    while destino.exists():
        destino = destino_dir / f"{origem.stem}.{contador}.json"
        contador += 1
    with _write_lock:
        os.replace(origem, destino)
    return destino


def descartar_muitos(ids: list[str]) -> tuple[int, list[str]]:
    """Descarta vários. Devolve quantos saíram e os erros encontrados."""
    saidas, erros = 0, []
    for document_id in ids:
        try:
            descartar(document_id)
        except (OSError, ValueError) as exc:
            erros.append(f"{str(document_id)[:8]}: {exc}")
        else:
            saidas += 1
    return saidas, erros


def corrupted() -> list[str]:
    """Nomes dos arquivos que list_all() não conseguiu ler."""
    if not paths.DATA_DIR.exists():
        return []
    broken = []
    for path in sorted(paths.DATA_DIR.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            broken.append(path.name)
    return broken

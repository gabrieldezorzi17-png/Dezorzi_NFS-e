"""Gera o executável do programa em ``executavel/``.

    python empacotar.py              pasta com o .exe e os arquivos ao lado
    python empacotar.py --instalador o que se publica: um .exe que instala
                                    a versão em pasta e cria o atalho
    python empacotar.py --unico      um único .exe, que se instala ao abrir
    python empacotar.py --seguro     sai em modo seguro (não transmite)

QUAL DOS DOIS FORMATOS
----------------------
**Pasta** é o formato de trabalho. Abre na hora, e o ``config/`` e o ``data/``
ficam à vista ao lado do programa, onde podem ser abertos e copiados.

**Arquivo único** é o formato de entregar: um .exe só, que se copia por e-mail
ou pendrive. Em troca, abre mais devagar — ele descompacta o programa inteiro a
cada execução — e é o formato que antivírus mais estranha. Ao abrir pela
primeira vez, ele cria o ``config/`` e o ``data/`` ao lado de si; a partir daí
os dois formatos são a mesma coisa.

A SEMENTE
---------
Os dois partem da mesma pasta ``build/semente``: os arquivos de configuração já
limpos, com o .env sem senha. No formato pasta ela é copiada para o lado do
.exe; no formato único ela viaja dentro dele. Assim não há dois caminhos
diferentes para o mesmo conteúdo — que é como um deles fica para trás.

A senha nunca vai junto: é digitada na tela de entrada e vive só na memória.
A pasta pode ir para um pendrive, e a senha iria com ela.
"""
from __future__ import annotations

import json
import os
import shutil
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SAIDA = BASE / "executavel"
TRABALHO = BASE / "build"
SEMENTE = TRABALHO / "semente"
NOME = "Dezorzi NFS-e"

# O que o programa lê e grava, e que precisa existir ao lado dele.
PASTAS = ("config", "static", "assets")

# Nem tudo que está em config/ deve ser distribuído: empresa ativa e cadastro de
# empresas são desta máquina e não dizem respeito a outra.
DESCARTAR = ("empresa_ativa.txt", "empresas.json")

# Caches por inscrição municipal — `servicos_304838.json`, `obras_285504.json`.
# São a lista de serviços e as obras dos clientes DESTA máquina: identificam
# quem usa o programa, e não servem para mais ninguém. O programa os reconstrói
# no primeiro login, consultando o portal com o usuário de quem abriu.
POR_INSCRICAO = re.compile(r"^(servicos|obras)_\d+\.json$")

# Módulos que o programa importa por nome; sem isto o PyInstaller não os
# enxerga e o .exe estoura na primeira tela.
MODULOS = (
    "cep", "instalacao", "marca", "municipios", "obras", "recursos",
    "impressao", "pdf", "prestador", "tomador", "services", "templates",
    "storage", "session", "service", "validation", "config", "paths", "ui",
    "portal", "reforma", "registro", "updater",
    # Só é chamado por `--desinstalar`, então o PyInstaller não o vê seguindo
    # os imports do topo — e sem ele "Aplicativos instalados" abriria um
    # programa que não sabe se remover.
    "desinstalar", "instalador",
)


def limpar() -> None:
    for pasta in (SAIDA, TRABALHO):
        if pasta.exists():
            shutil.rmtree(pasta)
    spec = BASE / f"{NOME}.spec"
    if spec.exists():
        spec.unlink()


def preparar_semente(*, seguro: bool) -> Path:
    """Monta os arquivos de configuração já prontos para distribuir."""
    SEMENTE.mkdir(parents=True, exist_ok=True)
    for nome in PASTAS:
        origem = BASE / nome
        if not origem.exists():
            continue
        alvo = SEMENTE / nome
        shutil.copytree(origem, alvo, dirs_exist_ok=True)
        for lixo in DESCARTAR:
            (alvo / lixo).unlink(missing_ok=True)
        for arquivo in list(alvo.glob("*.json")):
            if POR_INSCRICAO.match(arquivo.name):
                arquivo.unlink()

    # O .env sai sem a senha, e o comentário vai na linha de cima — nunca ao
    # lado do valor: `NFSE_LIVE_MODE=true # nota` já foi lido como o texto
    # inteiro, e a transmissão ficou desligada sem ninguém entender por quê.
    modo = "false" if seguro else "true"
    # Na nuvem não existe `.env` — ele é justamente o que não se versiona.
    # `.env.example` traz as mesmas chaves e é o ponto de partida de lá.
    origem_env = BASE / ".env"
    if not origem_env.exists():
        origem_env = BASE / ".env.example"
        print(f"sem .env: partindo de {origem_env.name}")
    linhas: list[str] = []
    for linha in origem_env.read_text(encoding="utf-8").splitlines():
        chave = linha.split("=", 1)[0].strip().upper()
        if chave == "NFSE_SENHA":
            linhas.append("# NFSE_SENHA fica de fora de propósito — digite na tela de entrada.")
        elif chave == "NFSE_LIVE_MODE":
            linhas.append("# Troque também por Configurações, dentro do programa.")
            linhas.append(f"NFSE_LIVE_MODE={modo}")
        else:
            linhas.append(linha)
    (SEMENTE / ".env").write_text("\n".join(linhas) + "\n", encoding="utf-8")

    shutil.copy2(BASE / "assets" / "LEIA-ME.txt", SEMENTE / "LEIA-ME.txt")
    shutil.copy2(BASE / "assets" / "COMO-USAR.txt", SEMENTE / "COMO USAR.txt")
    return SEMENTE


# Dados que entram no pacote e nunca são abertos. Cada um é um arquivo a menos
# para descompactar toda vez que o programa abre — e no arquivo único isso é o
# custo da abertura inteira.
#
# `tzdata` é a tabela de fusos horários do Tcl: uma linha por cidade do mundo,
# 609 arquivos, para o comando `clock` do Tcl com nome de fuso. As datas deste
# programa são todas do `datetime` do Python.
DADOS_INUTEIS = ("_tcl_data/tzdata",)

# O gerador de .spec não conhece estas: são opções de compilação, não de
# receita. Passá-las ali é erro de linha de comando.
SO_NA_COMPILACAO = {"--noconfirm"}
SO_NA_COMPILACAO_COM_VALOR = {"--distpath", "--workpath"}

PENEIRA = """
# --- acrescentado por empacotar.py -------------------------------------- #
# Tira do pacote o que nunca e aberto. Ver DADOS_INUTEIS la.
_fora = {fora}
a.datas = [_item for _item in a.datas
           if not str(_item[0]).replace(chr(92), "/").startswith(_fora)]
# ------------------------------------------------------------------------ #
"""


def _receita(comando: list[str]) -> list[str]:
    """A mesma linha de comando, sem o que só vale na hora de compilar."""
    limpa: list[str] = []
    pular = False
    for parte in comando:
        if pular:
            pular = False
            continue
        if parte in SO_NA_COMPILACAO:
            continue
        if parte in SO_NA_COMPILACAO_COM_VALOR:
            pular = True
            continue
        limpa.append(parte)
    return limpa


def _peneirar(spec: Path) -> None:
    """Insere o filtro no .spec, entre a análise e o empacotamento."""
    conteudo = spec.read_text(encoding="utf-8")
    marca_do_pyz = "pyz = PYZ("
    assert marca_do_pyz in conteudo, "o .spec do PyInstaller mudou de forma"
    peneira = PENEIRA.format(fora=repr(DADOS_INUTEIS))
    spec.write_text(conteudo.replace(marca_do_pyz, peneira + "\n" + marca_do_pyz, 1),
                    encoding="utf-8")


def construir(*, unico: bool) -> Path:
    import marca

    icone, origem = marca.icone_do_windows(BASE / "assets" / "app_icon.ico")
    print(f"ícone do executável: {icone.name} (do {origem})")
    comando = [
        sys.executable, "-m", "PyInstaller", "desktop.py",
        "--name", NOME,
        "--onefile" if unico else "--onedir",
        "--windowed",              # sem janela preta de console atrás do programa
        "--noconfirm",
        "--icon", str(icone),
        "--distpath", str(SAIDA),
        "--workpath", str(TRABALHO),
        "--specpath", str(BASE),
        *sum((["--hidden-import", m] for m in MODULOS), []),
        "--exclude-module", "pytest",
        "--exclude-module", "unittest",
        # Pillow serve só para gerar o .ico, e isso acontece ACIMA, antes de o
        # PyInstaller rodar. Deixá-lo entrar acrescentava 7 MB ao executável
        # para um código que nunca é chamado depois de compilado.
        "--exclude-module", "PIL",
    ]
    if unico:
        # No arquivo único a semente viaja dentro do .exe; instalacao.preparar()
        # a copia para o lado dele na primeira abertura.
        for nome in (*PASTAS, ".env", "LEIA-ME.txt", "COMO USAR.txt"):
            origem = SEMENTE / nome
            if origem.exists():
                destino = nome if origem.is_dir() else "."
                comando += ["--add-data", f"{origem}{os.pathsep}{destino}"]

    # Em dois passos: primeiro o `.spec`, que é peneirado; depois a compilação
    # a partir dele. A linha de comando do PyInstaller não sabe excluir dado —
    # só módulo —, e o que pesa na abertura é justamente dado.
    receita = _receita(comando)
    receita[1:3] = ["-m", "PyInstaller.utils.cliutils.makespec"]
    subprocess.run(receita, check=True, cwd=BASE)
    spec = BASE / f"{NOME}.spec"
    _peneirar(spec)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                    "--distpath", str(SAIDA), "--workpath", str(TRABALHO),
                    str(spec)], check=True, cwd=BASE)
    return (SAIDA / f"{NOME}.exe") if unico else (SAIDA / NOME)


def publicar_manifesto(exe: Path, *, instalador: bool = False) -> Path:
    """Escreve o `version.json` que o auto-atualizador vai ler.

    A impressão digital do arquivo nasce aqui, onde o arquivo acabou de ser
    feito — é o único lugar em que ela é confiável de graça. Publicada junto
    com o .exe, é o que permite à máquina do cliente saber que baixou o que
    você publicou, e não outra coisa.

    O endereço fica em branco de propósito: só quem publica sabe para onde o
    arquivo vai. Preencher aqui um endereço chutado seria pior que deixar
    vazio — o programa recusa vazio, e aceitaria o chute.
    """
    import hashlib

    import updater

    digestor = hashlib.sha256()
    with exe.open("rb") as arquivo:
        for pedaco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digestor.update(pedaco)

    manifesto = SAIDA / "version.json"
    corpo = {
        "versao": updater.VERSAO_ATUAL,
        "arquivo": "",
        "sha256": digestor.hexdigest(),
        "notas": "",
    }
    if instalador:
        # É por este campo que o programa do cliente decide o que fazer com o
        # arquivo baixado: rodar (instalador) ou trocar por cima do .exe.
        corpo["formato"] = "instalador"
    manifesto.write_text(json.dumps({
        **corpo,
        "_como_usar": (
            "Suba este arquivo e o .exe para o mesmo lugar (https). Preencha "
            "'arquivo' com o endereço do .exe e 'notas' com o que mudou. "
            "Aponte NFSE_ATUALIZACAO_URL no .env do cliente para este JSON."),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifesto


def acompanhar(destino: Path) -> None:
    """Copia a semente para o lado do executável (formato pasta)."""
    shutil.copytree(SEMENTE, destino, dirs_exist_ok=True)
    (destino / "data").mkdir(exist_ok=True)


def conferir(alvo: Path, *, unico: bool, seguro: bool) -> None:
    """Confere o que costuma faltar, antes de a máquina de destino descobrir."""
    problemas: list[str] = []
    if not alvo.exists():
        problemas.append(f"não achei {alvo.name}")

    if unico:
        # No arquivo único só dá para conferir a semente — ela é o que vai
        # dentro. O teste de verdade é abrir o .exe, feito logo adiante.
        pasta = SEMENTE
    else:
        pasta = alvo
        for nome in ("data", "COMO USAR.txt"):
            if not (pasta / nome).exists():
                problemas.append(f"faltou {nome}")

    for nome in ("config/templates", "config/ufs.json", "config/login_template.json",
                 ".env",
                 # Sem as tabelas da reforma a nota é recusada com HTTP 500 e
                 # sem explicação; sem a correlação, o NBS teria de ser
                 # escolhido entre 675 códigos.
                 "config/reforma_codigos.json", "config/nbs_por_item.json"):
        if not (pasta / nome).exists():
            problemas.append(f"faltou {nome}")
    modelos = list((pasta / "config" / "templates").glob("*.json"))
    if not modelos:
        problemas.append("nenhum modelo de emissão em config/templates")
    for modelo in modelos:
        try:
            declarado = json.loads(modelo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problemas.append(f"{modelo.name} ilegível ({exc})")
            continue
        reforma_declarada = declarado.get("servico_reforma") or {}
        faltam = [c for c in ("nbs", "indicador_operacao", "situacao_tributaria",
                              "classificacao_tributaria")
                  if c not in reforma_declarada]
        if faltam:
            problemas.append(f"{modelo.name} não diz onde escrever: {', '.join(faltam)}")

    env = (pasta / ".env").read_text(encoding="utf-8")
    if "NFSE_SENHA=" in env:
        problemas.append("a senha vazou para o .env distribuído")
    # Aviso, não erro: dá para distribuir sem atualização automática — mas quem
    # esquece disto só descobre quando precisar publicar a correção, e aí já
    # mandou para todo mundo uma cópia que nunca vai procurar versão nova.
    endereco = ""
    for linha in env.splitlines():
        if linha.strip().startswith("NFSE_ATUALIZACAO_URL="):
            endereco = linha.split("=", 1)[1].strip()
    if not endereco:
        print("\n  ATENÇÃO: NFSE_ATUALIZACAO_URL está vazio no .env desta pasta.")
        print("  Esta cópia NUNCA vai procurar atualização — quem recebê-la só")
        print("  troca de versão recebendo o arquivo de novo, à mão.")
        print("  Preencha no .env daqui e compile outra vez.")
    esperado = f"NFSE_LIVE_MODE={'false' if seguro else 'true'}"
    if esperado not in env:
        problemas.append(f"o modo de transmissão não ficou como pedido ({esperado})")
    # As duas identificações do GWT: a do cabeçalho e a que vai dentro do corpo.
    # Faltando qualquer uma, o portal recusa o login — e sem dizer por quê.
    for chave, oque in (("NFSE_GWT_PERMUTATION", "a identificação da versão do portal"),
                        ("NFSE_GWT_POLICY", "a assinatura do serviço")):
        if f"{chave}=" not in env:
            problemas.append(f"falta a linha {chave} — o login não funciona sem ela")
        elif f"{chave}=\n" in env:
            # Vazia não é erro: `session.login()` lê a versão do portal antes
            # de entrar e grava no .env. Custa só a primeira abertura ser um
            # pouco mais lenta — e é o único jeito de compilar na nuvem, onde
            # não há .env para copiar esses valores.
            print(f"  nota: {chave} sai vazia; {oque} será lida no primeiro login.")

    if problemas:
        raise SystemExit("Empacotamento incompleto:\n  - " + "\n  - ".join(problemas))

    if unico:
        tamanho = alvo.stat().st_size / 1024 / 1024
        print(f"\nPronto: {alvo}\n  arquivo único, {tamanho:.0f} MB")
    else:
        arquivos = [f for f in alvo.rglob("*") if f.is_file()]
        tamanho = sum(f.stat().st_size for f in arquivos) / 1024 / 1024
        print(f"\nPronto: {alvo}\n  {len(arquivos)} arquivos, {tamanho:.0f} MB")
    import updater

    print(f"  versão: {updater.VERSAO_ATUAL}")
    print(f"  modelos de emissão: {', '.join(m.stem for m in modelos)}")
    print(f"  transmissão: {'MODO SEGURO — não envia' if seguro else 'ATIVA — envia de verdade'}")


# O nome do arquivo baixado é o primeiro contato com a marca; o do
# executável de dentro é endereço, e continua como está (ver instalador.py).
NOME_INSTALADOR = "Instalar DINELLY NFS-e"


def compactar_o_programa(pasta_do_programa: Path) -> Path:
    """A pasta do programa vira um .zip — o que o instalador carrega dentro.

    Compactada porque o PyInstaller guarda dado quase do tamanho que recebe:
    a pasta solta dava um instalador de 24 MB; em .zip são 12,6 MB, o mesmo
    que o arquivo único de hoje. E descompactar UM arquivo custa ~1,2 s,
    contra 412 arquivos abertos um a um.
    """
    import zipfile

    import updater

    alvo = TRABALHO / "app.zip"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.unlink(missing_ok=True)
    with zipfile.ZipFile(alvo, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as pacote:
        for arquivo in sorted(pasta_do_programa.rglob("*")):
            if arquivo.is_file():
                pacote.write(arquivo, arquivo.relative_to(pasta_do_programa))
        # Para o instalador saber se o que já está instalado é isto mesmo, e
        # poder pular a cópia. Vai junto na pasta instalada, não só no .zip.
        pacote.writestr("versao.txt", updater.VERSAO_ATUAL)
    return alvo


def construir_instalador(pasta_do_programa: Path) -> Path:
    """Embrulha a pasta do programa num arquivo único que se instala."""
    import marca

    embrulhado = compactar_o_programa(pasta_do_programa)
    icone, _origem = marca.icone_do_windows(BASE / "assets" / "app_icon.ico")
    comando = [
        sys.executable, "-m", "PyInstaller", "instalador.py",
        "--name", NOME_INSTALADOR,
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--icon", str(icone),
        "--distpath", str(SAIDA),
        "--workpath", str(TRABALHO),
        "--specpath", str(BASE),
        "--add-data", f"{embrulhado}{os.pathsep}.",
        # O assistente usa a mesma paleta e o mesmo monograma do programa: um
        # instalador com cara de outro programa já começa dizendo que as duas
        # coisas não são a mesma.
        "--hidden-import", "ui",
        "--hidden-import", "marca",
        "--hidden-import", "paths",
        "--exclude-module", "pytest",
        "--exclude-module", "unittest",
        "--exclude-module", "PIL",
    ]
    receita = _receita(comando)
    receita[1:3] = ["-m", "PyInstaller.utils.cliutils.makespec"]
    subprocess.run(receita, check=True, cwd=BASE)
    spec = BASE / f"{NOME_INSTALADOR}.spec"
    _peneirar(spec)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                    "--distpath", str(SAIDA), "--workpath", str(TRABALHO),
                    str(spec)], check=True, cwd=BASE)
    spec.unlink(missing_ok=True)
    return SAIDA / f"{NOME_INSTALADOR}.exe"


def conferir_instalador(instalador: Path, pasta: Path) -> None:
    """O instalador tem de ser maior que o programa que carrega dentro."""
    problemas: list[str] = []
    if not instalador.exists():
        problemas.append(f"não achei {instalador.name}")
        raise SystemExit("\n".join(problemas))
    dentro = sum(f.stat().st_size for f in pasta.rglob("*") if f.is_file())
    if instalador.stat().st_size < dentro * 0.25:
        # Comprime bem, mas não some: um instalador muito menor que o
        # conteúdo é sinal de que a pasta não entrou.
        problemas.append(
            f"o instalador tem {instalador.stat().st_size/1e6:.1f} MB para "
            f"{dentro/1e6:.1f} MB de programa — a pasta não entrou")
    # E o teste que não depende de tamanho nenhum: o programa está lá dentro?
    import instalador as programa_instalador

    if not programa_instalador._tem_o_programa(TRABALHO / "app.zip"):
        problemas.append("o .zip da carga não tem o executável do programa")
    if problemas:
        raise SystemExit("\n".join(f"  - {p}" for p in problemas))


def gerar(*, unico: bool, seguro: bool) -> Path:
    spec = BASE / f"{NOME}.spec"
    if spec.exists():
        spec.unlink()     # senão o PyInstaller reaproveita o formato anterior
    alvo = construir(unico=unico)
    if not unico:
        acompanhar(alvo)
    conferir(alvo, unico=unico, seguro=seguro)
    if unico:
        # Só o arquivo único se atualiza sozinho; o manifesto é dele.
        manifesto = publicar_manifesto(alvo)
        print(f"  para publicar: {manifesto.name} (preencha 'arquivo' com a URL)")
    return alvo


if __name__ == "__main__":
    seguro = "--seguro" in sys.argv
    # Sem escolha, gera os dois: a pasta para trabalhar e o arquivo único para
    # entregar. São o mesmo programa, com a mesma semente.
    instalador = "--instalador" in sys.argv
    formatos = []
    if instalador:
        formatos = [False]        # a pasta é o recheio do instalador
    elif "--unico" in sys.argv:
        formatos = [True]
    elif "--pasta" in sys.argv:
        formatos = [False]
    else:
        formatos = [False, True]

    limpar()
    preparar_semente(seguro=seguro)
    for unico in formatos:
        alvo = gerar(unico=unico, seguro=seguro)

    if instalador:
        embrulho = construir_instalador(alvo)
        conferir_instalador(embrulho, alvo)
        manifesto = publicar_manifesto(embrulho, instalador=True)
        print(f"\nPronto: {embrulho}")
        print(f"  {embrulho.stat().st_size/1e6:.0f} MB — instala e abre "
              f"{NOME} em %LOCALAPPDATA%")
        print(f"  para publicar: {manifesto.name} "
              f"(preencha 'arquivo' com a URL)")

    spec = BASE / f"{NOME}.spec"
    if spec.exists():
        spec.unlink()
    if TRABALHO.exists():
        shutil.rmtree(TRABALHO)
    print(f"\nTudo em: {SAIDA}")

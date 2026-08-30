"""Aplicativo desktop para emitir e acompanhar NFS-e.

Execute com: python desktop.py

A aparência mora em ``ui.py`` — cores, tipografia e componentes. Aqui ficam as
telas e o que elas fazem. A separação existe porque as duas coisas mudam por
motivos diferentes: a paleta muda por gosto, a tela muda por regra fiscal.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import sys
import threading
import traceback
import tkinter as tk
from datetime import date
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

import config
import impressao
import cep
import instalacao
import marca
import municipios
import nfse_client
import obras
import paths
import pdf
import portal
import prestador
import recursos
import reforma
import registro
import service
import services
import session
import storage
import ui
import updater
import validation

STATUS_LABELS = {"draft": "Rascunho", "submitted": "Emitida", "failed": "Falhou"}
# O tom de cada status é o nome do tom, não a cor: a cor depende do tema em
# vigor, e um dicionário montado no import guardaria a paleta clara para
# sempre — a tela escura sairia com texto quase invisível.
STATUS_TOM = {"draft": "neutro", "submitted": "sucesso", "failed": "erro"}


def motivo_da_falha(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """Por que o portal recusou esta nota, em pares (rótulo, texto).

    Tudo isto já era gravado em `last_submission` a cada envio — só nunca
    tinha chegado à tela. Quem via "Falhou" precisava abrir o arquivo JSON
    para descobrir que o problema era o valor líquido, ou a sessão expirada.

    A mensagem do portal vem primeiro porque é a única que diz o que corrigir:
    "E181 — o valor líquido deve ser o resultado de..." resolve a nota; "HTTP
    500" só diz que deu errado.
    """
    envio = doc.get("last_submission") or {}
    if not envio:
        return [("Sem registro", "Esta nota não chegou a ser enviada ao portal.")]

    linhas: list[tuple[str, str]] = []
    mensagens = [str(m).strip() for m in (envio.get("portal_mensagens") or []) if str(m).strip()]
    if mensagens:
        # O portal manda o código e o texto em itens separados: "E181" seguido
        # da explicação. Juntos numa linha só se leem como uma frase.
        if len(mensagens) > 1 and len(mensagens[0]) <= 8:
            # "E181" sozinho não diz nada; grudado no texto, vira uma frase.
            linhas.append((f"Portal · {mensagens[0]}", mensagens[1]))
            linhas.extend(("", extra) for extra in mensagens[2:])
        else:
            linhas.extend(("Portal" if i == 0 else "", m)
                          for i, m in enumerate(mensagens))

    erro = str(envio.get("error") or "").strip()
    if erro and not any(erro in linha[1] for linha in linhas):
        linhas.append(("Falha", erro))

    status = envio.get("http_status")
    if status and status != 200:
        linhas.append(("Resposta HTTP", str(status)))

    if not linhas:
        resposta = str(envio.get("response") or "").strip()
        linhas.append(("Resposta do portal", resposta[:400] or "sem detalhes registrados"))

    quando = str(envio.get("at") or "")
    if quando:
        linhas.append(("Tentativa em", quando.replace("T", " ")[:19]))
    return linhas


def _data_br(bruto: Any) -> str:
    """2026-08-29 vira 29/08/2026 — como se lê no Brasil.

    O que não estiver nesse formato passa direto: rascunho antigo com data
    estranha continua visível na lista, em vez de sumir por causa da coluna.
    """
    texto = str(bruto or "")[:10]
    partes = texto.split("-")
    if len(partes) == 3 and all(p.isdigit() for p in partes):
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return texto


def cor_do_status(status: str) -> str:
    """A cor de texto do status, resolvida no tema em vigor."""
    return ui.cores_do_tom(STATUS_TOM.get(status, "neutro"))[0]


class AreaRolavel(tk.Frame):
    """Região de conteúdo que rola quando a janela fica pequena.

    Sem isto, encolher a janela simplesmente esconde o botão de emitir — e o
    usuário fica sem saída. A barra só aparece quando de fato falta espaço.
    """

    def __init__(self, pai: tk.Widget, *, fundo: str | None = None) -> None:
        fundo = fundo or ui.BG
        super().__init__(pai, bg=fundo)
        self.canvas = tk.Canvas(self, bg=fundo, highlightthickness=0, bd=0)
        self.barra = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.interior = tk.Frame(self.canvas, bg=fundo)
        self._janela = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self.canvas.configure(yscrollcommand=self._ao_rolar)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.interior.bind("<Configure>", self._medir)
        self.canvas.bind("<Configure>", self._acompanhar_largura)
        # A roda só age enquanto o ponteiro está sobre a área — do contrário
        # rolaria a página ao girar a roda dentro de uma lista suspensa.
        self.canvas.bind("<Enter>", lambda _e: self.bind_all("<MouseWheel>", self._rolar))
        self.canvas.bind("<Leave>", lambda _e: self.unbind_all("<MouseWheel>"))

    def _medir(self, _evento=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _acompanhar_largura(self, evento) -> None:
        self.canvas.itemconfigure(self._janela, width=evento.width)

    def _ao_rolar(self, inicio: str, fim: str) -> None:
        if float(inicio) <= 0.0 and float(fim) >= 1.0:
            self.barra.pack_forget()
        else:
            self.barra.pack(side="right", fill="y")
        self.barra.set(inicio, fim)

    def _rolar(self, evento) -> None:
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(-1 * (evento.delta // 120), "units")

    def limpar(self) -> None:
        for filho in self.interior.winfo_children():
            filho.destroy()
        self.canvas.yview_moveto(0)

    def pintar(self, fundo: str) -> None:
        """Repinta a área ao trocar de tema."""
        self.configure(bg=fundo)
        self.canvas.configure(bg=fundo)
        self.interior.configure(bg=fundo)


def colunas_de_notas() -> list["ui.Celula"]:
    """As colunas da lista.

    Larguras somadas cabem na janela mínima; as três com peso crescem quando
    sobra espaço. Número e data à direita, texto à esquerda — é como se lê uma
    tabela de valores.
    """
    return [
        # As larguras-base saem da medida do conteúdo real: o maior nome de
        # prestador nas notas gravadas pede 257px, e o maior tomador, 253.
        # Abaixo disso a razão social aparece cortada, que é justamente o que
        # não pode acontecer numa lista de notas fiscais.
        #
        # A coluna "Serviço" saiu daqui pela mesma conta: com ela, as seis
        # colunas somam mais do que a janela tem, e a sobra saía do nome das
        # empresas — que apareciam todas cortadas. A descrição do serviço é
        # texto corrido, o único campo que se lê inteiro sem pressa: ela
        # continua no painel da direita, completa, ao escolher a nota. Trocar
        # uma razão social cortada por uma descrição a um clique é o negócio
        # que fecha.
        # `px`: as medidas abaixo foram tiradas de um monitor a 100%. Num a
        # 150% a mesma razão social ocupa uma vez e meia isto — e apareceria
        # cortada de novo, que é o defeito que a medida veio consertar.
        ui.Celula("prestador", "Prestador", ui.px(252), tipo="duplo", peso=3,
                  minimo=ui.px(150)),
        ui.Celula("tomador", "Tomador", ui.px(248), tipo="duplo", peso=3,
                  minimo=ui.px(150)),
        # Estas quatro não esticam, então a base é o que o conteúdo mais
        # largo pede, medido: R$ 40.416,25 dá 82px; a pílula "Emitida · nº
        # 1412" dá 117; "29/08/2026" dá 76, mais os 8 que o recorte reserva.
        ui.Celula("valor", "Valor", ui.px(86), tipo="dinheiro", fim=True),
        ui.Celula("status", "Situação", ui.px(120), tipo="pilula"),
        ui.Celula("data", "Emissão", ui.px(86), tipo="duplo", fim=True),
        ui.Celula("acoes", "", ui.px(52), tipo="acoes", fim=True, ordenavel=False),
    ]


TOM_DO_STATUS = {"submitted": "sucesso", "draft": "neutro", "failed": "erro"}


def linha_da_nota(doc: dict[str, Any], prestador_de, *,
                  ocultar_valores: bool = False) -> dict[str, Any]:
    """Uma nota, no formato que a tabela desenha."""
    payload = doc.get("payload") or {}
    tomador = payload.get("tomador") or {}
    servico = payload.get("servico") or {}
    status = doc.get("status", "")
    numero = (doc.get("nota") or {}).get("numero")

    quem = prestador_de(doc)
    inscricao = str(((payload.get("prestador") or {}).get("inscricao") or "")).strip()
    documento = str(tomador.get("documento", ""))
    rotulo = STATUS_LABELS.get(status, status)
    if numero:
        rotulo = f"{rotulo} · nº {numero}"

    return {
        "id": doc["id"],
        "prestador": (quem, f"CCM {inscricao}" if inscricao else ""),
        "tomador": (tomador.get("nome") or validation.format_document(documento)
                    or "Sem tomador",
                    validation.format_document(documento) if tomador.get("nome") else ""),
        "servico": " ".join((servico.get("descricao") or "—").split()),
        "valor": "•••" if ocultar_valores else validation.format_money(servico.get("valor")),
        "status": (rotulo, TOM_DO_STATUS.get(status, "neutro")),
        "data": (_data_br(doc.get("created_at")), _ha_quanto(doc.get("created_at"))),
        "acoes": {"pdf": status == "submitted" and bool(numero),
                  "enviar": status != "submitted"},
    }


def _ha_quanto(bruto: Any) -> str:
    """"hoje", "ontem", "há 4 dias" — para não fazer conta de cabeça."""
    iso = str(bruto or "")[:10]
    partes = iso.split("-")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return ""
    alvo = date(int(partes[0]), int(partes[1]), int(partes[2]))
    dias = (date.today() - alvo).days
    if dias <= 0:
        return "hoje"
    if dias == 1:
        return "ontem"
    if dias < 30:
        return f"há {dias} dias"
    if dias < 60:
        return "há 1 mês"
    return f"há {dias // 30} meses"


class BarraDeComando(tk.Frame):
    """A faixa do topo: marca, navegação, empresa e modo de transmissão.

    Substitui a barra lateral. Uma coluna de 78px à esquerda custava largura
    justamente onde a tabela precisava, e mantinha a silhueta do programa
    antigo — era a primeira coisa que se via, e a que menos mudava.
    """

    # Sem "Painel": ele mostrava contadores que a tela de Notas já mostra —
    # e lá eles ainda filtram a lista. Era um passo a mais entre abrir o
    # programa e ver as notas.
    SECOES = (("notas", "Notas"), ("emitir", "Emitir"), ("ajustes", "Ajustes"))

    def __init__(self, pai: tk.Widget, app: "NfseDesktop") -> None:
        super().__init__(pai, bg=ui.NAVY, padx=ui.E5, pady=ui.E3)
        self.app = app

        marca_caixa = tk.Frame(self, bg=ui.NAVY)
        marca_caixa.pack(side="left")
        ui.losango(marca_caixa, "DZ", lado=32, fundo=ui.NAVY).pack(side="left")
        nomes = tk.Frame(marca_caixa, bg=ui.NAVY)
        nomes.pack(side="left", padx=(ui.E2, 0))
        # A marca, e não um nome de produto inventado: é o programa da casa.
        # Desenhada em vez de escrita para o ® sair pequeno e no alto, e para
        # as maiúsculas terem respiro entre si.
        ui.assinatura(nomes, marca.NOME.upper(), fundo=ui.NAVY, cor=ui.INK,
                      tamanho=14, espaco=2.4, registrada=marca.REGISTRADA,
                      cor_registrada=ui.NAV_LEGENDA).pack(anchor="w")
        tk.Label(nomes, text="NOTAS FISCAIS  ·  SÃO BERNARDO DO CAMPO", bg=ui.NAVY,
                 fg=ui.NAV_LEGENDA, font=ui.MICRO).pack(anchor="w", pady=(1, 0))

        self.navegacao = ui.Segmentado(
            self, list(self.SECOES), self._escolher, fundo=ui.NAVY)
        self.navegacao.pack(side="left", padx=(ui.E5, 0))

        direita = tk.Frame(self, bg=ui.NAVY)
        direita.pack(side="right")

        self.botao_tema = self._botao_de_icone(
            direita, "tema", lambda: self.app._trocar_tema(ui.outro_tema()))
        self.botao_tema.pack(side="right", padx=(ui.E2, 0))

        self.farol = tk.Frame(direita, bg=ui.NAVY)
        self.farol.pack(side="right", padx=(ui.E2, 0))

        self.empresa = ui.Redondo(direita, raio=10, fundo=ui.SURFACE_ALT,
                                  borda=ui.BORDER, fundo_externo=ui.NAVY,
                                  padx=ui.E3, pady=6)
        self.empresa.pack(side="right")
        tk.Label(self.empresa.interior, text="EMITINDO COMO", bg=ui.SURFACE_ALT,
                 fg=ui.INK_3, font=ui.MICRO).pack(anchor="w")
        self.empresa_nome = tk.Label(
            self.empresa.interior, text="", bg=ui.SURFACE_ALT, fg=ui.INK,
            font=ui.CORPO_FORTE, cursor="hand2")
        self.empresa_nome.pack(anchor="w")
        self.empresa_nome.bind("<Button-1>", lambda _e: self.app.sair())

        self.atualizar()

    def _botao_de_icone(self, pai, nome, comando):
        """Botão redondo de ícone.

        Era um Frame com `highlightthickness=1`: uma moldura quadrada de um
        pixel, o único canto vivo num programa todo de cantos redondos — e
        justo no alto da tela, onde o olho passa primeiro.
        """
        caixa = ui.Redondo(pai, raio=9, fundo=ui.NAVY, borda=ui.BORDER,
                           fundo_externo=ui.NAVY, padx=7, pady=7, cursor="hand2")
        desenho = ui.icone_vetor(caixa.interior, nome, cor=ui.NAV_TEXTO,
                                 fundo=ui.NAVY, lado=16)
        desenho.pack()

        def pintar(fundo: str) -> None:
            caixa.pintar(fundo=fundo)
            desenho.configure(bg=fundo)

        for widget in (caixa, caixa.interior, desenho):
            widget.bind("<Button-1>", lambda _e: comando())
            widget.bind("<Enter>", lambda _e: pintar(ui.NAVY_HOVER))
            widget.bind("<Leave>", lambda _e: pintar(ui.NAVY))
        return caixa

    # -- estado ---------------------------------------------------------- #

    def marcar(self, chave: str) -> None:
        self.navegacao.escolher(chave)

    def _escolher(self, chave: str) -> None:
        telas = {"notas": self.app.show_documents,
                 "emitir": self.app.show_new_note, "ajustes": self.app.show_settings}
        telas[chave]()

    def atualizar(self) -> None:
        """Repõe a empresa e o farol de transmissão."""
        self.empresa_nome.configure(
            text=(self.app.empresa_logada or "Sem empresa")[:34])
        for filho in self.farol.winfo_children():
            filho.destroy()
        vivo = config.live_mode()
        ui.pilula(self.farol,
                  "TRANSMISSÃO ATIVA" if vivo else "MODO SEGURO",
                  tom="alerta" if vivo else "sucesso",
                  fundo=ui.NAVY).pack()


class NfseDesktop(tk.Tk):
    def __init__(self) -> None:
        escala = ui.ativar_nitidez()
        # Antes do `super().__init__()`: depois de a janela existir, o Windows
        # já escolheu sob qual ícone agrupá-la.
        ui.identificar_no_windows("Dezorzi.NFSe")
        super().__init__()
        ui.aplicar_escala(self, escala)
        # Antes de qualquer leitura: no executável de arquivo único não existe
        # config/ nem .env ao lado do programa até esta linha rodar.
        self._instalado = instalacao.preparar()
        config.load_env()
        config.aplicar_empresa_ativa()
        # Antes de criar widget nenhum: eles leem a cor na hora em que nascem.
        ui.usar_tema(config.tema())
        ui.escolher_familia(self)

        self.title(f"{marca.ASSINATURA} · NFS-e")
        # Em pixels da tela: a 150% a mesma janela "mínima" cabe menos
        # conteúdo, porque a letra ocupa uma vez e meia. O mínimo cresce junto.
        self.minsize(ui.px(980), ui.px(600))
        # Pede a tela inteira: `centralizar` já corta pelo que couber na área
        # livre, então pedir grande é pedir "o máximo que couber".
        ui.centralizar(self, 1600, 1000)
        # Agora que a janela existe, dá para perguntar em que monitor ela
        # está: `ativar_nitidez` só sabia responder pelo monitor principal, e
        # quem abre o programa no segundo monitor abriria na escala errada.
        # Nenhum widget nasceu ainda, então trocar a escala aqui não custa
        # remontagem nenhuma.
        self._densidade = ui.densidade_da_janela(self)
        if abs(self._densidade - escala) > 0.01:
            ui.aplicar_escala(self, self._densidade)
        self.configure(bg=ui.BG)
        try:
            self._icone = marca.icone(56, self)
            self.iconphoto(True, self._icone)
        except tk.TclError:
            pass  # sem ícone é feio, não é motivo para não abrir

        self._busy = False
        self._nav_atual = ""
        self._valores_ocultos = False
        self._abrir_fila_interface()
        ui.aplicar_estilo(self)
        self._montar_menu()

        # A barra de comando é criada depois do login ser conhecido, mas
        # antes das telas: `_montar_comando` a coloca no topo.
        self.comando: BarraDeComando | None = None
        self.divisoria_topo = tk.Frame(self, bg=ui.BORDER, height=1)
        self.principal = tk.Frame(self, bg=ui.BG)
        self.principal.pack(side="bottom", expand=True, fill="both")

        # Sem título de página, esta faixa é só a linha de ações da tela.
        # Pouco respiro: o que interessa é o conteúdo, logo abaixo.
        self.cabecalho = tk.Frame(self.principal, bg=ui.BG, padx=ui.E5, pady=ui.E2)
        self.cabecalho.pack(fill="x")
        self.divisoria = tk.Frame(self.principal, bg=ui.BG, height=0)
        self.rolagem = AreaRolavel(self.principal)
        self.rolagem.pack(fill="both", expand=True)
        self.content = tk.Frame(self.rolagem.interior, bg=ui.BG, padx=ui.E5,
                                pady=(ui.E2))
        self.content.pack(fill="both", expand=True)

        self.avisos = ui.Notificacoes(self)
        self.empresa_logada = ""  # antes da barra: ela já lê este valor
        self._montar_comando()
        # A faixa de minimizar/maximizar/fechar é do Windows; pedimos que ela
        # acompanhe o programa, senão fica clara sobre uma janela escura.
        self.after(120, self._pintar_moldura)
        self.show_login()
        self.bind("<Configure>", self._conferir_densidade, add="+")
        # Em segundo plano: a abertura não espera a internet. Se a rede estiver
        # fora, o motivo vai para o diário e a tela abre como sempre.
        updater.procurar_em_segundo_plano(
            lambda nova: self._na_interface(lambda: self._oferecer_atualizacao(nova)))
        self._sincronizar_portal_ao_abrir()
        if not instalacao.pasta_grava():
            # Avisar agora, e não na hora de salvar: quem descobre que a pasta
            # é somente-leitura depois de preencher a nota inteira perdeu o
            # trabalho todo.
            self.after(400, self._avisar_pasta_travada)

    # ------------------------------------------------------------------ #
    # Ponte entre as threads e a tela
    # ------------------------------------------------------------------ #

    def _abrir_fila_interface(self) -> None:
        """Canal por onde as threads de trabalho devolvem resultado à tela.

        `after` chamado de dentro de uma thread depende de o laço principal já
        estar rodando e estoura RuntimeError quando não está — o download do PDF
        pode terminar exatamente nessa fresta. A fila é sempre lida pela thread
        da interface, então o resultado nunca se perde.
        """
        self._fila_interface: queue.Queue = queue.Queue()
        self._drenar_fila()

    def _drenar_fila(self) -> None:
        while True:
            try:
                callback = self._fila_interface.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception as exc:
                # Um callback quebrado não pode parar a fila — mas também não
                # pode sumir. Só o print para o terminal escondeu uma janela de
                # impressão que ficava "Buscando o PDF…" para sempre porque
                # estourou antes de iniciar o download, e ninguém viu.
                #
                # Tudo aqui é protegido: se o próprio aviso de erro falhar, a
                # fila para de ser reagendada e a tela congela sem explicação —
                # um defeito no tratamento de erro derrubando o programa todo.
                try:
                    registro.falha("callback da interface", exc)
                    traceback.print_exc()
                except Exception:
                    pass
                try:
                    messagebox.showerror(
                        "Erro na interface",
                        f"{type(exc).__name__}: {exc}\n\n"
                        f"A operação anterior pode não ter sido concluída.",
                    )
                except Exception:
                    pass
        if self.winfo_exists():
            self.after(60, self._drenar_fila)

    def _na_interface(self, callback: Callable[[], None]) -> None:
        """Agenda um callback para rodar na thread da interface."""
        self._fila_interface.put(callback)

    # ------------------------------------------------------------------ #
    # Avisos
    # ------------------------------------------------------------------ #
    # No lugar da caixa de diálogo que trava a tela e pede um clique para
    # dizer algo que já aconteceu. O que é do envio ao portal continua em
    # caixa: ali a diferença entre "foi" e "não foi" é fiscal, e um aviso que
    # some sozinho pode passar batido na hora errada.
    #
    # Todos aceitam `parent` e descartam: várias chamadas antigas passavam o
    # modal de origem, e o aviso flutuante mora preso à janela principal.

    def _info(self, titulo: str, texto: str = "", **_ignorado) -> None:
        self.avisos.info(titulo, texto)

    def _sucesso(self, titulo: str, texto: str = "", **_ignorado) -> None:
        self.avisos.sucesso(titulo, texto)

    def _alerta(self, titulo: str, texto: str = "", **_ignorado) -> None:
        self.avisos.alerta(titulo, texto)

    def _erro(self, titulo: str, texto: str = "", **_ignorado) -> None:
        self.avisos.erro(titulo, texto)

    # ------------------------------------------------------------------ #
    # Estrutura da janela
    # ------------------------------------------------------------------ #

    def _montar_menu(self) -> None:
        """Só o atalho de teclado. A barra de menu do Windows saiu.

        Ela é desenhada pelo sistema: não aceita cor, forma nem tipo de letra,
        e ficaria como a única faixa de aparência antiga acima de uma tela
        inteira refeita. Os comandos que moravam nela agora estão em Ajustes,
        que é onde se procura por "testar conexão" ou "diário do programa".
        """
        self.bind_all("<Control-n>", lambda _e: self.show_new_note())

    def _sincronizar_portal_ao_abrir(self) -> None:
        """Confere a versão do portal ao abrir, sem segurar a tela.

        `session.login()` já faz isto antes de tentar entrar, e ainda força a
        releitura quando o login é recusado — o programa se conserta sozinho
        quando a prefeitura republica. Fazer aqui também adianta o trabalho:
        quando o usuário terminar de digitar a senha, a versão já está em dia,
        e a primeira tentativa de login não é gasta descobrindo isso.

        Não custa rede à toa: `portal.descobrir` guarda o que leu com data, e
        dentro da validade nem sai da máquina.
        """
        def trabalho() -> None:
            try:
                portal.sincronizar()
            except Exception as exc:
                # Rede fora não pode impedir ninguém de abrir o programa: sem
                # a releitura, vale a versão gravada, que costuma servir.
                registro.falha("sincronizar portal ao abrir", exc)

        threading.Thread(target=trabalho, daemon=True).start()

    def _reler_portal(self) -> None:
        """Relê no portal em que versão ele está.

        O programa já faz isso sozinho a cada login, mas quando a prefeitura
        publica versão nova no meio do expediente é bom poder forçar sem
        esperar o cache vencer.

        A ida ao portal roda em thread. Antes ficava aqui mesmo, e enquanto a
        prefeitura não respondesse a janela não repintava — o Windows chega a
        escurecê-la e a chamar de "não está respondendo", que é o retrato de
        um programa quebrado quando ele só está esperando.
        """
        self._info("Consultando o portal", "Lendo em que versão o portal está…")

        def trabalho() -> None:
            try:
                antes = portal.em_uso()
                agora = portal.sincronizar(forcar=True)
            except Exception as exc:
                registro.falha("reler versao do portal", exc)
                aviso = str(exc)
                self._na_interface(
                    lambda: messagebox.showerror("Não deu para ler", aviso))
                return
            self._na_interface(lambda: self._contar_do_portal(antes, agora))

        threading.Thread(target=trabalho, daemon=True).start()

    def _contar_do_portal(self, antes: str, agora: str) -> None:
        """O resultado da releitura, já na thread da tela."""
        registro.escrever("versao do portal", f"{antes or '(nenhuma)'} -> {agora}")
        if not agora:
            self._alerta(
                "Sem resposta",
                "Não consegui ler a versão do portal. Confira a conexão e tente de novo.",
            )
        elif antes == agora:
            self._info(
                "Portal conferido",
                f"Continua na mesma versão.\n\nIdentificação: {agora}",
            )
        else:
            self._info(
                "Portal atualizado",
                "A prefeitura publicou versão nova e o programa já se ajustou.\n\n"
                f"antes:  {antes or '(nenhuma)'}\n"
                f"agora:  {agora}",
            )

    def _abrir_registro(self) -> None:
        """Mostra o diário — é o que se manda quando algo falha em outra máquina."""
        arquivo = paths.DATA_DIR / "registro.txt"
        if not arquivo.exists():
            self._info(
                "Diário do programa",
                "Ainda não há nada registrado. O arquivo é criado conforme o "
                "programa é usado, e fica em:\n\n" + str(arquivo),
            )
            return
        self._janela_bruta(
            "Diário do programa",
            lambda: arquivo.read_text(encoding="utf-8", errors="replace"),
        )

    def _avisar_pasta_travada(self) -> None:
        self._alerta(
            "Pasta somente-leitura",
            f"O programa não consegue gravar em:\n{paths.BASE_DIR}\n\n"
            "As notas emitidas não serão salvas e os ajustes não ficam guardados.\n\n"
            "Copie o programa para uma pasta do disco — a Área de Trabalho ou "
            "Documentos servem — e abra de lá.",
        )

    def _trocar_logotipo(self) -> None:
        """Passa a usar o arquivo oficial da marca no lugar do desenho interno.

        O desenho que acompanha o programa é uma reconstrução do monograma. Com
        o arquivo original em mãos, este é o caminho de troca: ele é copiado
        para ``assets/logo.png`` e passa a valer em todas as telas.
        """
        escolhido = filedialog.askopenfilename(
            title="Escolha o arquivo do logotipo",
            filetypes=[("Imagem PNG", "*.png"), ("Todos os arquivos", "*.*")],
        )
        if not escolhido:
            return
        origem = Path(escolhido)
        try:
            teste = tk.PhotoImage(file=str(origem))
        except tk.TclError:
            messagebox.showerror(
                "Arquivo não aceito",
                "O Tk só lê PNG e GIF. Exporte o logotipo em PNG e tente de novo.",
            )
            return
        if teste.height() < 80:
            self._alerta(
                "Imagem pequena",
                f"O arquivo tem {teste.height()} px de altura. Abaixo de 80 px a marca "
                "sai serrilhada na tela de entrada — exporte com uns 600 px.",
            )
        marca.ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origem, marca.ARQUIVO)
        marca.esquecer()
        self._info(
            "Logotipo trocado",
            f"O arquivo foi copiado para:\n{marca.ARQUIVO}\n\n"
            "Feche e abra o programa para ver a marca nova em todas as telas.\n"
            "Para voltar ao desenho interno, basta apagar esse arquivo.",
        )

    def _exportar_marca(self) -> None:
        """Grava o monograma em PNG — para papel timbrado, assinatura, atalho."""
        destino = filedialog.asksaveasfilename(
            title="Salvar a marca", defaultextension=".png",
            initialfile="dezorzi.png", filetypes=[("Imagem PNG", "*.png")],
        )
        if not destino:
            return
        try:
            caminho = marca.salvar_png(destino, 600)
        except OSError as exc:
            messagebox.showerror("Não deu para salvar", str(exc))
            return
        self._sucesso("Marca exportada", f"Salvo em:\n{caminho}")

    def _about(self) -> None:
        self._info(
            "Sobre",
            f"{marca.ASSINATURA} · Emissor de NFS-e\n"
            "Emissão e acompanhamento de notas de serviço.\n\n"
            "A senha do portal fica apenas na memória desta sessão — "
            "nunca é gravada em disco.",
        )

    @staticmethod
    def duas_colunas(pai: tk.Widget, largura: int = 0) -> tuple[tk.Frame, tk.Frame]:
        """Lista à esquerda, detalhe à direita. Devolve as duas.

        Em `grid` e não em `pack`: empacotada com `fill="y"`, a coluna da
        direita herda a altura da esquerda, e o que passar disso não aparece —
        sem erro, sem aviso. Foi assim que dois cartões de Ajustes sumiram.
        """
        pai.columnconfigure(0, weight=1)
        pai.columnconfigure(1, weight=0, minsize=largura or ui.px(330))
        pai.rowconfigure(0, weight=1)
        esquerda = tk.Frame(pai, bg=ui.BG)
        esquerda.grid(row=0, column=0, sticky="nsew")
        direita = tk.Frame(pai, bg=ui.BG)
        direita.grid(row=0, column=1, sticky="new", padx=(ui.E3, 0))
        return esquerda, direita

    def _degrau(self, onde: tk.Widget, numero: int, titulo: str,
                explicacao: str) -> tk.Frame:
        """Um passo da emissão: número, título e o miolo para os campos.

        Quatro cartões numerados no lugar de uma lista de dezesseis linhas.
        Quem preenche vê onde está e quanto falta — e cada assunto termina
        num lugar visível, em vez de escorrer para o seguinte.
        """
        caixa = ui.cartao(onde, raio=14, padx=ui.E5, pady=ui.E4)
        caixa.pack(fill="x", pady=(0, ui.E3))
        cabeca = tk.Frame(caixa.interior, bg=ui.SURFACE)
        cabeca.pack(fill="x", pady=(0, ui.E3))
        selo = tk.Canvas(cabeca, width=24, height=24, bg=ui.SURFACE,
                         highlightthickness=0, bd=0)
        selo.pack(side="left")
        ui.retangulo_redondo(selo, 0.5, 0.5, 23.5, 23.5, 8,
                             fill=ui.PRIMARIA_CLARA, outline=ui.PRIMARIA_CLARA)
        selo.create_text(12, 13, text=str(numero), fill=ui.PRIMARIA,
                         font=(ui.FAMILIA, 10, "bold"))
        nomes = tk.Frame(cabeca, bg=ui.SURFACE)
        nomes.pack(side="left", padx=(ui.E2, 0))
        tk.Label(nomes, text=titulo, bg=ui.SURFACE, fg=ui.INK,
                 font=ui.CORPO_FORTE).pack(anchor="w")
        tk.Label(nomes, text=explicacao, bg=ui.SURFACE, fg=ui.INK_3,
                 font=ui.MICRO).pack(anchor="w")
        miolo = tk.Frame(caixa.interior, bg=ui.SURFACE)
        miolo.pack(fill="x")
        miolo.columnconfigure(0, weight=1)
        miolo.columnconfigure(1, weight=1)
        return miolo

    def _pintar_moldura(self) -> None:
        """Põe a barra de título do Windows no tom da barra de comando."""
        ui.pintar_barra_de_titulo(self, escuro=ui.escuro(), cor=ui.NAVY)

    def _montar_comando(self) -> None:
        """Cria a faixa do topo e a coloca antes de tudo."""
        self.comando = BarraDeComando(self, self)
        self.comando.pack(side="top", fill="x", before=self.principal)
        self.divisoria_topo.pack(side="top", fill="x", before=self.principal)

    def _assinatura(self, pai: tk.Widget, fundo: str, cor: str) -> tk.Label:
        """O nome, no tamanho de uma linha de rodapé.

        Só texto: o monograma miniaturizado aqui vira um retângulo e acaba
        puxando mais o olho que o próprio nome.
        """
        return tk.Label(pai, text=marca.ASSINATURA, bg=fundo, fg=cor, font=ui.MICRO)

    def _marcar_nav(self, chave: str) -> None:
        """Diz à barra qual seção está aberta."""
        self._nav_atual = chave
        if self.comando is not None and self.comando.winfo_exists():
            self.comando.marcar(chave)

    def _refresh_mode_label(self) -> None:
        """Repõe empresa e modo de transmissão na barra de comando."""
        if self.comando is not None and self.comando.winfo_exists():
            self.comando.atualizar()

    def _trocar_tema(self, nome: str) -> None:
        """Troca a paleta e redesenha a tela em vigor.

        Widget já criado não muda de cor: a única forma honesta de trocar o
        tema é montar a tela de novo. Por isso a nota em edição é perguntada
        antes — ela se perde no redesenho.
        """
        if nome == ui.TEMA:
            return
        if self._nav_atual == "emitir" and not messagebox.askyesno(
            "Trocar o tema",
            "A nota que está sendo preenchida será recomeçada."
            + chr(10) * 2 + "Trocar o tema mesmo assim?",
        ):
            return
        config.definir_tema(nome)
        ui.usar_tema(nome)
        ui.aplicar_estilo(self)
        self._redesenhar()
        self._pintar_moldura()

    def _conferir_densidade(self, evento=None) -> None:
        """Mudou de monitor? Então mudou a densidade — e a escala tem de mudar.

        `<Configure>` também sobe dos filhos e dispara a cada pixel de
        arrasto; por isso o evento é filtrado pela janela e a conta só é feita
        quando a densidade realmente mudou. Perguntar custa microssegundos;
        remontar a tela, não.
        """
        if evento is not None and evento.widget is not self:
            return
        agora = ui.densidade_da_janela(self)
        if abs(agora - getattr(self, "_densidade", 1.0)) < 0.01:
            return
        self._densidade = agora
        ui.aplicar_escala(self, agora)
        ui.aplicar_estilo(self)
        if self._nav_atual == "emitir":
            # Remontar seria recomeçar a nota. Quem arrastou a janela não
            # pediu isso. A escala nova vale da próxima tela em diante.
            return
        self._redesenhar()

    def _redesenhar(self) -> None:
        """Repinta a moldura e remonta a tela atual com a paleta em vigor."""
        self.configure(bg=ui.BG)
        self.principal.configure(bg=ui.BG)
        self.cabecalho.configure(bg=ui.BG)
        self.divisoria.configure(bg=ui.BORDER)
        self.divisoria_topo.configure(bg=ui.BORDER)
        self.rolagem.pintar(ui.BG)
        self.content.configure(bg=ui.BG)
        # A barra inteira é refeita: ela desenha o degradê da marca e a forma
        # do realce, e nenhum dos dois se repinta com `configure`.
        if self.comando is not None:
            self.comando.destroy()
        self.divisoria_topo.pack_forget()
        self._montar_comando()
        # Os avisos abertos foram desenhados com a paleta antiga.
        self.avisos.limpar()
        # "ajustes" — é a chave que `show_settings` grava. Enquanto isto dizia
        # "config", trocar o tema estando em Ajustes caía no padrão do `.get`
        # e devolvia a pessoa para a tela de login, com a sessão de pé.
        telas = {
            "emitir": self.show_new_note,
            "notas": self.show_documents,
            "ajustes": self.show_settings,
        }
        telas.get(self._nav_atual, self.show_login)()

    def _mostrar_comando(self, visivel: bool) -> None:
        """A barra de comando só existe depois do login — antes não há aonde ir.

        A pergunta é `winfo_manager`, não `winfo_ismapped`: o segundo responde
        "não" enquanto a janela ainda não apareceu, e a barra acabaria
        empilhada de novo a cada troca de tela.
        """
        if self.comando is None:
            return
        gerenciada = bool(self.comando.winfo_manager())
        if visivel and not gerenciada:
            self.comando.pack(side="top", fill="x", before=self.principal)
            self.divisoria_topo.pack(side="top", fill="x", before=self.principal)
        elif not visivel and gerenciada:
            self.comando.pack_forget()
            self.divisoria_topo.pack_forget()

    def _clear(self) -> None:
        for widget in self.content.winfo_children():
            widget.destroy()
        for widget in self.cabecalho.winfo_children():
            widget.destroy()
        self.rolagem.canvas.yview_moveto(0)

    def _title(self, titulo: str, subtitulo: str) -> tk.Frame:
        """A área das ações da tela. NÃO desenha mais título nem subtítulo.

        A barra de comando no topo já diz o nome do programa e qual seção está
        aberta. Repetir isso num título de 22pt com subtítulo gastava uns 90px
        de altura — numa área útil de 728px, um oitavo da tela dizendo o que
        já estava dito.

        A assinatura continua a mesma para as telas não precisarem mudar; o
        que elas passam em `titulo` vira o nome da janela, onde é útil.
        """
        self.title(f"{marca.ASSINATURA} · {titulo}")
        acoes = tk.Frame(self.cabecalho, bg=ui.BG)
        acoes.pack(side="right", anchor="e")
        return acoes

    def _selos_do_cabecalho(self, pai: tk.Widget | None = None) -> tk.Frame:
        """Empresa conectada e ambiente, à vista no alto de toda tela.

        O modo de transmissão aparece na barra lateral e aqui. Repetição de
        propósito: é a informação que muda o significado de apertar "Emitir",
        e ela precisa estar no campo de visão de quem vai apertar.
        """
        caixa = tk.Frame(pai or self.cabecalho, bg=ui.BG)
        if self.empresa_logada:
            tk.Label(caixa, text=self.empresa_logada[:40], bg=ui.BG, fg=ui.INK_2,
                     font=ui.PEQUENO_FORTE).pack(side="left", padx=(0, ui.E2))
        live = config.live_mode()
        ui.pilula(
            caixa, "TRANSMISSÃO ATIVA" if live else "MODO SEGURO",
            tom="alerta" if live else "neutro", fundo=ui.BG,
        ).pack(side="left")
        return caixa

    # ------------------------------------------------------------------ #
    # Login
    # ------------------------------------------------------------------ #

    def show_login(self) -> None:
        """Entrada do portal. A senha não é gravada em lugar nenhum."""
        self._clear()
        self._mostrar_comando(False)
        self._nav_atual = ""

        centro = tk.Frame(self.content, bg=ui.BG)
        centro.pack(expand=True, pady=(ui.E6, 0))

        topo = tk.Frame(centro, bg=ui.BG)
        topo.pack(pady=(0, ui.E5))
        tk.Label(topo, text="NF", bg=ui.PRIMARIA, fg="white",
                 font=(ui.FAMILIA, 15, "bold"), padx=12, pady=7).pack()
        tk.Label(centro, text="Entrar no portal", bg=ui.BG, fg=ui.INK,
                 font=ui.DISPLAY).pack()
        tk.Label(centro, text="Use o login da empresa que vai emitir a nota.",
                 bg=ui.BG, fg=ui.INK_3, font=ui.SUBTITULO).pack(pady=(4, ui.E5))

        caixa = ui.cartao(centro, padx=ui.E6, pady=ui.E6)
        caixa.pack()
        form = caixa.interior
        form.columnconfigure(0, minsize=ui.px(380))

        ui.etiqueta_campo(form, "Usuário (inscrição municipal)").grid(row=0, column=0, sticky="w")
        usuario = ttk.Entry(form, font=(ui.FAMILIA, 12))
        usuario.grid(row=1, column=0, sticky="ew", pady=(ui.E2, ui.E4))
        usuario.insert(0, os.environ.get("NFSE_USUARIO", ""))

        ui.etiqueta_campo(form, "Senha").grid(row=2, column=0, sticky="w")
        senha = ttk.Entry(form, font=(ui.FAMILIA, 12), show="•")
        senha.grid(row=3, column=0, sticky="ew", pady=(ui.E2, ui.E2))
        senha.insert(0, os.environ.get("NFSE_SENHA", ""))

        # O aviso tem de bater com a realidade: se a senha veio do .env, dizer
        # que ela "não é gravada em disco" seria mentira ao lado de um campo
        # preenchido a partir do disco.
        no_arquivo = config.senha_no_arquivo()
        ui.rotulo(
            form,
            "Senha lida do arquivo .env. O programa não grava senha;\n"
            "para tirá-la do disco, apague a linha NFSE_SENHA de lá."
            if no_arquivo
            else "A senha fica só nesta sessão — não é gravada em disco.",
            fonte=ui.MICRO, cor=ui.ALERTA if no_arquivo else ui.INK_3, justify="left",
        ).grid(row=4, column=0, sticky="w", pady=(0, ui.E5))

        entrar = ttk.Button(form, text="Entrar", style="Primaria.TButton")
        entrar.grid(row=5, column=0, sticky="ew", ipady=4)

        recado = tk.Frame(form, bg=ui.SURFACE)
        recado.grid(row=6, column=0, sticky="w", pady=(ui.E3, 0))
        girador_login = ui.Girador(recado, fundo=ui.SURFACE, lado=14)
        estado = tk.Label(recado, text="", bg=ui.SURFACE, fg=ui.ERRO,
                          font=ui.PEQUENO, wraplength=ui.px(380), justify="left")
        estado.pack(side="left")

        def esperando_o_portal(ligado: bool) -> None:
            """O girador aparece enquanto o portal não responde."""
            if ligado:
                girador_login.pack(side="left", padx=(0, ui.E2), before=estado)
                girador_login.girar()
            else:
                girador_login.parar()
                girador_login.pack_forget()

        self._assinatura(centro, ui.BG, ui.INK_3).pack(pady=(ui.E5, 0))

        def concluir(nome: str) -> None:
            esperando_o_portal(False)
            entrar.state(["!disabled"])
            entrar.configure(text="Entrar")
            self.empresa_logada = nome
            self._refresh_mode_label()
            self._aquecer_o_portal()
            self.show_documents()

        def falhar(mensagem: str) -> None:
            esperando_o_portal(False)
            entrar.state(["!disabled"])
            entrar.configure(text="Entrar")
            estado.configure(text=mensagem, fg=ui.ERRO)

        def tentar() -> None:
            estado.configure(text="")
            login, chave = usuario.get().strip(), senha.get().strip()
            if not login or not chave:
                estado.configure(text="Preencha usuário e senha.")
                return
            entrar.state(["disabled"])
            entrar.configure(text="Entrando…")
            estado.configure(text="Falando com o portal…", fg=ui.INK_3)
            esperando_o_portal(True)

            def trabalho() -> None:
                try:
                    nome = session.get_session().autenticar(login, chave)
                except Exception as exc:
                    mensagem = str(exc).splitlines()[0]
                    self._na_interface(lambda: falhar(mensagem))
                    return
                self._na_interface(lambda: concluir(nome))

            threading.Thread(target=trabalho, daemon=True).start()

        entrar.configure(command=tentar)
        senha.bind("<Return>", lambda _e: tentar())
        usuario.bind("<Return>", lambda _e: senha.focus_set())
        (senha if usuario.get() else usuario).focus_set()

    def _aquecer_o_portal(self) -> None:
        """Traz para a memória o que a emissão vai pedir, antes de ser pedido.

        `prestador.do_portal()` é uma ida à rede na primeira vez de cada
        empresa, e quem a chama é o botão de emitir — na thread da tela. Feita
        aqui, a resposta já está guardada quando o clique chegar, e o clique
        não espera por rede nenhuma.

        Falhar aqui não é problema: quem precisa do dado torna a pedir, e aí
        o erro aparece no lugar certo, com a nota na frente.
        """
        def trabalho() -> None:
            try:
                prestador.do_portal()
            except Exception as exc:
                registro.falha("aquecer dados do prestador", exc)

        threading.Thread(target=trabalho, daemon=True).start()

    def sair(self) -> None:
        if not messagebox.askyesno("Trocar de empresa", "Encerrar a sessão desta empresa?"):
            return
        session.get_session().encerrar()
        self.empresa_logada = ""
        self._refresh_mode_label()
        self.show_login()

    # ------------------------------------------------------------------ #
    # Painel
    # ------------------------------------------------------------------ #

    @staticmethod
    def _valor_da_nota(doc: dict[str, Any]) -> Decimal:
        """O valor de uma nota, ou zero quando ele estiver ilegível.

        Somar não pode ser o que impede o painel de abrir: um rascunho com
        valor mal digitado vale zero aqui e continua visível na lista.
        """
        bruto = (doc.get("payload") or {}).get("servico", {}).get("valor")
        try:
            return validation.normalize_money(str(bruto or "0"))
        except (validation.ValidationError, ArithmeticError, TypeError):
            return Decimal("0")

    def _resumo_por_empresa(self, onde: tk.Widget, emitidas: list[dict[str, Any]]) -> None:
        """Quanto cada login faturou — a pergunta de quem emite por várias.

        Fica no mesmo lugar que o painel de detalhe ocupa na tela de Notas:
        as duas telas têm a mesma divisão, e o olho não precisa reaprender.
        """
        por_empresa: dict[str, Decimal] = {}
        for doc in emitidas:
            quem = self.prestador_do_doc(doc)
            por_empresa[quem] = por_empresa.get(quem, Decimal("0")) + self._valor_da_nota(doc)
        total = sum(por_empresa.values(), Decimal("0"))

        caixa = ui.cartao(onde, raio=14, padx=0, pady=0)
        caixa.pack(fill="x")
        capa = tk.Frame(caixa.interior, bg=ui.SURFACE_ALT, padx=ui.E4, pady=ui.E4)
        capa.pack(fill="x")
        tk.Label(capa, text=f"R$ {validation.format_money(total)}", bg=ui.SURFACE_ALT,
                 fg=ui.INK, font=(ui.FAMILIA, 21, "bold")).pack(anchor="w")
        tk.Label(capa, text="faturado, somando as empresas", bg=ui.SURFACE_ALT,
                 fg=ui.INK_2, font=ui.PEQUENO).pack(anchor="w", pady=(3, 0))

        corpo = tk.Frame(caixa.interior, bg=ui.SURFACE, padx=ui.E4, pady=ui.E4)
        corpo.pack(fill="x")
        if not por_empresa:
            tk.Label(corpo, text="Nenhuma nota emitida ainda.", bg=ui.SURFACE,
                     fg=ui.INK_3, font=ui.PEQUENO).pack(anchor="w")
            return
        for quem, valor in sorted(por_empresa.items(), key=lambda item: -item[1]):
            linha = tk.Frame(corpo, bg=ui.SURFACE)
            linha.pack(fill="x", pady=(0, ui.E2))
            tk.Label(linha, text=f"R$ {validation.format_money(valor)}",
                     bg=ui.SURFACE, fg=ui.INK, font=(ui.MONO, 10)).pack(side="right")
            nome = tk.Label(linha, bg=ui.SURFACE, fg=ui.INK_2, font=ui.PEQUENO,
                            anchor="w")
            nome.pack(side="left", fill="x", expand=True)
            # Cortar no 26.o caractere deixava "INDUSTRIA" pendurado, sem sinal
            # de que havia mais nome. A largura e fixa de proposito: a coluna
            # tem tamanho proprio, e pedir mais que isso a faria roubar espaco
            # da lista de notas.
            ui.encurtar(nome, quem, 190)

    def _historico_lateral(self, onde: tk.Widget, quantas: int = 7) -> None:
        """As últimas notas que saíram, ao lado de quem está emitindo a próxima.

        Responde de olho a pergunta que se faz depois de clicar em emitir:
        "saiu?". Mostra as mais recentes de todas as empresas, com o nome do
        prestador em cada linha, porque este programa emite por vários logins
        e esconder isso faria a lista mentir sobre de quem é cada nota.
        """
        docs = sorted(storage.list_all(),
                      key=lambda doc: str(doc.get("created_at") or ""), reverse=True)
        emitidas = [doc for doc in docs if doc.get("status") == "submitted"]

        caixa = ui.cartao(onde, raio=14, padx=0, pady=0)
        caixa.pack(fill="x")

        capa = tk.Frame(caixa.interior, bg=ui.SURFACE_ALT, padx=ui.E4, pady=ui.E4)
        capa.pack(fill="x")
        tk.Label(capa, text="ÚLTIMAS EMITIDAS", bg=ui.SURFACE_ALT, fg=ui.INK_3,
                 font=ui.MICRO).pack(anchor="w")
        tk.Label(capa, text=str(len(emitidas)), bg=ui.SURFACE_ALT, fg=ui.INK,
                 font=(ui.FAMILIA, 21, "bold")).pack(anchor="w")
        tk.Label(capa, text="notas no histórico deste computador",
                 bg=ui.SURFACE_ALT, fg=ui.INK_2, font=ui.PEQUENO).pack(anchor="w")

        corpo = tk.Frame(caixa.interior, bg=ui.SURFACE, padx=ui.E4, pady=ui.E3)
        corpo.pack(fill="x")
        if not emitidas:
            tk.Label(corpo, text="Nenhuma nota emitida ainda.", bg=ui.SURFACE,
                     fg=ui.INK_3, font=ui.PEQUENO).pack(anchor="w", pady=ui.E2)
            return

        for doc in emitidas[:quantas]:
            self._linha_do_historico(corpo, doc)

        rodape = tk.Frame(caixa.interior, bg=ui.SURFACE, padx=ui.E4,
                          pady=ui.E3)
        rodape.pack(fill="x")
        # O roxo de PREENCHIMENTO nao serve como TEXTO sobre fundo escuro —
        # dava 4,36:1. INFO e o mesmo roxo na versao que se le: 7,01:1.
        ver_todas = tk.Label(rodape, text=f"Ver todas as {len(emitidas)}  ›",
                             bg=ui.SURFACE, fg=ui.INFO, font=ui.PEQUENO_FORTE,
                             cursor="hand2")
        ver_todas.pack(anchor="w")
        ver_todas.bind("<Button-1>", lambda _e: self.show_documents())

    def _linha_do_historico(self, onde: tk.Widget, doc: dict[str, Any]) -> None:
        """Uma nota da lateral: número, tomador, valor — e abre ao clicar."""
        payload = doc.get("payload") or {}
        nota = doc.get("nota") or {}
        servico = payload.get("servico") or {}
        tomador = payload.get("tomador") or {}
        documento = str(tomador.get("documento", ""))

        linha = tk.Frame(onde, bg=ui.SURFACE, cursor="hand2", pady=6)
        linha.pack(fill="x")
        linha.columnconfigure(0, weight=1)

        alto = tk.Frame(linha, bg=ui.SURFACE)
        alto.grid(row=0, column=0, sticky="ew")
        numero = tk.Label(alto, text=f"nº {nota.get('numero') or '—'}", bg=ui.SURFACE,
                          fg=ui.INK, font=(ui.MONO, 10), anchor="w")
        numero.pack(side="left")
        valor = tk.Label(
            alto,
            text=("•••" if self._valores_ocultos
                  else f"R$ {validation.format_money(servico.get('valor'))}"),
            bg=ui.SURFACE, fg=ui.INK, font=ui.PEQUENO_FORTE)
        valor.pack(side="right")

        quem = (tomador.get("nome") or validation.format_document(documento)
                or "Sem tomador")
        baixo = tk.Label(linha, text=quem, bg=ui.SURFACE, fg=ui.INK_2,
                         font=ui.PEQUENO, anchor="w")
        baixo.grid(row=1, column=0, sticky="ew")
        pe = tk.Label(linha,
                      text=f"{self.prestador_do_doc(doc)[:22]}  ·  "
                           f"{_ha_quanto(doc.get('created_at')) or _data_br(doc.get('created_at'))}",
                      bg=ui.SURFACE, fg=ui.INK_3, font=ui.MICRO, anchor="w")
        pe.grid(row=2, column=0, sticky="ew")

        risco = tk.Frame(linha, bg=ui.BORDER, height=1)
        risco.grid(row=3, column=0, sticky="ew", pady=(ui.E2, 0))

        filhos = (linha, alto, numero, valor, baixo, pe)
        for widget in filhos:
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", lambda _e, d=doc: self.janela_impressao(
                d.get("nota") or {}, d))
            widget.bind("<Enter>", lambda _e, ws=filhos: [
                w.configure(bg=ui.SURFACE_ALT) for w in ws])
            widget.bind("<Leave>", lambda _e, ws=filhos: [
                w.configure(bg=ui.SURFACE) for w in ws])

    # ------------------------------------------------------------------ #
    # Emissão
    # ------------------------------------------------------------------ #

    def show_new_note(self) -> None:
        """Tela de emissão: só o que muda de uma nota para outra.

        Nome do tomador, competência e alíquota não aparecem porque não variam
        por nota — o portal resolve o nome pelo CNPJ, a competência é sempre o
        dia da emissão e a alíquota é uma propriedade do código de serviço.
        """
        self._clear()
        self._mostrar_comando(True)
        self._marcar_nav("emitir")
        self._title("Emitir NFS-e", "Preencha o serviço e emita a nota.")

        defaults = service.template_defaults()

        # Mesma divisão das outras telas: o que se faz à esquerda, o que já
        # foi feito à direita. Aqui isso vale dobrado — quem emite quer ver a
        # nota anterior sem sair do formulário e perder o que digitou.
        colunas = tk.Frame(self.content, bg=ui.BG)
        colunas.pack(fill="both", expand=True)
        formulario, lateral = self.duas_colunas(colunas, largura=340)

        passo_tomador = self._degrau(formulario, 1, "Tomador",
                                     "Quem recebe a nota — em branco emite sem tomador")
        passo_servico = self._degrau(
            formulario, 2, "Serviço",
            "Código, NBS e a descrição como ela sai escrita na nota")
        passo_valores = self._degrau(formulario, 3, "Valores e local",
                                     "O ISS é calculado enquanto você digita")
        self._historico_lateral(lateral)
        # `form` continua existindo como nome para o que ainda não tem degrau
        # próprio; os widgets abaixo já nascem no passo a que pertencem.
        form = passo_valores

        # A barra do rodapé nasce aqui porque o botão de emitir é filho dela:
        # o Tk só empacota um widget dentro do próprio pai.
        barra_resumo = ui.cartao(formulario, raio=14, padx=ui.E5, pady=ui.E3)
        barra_resumo.pack(fill="x", pady=(ui.E2, 0))
        rodape_emissao = barra_resumo.interior

        # --- Tomador ----------------------------------------------------- #
        cabeca = tk.Frame(passo_tomador, bg=ui.SURFACE)
        cabeca.grid(row=0, column=0, columnspan=2, sticky="ew")
        ui.etiqueta_campo(cabeca, "CNPJ / CPF do tomador").pack(side="left")
        ui.rotulo(cabeca, "clique em Buscar para trazer os dados", fonte=ui.MICRO,
                  cor=ui.INK_3).pack(side="right")
        linha_doc = tk.Frame(passo_tomador, bg=ui.SURFACE)
        linha_doc.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(ui.E2, 2))
        linha_doc.columnconfigure(0, weight=1)
        documento = ttk.Entry(linha_doc, font=(ui.FAMILIA, 13))
        documento.grid(row=0, column=0, sticky="ew")
        botao_buscar = ttk.Button(linha_doc, text="Buscar")
        botao_buscar.grid(row=0, column=1, padx=(ui.E2, 0))
        girador_tomador = ui.Girador(linha_doc, fundo=ui.SURFACE, lado=16)
        if defaults.get("tomador.documento"):
            documento.insert(0, validation.format_document(defaults["tomador.documento"]))

        # --- Dados do tomador --------------------------------------------- #
        # O mesmo bloco serve aos dois casos: achou, mostra os dados do portal
        # travados; não achou, abre os campos para digitar. O portal responde
        # vazio para CNPJ fora do cadastro dele — sem razão social, sem endereço
        # e sem id interno —, então digitar é a única saída.
        situacao_tomador = ui.rotulo(passo_tomador, "Digite o CNPJ e clique em Buscar.",
                                     fonte=ui.MICRO, cor=ui.INK_3,
                                     justify="left", wraplength=620)
        situacao_tomador.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, ui.E4))

        bloco_tomador = tk.Frame(passo_tomador, bg=ui.SURFACE_ALT, padx=ui.E4, pady=ui.E3,
                                 highlightbackground=ui.BORDER, highlightthickness=1)
        bloco_tomador.columnconfigure(1, weight=1)
        bloco_tomador.columnconfigure(3, weight=1)
        campos_tomador: dict[str, Any] = {}
        titulo_tomador = tk.Label(bloco_tomador, text="", font=ui.PEQUENO_FORTE,
                                  fg=ui.ALERTA, bg=ui.SURFACE_ALT)
        titulo_tomador.grid(row=0, column=0, columnspan=4, sticky="w")
        estado_tomador: dict[str, Any] = {"manual": False}

        def _campo_tomador(rotulo_: str, chave: str, linha: int, coluna: int,
                           largura: int = 1, lupa=None) -> None:
            tk.Label(bloco_tomador, text=rotulo_.upper(), font=ui.ETIQUETA, fg=ui.INK_2,
                     bg=ui.SURFACE_ALT).grid(row=linha, column=coluna, sticky="w",
                                             padx=(0, ui.E2), pady=(ui.E2, 1))
            if lupa is None:
                entrada = ttk.Entry(bloco_tomador, font=ui.PEQUENO)
                entrada.grid(row=linha + 1, column=coluna, columnspan=largura,
                             sticky="ew", padx=(0, ui.E2))
            else:
                # O campo divide a célula com o botão de busca.
                caixa = tk.Frame(bloco_tomador, bg=ui.SURFACE_ALT)
                caixa.grid(row=linha + 1, column=coluna, columnspan=largura,
                           sticky="ew", padx=(0, ui.E2))
                caixa.columnconfigure(0, weight=1)
                entrada = ttk.Entry(caixa, font=ui.PEQUENO)
                entrada.grid(row=0, column=0, sticky="ew")
                ttk.Button(caixa, text="🔍", width=3, style="Lupa.TButton",
                           command=lupa).grid(row=0, column=1, padx=(2, 0))
            campos_tomador[chave] = entrada

        _campo_tomador("Razão social", "razao_social", 1, 0, largura=4)
        _campo_tomador("Logradouro", "logradouro", 3, 0, largura=2)
        _campo_tomador("Número", "numero", 3, 2)
        _campo_tomador("Complemento", "complemento", 3, 3)
        _campo_tomador("Bairro", "bairro", 5, 0, largura=2)
        _campo_tomador("CEP", "cep", 5, 2, lupa=lambda: preencher_pelo_cep())
        _campo_tomador("E-mail", "email", 5, 3)

        def preencher_pelo_cep(_evento=None) -> None:
            """Busca o endereço do CEP e completa o que estiver vazio.

            Campo já digitado não é sobrescrito: quem corrigiu o logradouro à
            mão não quer ver a correção sumir.
            """
            if not estado_tomador["manual"]:
                return
            digitado = cep.limpar(campos_tomador["cep"].get())
            if len(digitado) != 8:
                return

            def aplicar(endereco: dict) -> None:
                if not bloco_tomador.winfo_exists():
                    return
                for chave in ("logradouro", "bairro"):
                    entrada = campos_tomador[chave]
                    if endereco.get(chave) and not entrada.get().strip():
                        entrada.insert(0, endereco[chave])
                if endereco.get("uf"):
                    escolher_cidade(endereco["uf"], endereco.get("municipio", ""))
                situacao_tomador.configure(
                    text=f"Endereço do CEP: {endereco.get('cidade', '')}/{endereco.get('uf', '')}",
                    fg=ui.INK_3)

            def trabalho() -> None:
                try:
                    endereco = cep.buscar(digitado)
                except Exception as exc:
                    aviso = str(exc).splitlines()[0][:60]
                    self._na_interface(lambda: situacao_tomador.configure(
                        text=f"CEP: {aviso}", fg=ui.ALERTA))
                    return
                self._na_interface(lambda: aplicar(endereco))

            threading.Thread(target=trabalho, daemon=True).start()

        campos_tomador["cep"].bind("<FocusOut>", preencher_pelo_cep)
        campos_tomador["cep"].bind("<Return>", preencher_pelo_cep)

        # Cidade do cliente. Quem não está no cadastro de São Bernardo costuma
        # ser de fora, então o município é escolhido em vez de assumido.
        rotulo_uf = tk.Label(bloco_tomador, text="UF", font=ui.ETIQUETA, fg=ui.INK_2,
                             bg=ui.SURFACE_ALT)
        rotulo_uf.grid(row=8, column=0, sticky="w", pady=(ui.E2, 1))
        rotulo_municipio = tk.Label(bloco_tomador, text="MUNICÍPIO", font=ui.ETIQUETA,
                                    fg=ui.INK_2, bg=ui.SURFACE_ALT)
        rotulo_municipio.grid(row=8, column=1, sticky="w", padx=(0, ui.E2), pady=(ui.E2, 1))
        uf_tomador = ttk.Combobox(bloco_tomador, font=ui.PEQUENO, width=6)
        uf_tomador.grid(row=9, column=0, sticky="w", padx=(0, ui.E2))
        municipio_tomador = ttk.Combobox(bloco_tomador, font=ui.PEQUENO)
        municipio_tomador.grid(row=9, column=1, columnspan=3, sticky="ew")
        cidades_tomador: dict[str, list] = {"ufs": [], "municipios": []}

        # O portal traz esta caixa marcada por padrão ao cadastrar um cliente
        # novo; aqui é igual, para a próxima nota já achar o CNPJ.
        cadastrar_tomador = tk.BooleanVar(value=True)
        caixa_cadastrar = tk.Checkbutton(
            bloco_tomador, text="  Cadastrar este cliente no portal",
            variable=cadastrar_tomador, bg=ui.SURFACE_ALT,
            activebackground=ui.SURFACE_ALT, selectcolor=ui.SURFACE, fg=ui.INK,
            font=ui.PEQUENO, anchor="w", bd=0, highlightthickness=0, cursor="hand2",
        )
        caixa_cadastrar.grid(row=10, column=0, columnspan=4, sticky="w", pady=(ui.E3, 0))

        def municipio_do_tomador() -> str:
            # Casa pelo texto, não pelo índice: com a lista filtrada por
            # digitação, o índice deixa de corresponder à lista completa.
            escolhido = municipio_tomador.get().strip().upper()
            return next((m["codigo"] for m in cidades_tomador["municipios"]
                         if m["nome"].upper() == escolhido), "")

        def escolher_cidade(sigla: str, codigo_ibge: str = "") -> None:
            """Deixa UF e município já apontando para o endereço encontrado."""
            uf_tomador.set(sigla)
            carregar_cidades_tomador(alvo=codigo_ibge)

        def carregar_ufs_tomador() -> None:
            if cidades_tomador["ufs"]:
                return
            uf_tomador.set("…")

            def aplicar(lista) -> None:
                cidades_tomador["ufs"] = lista
                uf_tomador["values"] = [u["sigla"] for u in lista]
                uf_tomador.set("SP")
                carregar_cidades_tomador()

            def trabalho() -> None:
                try:
                    lista = municipios.ufs()
                except Exception:
                    self._na_interface(lambda: uf_tomador.set(""))
                    return
                self._na_interface(lambda: aplicar(lista))

            threading.Thread(target=trabalho, daemon=True).start()

        def carregar_cidades_tomador(_evento=None, alvo: str = "") -> None:
            sigla = uf_tomador.get().strip().upper()
            uf = next((u for u in cidades_tomador["ufs"] if u["sigla"] == sigla), None)
            if uf is None:
                return
            municipio_tomador.set("consultando…")

            def aplicar(lista) -> None:
                cidades_tomador["municipios"] = lista
                municipio_tomador["values"] = [m["nome"] for m in lista]
                achado = next((m["nome"] for m in lista if m["codigo"] == alvo), "")
                municipio_tomador.set(achado)

            def trabalho() -> None:
                try:
                    lista = municipios.municipios(uf["codigo"])
                except Exception:
                    self._na_interface(lambda: municipio_tomador.set(""))
                    return
                self._na_interface(lambda: aplicar(lista))

            threading.Thread(target=trabalho, daemon=True).start()

        uf_tomador.bind("<<ComboboxSelected>>", carregar_cidades_tomador)
        ui.autocompletar(uf_tomador, lambda: [u["sigla"] for u in cidades_tomador["ufs"]])
        ui.autocompletar(municipio_tomador,
                         lambda: [m["nome"] for m in cidades_tomador["municipios"]])

        def dados_manuais() -> dict[str, str]:
            """O que foi digitado — vazio quando o portal já conhece o cliente."""
            if not estado_tomador["manual"]:
                return {}
            dados = {chave: entrada.get().strip()
                     for chave, entrada in campos_tomador.items()}
            dados["municipio"] = municipio_do_tomador()
            dados["cadastrar"] = cadastrar_tomador.get()
            return dados

        def _preencher(dados: dict[str, str], *, editavel: bool) -> None:
            estado_tomador["manual"] = editavel
            for chave, entrada in campos_tomador.items():
                entrada.configure(state="normal")
                entrada.delete(0, "end")
                if dados.get(chave):
                    entrada.insert(0, dados[chave])
                if not editavel:
                    entrada.configure(state="readonly")
            # Vindo do portal, a cidade já está resolvida lá: mostrar dois
            # campos vazios e travados pareceria dado faltando.
            cidade = (rotulo_uf, rotulo_municipio, uf_tomador, municipio_tomador)
            if editavel:
                # "normal", não "readonly": readonly só deixa escolher da lista,
                # e 645 municípios não se acham arrastando a barra.
                uf_tomador.configure(state="normal")
                municipio_tomador.configure(state="normal")
                for widget in cidade:
                    widget.grid()
                caixa_cadastrar.grid()
            else:
                caixa_cadastrar.grid_remove()
                municipio_tomador.set("")
                for widget in cidade:
                    widget.grid_remove()
            if not bloco_tomador.winfo_manager():
                bloco_tomador.grid(row=3, column=0, columnspan=2, sticky="ew",
                                   pady=(0, ui.E4))
            if editavel:
                carregar_ufs_tomador()

        def esconder_tomador() -> None:
            estado_tomador["manual"] = False
            if bloco_tomador.winfo_manager():
                bloco_tomador.grid_forget()

        def buscar_tomador() -> None:
            """Consulta o CNPJ no portal e decide qual dos dois casos mostrar."""
            digitado = re.sub(r"\D", "", documento.get())
            if len(digitado) not in (11, 14):
                situacao_tomador.configure(
                    text="Informe um CNPJ (14 dígitos) ou CPF (11) para buscar.",
                    fg=ui.ERRO)
                esconder_tomador()
                return
            situacao_tomador.configure(text="Consultando o cliente no portal…", fg=ui.INK_3)
            botao_buscar.state(["disabled"])
            girador_tomador.grid(row=0, column=2, padx=(ui.E2, 0))
            girador_tomador.girar()

            def parou() -> None:
                girador_tomador.parar()
                if girador_tomador.winfo_manager():
                    girador_tomador.grid_forget()

            def achou(dados: dict[str, str]) -> None:
                if not situacao_tomador.winfo_exists():
                    return
                parou()
                botao_buscar.state(["!disabled"])
                nome = dados.get("razao_social") or digitado
                situacao_tomador.configure(text=f"Cliente encontrado no portal: {nome}",
                                           fg=ui.SUCESSO)
                titulo_tomador.configure(text="DADOS DO CLIENTE (vindos do portal)",
                                         fg=ui.SUCESSO)
                _preencher(dados, editavel=False)

            def nao_achou() -> None:
                if not situacao_tomador.winfo_exists():
                    return
                parou()
                botao_buscar.state(["!disabled"])
                situacao_tomador.configure(
                    text="O portal não tem este CNPJ cadastrado — preencha os dados abaixo.",
                    fg=ui.ALERTA)
                titulo_tomador.configure(text="DADOS DO CLIENTE (preencha — o portal não tem)",
                                         fg=ui.ALERTA)
                _preencher({}, editavel=True)

            def falhou(mensagem: str) -> None:
                if situacao_tomador.winfo_exists():
                    parou()
                    botao_buscar.state(["!disabled"])
                    situacao_tomador.configure(text=f"Não consegui consultar: {mensagem}",
                                               fg=ui.ERRO)

            def trabalho() -> None:
                import tomador as tomador_portal

                try:
                    dados = tomador_portal.consultar(digitado, recarregar=True)
                except tomador_portal.NaoEncontrado:
                    self._na_interface(nao_achou)
                    return
                except Exception as exc:
                    aviso = str(exc).splitlines()[0][:70]
                    self._na_interface(lambda: falhou(aviso))
                    return
                self._na_interface(lambda: achou(dados))

            threading.Thread(target=trabalho, daemon=True).start()

        botao_buscar.configure(command=buscar_tomador)
        documento.bind("<Return>", lambda _e: buscar_tomador())

        # --- Serviço ----------------------------------------------------- #
        cabeca_servico = tk.Frame(passo_servico, bg=ui.SURFACE)
        cabeca_servico.grid(row=0, column=0, columnspan=2, sticky="ew")
        ui.etiqueta_campo(cabeca_servico, "Código do serviço").pack(side="left")
        ui.rotulo(cabeca_servico, "lista do portal para esta empresa", fonte=ui.MICRO,
                  cor=ui.INK_3).pack(side="right")

        catalogo = services.em_cache()

        def rotulo_de(servico: dict) -> str:
            return f"{servico['codigo']}  —  {servico['nome']}"

        rotulos = [rotulo_de(s) for s in catalogo]
        codigo_box = ttk.Combobox(passo_servico, values=rotulos, font=ui.CORPO)
        codigo_box.grid(row=1, column=0, sticky="ew", pady=(ui.E2, ui.E3))
        ui.autocompletar(codigo_box, lambda: [rotulo_de(s) for s in catalogo])
        if rotulos:
            codigo_box.current(0)

        def codigo_escolhido() -> str:
            """O código do serviço escolhido, resolvido pelo texto.

            Pelo índice (``current()``) não serve: assim que a lista filtra ao
            digitar, o índice passa a ser o da lista filtrada, e a nota sairia
            com o serviço errado — que é dos erros mais caros que existem aqui.
            """
            escrito = codigo_box.get().strip()
            for servico in catalogo:
                # Comparar os dois lados aparados: o Tk devolve o texto do
                # campo, e nomes vindos do portal trazem espaço no fim com
                # frequência. Comparando um aparado com outro não, o serviço
                # ficava irreconhecível e a emissão era barrada sem motivo
                # aparente — aconteceu com 15 dos 200 itens da LC 116.
                if rotulo_de(servico).strip() == escrito:
                    return servico["codigo"]
            return ""

        def atualizar_lista() -> None:
            """Pergunta ao portal quais serviços a empresa logada tem."""
            try:
                encontrados = services.disponiveis(atualizar=True)
            except Exception as exc:
                messagebox.showerror("Não foi possível consultar", str(exc))
                return
            catalogo[:] = encontrados
            codigo_box["values"] = [f"{s['codigo']}  —  {s['nome']}" for s in encontrados]
            if encontrados:
                codigo_box.current(0)
            carregar_nbs()
            self._info(
                "Serviços atualizados",
                f"{len(encontrados)} serviço(s) habilitado(s) para esta empresa.",
            )

        def ajustar_aliquota() -> None:
            escolhido = codigo_escolhido()
            if not escolhido:
                return
            resposta = self._pedir_aliquota(escolhido, config.aliquota_do_servico(escolhido))
            if resposta is None:
                return
            try:
                validation.normalize_rate(resposta)
            except validation.ValidationError as exc:
                self._alerta("Alíquota inválida", exc.message)
                return
            config.definir_aliquota(escolhido, resposta.strip())
            atualizar_resumo()

        acoes_servico = tk.Frame(passo_servico, bg=ui.SURFACE)
        acoes_servico.grid(row=1, column=1, sticky="e", padx=(ui.E2, 0), pady=(ui.E2, ui.E3))
        ttk.Button(acoes_servico, text="Alíquota", style="Discreto.TButton",
                   command=ajustar_aliquota).pack(side="left", padx=(0, ui.E2))
        ttk.Button(acoes_servico, text="Atualizar", style="Discreto.TButton",
                   command=atualizar_lista).pack(side="left")

        # --- Reforma tributária (IBS/CBS) --------------------------------- #
        # Quatro campos que a prefeitura passou a exigir em 24/08/2026. Sem
        # eles a nota não é recusada com mensagem: o servidor lança exceção e
        # responde HTTP 500 sem dizer por quê.
        #
        # O encadeamento evita escolha à toa: o serviço define quais NBS cabem
        # (675 viram algumas dezenas), e o NBS define o indicador de operação e
        # a classificação tributária. Só sobra escolha quando a tabela oferece
        # mais de uma alternativa.
        # Quem entra na grade é o CARTÃO; `.interior` é só onde os campos
        # moram. Guardar o interior na variável e chamar `.grid()` nele o
        # coloca dentro do próprio canvas do cartão — e o cartão fica sem
        # gerenciador de geometria, isto é, nunca é desenhado. Foi assim que
        # o NBS sumiu: existia, com a lista carregada, fora da tela.
        caixa_reforma = ui.cartao(passo_servico, raio=12, fundo=ui.SURFACE_ALT,
                                  padx=ui.E4, pady=ui.E4)
        caixa_reforma.grid(row=2, column=0, columnspan=2, sticky="ew",
                           pady=(0, ui.E4))
        bloco_reforma = caixa_reforma.interior
        bloco_reforma.columnconfigure(0, weight=1)
        bloco_reforma.columnconfigure(1, weight=1)

        tk.Label(bloco_reforma, text="Reforma tributária (IBS/CBS)",
                 bg=ui.SURFACE_ALT, fg=ui.INK, font=ui.PEQUENO_FORTE).grid(
                     row=0, column=0, columnspan=2, sticky="w")
        aviso_reforma = ui.rotulo(
            bloco_reforma, "Preenchido pela tabela de correlação a partir do NBS.",
            fonte=ui.MICRO, cor=ui.INK_3, fundo=ui.SURFACE_ALT, justify="left")
        aviso_reforma.grid(row=1, column=0, columnspan=2, sticky="w", pady=(1, ui.E3))

        ui.etiqueta_campo(bloco_reforma, "NBS",
                          fundo=ui.SURFACE_ALT).grid(row=2, column=0, sticky="w")
        nbs_box = ttk.Combobox(bloco_reforma, font=ui.PEQUENO)
        nbs_box.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(ui.E2, ui.E3))

        ui.etiqueta_campo(bloco_reforma, "Código Indicador da Operação",
                          fundo=ui.SURFACE_ALT).grid(
            row=4, column=0, sticky="w")
        ui.etiqueta_campo(bloco_reforma, "Classificação Tributária",
                          fundo=ui.SURFACE_ALT).grid(
            row=4, column=1, sticky="w", padx=(ui.E2, 0))
        indop_box = ttk.Combobox(bloco_reforma, font=ui.PEQUENO)
        indop_box.grid(row=5, column=0, sticky="ew", pady=(ui.E2, ui.E3))
        classe_box = ttk.Combobox(bloco_reforma, font=ui.PEQUENO)
        classe_box.grid(row=5, column=1, sticky="ew", padx=(ui.E2, 0), pady=(ui.E2, ui.E3))

        ui.etiqueta_campo(bloco_reforma, "Situação Tributária (CST-IBS/CBS)",
                          fundo=ui.SURFACE_ALT).grid(
            row=6, column=0, sticky="w")
        cst_box = ttk.Combobox(bloco_reforma, font=ui.PEQUENO)
        cst_box.grid(row=7, column=0, sticky="ew", pady=(ui.E2, 0))

        catalogos_reforma: dict[str, list[dict]] = {"nbs": [], "cst": []}

        def _rotulo(item: dict) -> str:
            return f"{item['codigo']}  —  {item['descricao']}" if item.get("descricao") \
                else str(item.get("codigo", ""))

        def _codigo_de(caixa: ttk.Combobox, lista: list[dict]) -> str:
            """O código escolhido, resolvido pelo texto — nunca pelo índice.

            Mesmo motivo do código de serviço: com a lista filtrando ao digitar,
            o índice passa a ser o da lista filtrada.
            """
            escrito = caixa.get().strip()
            for item in lista:
                # Aparado dos dois lados, pelo mesmo motivo do código de
                # serviço: descrição com espaço no fim tornaria o código
                # irreconhecível.
                if _rotulo(item).strip() == escrito or item["codigo"].strip() == escrito:
                    return item["codigo"]
            return ""

        def nbs_escolhido() -> str:
            return _codigo_de(nbs_box, catalogos_reforma["nbs"])

        def preencher_pelo_nbs(_evento=None) -> None:
            """Indicador e classificação saem do NBS, conforme a planilha."""
            escolhido = nbs_escolhido()
            opcoes = reforma.opcoes_do_nbs(codigo_escolhido(), escolhido) if escolhido \
                else {"indop": [], "classificacao": []}
            for caixa, chave, geral in ((indop_box, "indop", "indicador_operacao"),
                                        (classe_box, "classificacao", "classificacao_tributaria")):
                sugeridos = opcoes[chave]
                # Sem sugestão da tabela, oferece tudo que o portal aceita —
                # esconder a opção certa seria pior que mostrar demais.
                lista = sugeridos or _tabela_do_portal(geral)
                catalogos_reforma[chave] = lista
                caixa["values"] = [_rotulo(i) for i in lista]
                ui.autocompletar(caixa, lambda l=lista: [_rotulo(i) for i in l])
                # Só preenche sozinho o que a tabela de fato responde. Sem
                # resposta, o campo fica **vazio** em vez de mostrar o primeiro
                # da lista geral: um código plausível já escolhido passa
                # despercebido, e aqui isso sai como tributo errado na nota.
                caixa.set(_rotulo(sugeridos[0]) if sugeridos else "")

            if not escolhido:
                texto, cor = "Escolha o NBS — os outros dois se preenchem sozinhos.", ui.INK_3
            elif not opcoes["indop"] or not opcoes["classificacao"]:
                texto, cor = ("A tabela não traz todos os códigos para este NBS. "
                              "Escolha você mesmo e confira antes de emitir."), ui.ALERTA
            else:
                texto, cor = "Preenchido pela tabela de correlação a partir do NBS.", ui.INK_3
            aviso_reforma.configure(text=texto, fg=cor)
            atualizar_resumo()

        def _tabela_do_portal(campo: str) -> list[dict]:
            """Só o que está em disco. A rede é assunto de segundo plano."""
            try:
                return reforma.opcoes(campo, rede=False)
            except Exception as exc:
                registro.falha(f"tabela {campo}", exc)
                return []

        def carregar_nbs(_evento=None) -> None:
            """A lista de NBS do serviço escolhido."""
            servico = codigo_escolhido()
            try:
                lista = reforma.nbs_do_servico(servico) if servico else []
            except Exception as exc:
                registro.falha("lista de NBS", exc)
                lista = []
            catalogos_reforma["nbs"] = lista
            nbs_box["values"] = [_rotulo(i) for i in lista]
            ui.autocompletar(nbs_box, lambda: [_rotulo(i) for i in catalogos_reforma["nbs"]])
            # Um único NBS possível não é escolha: 83 dos 200 itens da LC 116
            # têm um só, e pedir confirmação neles seria só atrito.
            nbs_box.set(_rotulo(lista[0]) if len(lista) == 1 else "")
            preencher_pelo_nbs()

        nbs_box.bind("<<ComboboxSelected>>", preencher_pelo_nbs)
        nbs_box.bind("<Return>", preencher_pelo_nbs)

        def montar_cst() -> None:
            """CST não vem da planilha; o padrão é 000 (tributação integral)."""
            lista = _tabela_do_portal("situacao_tributaria")
            catalogos_reforma["cst"] = lista
            cst_box["values"] = [_rotulo(i) for i in lista]
            ui.autocompletar(cst_box, lambda: [_rotulo(i) for i in catalogos_reforma["cst"]])
            padrao = next((i for i in lista if i["codigo"] == reforma.CST_PADRAO), None)
            cst_box.set(_rotulo(padrao) if padrao else reforma.CST_PADRAO)

        # --- Valor e descrição ------------------------------------------- #
        ui.etiqueta_campo(form, "Valor do serviço (R$)").grid(row=0, column=0, sticky="w")
        valor = ttk.Entry(form, font=(ui.FAMILIA, 17))
        valor.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(ui.E2, ui.E3))

        # Quem recolhe o ISS. Fica ao lado do valor porque muda o líquido da
        # nota — e antes saía retido sem ninguém escolher.
        iss_retido = tk.BooleanVar(value=False)
        caixa_retencao = tk.Checkbutton(
            form, text="  ISS retido pelo tomador", variable=iss_retido,
            command=lambda: atualizar_resumo(), bg=ui.SURFACE,
            activebackground=ui.SURFACE, selectcolor=ui.SURFACE, fg=ui.INK,
            font=ui.CORPO, anchor="w", bd=0, highlightthickness=0, cursor="hand2",
        )

        def conferir_retencao() -> None:
            """A caixa só existe se o portal oferecer a retenção a esta empresa.

            Uma nota emitida com "ISS retido" marcado saiu sem retenção porque o
            portal nem dava a opção. Campo que não faz nada é pior que campo
            nenhum: faz acreditar num imposto que não vai acontecer.
            """
            def aplicar(liberado: bool) -> None:
                if not caixa_retencao.winfo_exists():
                    return
                if liberado:
                    caixa_retencao.grid(row=10, column=0, columnspan=2, sticky="w",
                                        pady=(0, ui.E3))
                else:
                    iss_retido.set(False)
                    caixa_retencao.grid_forget()
                atualizar_resumo()

            def trabalho() -> None:
                try:
                    liberado = recursos.pode_reter_iss()
                except Exception:
                    liberado = False  # sem resposta, não oferece o que não se sabe
                self._na_interface(lambda: aplicar(liberado))

            threading.Thread(target=trabalho, daemon=True).start()

        faixa = tk.Frame(form, bg=ui.SURFACE_ALT, padx=ui.E4, pady=ui.E3,
                         highlightbackground=ui.BORDER, highlightthickness=1)
        faixa.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, ui.E3))
        resumo = tk.Label(faixa, text="", bg=ui.SURFACE_ALT, fg=ui.INK_2, font=ui.PEQUENO,
                          anchor="w", justify="left")
        resumo.pack(anchor="w")

        # --- Obra (só nos serviços que exigem) ---------------------------- #
        # O campo não fica sempre visível de propósito: pedir Código da Obra
        # numa nota de usinagem confunde, e é campo que só a construção civil
        # usa. Ele aparece quando o serviço escolhido exige.
        obra_bloco = tk.Frame(form, bg=ui.SURFACE)
        ui.etiqueta_campo(obra_bloco, "Obra").pack(anchor="w")
        # Combobox editável: escolhe da lista da empresa quando ela existe, e
        # aceita o código digitado enquanto a consulta ao portal não existe.
        catalogo_obras = obras.disponiveis()
        obra = ttk.Combobox(obra_bloco, font=(ui.FAMILIA, 11),
                            values=[obras.rotulo(o) for o in catalogo_obras])
        obra.pack(fill="x", pady=(ui.E2, 2))
        aviso_obra = ui.rotulo(obra_bloco, "", fonte=ui.MICRO, cor=ui.INK_3,
                               justify="left", wraplength=620)
        aviso_obra.pack(anchor="w")

        def obra_escolhida() -> str:
            """Código da obra: da lista quando escolhida, ou o que foi digitado."""
            posicao = obra.current()
            if 0 <= posicao < len(catalogo_obras):
                return catalogo_obras[posicao]["codigo"]
            return obra.get().split("  —  ")[0].strip()

        def alternar_obra() -> None:
            """Mostra ou esconde o campo conforme o serviço escolhido."""
            if not config.exige_obra(codigo_escolhido()):
                if obra_bloco.winfo_manager():
                    obra_bloco.grid_forget()
                return
            if not obra_bloco.winfo_manager():
                obra_bloco.grid(row=2, column=0, columnspan=2, sticky="ew",
                                pady=(0, ui.E4))
            aviso_obra.configure(
                text=("Obrigatório neste serviço." if catalogo_obras
                      else "Obrigatório neste serviço — consultando as obras…"),
                fg=ui.INK_3,
            )
            if catalogo_obras or escolha_uf.get("obras_consultadas"):
                return
            escolha_uf["obras_consultadas"] = True

            def aplicar_obras(lista: list[dict[str, str]]) -> None:
                catalogo_obras[:] = lista
                obra["values"] = [obras.rotulo(o) for o in lista]
                aviso_obra.configure(
                    text=("Obrigatório neste serviço." if lista else
                          "Obrigatório neste serviço. Não reconheci obras na resposta "
                          "do portal — digite o código, e veja Configurações → "
                          "\"Ver obras (bruto)\" para eu corrigir a leitura."),
                    fg=ui.INK_3 if lista else ui.ALERTA,
                )

            def buscar_obras() -> None:
                try:
                    lista = obras.do_portal()
                except Exception as exc:
                    aviso = str(exc).splitlines()[0][:60]
                    self._na_interface(lambda: aviso_obra.configure(
                        text=f"Não consegui consultar as obras: {aviso}. "
                             f"Digite o código que aparece no portal.", fg=ui.ALERTA))
                    return
                self._na_interface(lambda: aplicar_obras(lista))

            threading.Thread(target=buscar_obras, daemon=True).start()

        # --- Local da prestação ------------------------------------------- #
        local = tk.Frame(form, bg=ui.SURFACE)
        local.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 0))
        local.columnconfigure(1, weight=1)
        fora = tk.BooleanVar(value=False)
        escolha_uf: dict[str, Any] = {"ufs": [], "municipios": []}

        uf_box = ttk.Combobox(local, state="disabled", font=ui.PEQUENO, width=18)
        municipio_box = ttk.Combobox(local, state="disabled", font=ui.PEQUENO)

        def municipio_escolhido() -> str:
            if not fora.get():
                return ""
            escolhido = municipio_box.get().strip().upper()
            return next((m["codigo"] for m in escolha_uf["municipios"]
                         if m["nome"].upper() == escolhido), "")

        def carregar_municipios(_evento=None) -> None:
            sigla = uf_box.get().strip().upper()
            uf = next((u for u in escolha_uf["ufs"] if u["sigla"] == sigla), None)
            if uf is None:
                return
            codigo = uf["codigo"]
            municipio_box.set("consultando o portal…")
            municipio_box.configure(state="disabled")

            def aplicar(lista: list[dict[str, str]]) -> None:
                escolha_uf["municipios"] = lista
                municipio_box["values"] = [m["nome"] for m in lista]
                municipio_box.configure(state="normal")
                municipio_box.set("")
                atualizar_resumo()

            def trabalho() -> None:
                try:
                    lista = municipios.municipios(codigo)
                except Exception as exc:
                    aviso = str(exc).splitlines()[0][:50]
                    self._na_interface(lambda: municipio_box.set(f"(falhou: {aviso})"))
                    return
                self._na_interface(lambda: aplicar(lista))

            threading.Thread(target=trabalho, daemon=True).start()

        def alternar_local() -> None:
            ligado = fora.get()
            uf_box.configure(state="normal" if ligado else "disabled")
            municipio_box.configure(state="normal" if ligado else "disabled")
            if not ligado:
                municipio_box.set("")
                atualizar_resumo()
                return
            if not escolha_uf["ufs"]:
                uf_box.set("consultando o portal…")

                def aplicar(lista: list[dict[str, str]]) -> None:
                    escolha_uf["ufs"] = lista
                    uf_box["values"] = [u["sigla"] for u in lista]
                    uf_box.configure(state="normal")
                    uf_box.set("")

                def trabalho() -> None:
                    try:
                        lista = municipios.ufs()
                    except Exception as exc:
                        aviso = str(exc).splitlines()[0][:50]
                        self._na_interface(lambda: uf_box.set(f"(falhou: {aviso})"))
                        return
                    self._na_interface(lambda: aplicar(lista))

                threading.Thread(target=trabalho, daemon=True).start()
            atualizar_resumo()

        tk.Checkbutton(
            local, text="  Serviço prestado fora de São Bernardo do Campo",
            variable=fora, command=alternar_local, bg=ui.SURFACE,
            activebackground=ui.SURFACE, selectcolor=ui.SURFACE, fg=ui.INK,
            font=ui.CORPO, anchor="w", bd=0, highlightthickness=0, cursor="hand2",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ui.etiqueta_campo(local, "UF").grid(row=1, column=0, sticky="w", pady=(ui.E3, 2))
        ui.etiqueta_campo(local, "Município da prestação").grid(row=1, column=1, sticky="w",
                                                               padx=(ui.E2, 0), pady=(ui.E3, 2))
        uf_box.grid(row=2, column=0, sticky="w")
        uf_box.bind("<<ComboboxSelected>>", carregar_municipios)
        ui.autocompletar(uf_box, lambda: [u["sigla"] for u in escolha_uf["ufs"]])
        ui.autocompletar(municipio_box, lambda: [m["nome"] for m in escolha_uf["municipios"]])
        municipio_box.grid(row=2, column=1, sticky="ew", padx=(ui.E2, 0))
        municipio_box.bind("<<ComboboxSelected>>", lambda _e: atualizar_resumo())

        ui.etiqueta_campo(passo_servico, "Descrição do serviço").grid(
            row=3, column=0, sticky="w")
        descricao = ui.caixa_texto(passo_servico, altura=4, fonte=(ui.FAMILIA, 11))
        descricao.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(ui.E2, 0))

        def atualizar_resumo(_evento=None) -> None:
            escolhido = codigo_escolhido()
            taxa = config.aliquota_do_servico(escolhido)
            confirmada = config.aliquota_confirmada(escolhido)
            partes = [f"Alíquota {taxa}%" + ("" if confirmada else "   NÃO CONFIRMADA")]
            try:
                bruto = validation.normalize_money(valor.get())
            except validation.ValidationError:
                pass
            else:
                # Fora do município o ISS não é de São Bernardo. Precisa estar
                # à vista antes de emitir: é imposto que deixa de sair na nota.
                if fora.get() and municipio_escolhido():
                    partes.append("ISS R$ 0,00 (devido ao município da prestação)")
                else:
                    iss = bruto * Decimal(taxa.replace(",", ".")) / Decimal(100)
                    quem = "retido pelo tomador" if iss_retido.get() else "pago pelo prestador"
                    partes.append(f"ISS R$ {validation.format_money(iss)} ({quem})")
            # Mostra e esconde o campo Obra conforme o serviço escolhido.
            alternar_obra()
            falta_obra = config.exige_obra(escolhido) and not obra_escolhida()
            if falta_obra:
                partes.append("FALTA o código da obra")
            partes.append(f"competência {date.today():%d/%m/%Y}")
            falta_municipio = False
            if fora.get():
                escolhido_mun = municipio_escolhido()
                falta_municipio = not escolhido_mun
                partes.append(
                    f"prestado em {municipio_box.get()}" if escolhido_mun
                    else "FALTA escolher o município da prestação"
                )
            # Vermelho é sinal de "isto ainda impede a emissão". A alíquota não
            # confirmada também entra, porque vira o imposto da nota.
            resumo.configure(
                text="      ·      ".join(partes),
                fg=ui.INK_2 if (confirmada and not falta_obra and not falta_municipio)
                else ui.ERRO,
            )

        codigo_box.bind("<<ComboboxSelected>>", carregar_nbs)
        obra.bind("<<ComboboxSelected>>", atualizar_resumo)
        obra.bind("<KeyRelease>", atualizar_resumo)
        valor.bind("<KeyRelease>", atualizar_resumo)
        montar_cst()
        carregar_nbs()          # já deixa o NBS e os códigos preenchidos
        if not reforma.em_disco():
            # Primeira vez nesta máquina: as tabelas ainda não existem. A busca
            # traz 675 NBS e leva segundos — na thread da interface, a tela
            # abriria congelada.
            aviso_reforma.configure(text="Buscando as tabelas da reforma no portal…",
                                    fg=ui.INK_3)

            def trazer_tabelas() -> None:
                try:
                    reforma.tabelas(atualizar=True)
                except Exception as exc:
                    registro.falha("tabelas da reforma", exc)
                    self._na_interface(lambda: aviso_reforma.configure(
                        text="Não consegui buscar as tabelas da reforma — "
                             "sem elas a nota não é aceita.", fg=ui.ERRO))
                    return
                self._na_interface(lambda: (montar_cst(), carregar_nbs()))

            threading.Thread(target=trazer_tabelas, daemon=True).start()
        atualizar_resumo()
        conferir_retencao()

        def buscar_em_segundo_plano() -> None:
            """Busca a lista no portal sem travar a janela.

            A consulta faz login e vai à rede. Rodando na thread da interface,
            o aplicativo congelaria por segundos toda vez que a tela abrisse.
            """
            def aplicar(encontrados: list[dict[str, str]]) -> None:
                catalogo[:] = encontrados
                codigo_box["values"] = [f"{s['codigo']}  —  {s['nome']}" for s in encontrados]
                if encontrados:
                    codigo_box.current(0)
                carregar_nbs()

            def trabalho() -> None:
                try:
                    encontrados = services.disponiveis(atualizar=True)
                except Exception as exc:
                    # Cortada a 45 caracteres, a mensagem virava reticências e
                    # o usuário só via "não carrega". Sem a lista não há nota a
                    # emitir, então o motivo tem de aparecer por inteiro.
                    registro.falha("consulta de servicos", exc)
                    motivo = str(exc).strip()
                    self._na_interface(lambda: codigo_box.set("(a lista não veio)"))
                    self._na_interface(lambda: self._alerta(
                        "Serviços não carregaram",
                        f"O portal não devolveu a lista de serviços desta empresa.\n\n"
                        f"{motivo}\n\n"
                        f"Sem ela não dá para emitir. Tente “Atualizar”; se persistir, "
                        f"use Configurações → Reler a versão do portal.",
                    ))
                    return
                registro.escrever("servicos carregados", f"{len(encontrados)} código(s)")
                self._na_interface(lambda: aplicar(encontrados))

            codigo_box.set("consultando o portal…")
            threading.Thread(target=trabalho, daemon=True).start()

        # Sem lista em cache para esta empresa, busca sozinho — é o que o
        # login já sabe responder.
        if not catalogo:
            buscar_em_segundo_plano()

        def montar() -> dict[str, Any]:
            return {
                # Gravado na nota, não só mostrado na tela: é o que permite
                # separar depois as notas de cada login.
                "prestador": self._prestador_em_uso(),
                "tomador": {"documento": documento.get().strip(), **dados_manuais()},
                "servico": {
                    "descricao": descricao.get("1.0", "end").strip(),
                    "valor": valor.get().strip(),
                    "codigo": codigo_escolhido(),
                    "municipio": municipio_escolhido(),
                    "obra": obra_escolhida(),
                    "iss_retido": iss_retido.get(),
                    # Reforma tributária: os quatro que a nota passou a exigir.
                    "nbs": nbs_escolhido(),
                    "indicador_operacao": _codigo_de(indop_box,
                                                     catalogos_reforma.get("indop", [])),
                    "classificacao_tributaria": _codigo_de(
                        classe_box, catalogos_reforma.get("classificacao", [])),
                    "situacao_tributaria": _codigo_de(cst_box,
                                                      catalogos_reforma.get("cst", [])),
                },
            }

        def emitir() -> None:
            if not codigo_escolhido():
                escrito = codigo_box.get().strip()
                if escrito and not escrito.startswith(("consultando", "(não consultei")):
                    # Digitou para filtrar mas não escolheu na lista: o texto
                    # solto não é um código, e adivinhar qual seria é justamente
                    # o que não se faz numa nota fiscal.
                    self._alerta(
                        "Serviço não escolhido",
                        f"“{escrito}” não é um serviço da lista.\n\n"
                        "Digitar filtra as opções; falta clicar na que você quer.",
                    )
                else:
                    self._alerta(
                        "Serviço não selecionado",
                        "Escolha o código do serviço. Se a lista estiver vazia, "
                        "clique em Atualizar para buscá-la no portal.",
                    )
                return
            # Os quatro da reforma. O portal não recusa com mensagem quando
            # faltam: lança exceção e responde HTTP 500 sem dizer o motivo.
            # Barrar aqui troca um erro indecifrável por um recado claro.
            faltando = [rotulo for rotulo, valor in (
                ("NBS", nbs_escolhido()),
                ("Código Indicador da Operação",
                 _codigo_de(indop_box, catalogos_reforma.get("indop", []))),
                ("Classificação Tributária",
                 _codigo_de(classe_box, catalogos_reforma.get("classificacao", []))),
                ("Situação Tributária (CST-IBS/CBS)",
                 _codigo_de(cst_box, catalogos_reforma.get("cst", []))),
            ) if not valor]
            if faltando:
                self._alerta(
                    "Reforma tributária",
                    "Falta escolher:\n\n• " + "\n• ".join(faltando) +
                    "\n\nEsses campos passaram a ser exigidos pela prefeitura. "
                    "Escolha o NBS — os outros se preenchem sozinhos.",
                )
                return
            if fora.get() and not municipio_escolhido():
                self._alerta(
                    "Local da prestação",
                    "Você marcou que o serviço foi prestado fora de São Bernardo, "
                    "mas não escolheu o município.\n\n"
                    "Sem essa escolha a nota sairia como prestada em São Bernardo.",
                )
                return
            try:
                dados = validation.validate_payload(montar())
            except validation.ValidationError as exc:
                self._alerta("Dados incompletos", exc.message)
                return

            if not self._confirmar_emissao(dados):
                return

            try:
                item = service.create_document(montar())
            except OSError as exc:
                messagebox.showerror("Erro ao salvar", str(exc))
                return
            self._submit_item(item)

        self.emit_button = ttk.Button(rodape_emissao, text="Emitir NFS-e",
                                      style="Primaria.TButton", command=emitir)
        # Fora da grade: o botão fica na barra do rodapé, ao lado dos números
        # que ele vai transmitir.
        self.emit_button.pack(side="right", ipady=4)

        ui.rotulo(
            self.content,
            "A competência é sempre a data de hoje. O nome do tomador vem do "
            "cadastro do portal, pelo CNPJ.",
            fonte=ui.MICRO, cor=ui.INK_3, fundo=ui.BG, justify="left",
        ).pack(anchor="w", pady=(ui.E3, 0))

    # ------------------------------------------------------------------ #
    # Diálogos próprios
    # ------------------------------------------------------------------ #

    def _procurar_atualizacao(self) -> None:
        """A mesma procura da abertura, pedida à mão.

        Diferença de uma só: aqui o "não há nada novo" é dito. Na abertura ele
        é calado — avisar que está tudo certo a cada vez que o programa abre é
        ruído.
        """
        if not os.getenv(updater.VARIAVEL_URL, "").strip():
            self._info(
                "Atualização não configurada",
                f"Você está na versão {updater.VERSAO_ATUAL}. Para o programa "
                f"procurar sozinho, preencha {updater.VARIAVEL_URL} no .env "
                "com o endereço do version.json.",
                segundos=12,
            )
            return
        self._info("Procurando atualização", "Consultando o servidor…")

        def trabalho() -> None:
            try:
                achada = updater.verificar_atualizacao()
            except Exception as exc:
                registro.falha("procura de atualizacao", exc)
                mensagem = str(exc)
                self._na_interface(
                    lambda: self._erro("Não consegui procurar", mensagem))
                return
            if achada is None:
                self._na_interface(lambda: self._sucesso(
                    "Tudo em dia", f"A versão {updater.VERSAO_ATUAL} é a mais "
                                   "recente publicada."))
                return
            self._na_interface(lambda: self._oferecer_atualizacao(achada))

        threading.Thread(target=trabalho, daemon=True).start()

    def _oferecer_atualizacao(self, nova) -> None:
        """Baixa e aplica a versão nova, sem perguntar nada.

        Sem perguntar porque isto roda na ABERTURA, e na abertura não existe
        nota digitada para se perder — a pessoa acabou de abrir o programa.
        Perguntar ali seria só um botão entre ela e o trabalho, e a resposta
        seria sempre a mesma.

        No formato de pasta não há troca automática: o `.exe` não anda sem o
        `_internal/` do lado, e trocar só um deixaria os dois em versões
        diferentes — quebra difícil de entender. Ali o aviso é só aviso.
        """
        if updater.formato() != "unico":
            self._info(
                f"Versão {nova.versao} disponível",
                "Esta cópia é a de pasta, que se atualiza trocando a pasta "
                "inteira. Baixe a versão nova e substitua a pasta do programa.",
                segundos=12,
            )
            return

        janela = tk.Toplevel(self)
        janela.title("Atualizando")
        janela.configure(bg=ui.SURFACE)
        janela.resizable(False, False)
        janela.transient(self)
        # Sem o X: fechar no meio do download deixaria um arquivo pela metade
        # e nenhuma explicação. A saída é o botão que aparece adiante.
        janela.protocol("WM_DELETE_WINDOW", lambda: None)

        corpo = tk.Frame(janela, bg=ui.SURFACE, padx=ui.E6, pady=ui.E5)
        corpo.pack(fill="both", expand=True)
        tk.Label(corpo, text=f"Atualizando para a versão {nova.versao}",
                 bg=ui.SURFACE, fg=ui.INK, font=ui.TITULO).pack(anchor="w")
        tk.Label(corpo, text="O programa vai fechar e abrir de novo sozinho. "
                             "Suas notas e configurações continuam onde estão.",
                 bg=ui.SURFACE, fg=ui.INK_2, font=ui.PEQUENO, justify="left",
                 wraplength=420).pack(anchor="w", pady=(ui.E2, ui.E4))
        andamento = tk.Label(corpo, text="Baixando…", bg=ui.SURFACE,
                             fg=ui.INK_3, font=ui.PEQUENO, anchor="w")
        andamento.pack(fill="x")
        barra = ui.Redondo(corpo, raio=5, fundo=ui.SURFACE_ALT,
                           borda=ui.BORDER, padx=0, pady=0, height=10)
        barra.pack(fill="x", pady=(ui.E2, 0))
        preenchida = tk.Frame(barra.interior, bg=ui.PRIMARIA, height=6)
        preenchida.place(x=0, y=0, relwidth=0, relheight=1)

        rodape = tk.Frame(corpo, bg=ui.SURFACE)
        rodape.pack(fill="x", pady=(ui.E4, 0))
        escapar = ttk.Button(rodape, text="Continuar sem atualizar")

        # Enquanto isso a janela principal fica travada: começar a digitar uma
        # nota que vai se perder no reinício seria pior que esperar.
        self._set_busy(True)
        janela.grab_set()

        estado = {"desistiu": False}

        def desistir() -> None:
            estado["desistiu"] = True
            self._set_busy(False)
            if janela.winfo_exists():
                janela.grab_release()
                janela.destroy()
            self._info("Atualização adiada",
                       f"O programa segue na versão {updater.VERSAO_ATUAL}. "
                       "Ele tenta de novo na próxima vez que abrir.")

        escapar.configure(command=desistir)

        def oferecer_saida() -> None:
            # Só depois de um tempo: numa conexão normal o download termina
            # antes, e o botão nem chega a aparecer.
            if janela.winfo_exists() and not estado["desistiu"]:
                escapar.pack(side="right")

        janela.after(45_000, oferecer_saida)

        def contar(feito: int, total: int) -> None:
            def mostrar() -> None:
                if not janela.winfo_exists() or estado["desistiu"]:
                    return
                if total > 0:
                    fracao = min(1.0, feito / total)
                    preenchida.place_configure(relwidth=fracao)
                    andamento.configure(text=f"Baixando… {int(fracao * 100)}%")
                else:
                    andamento.configure(
                        text=f"Baixando… {feito / 1024 / 1024:.1f} MB")

            self._na_interface(mostrar)

        def falhou(mensagem: str) -> None:
            if estado["desistiu"]:
                return
            self._set_busy(False)
            if janela.winfo_exists():
                janela.grab_release()
                janela.destroy()
            # Falha de atualização não pode impedir ninguém de emitir: o aviso
            # é discreto e o programa continua funcionando como estava.
            self._alerta("A atualização não veio",
                         f"{mensagem}  O programa segue na versão "
                         f"{updater.VERSAO_ATUAL}.")

        def trocar(arquivo) -> None:
            if estado["desistiu"]:
                return
            try:
                updater.aplicar_atualizacao(arquivo,
                                            instalador=nova.instalador)
            except Exception as exc:
                registro.falha("troca do executavel", exc)
                falhou(str(exc))
                return
            if janela.winfo_exists():
                andamento.configure(text="Reabrindo o programa…")
                janela.update_idletasks()
            self.destroy()
            sys.exit(0)

        def trabalho() -> None:
            try:
                arquivo = updater.baixar(nova, progresso=contar)
            except Exception as exc:
                registro.falha("download da atualizacao", exc)
                mensagem = str(exc)
                self._na_interface(lambda: falhou(mensagem))
                return
            self._na_interface(lambda: trocar(arquivo))

        threading.Thread(target=trabalho, daemon=True).start()
        ui.dimensionar(janela, 480)

    def _modal(self, titulo: str, largura: int) -> tuple[tk.Toplevel, tk.Frame, tk.Frame]:
        """Janela modal com rodapé garantido.

        O rodapé é empacotado **antes** do corpo, de propósito: no pack, quem
        vem primeiro reserva seu espaço. Com o corpo primeiro, um conteúdo mais
        alto que a janela empurrava os botões para fora e a caixa ficava sem
        como confirmar — sem erro, só sem botão.
        """
        janela = tk.Toplevel(self)
        janela.title(titulo)
        janela.configure(bg=ui.SURFACE)
        janela.resizable(False, False)
        janela.transient(self)
        rodape = tk.Frame(janela, bg=ui.SURFACE, padx=ui.E6, pady=ui.E4)
        rodape.pack(side="bottom", fill="x")
        corpo = tk.Frame(janela, bg=ui.SURFACE, padx=ui.E6, pady=ui.E5)
        corpo.pack(side="top", fill="both", expand=True)
        janela._largura_modal = largura  # usada por _fechar_modal
        return janela, corpo, rodape

    @staticmethod
    def _dimensionar_modal(janela: tk.Toplevel) -> None:
        ui.dimensionar(janela, getattr(janela, "_largura_modal", 460))

    def _razao_social_atual(self) -> str:
        """Razão social que irá na nota, lida do portal (cache do login)."""
        return self._prestador_em_uso().get("razao_social") or "(não lida)"

    def _prestador_em_uso(self) -> dict[str, str]:
        """Quem está emitindo agora: inscrição municipal e razão social.

        Sai do cache do login, não do que foi digitado — é o que o portal
        respondeu para a sessão em curso. Falhando a leitura, devolve o que
        souber, nem que seja só o CCM: identificação parcial ainda separa uma
        empresa da outra, e vazio não separa nada.
        """
        dados: dict[str, str] = {}
        try:
            portal = prestador.do_portal() or {}
        except Exception:
            portal = {}
        for origem, destino in (("inscricao", "inscricao"), ("razao_social", "razao_social")):
            valor = str(portal.get(origem, "") or "").strip()
            if valor:
                dados[destino] = valor
        if "inscricao" not in dados:
            ativa = config.empresa_ativa()
            if ativa:
                dados["inscricao"] = ativa
        return dados

    def _confirmar_emissao(self, dados: dict[str, Any]) -> bool:
        """Última conferência antes de transmitir.

        Tem janela própria em vez de messagebox porque é o momento mais caro do
        programa: depois daqui a nota existe no portal e não há desfazer.
        """
        janela, corpo, rodape = self._modal("Confirmar emissão", 480)
        resposta = {"ok": False}

        tk.Label(corpo, text="Confirmar emissão", bg=ui.SURFACE, fg=ui.INK,
                 font=ui.TITULO).pack(anchor="w")
        tk.Label(corpo, text="Confira antes de transmitir — não há desfazer.",
                 bg=ui.SURFACE, fg=ui.INK_3, font=ui.PEQUENO).pack(anchor="w", pady=(2, ui.E4))

        servico = dados["servico"]
        # A razão social do prestador aparece aqui de propósito: ela é lida do
        # portal por vizinhança, sem digitação, e uma leitura errada só seria
        # descoberta com a nota já emitida e o nome errado impresso nela.
        municipio = str(servico.get("municipio", "")).strip()
        # O local da prestação define onde o ISS é devido. Aparece na
        # confirmação sempre — inclusive quando é o padrão — para que uma
        # marcação errada seja vista antes de a nota existir.
        local = (
            f"{municipios.nome_do_codigo(municipio) or municipio}  (fora do município)"
            if municipio
            else "São Bernardo do Campo"
        )
        linhas = (
            ("Prestador", self._razao_social_atual()),
            ("Tomador", validation.format_document(dados["tomador"]["documento"])),
            ("Serviço", servico["codigo"]),
            *((("Obra", servico["obra"]),) if servico.get("obra") else ()),
            ("Local da prestação", local),
            ("Valor", f"R$ {validation.format_money(servico['valor'])}"),
            ("Alíquota", f"{servico['aliquota']}%"),
            ("ISS", f"R$ {validation.format_money(servico['iss'])}"
                    + ("  ·  retido pelo tomador" if servico.get("iss_retido")
                       else "  ·  pago pelo prestador")),
            ("Competência", f"{date.today():%d/%m/%Y}"),
        )
        for rotulo_, valor_ in linhas:
            linha = tk.Frame(corpo, bg=ui.SURFACE)
            linha.pack(fill="x", pady=3)
            tk.Label(linha, text=rotulo_, bg=ui.SURFACE, fg=ui.INK_3, font=ui.PEQUENO,
                     width=13, anchor="w").pack(side="left")
            tk.Label(linha, text=valor_, bg=ui.SURFACE, fg=ui.INK, font=ui.CORPO_FORTE,
                     anchor="w").pack(side="left")

        ui.separador(corpo, espaco=ui.E3)
        tk.Label(corpo, text=servico["descricao"][:220], bg=ui.SURFACE, fg=ui.INK_2,
                 font=ui.PEQUENO, wraplength=390, justify="left").pack(anchor="w")

        if not config.live_mode():
            ui.banner(corpo, "Modo seguro", ["Nada será transmitido ao portal."],
                      tom="info").pack(fill="x", pady=(ui.E4, 0))
        if not config.aliquota_confirmada(servico["codigo"]):
            ui.banner(corpo, "Alíquota não confirmada",
                      ["Confira no portal antes de emitir — este número vira o imposto."],
                      tom="alerta").pack(fill="x", pady=(ui.E3, 0))

        def confirmar() -> None:
            resposta["ok"] = True
            janela.destroy()

        ttk.Button(rodape, text="Emitir agora", style="Primaria.TButton",
                   command=confirmar).pack(side="right")
        ttk.Button(rodape, text="Cancelar", command=janela.destroy).pack(side="right", padx=ui.E2)

        janela.bind("<Escape>", lambda _e: janela.destroy())
        self._dimensionar_modal(janela)
        janela.grab_set()
        self.wait_window(janela)
        return resposta["ok"]

    def _pedir_aliquota(self, codigo: str, atual: str) -> str | None:
        janela, corpo, rodape = self._modal("Alíquota do serviço", 440)
        resultado: dict[str, str | None] = {"valor": None}

        tk.Label(corpo, text="Alíquota do ISS", bg=ui.SURFACE, fg=ui.INK,
                 font=ui.TITULO).pack(anchor="w")
        tk.Label(corpo, text=f"Serviço {codigo}", bg=ui.SURFACE, fg=ui.INK_3,
                 font=ui.PEQUENO).pack(anchor="w", pady=(2, ui.E4))

        ui.etiqueta_campo(corpo, "Percentual (%)").pack(anchor="w")
        campo = ttk.Entry(corpo, font=(ui.FAMILIA, 15))
        campo.pack(fill="x", pady=(ui.E2, ui.E3))
        campo.insert(0, atual)
        campo.select_range(0, "end")
        campo.focus_set()

        ui.banner(corpo, "Confira no portal antes de gravar",
                  ["Este número vira o imposto da nota."], tom="alerta").pack(fill="x")

        def gravar() -> None:
            resultado["valor"] = campo.get()
            janela.destroy()

        ttk.Button(rodape, text="Gravar", style="Primaria.TButton",
                   command=gravar).pack(side="right")
        ttk.Button(rodape, text="Cancelar", command=janela.destroy).pack(side="right", padx=ui.E2)

        campo.bind("<Return>", lambda _e: gravar())
        janela.bind("<Escape>", lambda _e: janela.destroy())
        self._dimensionar_modal(janela)
        janela.grab_set()
        self.wait_window(janela)
        return resultado["valor"]

    # ------------------------------------------------------------------ #
    # Listagem
    # ------------------------------------------------------------------ #

    @staticmethod
    def prestador_do_doc(doc: dict[str, Any]) -> str:
        """Quem emitiu a nota, como aparece na lista.

        Notas gravadas antes de o programa passar a registrar isto não têm o
        dado, e não há de onde tirá-lo. Elas dizem "não registrado" — que é a
        verdade — em vez de serem atribuídas a alguma empresa por chute.
        """
        dados = (doc.get("payload") or {}).get("prestador") or {}
        nome = str(dados.get("razao_social", "") or "").strip()
        if nome:
            return nome
        inscricao = str(dados.get("inscricao", "") or "").strip()
        return f"CCM {inscricao}" if inscricao else "— não registrado"

    @staticmethod
    def _texto_do_doc(doc: dict[str, Any]) -> str:
        """Tudo por que se procura uma nota, junto numa linha só.

        O documento entra cru e formatado, porque tanto se digita
        00000000000191 quanto 00.000.000/0001-91.
        """
        payload = doc.get("payload") or {}
        tomador = payload.get("tomador") or {}
        servico = payload.get("servico") or {}
        documento = str(tomador.get("documento", ""))
        try:
            formatado = validation.format_document(documento)
        except Exception:
            formatado = ""
        partes = (
            NfseDesktop.prestador_do_doc(doc),
            tomador.get("nome") or "",
            documento,
            formatado,
            servico.get("descricao") or "",
            servico.get("codigo") or "",
            # O valor entra formatado E cru: quem procura digita 5600, e o
            # formatado é "5.600,00" — o ponto de milhar no meio faz a busca
            # por dígitos seguidos não achar nada.
            validation.format_money(servico.get("valor")),
            str(servico.get("valor") or ""),
            STATUS_LABELS.get(doc.get("status", ""), ""),
            str((doc.get("nota") or {}).get("numero") or ""),
            str(doc.get("created_at", ""))[:10],
        )
        return " ".join(str(parte) for parte in partes if parte)

    def _documents_table(self, parent: tk.Widget, docs: list[dict[str, Any]], *,
                         actions: bool, filtrada: bool = False) -> None:
        """A lista simples do painel, e o estado vazio da tela de notas.

        A tela de notas tem a sua própria (``ViewDocumentos``), que atualiza no
        lugar. Esta serve ao painel, que é redesenhado raramente.
        """
        if not docs:
            moldura = tk.Frame(parent, bg=ui.SURFACE, highlightbackground=ui.BORDER,
                               highlightthickness=1)
            moldura.pack(fill="both", expand=True)
            if filtrada:
                ui.vazio(
                    moldura, "⌕", "Nenhuma nota com esses filtros",
                    "Tente outra empresa, outro período, ou limpe a busca.",
                ).pack(fill="both", expand=True)
            else:
                ui.vazio(
                    moldura, "▤", "Nenhuma nota ainda",
                    "As notas que você emitir aparecem aqui, com número, status e PDF.",
                    ("Emitir a primeira", self.show_new_note),
                ).pack(fill="both", expand=True)
            return

        moldura = ui.Redondo(parent, raio=14, fundo=ui.SURFACE, borda=ui.BORDER,
                             padx=0, pady=0)
        moldura.pack(fill="both", expand=True)
        tabela = ui.Tabela(moldura.interior, colunas_de_notas(),
                           ao_abrir=lambda identidade: self._details((identidade,)))
        tabela.pack(fill="both", expand=True)
        tabela.mostrar([
            linha_da_nota(doc, self.prestador_do_doc,
                          ocultar_valores=self._valores_ocultos)
            for doc in docs
        ])

    def show_documents(self, situacao: str = "") -> None:
        """A lista de notas. `situacao` abre já filtrada por ela."""
        self._clear()
        self._mostrar_comando(True)
        self._marcar_nav("notas")
        self._title("Notas fiscais de serviço", "Rascunhos, emissões e recusas.")
        ViewDocumentos(self.content, self, situacao=situacao).pack(
            fill="both", expand=True)

    # ------------------------------------------------------------------ #
    # Exclusão
    # ------------------------------------------------------------------ #

    def _excluir(self, selection: tuple[str, ...]) -> None:
        """Tira uma nota da lista, guardando o arquivo na lixeira."""
        item = self._selected(selection)
        if item is None:
            return
        emitida = item.get("status") == "submitted"
        numero = (item.get("nota") or {}).get("numero")
        aviso = (
            f"A NFS-e nº {numero} continua emitida no portal — sair da lista "
            f"não cancela a nota.\n\n"
            if emitida and numero
            else ""
        )
        if not messagebox.askyesno(
            "Excluir nota",
            f"{aviso}O arquivo vai para {storage.LIXEIRA}/ dentro da pasta de dados, "
            f"e some desta lista.\n\nExcluir?",
        ):
            return
        try:
            storage.descartar(item["id"])
        except (OSError, ValueError) as exc:
            messagebox.showerror("Não foi possível excluir", str(exc))
            return
        self.show_documents()

    def limpar_historico(self) -> None:
        """Esvazia a lista por status, com a contagem à vista.

        Separado do botão Excluir porque limpar em lote é a operação em que se
        perde algo sem perceber: aqui o número de cada grupo aparece antes.
        """
        docs = storage.list_all()
        if not docs:
            self._info("Histórico", "Não há notas na lista.")
            return

        grupos = {
            "draft": [d for d in docs if d.get("status") == "draft"],
            "failed": [d for d in docs if d.get("status") == "failed"],
            "submitted": [d for d in docs if d.get("status") == "submitted"],
        }
        janela, corpo, rodape = self._modal("Limpar histórico", 480)

        tk.Label(corpo, text="Limpar histórico", bg=ui.SURFACE, fg=ui.INK,
                 font=ui.TITULO).pack(anchor="w")
        tk.Label(corpo, text="Escolha o que sai da lista.", bg=ui.SURFACE, fg=ui.INK_3,
                 font=ui.PEQUENO).pack(anchor="w", pady=(2, ui.E4))

        marcados: dict[str, tk.BooleanVar] = {}
        opcoes = (
            ("draft", "Rascunhos", "nunca transmitidos"),
            ("failed", "Falhas", "tentativas recusadas pelo portal"),
            ("submitted", "Emitidas", "continuam válidas no portal"),
        )
        for chave, titulo, detalhe in opcoes:
            quantidade = len(grupos[chave])
            variavel = tk.BooleanVar(value=False)
            marcados[chave] = variavel
            linha = tk.Frame(corpo, bg=ui.SURFACE_ALT if quantidade else ui.SURFACE,
                             padx=ui.E3, pady=ui.E3, highlightbackground=ui.BORDER,
                             highlightthickness=1)
            linha.pack(fill="x", pady=(0, ui.E2))
            caixa = tk.Checkbutton(
                linha, variable=variavel, bg=linha["bg"], activebackground=linha["bg"],
                text=f"  {titulo}  ({quantidade})", font=ui.CORPO_FORTE, fg=ui.INK,
                selectcolor=ui.SURFACE, anchor="w", bd=0, highlightthickness=0,
                state="normal" if quantidade else "disabled",
                cursor="hand2" if quantidade else "",
            )
            caixa.pack(anchor="w")
            tk.Label(linha, text=f"      {detalhe}", bg=linha["bg"], fg=ui.INK_3,
                     font=ui.MICRO).pack(anchor="w")

        ui.banner(
            corpo, "Os arquivos vão para a lixeira",
            [f"Ficam em {storage.LIXEIRA}/ dentro da pasta de dados, e podem ser "
             f"recuperados de lá. Notas emitidas seguem valendo no portal."],
            tom="info",
        ).pack(fill="x", pady=(ui.E2, 0))

        def confirmar() -> None:
            alvos = [d["id"] for chave, var in marcados.items() if var.get()
                     for d in grupos[chave]]
            if not alvos:
                self._info("Nada marcado", "Marque ao menos um grupo.", parent=janela)
                return
            if not messagebox.askyesno(
                "Confirmar", f"Retirar {len(alvos)} nota(s) da lista?", parent=janela
            ):
                return
            saidas, erros = storage.descartar_muitos(alvos)
            janela.destroy()
            if erros:
                self._alerta(
                    "Histórico limpo em parte",
                    f"{saidas} nota(s) saíram.\n\nNão consegui em:\n• " + "\n• ".join(erros),
                )
            else:
                self._info("Histórico limpo", f"{saidas} nota(s) saíram da lista.")
            self.show_documents()

        ttk.Button(rodape, text="Limpar", style="Perigo.TButton",
                   command=confirmar).pack(side="right")
        ttk.Button(rodape, text="Cancelar", command=janela.destroy).pack(side="right", padx=ui.E2)

        janela.bind("<Escape>", lambda _e: janela.destroy())
        self._dimensionar_modal(janela)
        janela.grab_set()
        self.wait_window(janela)

    def _selected(self, selection: tuple[str, ...]) -> dict[str, Any] | None:
        """Devolve a nota selecionada, ou None explicando o motivo ao usuário."""
        if not selection:
            self._info("Seleção", "Selecione uma nota na lista.")
            return None
        try:
            item = storage.get(selection[0])
        except ValueError as exc:
            messagebox.showerror("Nota ilegível", str(exc))
            return None
        if item is None:
            self._alerta("Nota não encontrada", "O arquivo desta nota não existe mais.")
            self.show_documents()
            return None
        return item

    def _details(self, selection: tuple[str, ...]) -> None:
        item = self._selected(selection)
        if item is None:
            return

        janela = tk.Toplevel(self)
        janela.title(f"Nota {item['id'][:8]}")
        janela.configure(bg=ui.BG)

        payload = item.get("payload") or {}
        tomador = payload.get("tomador") or {}
        servico = payload.get("servico") or {}
        status = item.get("status", "")
        nota = item.get("nota") or {}

        # Rodapé preso embaixo antes do corpo — ver janela_impressao.
        rodape = tk.Frame(janela, bg=ui.BG, padx=ui.E5, pady=ui.E4)
        rodape.pack(side="bottom", fill="x")

        topo = tk.Frame(janela, bg=ui.SURFACE, padx=ui.E5, pady=ui.E4)
        topo.pack(fill="x")
        tk.Frame(janela, bg=ui.BORDER, height=1).pack(fill="x")
        titulo = f"NFS-e nº {nota['numero']}" if nota.get("numero") else "Nota sem número"
        tk.Label(topo, text=titulo, bg=ui.SURFACE, fg=ui.INK, font=ui.TITULO).pack(anchor="w")
        selo = tk.Frame(topo, bg=ui.SURFACE)
        selo.pack(anchor="w", pady=(ui.E2, 0))
        cores = {"draft": (ui.INK_2, ui.SURFACE_ALT), "submitted": (ui.SUCESSO, ui.SUCESSO_BG),
                 "failed": (ui.ERRO, ui.ERRO_BG)}
        cor, fundo = cores.get(status, (ui.INK_2, ui.SURFACE_ALT))
        ui.pilula(selo, STATUS_LABELS.get(status, status), cor=cor,
                  fundo_pilula=fundo).pack(side="left")
        if nota.get("codigo_verificacao"):
            tk.Label(selo, text=f"   verificação {nota['codigo_verificacao']}",
                     bg=ui.SURFACE, fg=ui.INK_3, font=ui.MICRO).pack(side="left")

        corpo = tk.Frame(janela, bg=ui.BG, padx=ui.E5, pady=ui.E4)
        corpo.pack(fill="both", expand=True)
        caixa_painel = ui.cartao(corpo, padx=ui.E5, pady=ui.E4)
        caixa_painel.pack(fill="both", expand=True)
        painel = caixa_painel.interior

        linhas = [
            ("Cliente", tomador.get("nome") or "(resolvido pelo portal)"),
            ("Documento", validation.format_document(str(tomador.get("documento", "")))),
            ("Serviço", servico.get("descricao", "—")),
            ("Código", servico.get("codigo", "—")),
            ("Valor", f"R$ {validation.format_money(servico.get('valor'))}"),
            ("Alíquota", f"{servico.get('aliquota', '—')}%"),
            ("ISS", f"R$ {validation.format_money(servico.get('iss'))}"),
            ("Competência", payload.get("competencia", "—")),
            ("Criada em", str(item.get("created_at", "—"))[:19].replace("T", " ")),
        ]
        if nota.get("emitida_em"):
            linhas.append(("Emitida em", str(nota["emitida_em"]).replace("T", " ")))
        for rotulo_, valor_ in linhas:
            linha = tk.Frame(painel, bg=ui.SURFACE)
            linha.pack(fill="x", pady=3)
            tk.Label(linha, text=rotulo_, bg=ui.SURFACE, fg=ui.INK_3, font=ui.PEQUENO,
                     width=14, anchor="w").pack(side="left")
            tk.Label(linha, text=str(valor_), bg=ui.SURFACE, fg=ui.INK, font=ui.CORPO,
                     anchor="w", justify="left", wraplength=400).pack(side="left")

        historico = item.get("submissions") or []
        ui.separador(painel, espaco=ui.E3)
        tk.Label(painel, text=f"Transmissões ({len(historico)})", bg=ui.SURFACE,
                 fg=ui.INK_2, font=ui.PEQUENO_FORTE).pack(anchor="w")
        if historico:
            for entrada in historico:
                tk.Label(painel, text=f"•  {entrada.get('at', '—')}  —  HTTP {entrada.get('http_status', '—')}",
                         bg=ui.SURFACE, fg=ui.INK_3, font=ui.PEQUENO).pack(anchor="w", pady=(2, 0))
        else:
            tk.Label(painel, text="Nenhuma transmissão registrada.", bg=ui.SURFACE,
                     fg=ui.INK_3, font=ui.PEQUENO).pack(anchor="w", pady=(2, 0))

        ttk.Button(rodape, text="Fechar", command=janela.destroy).pack(side="right")
        if item.get("status") == "submitted" or nota.get("numero"):
            ttk.Button(rodape, text="Imprimir nota", style="Primaria.TButton",
                       command=lambda: (janela.destroy(), self.janela_impressao(nota, item))
                       ).pack(side="right", padx=ui.E2)
        ui.dimensionar(janela, 640)

    def _preview(self, selection: tuple[str, ...]) -> None:
        """Mostra a requisição que seria enviada, sem tocar na rede."""
        item = self._selected(selection)
        if item is None:
            return
        try:
            preview = service.dry_run(item["payload"])
        except validation.ValidationError as exc:
            self._alerta("Dados inválidos", f"{exc.field}: {exc.message}")
            return
        except nfse_client.NfseError as exc:
            messagebox.showerror("Configuração incompleta", str(exc))
            return

        janela = tk.Toplevel(self)
        janela.title("Requisição preparada")
        janela.configure(bg=ui.BG)
        ui.centralizar(janela, 820, 600)

        topo = tk.Frame(janela, bg=ui.SURFACE, padx=ui.E5, pady=ui.E4)
        topo.pack(fill="x")
        tk.Frame(janela, bg=ui.BORDER, height=1).pack(fill="x")
        tk.Label(topo, text="Requisição preparada", bg=ui.SURFACE, fg=ui.INK,
                 font=ui.TITULO).pack(anchor="w")
        tk.Label(topo, text="Nada foi enviado ao portal. Segredos aparecem ocultos.",
                 bg=ui.SURFACE, fg=ui.INK_3, font=ui.PEQUENO).pack(anchor="w", pady=(2, 0))

        moldura = tk.Frame(janela, bg=ui.BG, padx=ui.E5, pady=ui.E4)
        moldura.pack(fill="both", expand=True)
        caixa = tk.Frame(moldura, bg=ui.SURFACE, highlightbackground=ui.BORDER,
                         highlightthickness=1)
        caixa.pack(fill="both", expand=True)
        texto = tk.Text(caixa, font=(ui.MONO, 9), wrap="none", padx=ui.E3, pady=ui.E3,
                        relief="flat", bd=0, bg=ui.SURFACE, fg=ui.INK)
        barra = ttk.Scrollbar(caixa, orient="vertical", command=texto.yview)
        texto.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        texto.pack(side="left", fill="both", expand=True)

        corpo = [
            f"{preview['method']} {preview['url']}",
            "",
            *(f"{chave}: {valor}" for chave, valor in preview["headers"].items()),
            "",
            f"— corpo ({preview['body_bytes']} bytes, segredos ocultos) —",
            preview["body_preview"],
        ]
        texto.insert("1.0", "\n".join(corpo))
        texto.configure(state="disabled")

        rodape = tk.Frame(janela, bg=ui.BG, padx=ui.E5)
        rodape.pack(fill="x", pady=(0, ui.E4))
        ttk.Button(rodape, text="Fechar", command=janela.destroy).pack(side="right")

    # ------------------------------------------------------------------ #
    # PDF e impressão
    # ------------------------------------------------------------------ #

    def _baixar_pdf(
        self,
        nota: dict[str, Any],
        pronto: Callable[[Any], None],
        falhou: Callable[[str], None],
        andamento: Callable[[str], None] | None = None,
    ) -> None:
        """Baixa o DANFSe fora da thread da interface.

        O download leva alguns segundos; feito aqui, a janela não congela e o
        layout de impressão já aparece enquanto o arquivo vem. Cada etapa é
        anunciada: uma espera muda é indistinguível de um travamento.
        """

        def etapa(texto: str) -> None:
            if andamento is not None:
                self._na_interface(lambda: andamento(texto))

        def trabalho() -> None:
            try:
                caminho = pdf.baixar(nota, progresso=etapa)
            except Exception as exc:
                # A mensagem é copiada agora: `exc` não existe mais quando o
                # callback roda na thread da interface.
                mensagem = str(exc)
                self._na_interface(lambda: falhou(mensagem))
                return
            self._na_interface(lambda: pronto(caminho))

        threading.Thread(target=trabalho, daemon=True).start()

    def _com_o_pdf(self, selection: tuple[str, ...],
                   fazer: Callable[[Any], None], aviso: str) -> None:
        """Garante o PDF no disco e então faz com ele o que se pediu.

        Um caminho só para os dois botões: se o arquivo já está gravado, age
        na hora; se não, baixa em segundo plano e age quando chegar. A tela
        nunca congela, e o usuário sempre sabe em que pé está.
        """
        item = self._selected(selection)
        if item is None:
            return
        nota = item.get("nota") or {}
        if not nota.get("numero") or not nota.get("codigo_verificacao"):
            self._info(
                "Sem PDF",
                "Esta nota não tem número e código de verificação registrados. "
                "O PDF é gerado pelo portal depois de a nota ser aceita.",
            )
            return

        pronto = pdf.ja_baixado(nota)
        if pronto is not None:
            registro.escrever("pdf do disco", str(pronto))
            fazer(pronto)
            return

        self._info(aviso, f"Nota nº {nota.get('numero')} — buscando no portal…")

        def falhou(mensagem: str) -> None:
            self._erro(
                "O PDF não veio",
                f"{mensagem}\n\nA nota existe no portal: use "
                f"'Ver no site da prefeitura' para chegar nela pelo navegador.",
            )

        self._baixar_pdf(nota, fazer, falhou)

    def abrir_pdf_direto(self, selection: tuple[str, ...]) -> None:
        """Abre o PDF no leitor do sistema — o Adobe, nesta máquina.

        Sem janela intermediária: quem clica em "Abrir em PDF" quer o PDF na
        tela, não um resumo com um botão para o PDF.
        """
        def abrir(caminho: Any) -> None:
            try:
                pdf.abrir(caminho)
            except OSError as exc:
                registro.falha("abrir pdf", exc)
                self._erro("Não deu para abrir",
                           f"{exc}\n\nO arquivo está em {caminho}")

        self._com_o_pdf(selection, abrir, "Abrindo o PDF")

    def salvar_pdf_como(self, selection: tuple[str, ...]) -> None:
        """Grava a nota em PDF na pasta que o usuário escolher."""

        def perguntar(caminho: Any) -> None:
            destino = filedialog.asksaveasfilename(
                parent=self, title="Salvar a nota em PDF", defaultextension=".pdf",
                initialfile=Path(caminho).name, filetypes=[("PDF", "*.pdf")],
            )
            if not destino:
                return
            try:
                shutil.copyfile(caminho, destino)
            except OSError as exc:
                registro.falha("salvar pdf", exc)
                self._erro("Não deu para salvar", str(exc))
                return
            registro.escrever("pdf salvo", destino)
            self._sucesso("PDF salvo", destino)

        self._com_o_pdf(selection, perguntar, "Preparando o PDF")

    def _abrir_pdf(self, selection: tuple[str, ...]) -> None:
        """Abre o layout de impressão da nota selecionada."""
        item = self._selected(selection)
        if item is None:
            return
        nota = item.get("nota") or {}
        if not nota.get("numero") and item.get("status") != "submitted":
            self._info(
                "Sem número",
                "Esta nota ainda não foi emitida — só há PDF depois de o portal aceitá-la.",
            )
            return
        # Nota emitida sem número reconhecido também abre: a janela mostra o que
        # faltou e permite tentar de novo. Recusar aqui deixava a nota — que
        # existe no portal — sem nenhuma saída na tela.
        self.janela_impressao(nota, item)

    def _abrir_no_portal(self, selection: tuple[str, ...]) -> None:
        """Mostra a nota no site da prefeitura, sem baixar arquivo.

        É a saída mais curta para só conferir uma nota: nada é gravado em
        disco, e o navegador atravessa proxy e certificado do Windows quando o
        download automático do programa não atravessa.
        """
        import webbrowser

        item = self._selected(selection)
        if item is None:
            return
        nota = item.get("nota") or {}
        try:
            endereco = pdf.endereco_no_portal(nota)
        except Exception as exc:
            registro.falha("endereco no portal", exc)
            endereco = ""
        if not endereco:
            self._alerta(
                "Ainda não há o que abrir",
                "Só depois de o portal aceitar a nota ela ganha número e código "
                "de verificação — que é o que localiza o PDF.",
            )
            return
        registro.escrever("abrindo no navegador", endereco)
        webbrowser.open(endereco)
        self._info("Abrindo no navegador", f"Nota nº {nota.get('numero', '')}.")

    def janela_impressao(
        self,
        nota: dict[str, Any],
        item: dict[str, Any],
        *,
        recem_emitida: bool = False,
    ) -> tk.Toplevel:
        """Abre o layout de impressão da NFS-e.

        A janela nasce antes do PDF chegar, de propósito: logo após emitir, o
        que o usuário precisa ver primeiro é que a nota saiu e qual é o número.
        Os botões só destravam quando o arquivo está no disco.
        """
        numero = str(nota.get("numero") or "—")
        registro.escrever("layout de impressao", f"nota nº {numero}")
        janela = tk.Toplevel(self)
        janela.title(f"NFS-e nº {numero}")
        janela.configure(bg=ui.BG)
        janela.transient(self)

        payload = item.get("payload") or {}
        tomador = payload.get("tomador") or {}
        servico = payload.get("servico") or {}

        # A barra de botões é empacotada ANTES do corpo, presa embaixo. No pack
        # do Tk, quem vem primeiro reserva seu espaço; empacotada por último,
        # depois de um corpo que se expande, ela some da área visível quando o
        # conteúdo passa da altura da janela — sem erro nenhum, só sem botão.
        # Foi o que deixou uma nota emitida sem opção de imprimir nem baixar,
        # em máquina com escala de tela maior. Mesmo motivo do rodapé em _modal.
        acoes = tk.Frame(janela, bg=ui.BG, padx=ui.E5, pady=ui.E4)
        acoes.pack(side="bottom", fill="x")

        topo = tk.Frame(janela, bg=ui.NAVY, padx=ui.E5, pady=ui.E4)
        topo.pack(fill="x")
        cabeca = tk.Frame(topo, bg=ui.NAVY)
        cabeca.pack(fill="x")
        tk.Label(cabeca, text="NFS-e emitida" if recem_emitida else "NFS-e",
                 bg=ui.NAVY, fg=ui.NAV_DESTAQUE, font=ui.PEQUENO_FORTE).pack(side="left")
        if recem_emitida:
            ui.pilula(cabeca, "NO PORTAL", tom="sucesso",
                      fundo=ui.NAVY).pack(side="right")
        tk.Label(topo, text=f"Nº {numero}", bg=ui.NAVY, fg=ui.INK,
                 font=(ui.FAMILIA, 27, "bold")).pack(anchor="w")
        tk.Label(topo, text=f"Código de verificação  ·  {nota.get('codigo_verificacao', '—')}",
                 bg=ui.NAVY, fg=ui.NAV_MONO, font=(ui.MONO, 10)).pack(anchor="w", pady=(2, 0))

        moldura = tk.Frame(janela, bg=ui.BG, padx=ui.E5, pady=ui.E4)
        moldura.pack(fill="both", expand=True)
        caixa_corpo = ui.cartao(moldura, padx=ui.E5, pady=ui.E4)
        caixa_corpo.pack(fill="both", expand=True)
        corpo = caixa_corpo.interior

        linhas = [
            ("Tomador", tomador.get("nome")
             or validation.format_document(str(tomador.get("documento", "")))),
            ("Documento", validation.format_document(str(tomador.get("documento", "")))),
            ("Serviço", f"{servico.get('codigo', '—')}  —  {servico.get('descricao', '—')}"),
            ("Valor", f"R$ {validation.format_money(servico.get('valor'))}"),
            ("ISS", f"R$ {validation.format_money(servico.get('iss'))}"),
            ("Competência", payload.get("competencia", "—")),
            ("Emitida em", str(nota.get("emitida_em", "—")).replace("T", " ")),
        ]
        for rotulo_, valor_ in linhas:
            linha = tk.Frame(corpo, bg=ui.SURFACE)
            linha.pack(fill="x", pady=3)
            tk.Label(linha, text=rotulo_, bg=ui.SURFACE, fg=ui.INK_3, width=13, anchor="w",
                     font=ui.PEQUENO).pack(side="left")
            tk.Label(linha, text=str(valor_)[:62], bg=ui.SURFACE, fg=ui.INK, anchor="w",
                     font=ui.CORPO).pack(side="left", fill="x", expand=True)

        ui.separador(corpo, espaco=ui.E4)

        escolha = tk.Frame(corpo, bg=ui.SURFACE)
        escolha.pack(fill="x")
        tk.Label(escolha, text="Impressora", bg=ui.SURFACE, fg=ui.INK_3, width=13,
                 anchor="w", font=ui.PEQUENO).pack(side="left")
        disponiveis = impressao.impressoras()
        combo = ttk.Combobox(escolha, values=disponiveis, state="readonly", font=ui.PEQUENO)
        combo.pack(side="left", fill="x", expand=True)
        if disponiveis:
            combo.current(0)  # a padrão do Windows vem em primeiro lugar

        estado = tk.Label(corpo, text="Buscando o PDF no portal…", bg=ui.SURFACE,
                          fg=ui.INK_3, font=ui.PEQUENO, anchor="w", justify="left",
                          wraplength=480)
        estado.pack(fill="x", pady=(ui.E4, 0))

        arquivo: dict[str, Any] = {"caminho": None}

        def imprimir() -> None:
            caminho = arquivo["caminho"]
            if caminho is None:
                return
            try:
                usada = impressao.imprimir(caminho, combo.get())
            except impressao.ImpressaoIndisponivel as exc:
                self._alerta("Impressão", str(exc), parent=janela)
                return
            estado.configure(text=f"Enviada para {usada}.", fg=ui.SUCESSO)

        def salvar() -> None:
            caminho = arquivo["caminho"]
            if caminho is None:
                return
            destino = filedialog.asksaveasfilename(
                parent=janela, title="Salvar cópia do PDF", defaultextension=".pdf",
                initialfile=caminho.name, filetypes=[("PDF", "*.pdf")],
            )
            if destino:
                shutil.copyfile(caminho, destino)
                estado.configure(text=f"Cópia salva em {destino}", fg=ui.SUCESSO)

        def no_navegador() -> None:
            """Abre a nota no site da prefeitura — saída que não depende de nós.

            Quando o download automático falha (rede de empresa costuma barrar
            o segundo endereço), o navegador ainda alcança: ele usa o proxy e
            os certificados do Windows. De lá dá para imprimir e salvar.
            """
            import webbrowser

            try:
                endereco = pdf.endereco_no_portal(nota)
            except Exception as exc:
                registro.falha("endereco no portal", exc)
                endereco = ""
            if not endereco:
                self._info(
                    "Sem endereço",
                    "Esta nota não tem número e código de verificação registrados, "
                    "então não dá para localizá-la no site da prefeitura.",
                    parent=janela,
                )
                return
            registro.escrever("abrindo no navegador", endereco)
            webbrowser.open(endereco)

        botao_imprimir = ttk.Button(acoes, text="Imprimir", style="Primaria.TButton",
                                    command=imprimir)
        botao_abrir = ttk.Button(acoes, text="Abrir PDF",
                                 command=lambda: pdf.abrir(arquivo["caminho"]))
        botao_salvar = ttk.Button(acoes, text="Salvar cópia…", command=salvar)
        for botao in (botao_salvar, botao_abrir, botao_imprimir):
            botao.state(["disabled"])
            botao.pack(side="right", padx=(ui.E2, 0))
        # Este fica sempre ativo: é justamente o que salva a situação quando o
        # PDF não vem. Um botão que só funciona quando tudo deu certo não serve
        # para quando alguma coisa deu errado.
        ttk.Button(acoes, text="Ver no site da prefeitura",
                   command=no_navegador).pack(side="right", padx=(ui.E2, 0))
        ttk.Button(acoes, text="Fechar", command=janela.destroy).pack(side="left")

        botao_repetir = ttk.Button(acoes, text="Tentar de novo")
        vigia: dict[str, Any] = {"id": None}

        def cancelar_vigia() -> None:
            if vigia["id"] is not None and janela.winfo_exists():
                janela.after_cancel(vigia["id"])
            vigia["id"] = None

        def pronto(caminho: Any) -> None:
            registro.escrever("pdf pronto", str(caminho))
            if not janela.winfo_exists():  # o usuário fechou antes de o PDF chegar
                return
            cancelar_vigia()
            botao_repetir.pack_forget()
            arquivo["caminho"] = caminho
            estado.configure(text=f"PDF pronto  ·  {caminho}", fg=ui.INK_3)
            for botao in (botao_imprimir, botao_abrir, botao_salvar):
                botao.state(["!disabled"])
            botao_imprimir.focus_set()

        def falhou(mensagem: str) -> None:
            registro.escrever("pdf falhou", mensagem)
            if not janela.winfo_exists():
                return
            cancelar_vigia()
            aviso = (
                f"A nota nº {numero} FOI emitida — só o PDF não veio agora.\n\n{mensagem}"
                if recem_emitida
                else mensagem
            )
            estado.configure(text=aviso, fg=ui.ERRO)
            botao_repetir.pack(side="right", padx=(ui.E2, 0))

        def andamento(texto: str) -> None:
            if janela.winfo_exists():
                estado.configure(text=texto, fg=ui.INK_3)

        def buscar() -> None:
            cancelar_vigia()
            botao_repetir.pack_forget()
            estado.configure(text="Buscando o PDF no portal…", fg=ui.INK_3)
            # Rede pode não responder nem falhar. Sem este limite, a janela
            # ficaria "buscando" para sempre e sem nada a fazer.
            vigia["id"] = janela.after(
                90_000,
                lambda: falhou(
                    "o portal de visualização não respondeu em 90 segundos.\n\n"
                    "O arquivo pode estar demorando a ser gerado — tente de novo."
                ),
            )
            self._baixar_pdf(nota, pronto, falhou, andamento)

        botao_repetir.configure(command=buscar)
        # Depois de tudo montado: a altura vem do que o conteúdo pede, nunca de
        # um número escolhido aqui. Tela menor ou escala do Windows em 125% e a
        # altura fixa passa a esconder justamente o que fica embaixo.
        ui.dimensionar(janela, 600)
        buscar()
        return janela

    # ------------------------------------------------------------------ #
    # Envio
    # ------------------------------------------------------------------ #

    def _submit(self, selection: tuple[str, ...]) -> None:
        item = self._selected(selection)
        if item is None:
            return
        if item.get("status") == "submitted":
            self._info(
                "Nota já emitida",
                "Esta nota já foi transmitida. Emitir de novo geraria duplicidade.",
            )
            return
        payload = item.get("payload") or {}
        nome = (payload.get("tomador") or {}).get("nome", "—")
        valor = (payload.get("servico") or {}).get("valor", "—")
        pergunta = f"Encaminhar a nota de {nome} (R$ {validation.format_money(valor)}) ao portal?"
        if not messagebox.askyesno("Confirmar envio", pergunta):
            return
        self._submit_item(item)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.configure(cursor="watch" if busy else "")
        for nome in ("send_button", "emit_button"):
            botao = getattr(self, nome, None)
            if botao is not None and botao.winfo_exists():
                botao.state(["disabled"] if busy else ["!disabled"])
        self._avisar_transmissao(busy)

    def _avisar_transmissao(self, ligado: bool) -> None:
        """Enquanto a nota está indo, algo se mexe no canto da tela.

        O botão desabilitado e o cursor de relógio dizem "não clique de novo";
        nenhum dos dois diz "ainda estou trabalhando". Numa transmissão que
        pode levar dezenas de segundos, é a diferença entre esperar e achar
        que travou — e fechar o programa no meio do envio.
        """
        aberto = getattr(self, "_espera_transmissao", None)
        if aberto is not None:
            self.avisos.fechar(aberto)
            self._espera_transmissao = None
        if ligado:
            self._espera_transmissao = self.avisos.trabalhando(
                "Transmitindo ao portal",
                "A prefeitura está processando a nota. Não feche o programa.",
            )

    def _submit_item(self, item: dict[str, Any]) -> None:
        if self._busy:
            messagebox.showinfo("Envio em andamento", "Aguarde a conclusão do envio atual.")
            return
        self._set_busy(True)

        def finish(callback: Callable[[], None]) -> None:
            self._na_interface(lambda: (self._set_busy(False), callback()))

        def send() -> None:
            try:
                outcome = service.submit_document(item)
            except validation.ValidationError as exc:
                # A mensagem é copiada agora: `exc` deixa de existir ao sair do
                # except, e o callback só roda depois, no laço da interface.
                message = f"{exc.field}: {exc.message}"
                finish(lambda: messagebox.showwarning("Dados inválidos", message))
                return
            except service.AlreadySubmitted as exc:
                message = str(exc)
                finish(lambda: messagebox.showinfo("Nota já enviada", message))
                return
            except service.ObraObrigatoria as exc:
                message = str(exc)
                finish(lambda: messagebox.showwarning("Código da Obra", message))
                return
            except service.PrestadorIncompleto as exc:
                message = str(exc)
                finish(lambda: messagebox.showwarning("Dados da empresa", message))
                return
            except nfse_client.NfseError as exc:
                message = str(exc)
                finish(lambda: messagebox.showerror("Erro na integração", message))
                return
            except OSError as exc:
                message = str(exc)
                finish(lambda: messagebox.showerror("Erro de disco", message))
                return
            except Exception as exc:  # nenhuma falha pode sumir silenciosamente
                message = f"{type(exc).__name__}: {exc}"
                finish(lambda: messagebox.showerror("Erro inesperado", message))
                return

            summary = outcome["message"]
            transmitted = outcome["transmitted"]
            status = outcome["status"]
            nota = (outcome.get("document") or {}).get("nota") or {}

            def report() -> None:
                if not transmitted:
                    messagebox.showinfo("Modo seguro", summary)
                elif status == "submitted":
                    # O layout de impressão é o próprio aviso de sucesso: traz o
                    # número da nota na hora e destrava a impressão assim que o
                    # PDF termina de baixar.
                    #
                    # Abre mesmo quando o número não foi reconhecido na resposta.
                    # Antes, esse caso caía numa caixa de aviso comum, sem PDF
                    # nem impressão, e a nota — já emitida — ficava sem saída na
                    # tela. A janela explica o que faltou e deixa tentar de novo.
                    registro.escrever("emissao ok", f"nota nº {nota.get('numero') or '(sem número)'}")
                    try:
                        self.janela_impressao(
                            nota, outcome.get("document") or {}, recem_emitida=True
                        )
                    except Exception as exc:
                        registro.falha("layout de impressao", exc)
                        messagebox.showwarning(
                            "Nota emitida",
                            f"{summary}\n\nO layout de impressão não abriu "
                            f"({type(exc).__name__}). Use Minhas notas → Imprimir.",
                        )
                else:
                    registro.escrever("emissao recusada", summary)
                    messagebox.showerror("Falha na emissão", summary)
                self.show_documents()

            finish(report)

        threading.Thread(target=send, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Configurações
    # ------------------------------------------------------------------ #

    def _test_configuration(self) -> None:
        """Monta a requisição a partir de um rascunho real, sem enviar."""
        rascunhos = [doc for doc in storage.list_all() if doc.get("status") == "draft"]
        if not rascunhos:
            self._info("Sem rascunho",
                                "Crie um rascunho para testar a montagem da requisição.")
            return
        self._preview((rascunhos[0]["id"],))

    def show_settings(self) -> None:
        """O que muda o comportamento do programa, e as ferramentas.

        Aqui já houve um despejo de diagnóstico — endereço do portal,
        marcadores do modelo, caminhos de pasta. Informação de quem escreve o
        programa, não de quem emite nota. Ficou o que decide alguma coisa: se
        transmite de verdade, e os comandos que antes moravam na barra de menu
        do Windows.
        """
        self._clear()
        self._mostrar_comando(True)
        self._marcar_nav("ajustes")
        self._title("Ajustes", "O que muda o comportamento do programa.")

        status = service.describe_configuration()
        colunas = tk.Frame(self.content, bg=ui.BG)
        colunas.pack(fill="both", expand=True)
        esquerda, direita = self.duas_colunas(colunas)

        self._painel_transmissao(status["live_mode"], onde=esquerda)

        # O que impede de emitir continua aparecendo — escondê-lo faria a nota
        # falhar depois, sem explicação.
        if status["pending"]:
            ui.banner(esquerda, "Falta para conseguir emitir:",
                      status["pending"], tom="alerta").pack(fill="x", pady=(0, ui.E3))
        if config.senha_no_arquivo():
            ui.banner(
                esquerda, "A senha do portal está gravada em disco",
                ["Apague a linha NFSE_SENHA do .env para que ela fique só na memória."],
                tom="erro").pack(fill="x", pady=(0, ui.E3))
        if status["corrupted_files"]:
            ui.banner(esquerda, "Arquivos ilegíveis ignorados",
                      list(status["corrupted_files"]), tom="erro").pack(fill="x")

        self._bloco_de_acoes(direita, "Ferramentas", (
            ("Testar conexão", "Confere login, modelo e tabelas",
             self._test_configuration),
            ("Reler a versão do portal", "Depois de uma atualização da prefeitura",
             self._reler_portal),
            ("Trocar de empresa", "Sai e volta à tela de entrada", self.sair),
        ))
        self._bloco_de_acoes(direita, "Marca", (
            ("Usar meu logotipo…", "Um PNG seu no lugar do desenho",
             self._trocar_logotipo),
            ("Exportar a marca…", "Salva o símbolo em PNG", self._exportar_marca),
        ))
        # A versão aparece aqui de propósito: quem dá suporte precisa saber o
        # que está rodando na máquina sem pedir para abrir arquivo nenhum.
        self._bloco_de_acoes(direita, "Programa", (
            ("Procurar atualização", f"Versão {updater.VERSAO_ATUAL}",
             self._procurar_atualizacao),
            ("Diário do programa…", "O que aconteceu, e quando", self._abrir_registro),
            ("Sobre", f"{marca.ASSINATURA} · NFS-e", self._about),
        ))

    def _bloco_de_acoes(self, onde: tk.Widget, titulo: str,
                        itens: tuple[tuple[str, str, Callable[[], None]], ...]) -> None:
        """Um cartão com comandos, um por linha.

        Cada linha diz o que faz embaixo do nome: "Reler a versão do portal"
        não significa nada sozinho para quem só emite nota.
        """
        caixa = ui.cartao(onde, raio=14, padx=0, pady=0)
        caixa.pack(fill="x", pady=(0, ui.E3))
        tk.Label(caixa.interior, text=titulo.upper(), bg=ui.SURFACE, fg=ui.INK_3,
                 font=ui.MICRO_FORTE, anchor="w").pack(fill="x", padx=ui.E4,
                                                       pady=(ui.E3, ui.E2))
        for indice, (nome, explicacao, comando) in enumerate(itens):
            if indice:
                tk.Frame(caixa.interior, bg=ui.SURFACE_FUNDA, height=1).pack(fill="x")
            linha = tk.Frame(caixa.interior, bg=ui.SURFACE, cursor="hand2",
                             padx=ui.E4, pady=ui.E3)
            linha.pack(fill="x")
            nome_widget = tk.Label(linha, text=nome, bg=ui.SURFACE, fg=ui.INK,
                                   font=ui.CORPO, anchor="w")
            nome_widget.pack(fill="x")
            explica = tk.Label(linha, text=explicacao, bg=ui.SURFACE, fg=ui.INK_3,
                               font=ui.MICRO, anchor="w")
            explica.pack(fill="x")
            alvos = (linha, nome_widget, explica)
            for widget in alvos:
                # A mãozinha nos rótulos também: eles cobrem quase toda a
                # linha, e sem isto o cursor mudava só nas beiradas.
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>", lambda _e, c=comando: c())
                widget.bind("<Enter>", lambda _e, a=alvos: [
                    w.configure(bg=ui.SURFACE_ALT) for w in a])
                widget.bind("<Leave>", lambda _e, a=alvos: [
                    w.configure(bg=ui.SURFACE) for w in a])

    def _painel_transmissao(self, ativo: bool, *, onde: tk.Widget | None = None) -> None:
        """Liga e desliga o envio real, sem precisar abrir o .env num editor.

        Antes isso só existia como variável de ambiente. Numa máquina onde o
        programa chegou como executável, "edite o .env" é instrução que ninguém
        cumpre — e o resultado era montar a nota inteira e ela não sair.
        """
        caixa = ui.Redondo(onde or self.content, raio=14, fundo=ui.SURFACE,
                           borda=ui.BORDER, padx=ui.E5, pady=ui.E4)
        caixa.pack(fill="x", pady=(0, ui.E3))
        painel = caixa.interior
        linha = tk.Frame(painel, bg=ui.SURFACE)
        linha.pack(fill="x")

        texto = tk.Frame(linha, bg=ui.SURFACE)
        texto.pack(side="left", fill="x", expand=True)
        ui.pilula(texto, "TRANSMISSÃO ATIVA" if ativo else "MODO SEGURO",
                  cor=ui.ALERTA if ativo else ui.SUCESSO,
                  fundo_pilula=ui.ALERTA_BG if ativo else ui.SUCESSO_BG).pack(anchor="w")
        ui.rotulo(
            texto,
            "As notas são enviadas de verdade à prefeitura."
            if ativo else
            "As notas são montadas e conferidas, mas não saem daqui.",
            fonte=ui.PEQUENO, cor=ui.INK_2,
        ).pack(anchor="w", pady=(ui.E2, 0))

        ttk.Button(
            linha, text="Voltar ao modo seguro" if ativo else "Ativar transmissão",
            style="Discreto.TButton" if ativo else "Primaria.TButton",
            command=lambda: self._trocar_transmissao(not ativo),
        ).pack(side="right", anchor="n")

    def _trocar_transmissao(self, ligar: bool) -> None:
        if ligar and not messagebox.askyesno(
            "Ativar transmissão real",
            "A partir de agora, emitir manda a nota para a prefeitura de verdade.\n\n"
            "Nota emitida não se apaga — só se cancela, e nem todo caso permite "
            "cancelamento.\n\nConfirma?",
            icon="warning", default="no",
        ):
            return
        try:
            config.definir_live_mode(ligar)
        except OSError as exc:
            messagebox.showerror(
                "Não deu para gravar",
                f"O ajuste não pôde ser salvo em {paths.ENV_FILE}:\n{exc}\n\n"
                "Se o programa está numa pasta somente-leitura (um CD, um "
                "pendrive protegido), copie-o para o disco e tente de novo.",
            )
            return
        self._refresh_mode_label()
        self.show_settings()

    def _ver_obras_bruto(self) -> None:
        """A resposta crua de listaObra, para quando a lista vem vazia.

        A leitura da lista de obras só pôde ser validada contra uma empresa sem
        obras cadastradas. Quando ela falha numa empresa que tem, é isto que
        mostra o formato real em vez de deixar adivinhar.
        """
        import obras as obras_portal

        def buscar() -> list[str]:
            bruto = obras_portal.resposta_bruta()
            lidas = obras_portal.ler_resposta(bruto)
            cabeca = [f"obras reconhecidas pela leitura atual: {len(lidas)}"]
            cabeca += [f"   {o['codigo']}  {o['descricao']}" for o in lidas]
            cabeca += ["", "--- resposta crua do portal ---", ""]
            return cabeca + [bruto]

        self._janela_bruta("Obras — listaObra", buscar)

    def _ver_leitura_bruta(self) -> None:
        """Lista, numerada, a tabela crua do getSession.

        Serve para consertar as regras de leitura: elas funcionam por
        vizinhança, e só a ordem real dos campos daquela empresa mostra qual é
        a razão social e qual é o nome fantasia.
        """
        import prestador

        self._janela_bruta("Leitura bruta do portal — getSession",
                           prestador.tabela_bruta, numerar=True)

    def _janela_bruta(self, titulo: str, buscar, *, numerar: bool = False) -> None:
        """Janela de diagnóstico: mostra o que o portal respondeu, sem interpretar."""
        janela = tk.Toplevel(self)
        janela.title(titulo)
        janela.configure(bg=ui.BG)
        ui.centralizar(janela, 620, 620)

        # Rodapé preso embaixo antes do corpo — ver janela_impressao.
        rodape = tk.Frame(janela, bg=ui.BG, padx=ui.E5, pady=ui.E4)
        rodape.pack(side="bottom", fill="x")

        topo = tk.Frame(janela, bg=ui.SURFACE, padx=ui.E5, pady=ui.E4)
        topo.pack(fill="x")
        tk.Frame(janela, bg=ui.BORDER, height=1).pack(fill="x")
        tk.Label(topo, text=titulo, bg=ui.SURFACE, fg=ui.INK,
                 font=ui.TITULO).pack(anchor="w")
        tk.Label(topo, text="O que o portal respondeu, sem interpretação.",
                 bg=ui.SURFACE, fg=ui.INK_3, font=ui.PEQUENO).pack(anchor="w", pady=(2, 0))

        moldura = tk.Frame(janela, bg=ui.BG, padx=ui.E5, pady=ui.E4)
        moldura.pack(fill="both", expand=True)
        caixa = tk.Frame(moldura, bg=ui.SURFACE, highlightbackground=ui.BORDER,
                         highlightthickness=1)
        caixa.pack(fill="both", expand=True)
        texto = tk.Text(caixa, font=(ui.MONO, 9), wrap="none", padx=ui.E3, pady=ui.E3,
                        relief="flat", bd=0, bg=ui.SURFACE, fg=ui.INK)
        barra = ttk.Scrollbar(caixa, orient="vertical", command=texto.yview)
        texto.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        texto.pack(side="left", fill="both", expand=True)
        texto.insert("1.0", "Consultando o portal…")

        def mostrar(linhas: list[str]) -> None:
            if not janela.winfo_exists():
                return
            texto.configure(state="normal")
            texto.delete("1.0", "end")
            texto.insert("1.0", "\n".join(
                f"{i:>3}  {valor}" for i, valor in enumerate(linhas, 1)
            ))
            texto.configure(state="disabled")

        def falhou(mensagem: str) -> None:
            if janela.winfo_exists():
                texto.configure(state="normal")
                texto.delete("1.0", "end")
                texto.insert("1.0", mensagem)

        def trabalho() -> None:
            try:
                linhas = buscar()
            except Exception as exc:
                mensagem = str(exc)
                self._na_interface(lambda: falhou(f"Não consegui ler: {mensagem}"))
                return
            self._na_interface(lambda: mostrar(linhas))

        threading.Thread(target=trabalho, daemon=True).start()

        ttk.Button(rodape, text="Fechar", command=janela.destroy).pack(side="right")
        ttk.Button(
            rodape, text="Copiar",
            command=lambda: (self.clipboard_clear(),
                             self.clipboard_append(texto.get("1.0", "end"))),
        ).pack(side="right", padx=ui.E2)


class ViewDocumentos(tk.Frame):
    """A tela "Minhas notas": filtros, contadores e a lista.

    Vive fora de ``NfseDesktop`` por dois motivos. O primeiro é tamanho: a
    janela já é grande demais para caber na cabeça de uma vez. O segundo é
    desempenho — como tela própria, ela guarda os widgets que criou e passa a
    ATUALIZAR em vez de reconstruir. Filtrar deixa de custar a montagem de uma
    Treeview inteira a cada tecla digitada.

    A regra fiscal continua em ``NfseDesktop``: enviar, excluir, imprimir e
    abrir no portal são chamadas de volta para lá. Esta classe desenha e
    pergunta.
    """

    GRUPOS = (
        ("", "Todas", "info"),
        ("submitted", "Emitidas", "sucesso"),
        ("draft", "Rascunhos", "neutro"),
        ("failed", "Recusadas", "erro"),
    )
    ESPERA_DATA = 300      # o mesmo respiro da caixa de busca

    def __init__(self, pai: tk.Widget, app: "NfseDesktop",
                 *, situacao: str = "") -> None:
        super().__init__(pai, bg=ui.BG)
        self.app = app
        self.docs = storage.list_all()
        self.situacao = situacao      # "" = todas
        self.procurado = ""
        # `None` = a ordem natural: a mais recente primeiro. É o que faz
        # sentido ao abrir, porque a nota que se procura costuma ser a última.
        self.ordem: tuple[str, bool] | None = None
        self._tarefa_data: str | None = None

        # Calculado uma vez. Estes três não mudam enquanto a tela está aberta,
        # e remontá-los para cada nota a cada tecla era o que sobrava de custo
        # depois de a tabela parar de ser reconstruída: formatar moeda e CNPJ
        # quinhentas vezes por letra digitada.
        self._busca_de: dict[str, str] = {}
        self._prestador_de: dict[str, str] = {}
        self._valor_de: dict[str, Decimal] = {}
        for doc in self.docs:
            chave = doc["id"]
            self._busca_de[chave] = self.app._texto_do_doc(doc)
            self._prestador_de[chave] = self.app.prestador_do_doc(doc)
            self._valor_de[chave] = self._calcular_valor(doc)

        if not self.docs:
            self.app._documents_table(self, self.docs, actions=True)
            return

        self._montar_filtros()
        self._montar_cartoes()

        # Duas colunas: a lista à esquerda, o detalhe à direita. Substituem a
        # janela de detalhes que abria por cima de tudo.
        self.divisao = tk.Frame(self, bg=ui.BG)
        self.divisao.pack(fill="both", expand=True)
        self.coluna_lista, self.coluna_detalhe = self.app.duas_colunas(self.divisao)

        self._montar_tabela()
        self._montar_rodape()
        self._ligar_teclado()
        self.atualizar()
        self._desenhar_detalhe()

    # ------------------------------------------------------------------ #
    # Montagem — acontece uma vez
    # ------------------------------------------------------------------ #

    def _montar_filtros(self) -> None:
        barra = tk.Frame(self, bg=ui.BG)
        barra.pack(fill="x", pady=(0, ui.E3))

        ui.CampoBusca(barra, self._buscar, largura=24,
                      dica="Tomador, CNPJ, nº, valor…", fundo=ui.BG).pack(side="left")

        # Tudo nesta fileira tem a mesma forma: cartão de canto redondo com
        # o rótulo em caixa alta e o controle dentro. Antes eram quatro formas
        # diferentes lado a lado — a lista quadrada, com moldura própria no
        # botão de seta, era a que mais destoava.
        self.empresas = ["Todas as empresas"] + sorted(
            {self.app.prestador_do_doc(doc) for doc in self.docs})
        self.empresa = tk.StringVar(value=self.empresas[0])
        cartao_empresa = ui.Redondo(barra, raio=10, fundo=ui.SURFACE,
                                    borda=ui.BORDER_FORTE, padx=ui.E2, pady=2)
        cartao_empresa.pack(side="left", padx=(ui.E2, 0))
        tk.Label(cartao_empresa.interior, text="EMPRESA", font=ui.ETIQUETA,
                 bg=ui.SURFACE, fg=ui.INK_3, padx=ui.E1).pack(side="left")
        caixa = ttk.Combobox(cartao_empresa.interior, textvariable=self.empresa,
                             values=self.empresas, state="readonly", width=22,
                             style="Plano.TCombobox", font=ui.PEQUENO)
        caixa.pack(side="left")
        caixa.bind("<<ComboboxSelected>>", lambda _e: self.atualizar())

        self.de = tk.StringVar()
        self.ate = tk.StringVar()
        for variavel, rotulo in ((self.de, "DE"), (self.ate, "ATÉ")):
            caixa = ui.Redondo(barra, raio=10, fundo=ui.SURFACE,
                               borda=ui.BORDER_FORTE, padx=ui.E2, pady=4)
            caixa.pack(side="left", padx=(ui.E2, 0))
            grupo = caixa.interior
            tk.Label(grupo, text=rotulo, font=ui.ETIQUETA, bg=ui.SURFACE,
                     fg=ui.INK_3, padx=(ui.E1)).pack(side="left")
            # 11 caracteres: cabem "29/08/2026" e a dica "dd/mm/aaaa" inteira.
            # Com 9, a dica saía cortada em "dd/mm/aa" e parecia defeito.
            campo = tk.Entry(grupo, textvariable=variavel, width=12, font=ui.PEQUENO,
                             relief="flat", bd=0, bg=ui.SURFACE, fg=ui.INK,
                             insertbackground=ui.INK)
            campo.pack(side="left", ipady=5, padx=(0, ui.E1))
            # A caixa vazia não dizia o que esperava. Agora diz.
            ui.dica_no_campo(campo, "dd/mm/aaaa")
            campo.bind("<FocusIn>", lambda _e, c=caixa: c.pintar(borda=ui.PRIMARIA))
            campo.bind("<FocusOut>", lambda _e, c=caixa: c.pintar(borda=ui.BORDER_FORTE))
            # Com respiro, como a busca: sem ele, cada dígito de "29/08/2026"
            # disparava um redesenho — dez redesenhos para uma data.
            variavel.trace_add("write", lambda *_a: self._adiar_atualizacao())

        # O mesmo cartão dos outros, e agora dizendo o que faz: o "R$" sozinho
        # não contava que era o botão de esconder os valores da tela.
        self.cartao_olho = ui.Redondo(barra, raio=10, fundo=ui.SURFACE,
                                      borda=ui.BORDER_FORTE, padx=ui.E3, pady=7,
                                      cursor="hand2")
        self.cartao_olho.pack(side="left", padx=(ui.E2, 0))
        self.olho = tk.Label(self.cartao_olho.interior, text="R$  À VISTA",
                             font=ui.ETIQUETA, bg=ui.SURFACE, fg=ui.INK_2,
                             cursor="hand2")
        self.olho.pack()
        for alvo in (self.cartao_olho, self.olho):
            alvo.bind("<Button-1>", lambda _e: self._alternar_valores())

        # As ações da tela ficam na mesma linha dos filtros: uma fileira de
        # botões sozinha no alto era uma faixa inteira sem função.
        ttk.Button(barra, text="Emitir NFS-e", style="Primaria.TButton",
                   command=self.app.show_new_note).pack(side="right")
        ttk.Button(barra, text="Limpar histórico…", style="Discreto.TButton",
                   command=self.app.limpar_historico).pack(side="right",
                                                           padx=(0, ui.E2))

    def _montar_cartoes(self) -> None:
        faixa = tk.Frame(self, bg=ui.BG)
        faixa.pack(fill="x", pady=(0, ui.E3))
        self.cartoes: dict[str, ui.CartaoFiltro] = {}
        for indice, (chave, titulo, tom) in enumerate(self.GRUPOS):
            cartao = ui.CartaoFiltro(faixa, titulo, tom=tom,
                                     ao_clicar=lambda c=chave: self._escolher(c))
            cartao.pack(side="left", expand=True, fill="both",
                        padx=(0 if indice == 0 else ui.E2, 0))
            self.cartoes[chave] = cartao

    def _montar_tabela(self) -> None:
        moldura = ui.Redondo(self.coluna_lista, raio=14, fundo=ui.SURFACE,
                             borda=ui.BORDER, padx=0, pady=0)
        moldura.pack(fill="both", expand=True)
        self.moldura = moldura
        self.selecionada: str | None = None
        self.tabela = ui.Tabela(
            moldura.interior, colunas_de_notas(),
            ao_selecionar=self._selecionar,
            ao_abrir=lambda identidade: self.app._details((identidade,)),
            ao_agir=self._agir_na_linha,
            ao_ordenar=self._ordenar_por,
        )
        self.tabela.pack(fill="both", expand=True)

        # O estado vazio mora ao lado da tabela e troca de lugar com ela — em
        # vez de a tabela ser destruída e refeita quando o filtro não acha nada.
        self.aviso_vazio = tk.Frame(moldura.interior, bg=ui.SURFACE)

    # ------------------------------------------------------------------ #
    # Teclado
    # ------------------------------------------------------------------ #

    def _ligar_teclado(self) -> None:
        """Setas andam pela lista; Enter abre a nota escolhida.

        As teclas são presas na janela, não na tabela: no Tk quem recebe tecla
        é quem tem o foco, e o foco quase sempre está na caixa de busca — onde
        a pessoa acabou de digitar. Presa na janela, a seta funciona de onde
        se estiver, e `_teclado_livre` garante que ela não roube a seta de
        quem está no meio de um campo de texto.
        """
        janela = self.winfo_toplevel()
        self._teclas = []
        for sequencia, acao in (("<Down>", lambda _e: self._andar(1)),
                                ("<Up>", lambda _e: self._andar(-1)),
                                ("<Home>", lambda _e: self._ir_para(0)),
                                ("<End>", lambda _e: self._ir_para(-1)),
                                ("<Return>", lambda _e: self._abrir_escolhida())):
            self._teclas.append((sequencia, janela.bind(sequencia, acao, add="+")))
        self.bind("<Destroy>", self._soltar_teclado, add="+")

    def _soltar_teclado(self, evento=None) -> None:
        # `<Destroy>` sobe dos filhos também; só interessa o desta tela.
        if evento is not None and evento.widget is not self:
            return
        try:
            janela = self.winfo_toplevel()
            for sequencia, identificador in getattr(self, "_teclas", []):
                janela.unbind(sequencia, identificador)
        except tk.TclError:
            pass
        self._teclas = []

    def _teclado_livre(self) -> bool:
        """Falso quando o foco está num campo de texto.

        Sem isto, a seta para baixo dentro da caixa de busca deixaria de mover
        o cursor e passaria a pular de nota — e ninguém entenderia por quê.
        """
        try:
            foco = self.focus_get()
        except (KeyError, tk.TclError):
            return False
        return not isinstance(foco, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox))

    def _visiveis(self) -> list:
        return [linha for linha in self.tabela._linhas if linha.winfo_manager()]

    def _andar(self, passo: int) -> None:
        if not self._teclado_livre():
            return
        linhas = self._visiveis()
        if not linhas:
            return
        atuais = [i for i, l in enumerate(linhas) if l.identidade == self.selecionada]
        if not atuais:
            self._ir_para(0 if passo > 0 else -1)
            return
        destino = max(0, min(len(linhas) - 1, atuais[0] + passo))
        self._escolher_linha(linhas[destino])

    def _ir_para(self, indice: int) -> None:
        if not self._teclado_livre():
            return
        linhas = self._visiveis()
        if linhas:
            self._escolher_linha(linhas[indice])

    def _escolher_linha(self, linha) -> None:
        self.tabela.marcada = linha.identidade
        self.tabela.mostrar(self.tabela._dados)
        self._selecionar(linha.identidade)

    def _abrir_escolhida(self) -> None:
        if self._teclado_livre() and self.selecionada:
            self.app.abrir_pdf_direto((self.selecionada,))

    def _escolhida(self) -> tuple[str, ...]:
        """A seleção, no formato que os métodos de emissão esperam."""
        return (self.selecionada,) if self.selecionada else ()

    def _selecionar(self, identidade: str | None) -> None:
        self.selecionada = identidade
        self._desenhar_detalhe()

    def _agir_na_linha(self, identidade: str, acao: str) -> None:
        """Os ícones da própria linha: ver em PDF, ou enviar."""
        self.selecionada = identidade
        self.tabela.marcada = identidade
        self._desenhar_detalhe()
        if acao == "pdf":
            self.app.abrir_pdf_direto((identidade,))
        else:
            self.app._submit((identidade,))

    def _desenhar_detalhe(self) -> None:
        """O painel da direita: tudo sobre a nota escolhida, e o que fazer com ela.

        Substitui a janela de "Detalhes". Uma janela por cima esconde a lista
        e obriga a fechá-la para escolher outra nota; ao lado, dá para andar
        pela lista lendo o detalhe de cada uma.
        """
        for filho in self.coluna_detalhe.winfo_children():
            filho.destroy()

        doc = next((d for d in self.docs if d["id"] == self.selecionada), None)
        if doc is None:
            # Sem nota escolhida, a coluna mostra quanto cada login faturou —
            # a única coisa que era exclusiva do Painel. Antes havia aqui um
            # convite ocupando a altura inteira sem dizer nada de novo.
            self.app._resumo_por_empresa(self.coluna_detalhe, self._faturadas())
            tk.Label(self.coluna_detalhe,
                     text="Clique numa nota para ver tudo sobre ela aqui — "
                          "inclusive por que foi recusada.",
                     bg=ui.BG, fg=ui.INK_3, font=ui.MICRO, justify="left",
                     wraplength=ui.px(310), anchor="w").pack(fill="x",
                                                            pady=(ui.E3, 0))
            return

        status = doc.get("status", "")
        tom = TOM_DO_STATUS.get(status, "neutro")
        cor = ui.cores_do_tom(tom)[0]
        numero = (doc.get("nota") or {}).get("numero")
        servico = (doc.get("payload") or {}).get("servico") or {}
        tomador = (doc.get("payload") or {}).get("tomador") or {}

        caixa = ui.Redondo(self.coluna_detalhe, raio=14, fundo=ui.SURFACE,
                           borda=ui.BORDER, padx=0, pady=0)
        caixa.pack(fill="x")
        dentro = caixa.interior

        capa = tk.Frame(dentro, bg=ui.SURFACE_ALT, padx=ui.E4, pady=ui.E4)
        capa.pack(fill="x")
        tk.Label(capa, text=f"nº {numero}" if numero else STATUS_LABELS.get(status, status),
                 bg=ui.SURFACE_ALT, fg=ui.INK,
                 font=(ui.FAMILIA, 19, "bold")).pack(anchor="w")
        tk.Label(capa, text=(tomador.get("nome")
                             or validation.format_document(str(tomador.get("documento", "")))
                             or "Sem tomador")[:38],
                 bg=ui.SURFACE_ALT, fg=ui.INK_2, font=ui.PEQUENO).pack(anchor="w",
                                                                       pady=(3, 0))
        tk.Frame(dentro, bg=ui.BORDER, height=1).pack(fill="x")

        corpo = tk.Frame(dentro, bg=ui.SURFACE, padx=ui.E4, pady=ui.E4)
        corpo.pack(fill="x")

        selo = tk.Frame(corpo, bg=ui.SURFACE)
        selo.pack(anchor="w", pady=(0, ui.E3))
        ui.pilula(selo, STATUS_LABELS.get(status, status), tom=tom,
                  fundo=ui.SURFACE).pack()

        # Nota reconstruída do PDF tem de se identificar. O número e o código
        # de verificação vieram do nome do arquivo e conferem com o miolo do
        # PDF; o resto foi lido do desenho da prefeitura, que pode mudar. Quem
        # olha precisa saber qual dos dois está vendo.
        if doc.get("recuperado_do_pdf"):
            aviso = tk.Frame(corpo, bg=ui.SURFACE_ALT, padx=ui.E3, pady=ui.E2)
            aviso.pack(fill="x", pady=(0, ui.E3))
            tk.Label(aviso, text="RECONSTRUÍDA DO PDF", bg=ui.SURFACE_ALT,
                     fg=ui.INK_3, font=ui.MICRO).pack(anchor="w")
            tk.Label(aviso,
                     text="Número e código conferem com o arquivo.\n"
                          "Os demais campos foram lidos do PDF.",
                     bg=ui.SURFACE_ALT, fg=ui.INK_2, font=ui.MICRO,
                     justify="left").pack(anchor="w")

        valor = self._valor(doc)
        try:
            aliquota = Decimal(str(servico.get("aliquota") or "0").replace(",", "."))
        except (ArithmeticError, ValueError):
            aliquota = Decimal("0")
        linhas = [
            ("Prestador", self._prestador(doc)),
            ("Serviço", " ".join((servico.get("descricao") or "—").split())),
            ("Valor", self._dinheiro(valor)),
            ("ISS", self._dinheiro(valor * aliquota / Decimal(100))),
            ("Emissão", _data_br(doc.get("created_at"))),
        ]
        codigo = (doc.get("nota") or {}).get("codigo_verificacao")
        if codigo:
            linhas.append(("Verificação", str(codigo)))

        for rotulo, conteudo in linhas:
            linha = tk.Frame(corpo, bg=ui.SURFACE)
            linha.pack(fill="x", pady=(0, ui.E2))
            tk.Label(linha, text=rotulo.upper(), bg=ui.SURFACE, fg=ui.INK_3,
                     font=ui.MICRO_FORTE, width=13, anchor="nw").pack(side="left",
                                                                      anchor="n")
            tk.Label(linha, text=conteudo, bg=ui.SURFACE, fg=ui.INK,
                     font=ui.PEQUENO, anchor="w", justify="left",
                     wraplength=178).pack(side="left", fill="x", expand=True)

        if status == "failed":
            aviso = ui.Redondo(dentro, raio=11, fundo=ui.ERRO_BG, borda=ui.ERRO,
                               fundo_externo=ui.SURFACE, padx=ui.E3, pady=ui.E3)
            aviso.pack(fill="x", padx=ui.E4, pady=(0, ui.E3))
            tk.Label(aviso.interior, text="POR QUE FOI RECUSADA", bg=ui.ERRO_BG,
                     fg=ui.ERRO, font=ui.MICRO_FORTE).pack(anchor="w")
            for rotulo, conteudo in motivo_da_falha(doc):
                tk.Label(aviso.interior,
                         text=f"{rotulo} — {conteudo}" if rotulo else conteudo,
                         bg=ui.ERRO_BG, fg=ui.INK, font=ui.PEQUENO, anchor="w",
                         justify="left", wraplength=250).pack(anchor="w",
                                                              pady=(ui.E1, 0))

        # `pady` de widget não aceita tupla — só o de `pack`. A folga de
        # baixo vai no empacotamento.
        botoes = tk.Frame(dentro, bg=ui.SURFACE, padx=ui.E4)
        botoes.pack(fill="x", pady=(0, ui.E4))
        tem_pdf = status == "submitted" and bool(numero)
        ttk.Button(botoes, text="Abrir em PDF", style="TButton",
                   state="normal" if tem_pdf else "disabled",
                   command=lambda: self.app.abrir_pdf_direto(self._escolhida())
                   ).pack(fill="x")
        ttk.Button(botoes, text="Salvar como…", style="TButton",
                   state="normal" if tem_pdf else "disabled",
                   command=lambda: self.app.salvar_pdf_como(self._escolhida())
                   ).pack(fill="x", pady=(ui.E2, 0))
        self.app.send_button = ttk.Button(
            botoes, text="Reenviar" if status == "failed" else "Enviar ao portal",
            style="Primaria.TButton",
            state="disabled" if status == "submitted" else "normal",
            command=lambda: self.app._submit(self._escolhida()))
        self.app.send_button.pack(fill="x", pady=(ui.E2, 0))
        ttk.Button(botoes, text="Excluir", style="PerigoLeve.TButton",
                   command=lambda: self.app._excluir(self._escolhida())
                   ).pack(fill="x", pady=(ui.E2, 0))
        if tem_pdf:
            # Não é um terceiro botão de igual peso: é o que salva a situação
            # quando a rede da empresa barra o download do portal. O navegador
            # atravessa com o proxy e os certificados do Windows.
            site = tk.Label(botoes, text="Ver no site da prefeitura",
                            bg=ui.SURFACE, fg=ui.INK_3, font=ui.MICRO,
                            cursor="hand2")
            site.pack(anchor="w", pady=(ui.E2, 0))
            site.bind("<Button-1>",
                      lambda _e: self.app._abrir_no_portal(self._escolhida()))

    def _montar_rodape(self) -> None:
        linha = tk.Frame(self.coluna_lista, bg=ui.BG)
        linha.pack(fill="x", pady=(ui.E2, 0))
        self.rodape = linha
        self.contagem = tk.Label(linha, text="", bg=ui.BG, fg=ui.INK_3, font=ui.PEQUENO)
        self.contagem.pack(side="left")
        self.total = tk.Label(linha, text="", bg=ui.BG, fg=ui.INK, font=ui.CORPO_FORTE)
        self.total.pack(side="right")
        tk.Label(linha, text="Soma do que está à vista:", bg=ui.BG, fg=ui.INK_3,
                 font=ui.PEQUENO).pack(side="right", padx=(0, ui.E2))

    # ------------------------------------------------------------------ #
    # Filtro
    # ------------------------------------------------------------------ #

    def _valor(self, doc: dict[str, Any]) -> Decimal:
        """O valor da nota, do índice."""
        return self._valor_de.get(doc["id"], Decimal("0"))

    def _prestador(self, doc: dict[str, Any]) -> str:
        """Quem emitiu, do índice."""
        return self._prestador_de.get(doc["id"], "— não registrado")

    @staticmethod
    def _calcular_valor(doc: dict[str, Any]) -> Decimal:
        """O valor de uma nota, ou zero quando ele estiver ilegível.

        Somar a coluna não pode ser o que impede a lista de abrir: um rascunho
        com valor mal digitado vale zero aqui e continua visível na tabela,
        onde dá para corrigi-lo.
        """
        bruto = (doc.get("payload") or {}).get("servico", {}).get("valor")
        try:
            return validation.normalize_money(str(bruto or "0"))
        except (validation.ValidationError, ArithmeticError, TypeError):
            return Decimal("0")

    @staticmethod
    def _limite(campo: tk.StringVar) -> str:
        """dd/mm/aaaa digitado vira aaaa-mm-dd, que é como a data é guardada.

        Data pela metade devolve vazio em vez de erro: quem está digitando
        "29/0" não pediu para a lista sumir.
        """
        bruto = re.sub(r"\D", "", campo.get())
        if len(bruto) != 8:
            return ""
        return f"{bruto[4:]}-{bruto[2:4]}-{bruto[:2]}"

    def _faturadas(self) -> list[dict[str, Any]]:
        """As notas emitidas que estão à vista, com os filtros em vigor.

        Do que está filtrado, e não de tudo: quem restringiu a busca a um mês
        quer o faturamento daquele mês, não o de sempre.
        """
        return [doc for doc in self._pelo_topo() if doc.get("status") == "submitted"]

    def _ordenar_por(self, chave: str, crescente: bool) -> None:
        self.ordem = (chave, crescente)
        self.atualizar()

    def _chave_de_ordem(self, chave: str):
        """Como comparar cada coluna — pelo VALOR, não pelo texto da tela.

        Ordenar "R$ 1.250,00" como texto põe mil antes de novecentos, e
        "29/08/2026" antes de "05/09/2026". O que se compara aqui é o número
        e a data de verdade, que é o que já está guardado na nota.
        """
        ordem_da_situacao = {"failed": 0, "draft": 1, "submitted": 2}

        def tomador(doc):
            dados = (doc.get("payload") or {}).get("tomador") or {}
            return str(dados.get("nome") or dados.get("documento") or "").lower()

        chaves = {
            "prestador": lambda doc: self._prestador(doc).lower(),
            "tomador": tomador,
            "valor": self._valor,
            # Recusada primeiro: é a que precisa de alguém.
            "status": lambda doc: ordem_da_situacao.get(doc.get("status"), 9),
            "data": lambda doc: str(doc.get("created_at") or ""),
        }
        return chaves.get(chave)

    def _pelo_topo(self) -> list[dict[str, Any]]:
        """As notas que passam por empresa, período e busca.

        A situação NÃO entra aqui: se entrasse, os contadores mudariam de
        número ao clicar num deles, e o total deixaria de ser o total.
        """
        empresa = self.empresa.get()
        de, ate = self._limite(self.de), self._limite(self.ate)
        escolhidas = []
        for doc in self.docs:
            if empresa != self.empresas[0] and self._prestador(doc) != empresa:
                continue
            dia = str(doc.get("created_at", ""))[:10]
            if de and dia < de:
                continue
            if ate and dia > ate:
                continue
            if not ui.combina(self._busca_de[doc["id"]], self.procurado):
                continue
            escolhidas.append(doc)

        if self.ordem is None:
            return escolhidas
        chave, crescente = self.ordem
        comparar = self._chave_de_ordem(chave)
        if comparar is None:
            return escolhidas
        return sorted(escolhidas, key=comparar, reverse=not crescente)

    def _dinheiro(self, soma: Decimal) -> str:
        if self.app._valores_ocultos:
            return "R$ •••"
        return f"R$ {validation.format_money(soma)}"

    # ------------------------------------------------------------------ #
    # Ações da tela
    # ------------------------------------------------------------------ #

    def _buscar(self, texto: str) -> None:
        self.procurado = texto
        self.atualizar()

    def _adiar_atualizacao(self) -> None:
        """Junta as teclas de uma data num redesenho só."""
        if self._tarefa_data:
            try:
                self.after_cancel(self._tarefa_data)
            except tk.TclError:
                pass
        self._tarefa_data = self.after(self.ESPERA_DATA, self.atualizar)

    def _escolher(self, chave: str) -> None:
        # Clicar de novo no que já está escolhido volta para "todas": é o jeito
        # de desfazer sem procurar um botão de limpar.
        self.situacao = "" if self.situacao == chave else chave
        self.atualizar()

    def _alternar_valores(self) -> None:
        self.app._valores_ocultos = not self.app._valores_ocultos
        oculto = self.app._valores_ocultos
        self.olho.configure(text="•••  OCULTOS" if oculto else "R$  À VISTA",
                            fg=ui.PRIMARIA if oculto else ui.INK_2)
        self.cartao_olho.pintar(borda=ui.PRIMARIA if oculto else ui.BORDER_FORTE)
        self.atualizar()

    # ------------------------------------------------------------------ #
    # Atualização — acontece a cada filtro
    # ------------------------------------------------------------------ #

    def atualizar(self) -> None:
        """Repõe o conteúdo. Nenhum widget nasce nem morre aqui."""
        if not self.winfo_exists() or not hasattr(self, "tabela"):
            return
        base = self._pelo_topo()
        for chave, _titulo, _tom in self.GRUPOS:
            lista = base if not chave else [d for d in base if d.get("status") == chave]
            self.cartoes[chave].atualizar(
                str(len(lista)),
                self._dinheiro(sum((self._valor(d) for d in lista), Decimal("0"))),
                ativo=self.situacao == chave,
            )

        visiveis = (base if not self.situacao
                    else [d for d in base if d.get("status") == self.situacao])
        self.tabela.mostrar([
            linha_da_nota(doc, self._prestador,
                          ocultar_valores=self.app._valores_ocultos)
            for doc in visiveis
        ])
        # Trocar as linhas pode apagar a seleção; a explicação da nota que
        # sumiu não pode continuar na tela falando de outra coisa.
        self.selecionada = self.tabela.marcada
        if hasattr(self, "coluna_detalhe"):
            self._desenhar_detalhe()

        if visiveis:
            self.aviso_vazio.pack_forget()
            for filho in self.aviso_vazio.winfo_children():
                filho.destroy()
            if not self.tabela.winfo_manager():
                self.tabela.pack(fill="both", expand=True)
        else:
            self.tabela.pack_forget()
            for filho in self.aviso_vazio.winfo_children():
                filho.destroy()
            # Mandar "emitir a primeira" para quem tem noventa notas e errou o
            # filtro é responder outra pergunta.
            ui.vazio(self.aviso_vazio, "⌕", "Nenhuma nota com esses filtros",
                     "Tente outra empresa, outro período, ou limpe a busca."
                     ).pack(fill="both", expand=True)
            self.aviso_vazio.pack(fill="both", expand=True)

        filtrando = len(visiveis) != len(self.docs)
        self.contagem.configure(
            text=f"{len(visiveis)} de {len(self.docs)} nota(s)" if filtrando
            else f"{len(self.docs)} nota(s)")
        self.total.configure(
            text=self._dinheiro(sum((self._valor(d) for d in visiveis), Decimal("0"))))


if __name__ == "__main__":
    NfseDesktop().mainloop()

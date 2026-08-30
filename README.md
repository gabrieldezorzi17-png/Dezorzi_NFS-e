# Automação NFS-e — São Bernardo do Campo

Automação **100% HTTP** para emitir NFS-e no portal municipal: o programa faz
login, mantém a sessão e transmite a nota por requisições HTTP diretas. Não há
navegador, Selenium nem robô de tela no caminho.

> A emissão fiscal exige credenciais válidas e conferência das regras da
> prefeitura. Por segurança, a transmissão real começa **desativada**.

Só a biblioteca padrão do Python é usada — não há nada para instalar além do
Python 3.11 ou superior.

## O que roda por HTTP e o que exige captura

| Etapa | Como funciona |
| --- | --- |
| Login no portal | HTTP, automático, com as credenciais do `.env` |
| Renovação de sessão | HTTP, automática, quando a sondagem detecta que caiu |
| Emissão da nota | HTTP, uma requisição por nota |
| **Descobrir o formato das requisições** | **Captura única no navegador** |

A captura é única e não se repete no dia a dia: o portal usa GWT-RPC, um formato
serializado que só pode ser conhecido observando uma chamada real. Depois que o
modelo existe, a operação é inteiramente HTTP.

## Qual arquivo executar

| Quero | Execute |
| --- | --- |
| **Interface web** (navegador) | `python server.py` → abra `http://127.0.0.1:8080` |
| **Aplicativo desktop** (janela) | `python desktop.py` |
| Conferir login e sessão | `python testar_conexao.py` |
| Rodar os testes | `python -m unittest discover -s tests` |

No VS Code é só **F5** e escolher a configuração; elas estão numeradas na mesma
ordem em [.vscode/launch.json](.vscode/launch.json).

## Instalação

1. Copie `.env.example` para `.env` e preencha os dados.
2. Gere os modelos de requisição (seção abaixo).
3. Rode a interface que preferir:

```bash
python desktop.py
```

```bash
python server.py
```

O desktop e a interface web usam os mesmos rascunhos, a mesma validação e as
mesmas regras de segurança — a lógica de emissão vive em um único lugar
(`service.py`).

## Capturando os modelos

No navegador: `F12` → aba **Rede** → faça a operação → botão direito → **Copiar
todas como cURL** → cole num arquivo `.txt`. Os formatos bash e cmd (`^"`) são
aceitos, e a captura pode ter dezenas de requisições — o importador separa e
lista todas pelo nome do método:

```bash
python import_curl.py captura/emitir.txt --listar
```

```
A captura tem 48 requisições. Escolha uma com --comando N ou --conter NOME:
    1. listaPais
    2. listaUF
   ...
   45. emitirNfs
```

Escolha a certa com `--conter emitirNfs` (por nome) ou `--comando 45` (por posição).

**Emissão** — capture uma chamada `emitirNfs` e marque os valores fiscais pela
posição na tabela GWT-RPC:

```bash
python import_curl.py captura/emitir.txt --conter emitirNfs --map-index 15=competencia --map-index 38=servico.descricao --map-index 46=servico.valor_liquido --map-index 47=servico.aliquota_fracao --map-index 48=servico.valor --map-index 54=servico.iss
```

**Login** — capture a chamada de autenticação. Atenção: as requisições que o
portal dispara logo *depois* de entrar (`listaUF`, `getSession`, `consultarServicos`…)
já carregam um `JSESSIONID` válido e **não** são o login. O login é a requisição
disparada no momento em que você clica em Entrar, e a resposta dela traz
`Set-Cookie`.

```bash
python import_curl.py captura/login.txt --login --usuario SEU_USUARIO --senha SUA_SENHA
```

O importador separa `Cookie`, `Authorization` e `X-GWT-Permutation` para o
`.env`, remove cabeçalhos que atrapalham (`Accept-Encoding` faria o portal
responder comprimido sem que o programa saiba descomprimir) e troca os valores
capturados por marcadores.

Depois de gerar `config/login_template.json`, ajuste o bloco `probe` para uma
URL que só responde autenticado e um trecho que só aparece na sessão válida — é
essa sondagem que dispara o relogin automático.

### O corpo GWT-RPC do portal de São Bernardo

A chamada `emitirNfs` é uma tabela de strings indexada com 68 entradas seguida
de 207 índices. Por isso o importador aceita `--map-index`, que troca a
**posição** em vez do texto: `1.00` pode aparecer em vários pontos do corpo, mas
a posição 48 é uma só.

Para inspecionar um corpo capturado:

```bash
python import_curl.py captura/emitir.txt --listar
```

O modelo atual foi gerado com estas posições, confirmadas por reconstrução
byte a byte da captura original:

| Posição | Valor na captura | Marcador |
| --- | --- | --- |
| 15 | `2026-08-15` | `{{competencia}}` |
| 38 | `serviços tomados` | `{{servico.descricao}}` |
| 46 | `0.98` | `{{servico.valor_liquido}}` |
| 47 | `0.0200` | `{{servico.aliquota_fracao}}` |
| 48 | `1.00` | `{{servico.valor}}` |
| 54 | `0.02` | `{{servico.iss}}` |

### Códigos de serviço

A lista vem do portal, pela chamada `consultarServicos` — **muda sozinha se o
login mudar de empresa**. O botão **Atualizar** na tela de emissão refaz a
consulta; o resultado fica em `config/servicos.json` para a tela abrir rápido.

O código aparece em duas posições do corpo GWT-RPC: completa na 37
(`14.05/107120/1581`) e só o item na 39 (`14.05`). O marcador
`{{servico.codigo_item}}` deriva a segunda da primeira, então trocar de serviço
altera exatamente essas duas posições e nada mais.

### Alíquota por serviço

Cada código tem a sua, em `config/aliquotas.json`:

```json
{ "14.05/107120/1581": "2" }
```

Só entram aqui as alíquotas **confirmadas**. Um código sem registro usa
`NFSE_ALIQUOTA` como padrão, e tanto o resumo da tela quanto a confirmação de
emissão avisam em vermelho que ela não foi conferida.

Isso existe por um motivo concreto: a resposta de `consultarServicos` trazia os
números 3 e 5 junto dos dois serviços, mas a nota realmente emitida usou 2% —
possivelmente por Simples Nacional ou benefício fiscal. Como a diferença não
foi explicada, o programa não deduz alíquota: você confirma no portal e grava
pelo botão **Alíquota**.

### HTTP 200 não quer dizer nota emitida

O GWT-RPC responde **200 mesmo quando a operação falha**. O portal recusa a nota
dentro de um `//OK`, num objeto `ListaMensagemRetorno`:

```
//OK[...,"E323","Favor informar o código da Obra",
        "Código da Obra é obrigatório mas não foi informado"],0,7]
```

Por isso `avaliar_resposta()` classifica pelo corpo, não pelo status, e a
mensagem do portal aparece na tela. Antes dessa checagem, uma nota recusada
ficava gravada como emitida — o pior desfecho possível num controle fiscal.

### Por que a leitura da empresa usa o fluxo, e não a tabela de strings

Este é o ponto mais delicado do projeto: os dados do prestador não são digitados
em lugar nenhum, saem do `getSession`. E a resposta GWT-RPC tem **duas** formas
de ser lida, com resultados diferentes.

A **tabela de strings** guarda só o que tem valor. Um campo vazio some dela e
empurra todos os seguintes uma casa para trás:

```
tabela:  … | 346186 | PRESTADOR EXEMPLO TRES | …
fluxo:   … | 346186 |  ø (fantasia vazia)  | PRESTADOR EXEMPLO TRES | …
```

Ler "a entrada seguinte à inscrição" acerta numa empresa sem nome fantasia e
**erra em toda empresa que tem os dois** — a fantasia é lida como razão social e
a nota sai com o nome errado, sem nada acusar. Aconteceu.

`nfse_client.gwt_fluxo()` decodifica a resposta preservando os campos vazios,
onde o layout é estável para qualquer empresa:

```
empresa:    … | e-mail | inscrição | nome fantasia | razão social | …
endereço:   … | "Comercial" | complemento | número | …
```

Confirmado em duas empresas reais com preenchimentos **opostos** — é essa
oposição que prova o layout, porque um campo vazio numa e preenchido na outra
deslocaria a leitura por vizinhança:

| | e-mail | fantasia | complemento | número |
| --- | --- | --- | --- | --- |
| 346186 | vazio | vazio | vazio | `1301` |
| 254765 | `viviane@…` | `MARMORARIA EXEMPLO` | `PRIMEBUSINESS CENTER SL.47` | `27` |

Ler "a entrada seguinte à inscrição" dava certo na primeira e, na segunda,
mandava `MARMORARIA EXEMPLO` como razão social (o correto é
`PRESTADOR EXEMPLO QUATRO`) e o complemento como número da rua.

O corpo capturado da MUNDIAL confirma a mesma ordem por outro caminho: suas
posições 33 e 34 trazem `RAZAO SOCIAL EXEMPLO` e
`ESTRUTURAS METALICAS EXEMPLO` — fantasia e razão social, distintas.

`prestador.ler()` combina as duas leituras, e o que vem do fluxo prevalece.
`tests/test_nfse.py` guarda o objeto real das duas empresas: se a prefeitura
mudar o layout, esses testes caem antes de sair nota errada.

### Todo campo do prestador é sobrescrito, inclusive vazio

`prestador.aplicar()` grava **todas** as posições do prestador, mesmo as que a
leitura não preencheu. Deixar a do modelo parece inofensivo e não é: o modelo
guarda os dados da empresa da captura, então a nota de uma empresa saía com o
e-mail de outra. O que a leitura não traz vira campo vazio — e `conferir()`
barra a emissão quando o campo vazio é obrigatório.

### "Erro ao processar retorno do servidor" — o que está por trás

Essa mensagem é o pior retorno do portal, porque ela **não diz se a nota saiu**.
Duas causas foram identificadas, ambas em dados que o portal aceita receber e só
depois derruba:

**1. Número do endereço do prestador vindo errado.** Os dados da empresa saem de
`getSession` por reconhecimento de formato, não por posição fixa. Numa empresa
com complemento cadastrado, o complemento entrava na frente do número:

| | posição 30 do corpo |
| --- | --- |
| Emissão que funcionou | `1301` |
| Emissão que falhou | `PRIMEBUSINESS CENTER SL.47` |

O portal recebe texto onde espera número e estoura. `prestador.conferir()` agora
barra isso **antes de transmitir**, dizendo qual campo está errado, e
**Configurações → Empresa lida do portal** mostra tudo que foi lido.

**2. Código da Obra ausente.** Só nos serviços que de fato o exigem — ver abaixo.

Nos dois casos o princípio é o mesmo: é melhor recusar antes de enviar do que
receber "consulte se a nota foi emitida", situação em que repetir pode duplicar
e desistir pode deixar de emitir.

### Código da Obra

O campo **Obra** aparece na tela de emissão **só quando o serviço escolhido
exige** — pedir Código da Obra numa nota de usinagem confunde, e é campo que só
a construção civil usa. Quem decide é `config/exige_obra.json`, a mesma lista
que cresce sozinha quando o portal responde `E323`.

O campo é uma lista editável: escolhe das obras da empresa quando há cadastro em
`config/obras_<CCM>.json`, e aceita o código digitado quando não há.

**Como a obra entra no corpo.** Não é um campo, é um **objeto**. No GWT-RPC um
objeto ausente é um único campo vazio; presente, ele vira a referência à classe
**seguida dos campos dele**, inline. Comparando o corpo sem obra com uma emissão
real de 7.02 capturada do portal:

```
sem obra:  … | competência | ø                        | ø | ø | «TcIdentificacaoNfse»
com obra:  … | competência | «TcDadosConstrucaoCivil» | 1213550 | ø | ø | 1213550 | ø | ø | «TcIdentificacaoNfse»
```

O objeto ocupa cinco campos (a classe e quatro dados, com o código repetido em
dois deles) e empurra o resto em +4 — os dois campos vazios irmãos continuam
logo antes do `TcIdentificacaoNfse` nos dois corpos, que é o que confirma o
alinhamento. Por isso existe `nfse_client.inserir_objeto()`, separado de
`apontar_indice()`: um acrescenta campos, o outro só repõe um.

O modelo declara:

```json
"servico_obra": {
  "indice": 30,
  "tipo": "br.eicon.nfse.xml.complexType.TcDadosConstrucaoCivil/243561992",
  "campos": ["obra", null, null, "obra"]
}
```

**Ordem importa.** A obra é aplicada por último em `build()`. Como ela desloca o
fluxo em +4, o município da prestação (índice 70) precisa ser ajustado antes —
na ordem inversa ele cairia na casa 74 sem que ninguém percebesse. Há teste para
isso.

**A lista de obras** vem de `listaObra`, por município e competência. O
município vai como `long` do GWT: 48708 (São Bernardo sem o prefixo da UF) vira
`L5E` — `nfse_client.long_gwt()` reproduz exatamente isso. O resultado fica em
`config/obras_<CCM>.json`.

**A leitura da lista tem dois níveis**, e isso não é preciosismo. A primeira
tentativa ancora no nome da classe de cada item — o jeito certo. Mas esse nome só
aparece numa resposta **com** obras, e a primeira versão exigia o sufixo
`ObraVO`: numa empresa que usa outro nome de classe, a lista voltava vazia sem
reclamar. Agora basta a classe conter "obra", e se nenhuma for reconhecida a
segunda tentativa emparelha os valores soltos — número vira código, o texto
seguinte vira descrição.

Se ainda assim a lista vier vazia, **Configurações → "Ver obras (bruto)"** mostra
a resposta crua do portal e quantas obras a leitura reconheceu. É com isso que a
regra se conserta, em vez de adivinhar.

O campo aceita o código digitado em qualquer caso — a lista é conveniência, não
requisito para emitir.

### Serviços que exigem campos extras

Alguns serviços pedem o **Código da Obra**, que não existe no corpo capturado
para o 14.05. Trocar só o código de serviço não basta: é preciso capturar uma
emissão real desse serviço e gerar um modelo próprio, porque a posição do campo
no corpo GWT-RPC não pode ser deduzida.

`config/exige_obra.json` lista os códigos com recusa registrada, e o programa
barra a emissão deles antes de transmitir. A lista cresce sozinha: quando o
portal responde `E323 Favor informar o código da Obra`, o código é anotado e a
tentativa seguinte já é barrada.

**O bloqueio é por código, nunca pelo item.** Dentro do item 7 convivem serviços
que exigem obra (7.02, 7.06) e serviços que não exigem — 7.07, raspagem e
polimento de pisos, emite sem obra. Barrar o item inteiro impediria emissão
válida, e foi o erro que uma primeira versão desta trava cometeu.

### O que vem da captura e o que vem do portal

A captura fornece só a **estrutura** do corpo GWT-RPC. Tudo que identifica a
nota é resolvido na hora de emitir:

| Dado | Origem |
| --- | --- |
| Prestador (inscrição, razão social, endereço, contato) | `getSession`, após o login |
| Tomador (razão social, endereço, e **id interno no portal**) | `buscaTomadorCnpj` |
| Código do serviço | marcador no corpo, escolhido na tela |
| Valor, ISS, líquido, alíquota, competência | marcadores, calculados do rascunho |

Por isso `cobre` está vazio no modelo: ele serve a qualquer empresa, qualquer
cliente e qualquer serviço. Trocar o login troca tudo junto.

O modelo declara onde cada bloco mora na tabela de strings:

```json
"prestador_posicoes": { "32": "inscricao", "34": "razao_social", … },
"tomador_posicoes":   { "65": "documento", "66": "id", "68": "razao_social", … }
```

**A posição 66 é o id interno do tomador** — `375662` para um cliente,
`304838` para outro. Sem substituí-lo, a nota sairia vinculada ao cliente
errado, ainda que o CNPJ estivesse certo.

### Leitura das respostas do portal

As respostas são objetos Java serializados numa tabela de strings
desduplicada, sem as definições das classes. Nada aqui usa índice fixo, porque
a estrutura muda entre empresas — uma sem e-mail cadastrado desloca todas as
posições seguintes. Cada campo é reconhecido por formato (e-mail tem `@`, CEP
são 5+3 dígitos vizinhos, UF são duas letras) ou por vizinhança (a razão social
vem logo após a inscrição; o id do tomador, logo antes do logradouro).

Todas as regras foram conferidas em **duas amostras reais** de empresas e de
tomadores diferentes antes de entrar no código.

### Tomador fora do cadastro do portal

Na tela de emissão, o botão **Buscar** ao lado do CNPJ consulta o cliente e leva
a um de dois caminhos:

* **encontrado** — os dados do portal aparecem preenchidos e travados;
* **não encontrado** — os mesmos campos abrem para digitar, com UF e município.

O portal responde **vazio** para CNPJ fora do cadastro dele (48 bytes, contra
~460 de um cliente conhecido). Não vem razão social, não vem endereço e, o que
mais importa, **não vem o id interno**.

Esse id é a razão de `tomador.aplicar()` sobrescrever **todas** as posições do
tomador, inclusive as vazias. Manter a do modelo deixaria no corpo o id do
cliente da captura — e a nota sairia apontando para outro tomador. Com dados
digitados o id vai em branco, que é a única resposta honesta: não existe.

Faltando qualquer campo essencial (razão social, logradouro, número, bairro,
CEP), a emissão é recusada antes de transmitir em vez de sair com endereço pela
metade.

### Cadastrar o cliente no portal — e por que parecia impossível

A caixa **"Cadastrar este cliente no portal"** (marcada por padrão, como no
portal) faz a próxima nota já encontrar o CNPJ pela busca.

Ligar isso **não é trocar um campo**. Comparando as duas emissões reais, a
região parecia ter estruturas diferentes:

```
já cadastrado:  «Boolean» 0  -37  «Reforma» ø×10  «Boolean» 1
cadastrando:    «Boolean» 1  «Boolean» 0  «Reforma» ø×10  -37
```

A chave é que **`-37` não é um valor, é uma retro-referência**: o GWT escreve
`Boolean.TRUE`/`FALSE` uma vez e, nas repetições, aponta para o objeto já
escrito. São os mesmos três campos nos dois corpos —

| | campo 1 | campo 2 | campo 3 |
| --- | --- | --- | --- |
| já cadastrado | `false` | retro-ref | `true` |
| **cadastrando** | **`true`** | `false` | retro-ref |

— e só o primeiro muda. O arranjo troca porque muda quem é objeto e quem é
referência. Por isso existe `nfse_client.trocar_janela()`: ele reescreve a
janela de 16 campos inteira, com o mesmo tamanho, resolvendo os nomes de classe.

Quando a obra também entra, ela acrescenta um objeto **antes** dessa janela, e a
retro-referência anda uma casa (`-37` → `-38`) — `ajuste_retro` cuida disso.

**Como isso foi validado:** montando o corpo para o mesmo caso de uma emissão
real capturada (tomador novo + cadastrar + prestação em Santo André) e
comparando campo a campo — **zero diferenças** fora do bloco do prestador, que é
de outra empresa.

### Local da prestação (serviço fora do município)

Na tela de emissão há a caixa **"Serviço prestado fora de São Bernardo do
Campo"**. Marcada, libera UF e município — as duas listas vêm do próprio portal
(`listaUF` e `listaMunicipio`) e ficam em cache em `config/`.

O código IBGE completo é a UF seguida do município com cinco dígitos:
`35` + `48708` = `3548708` (São Bernardo). Conferido contra códigos conhecidos:
Santo André `3547809`, São Caetano `3548807`, Adamantina `3500105`.

**Por que este campo vai por índice e não por marcador.** A tabela de strings do
GWT é desduplicada, e o código de São Bernardo é usado por **cinco** campos do
corpo — município do serviço, do tributo, do endereço do tomador e outros dois.
Trocar a string mudaria todos, e o endereço do cliente sairia noutra cidade.
`nfse_client.apontar_indice()` acrescenta o código novo ao fim da tabela (o que
não desloca nenhuma posição existente) e faz **só** o campo do serviço apontar
para ele. O modelo declara qual é esse campo:

```json
"servico_municipio_indice": 70
```

Sem essa chave, tentar emitir fora do município é recusado — em vez de sair uma
nota com o local errado. Marcar a caixa e não escolher o município também é
recusado, pelo mesmo motivo.

A confirmação de emissão mostra **sempre** o local da prestação, inclusive
quando é o padrão, porque é ele que define onde o ISS é devido.

### CEP preenche o endereço do cliente

No cadastro de um tomador que o portal não conhece, digitar o CEP preenche
logradouro, bairro, UF e município — e o serviço devolve o **código IBGE de sete
dígitos** pronto, que é exatamente o que a nota precisa.

Campo já digitado não é sobrescrito: quem corrigiu o logradouro à mão não perde
a correção.

As listas de UF e município **filtram conforme se digita** (`ui.autocompletar`).
São 645 municípios só em São Paulo; arrastar barra até achar não é opção. Como a
lista filtrada muda de tamanho, a seleção casa pelo **texto**, não pelo índice.

A consulta é a do **próprio portal** (`buscaEndereco`) — o programa continua sem
falar com ninguém além dele. O código do município vem como `long` do GWT
(`LrB` = 47809, que com a UF 35 forma `3547809`), e `nfse_client.long_gwt_para_int()`
o decodifica. Para desligar, `NFSE_CEP=off` no `.env`; o campo continua digitável.

Duas armadilhas resolvidas ali, ambas encontradas testando CEPs diferentes: o
tipo de logradouro vem separado do nome (`RUA` + `SÃO DOMINGOS SÁVIO`) e não
pode ser lido "três campos antes do bairro", porque alguns CEPs trazem faixa
("- DE 612 A 1510 - LADO PAR") no meio; e o long vem **entre aspas** na resposta,
o que fazia Santo André virar o município 3503453.

### E181 — o portal recalcula o valor líquido

```
E181 · O Valor líquido de NFSe deve ser o resultado da expressão
(Valor dos serviços − PIS − COFINS − INSS − IR − CSLL − OutrasRetenções
 − Valor ISS Retido − Descontos) e deve ser maior que R$ 0,00
```

O portal não aceita o líquido que a gente manda: ele refaz a conta e compara.
Três emissões reais mostram a regra:

| Caso | valor | líquido | ISS | marca | resultado |
| --- | --- | --- | --- | --- | --- |
| 14.05 em São Bernardo | 1,00 | 0,98 | 0,02 | 1 | emitiu |
| 7.02 sem ISS | 1,00 | **1,00** | **0,00** | **2** | emitiu |
| 14.05 com prestação em Santo André | 1,00 | 0,98 | 0,02 | 1 | **E181** |

A fórmula subtrai o **ISS retido**, não o ISS. Duas coisas decorrem disso:

**0. O que a captura de uma emissão real confirmou.** Comparando campo a campo o
corpo que este programa monta com uma emissão que o portal aceitou (tomador
novo, prestação em Santo André), sobraram só duas diferenças reais — e as duas
eram defeito daqui:

* o município da prestação vai em **dois** campos, não um: o do serviço e o do
  bloco IBS/CBS (`servico_municipio_indices`);
* o segundo campo do ISS vai **vazio**, não `0.00` (`servico_iss_vazio_indice`).

Fora isso, o corpo saiu idêntico — inclusive o id do tomador novo, que vai como
texto vazio.

**1. Retenção é escolha, não herança — e só quando o portal permite.** O corpo
capturado veio de uma nota *com* retenção e trazia `1` fixo nessa posição, o que
fazia **toda** nota sair com o ISS retido. Agora o padrão é **sem retenção**, e
a caixa **"ISS retido pelo tomador"** só aparece quando o portal responde que
essa empresa pode reter (`isPrestadorSubstituto`, em `recursos.py`).

Isso veio de um caso real: uma nota foi emitida com a caixa marcada e saiu
**sem** retenção, porque o portal nem oferecia a opção àquela empresa. Campo que
não faz nada é pior que campo nenhum — faz acreditar num imposto que não vai
acontecer. Na dúvida (erro de rede, resposta estranha) a caixa não aparece.

| | marca | ISS | líquido |
| --- | --- | --- | --- |
| Sem retenção (padrão) | `2` | 0,02 | **1,00** |
| Com retenção | `1` | 0,02 | 0,98 |
| Fora do município | `2` | **0,00** | 1,00 |

**2. Fora do município não há ISS aqui**, logo não há o que reter — marcar as
duas coisas não é contradição, a retenção simplesmente não se aplica.

Quem recolhe **aparece no resumo e na confirmação** antes de emitir
(`ISS R$ 0,02 (pago pelo prestador)`), porque muda o responsável pelo imposto —
não é detalhe interno.

### Excluir notas da lista

Duas formas, ambas em **Minhas notas**:

* **Excluir** — tira a nota selecionada.
* **Limpar histórico…** — tira por grupo (rascunhos, falhas, emitidas), com a
  contagem de cada um à vista antes de confirmar.

Nenhuma das duas apaga arquivo: o `.json` vai para `data/lixeira/`. É de
propósito. Uma nota emitida é registro fiscal, e a lista ficar limpa não pode
significar a prova sumir — nem "excluir" aqui cancela a nota no portal. Esvaziar
a lixeira é ato manual, fora do programa.

`storage.list_all()` varre só o primeiro nível de `data/`, então o arquivo movido
some da listagem sem precisar de filtro nenhum.

### A interface

`ui.py` guarda a camada visual — paleta, tipografia, estilos ttk e componentes
(`cartao`, `banner`, `pilula`, `vazio`). `desktop.py` só monta telas com eles. A
separação existe porque as duas coisas mudam por motivos diferentes: a paleta
muda por gosto, a tela muda por regra fiscal.

Detalhes que valem saber:

* **Nitidez em telas 125%/150%** — `ui.ativar_nitidez()` avisa o Windows antes de
  o Tk existir e reajusta a escala do ponto. Sem isso o texto sai borrado.
* **A barra lateral só aparece depois do login.** Antes dele não há para onde ir.
* **A página rola.** Encolher a janela até o mínimo (940×620) não esconde nenhum
  botão — as larguras da tabela foram calculadas para caber nesse pior caso.
* **Cor na tabela só na falha.** A cor da tag do `Treeview` pinta a linha
  inteira, não a célula: tingir cada status deixava a tabela em arco-íris, onde
  nada se destaca. Falha é a única linha que pede ação.
* **Diálogos próprios** para confirmar emissão e para a alíquota — são os dois
  momentos em que um clique errado custa caro.

### O PDF da nota (DANFSe) e a impressão

Emitiu, abre o **layout de impressão**: uma janela com o número da nota, o código
de verificação, o resumo do serviço e a impressora já escolhida. Os botões
—**Imprimir**, **Abrir PDF**, **Salvar cópia…**— destravam quando o arquivo
termina de baixar. O botão **Imprimir nota**, na tela de Notas, reabre essa mesma
janela para qualquer nota antiga.

O layout impresso é o próprio PDF do portal: ele já é o documento oficial, com
brasão e código de verificação. Nada é redesenhado aqui — um papel *parecido* com
a nota não é a nota.

O botão "Imprimir" do próprio portal não serve: ele reenvia o formulário com
`imprime=1` e o servidor redireciona para `erros.jsp` (testado em 15/08/2026). Por
isso a impressão sai daqui, via `impressao.py`, com os verbos `print` e `printto`
do Windows. Se o leitor de PDF instalado não registrar esses verbos, o aviso
manda usar **Abrir PDF** e imprimir pelo leitor.

O arquivo fica em `data/pdf/nfse-<numero>-<codigo>.pdf`.

Três particularidades do portal moldaram esse trecho:

1. **Outro host.** O PDF vem de `visualizar.isssbc.com.br`, não do portal de
   emissão. `config.download_hosts()` libera esse segundo endereço **só para o
   download**; a emissão continua restrita a `nfse.isssbc.com.br`.
2. **Dois passos.** `consultarNota` devolve HTML — a tela do visualizador, não o
   arquivo. Dentro dela há um formulário `exportar` com a nota inteira
   serializada num campo oculto; é o POST desse formulário em `exportacao` que
   traz o `%PDF`. Os campos ocultos são copiados da página porque não há como
   remontá-los deste lado.
3. **Dispensa login.** O código de verificação já autoriza a leitura — é o mesmo
   endereço que o tomador usa para conferir a nota. Por isso dá para baixar o
   PDF de uma nota emitida por outra empresa sem trocar de sessão.

Endereço e campos ficam em `config/pdf_template.json`. Se a prefeitura mudar a
rota, muda-se esse arquivo.

Se o PDF falhar depois de uma emissão bem-sucedida, o aviso diz isso com todas as
letras — a nota **foi** emitida, só o download falhou. Nada é reenviado.

### Marcadores disponíveis

Cada campo tem variações de formato, porque o portal pode exigir qualquer uma:

| Marcador | Exemplo |
| --- | --- |
| `{{servico.valor}}` | `1234.56` |
| `{{servico.valor_virgula}}` | `1234,56` |
| `{{servico.valor_br}}` | `1.234,56` |
| `{{servico.valor_centavos}}` | `123456` |
| `{{servico.iss}}` | calculado a partir de valor × alíquota |
| `{{tomador.documento}}` | só dígitos |
| `{{tomador.documento_formatado}}` | `00.000.000/0001-91` |
| `{{competencia}}` | `2026-08-15` |
| `{{competencia_br}}` | `15/08/2026` |
| `{{env:NFSE_COOKIE}}` | valor do `.env`, nunca gravado no modelo |

Filtros: `{{campo|url}}`, `{{campo|digits}}`, `{{campo|upper}}`, `{{campo|raw}}`.

Os valores do rascunho são escapados conforme o `Content-Type` do modelo. Em
corpo GWT-RPC, um `|` na descrição vira `\!` — sem isso, uma descrição como
"usinagem | solda" desalinharia a tabela de strings e a chamada falharia.

Cada marcador deve ocupar **uma posição inteira** da tabela de strings do
GWT-RPC. Substituir só um pedaço de uma entrada muda a contagem e quebra a
chamada.

## Liberando a emissão real

Com os modelos prontos, confira a montagem sem transmitir nada:

* no desktop: **Configurações → Testar configuração**, ou o botão
  **Conferir requisição** na lista de notas;
* na web: botão **Conferir** na linha da nota;
* pela API: `POST /documents/{id}/preview`.

A tela mostra exatamente o que sairia, com os segredos ocultos. Quando estiver
correto, defina no `.env`:

```
NFSE_LIVE_MODE=true
```

Comece por uma nota de valor baixo e confira o resultado no portal.

## Endpoints

| Rota | Função |
| --- | --- |
| `GET /health` | estado do serviço |
| `GET /config` | diagnóstico da configuração, sem segredos |
| `GET /documents` | lista os rascunhos e envios |
| `GET /documents/{id}` | consulta uma nota |
| `POST /documents` | cria um rascunho (validado) |
| `POST /documents/{id}/preview` | monta a requisição sem transmitir |
| `POST /documents/{id}/submit` | transmite, uma única vez |

Exemplo de rascunho:

```json
{
  "tomador": {"documento": "11222333000181", "nome": "Cliente"},
  "servico": {"descricao": "Consultoria", "valor": "150,00", "codigo": "14.05/107120/1581", "aliquota": "2"},
  "prestacao": {"fora_municipio": false, "uf": "", "cidade": ""},
  "competencia": "2026-08-15"
}
```

Valor e alíquota aceitam vírgula ou ponto; o programa normaliza. CPF e CNPJ são
conferidos pelos dígitos verificadores antes de qualquer gravação.

## Segurança

* **Credenciais** ficam apenas no `.env`. Nunca entram nos rascunhos, nos
  modelos, nos logs ou nas telas.
* **Nada é transmitido sem confirmação explícita**, nas duas interfaces.
* **Sem retentativa automática.** Se a emissão falhar, o programa não repete o
  envio: quando não se sabe se o portal processou a nota, reenviar é arriscar
  emitir duas. A sessão é conferida *antes* do envio justamente para isso.
* **Reenvio bloqueado** para nota já transmitida, no servidor e no desktop.
* **Só o host do portal** aceita transmissão, e só por HTTPS.
* **Redirecionamento não é seguido**: um `302` na emissão significa sessão
  expirada, e seguir o redirect transformaria o POST em GET, devolvendo um `200`
  de uma página que não emitiu nada.
* O servidor local **confere `Host` e `Origin`**, porque escutar em `127.0.0.1`
  não impede que uma página aberta no navegador dispare POST para localhost.
* **Escrita atômica** dos arquivos: uma queda de energia não deixa JSON pela
  metade nem derruba a listagem.

### O que fica gravado em disco

Cada tentativa de transmissão vira um registro no histórico da nota — é a trilha
de auditoria, e tentativas antigas nunca são sobrescritas. O registro inclui a
requisição enviada (com `Cookie` e `Authorization` ocultos) e a resposta do
portal, com `JSESSIONID`, tokens e senhas mascarados.

A resposta do portal pode conter dados da sua sessão. Controle isso com:

```
NFSE_STORE_RESPONSE=excerpt   # excerpt (padrão) | full | none
```

Os rascunhos guardam CPF/CNPJ, nomes e valores **sem criptografia**. Se a pasta
do programa fica dentro do OneDrive, esses dados sincronizam para a nuvem. Para
mantê-los fora:

```
NFSE_HOME=C:\NFSe
```

## Testes

```bash
python -m unittest discover -s tests -v
```

## Gerando o executável

Para rodar em máquina sem Python:

```bash
python empacotar.py
```

Sai uma pasta em `executavel/Dezorzi NFS-e/`, que se copia inteira para o outro
computador ou para um pendrive. Exige o PyInstaller instalado **aqui**
(`pip install pyinstaller`); a máquina de destino não precisa de nada.

Três decisões que estão no `empacotar.py` e valem saber:

* **Pasta, não arquivo único.** O modo arquivo único descompacta tudo num
  diretório temporário a cada abertura — demora e é o formato que antivírus
  mais barra. A pasta abre na hora.
* **`config/` e `data/` ficam ao lado do executável, não dentro dele.** O
  programa grava nesses dois (alíquotas, empresa ativa, cache de serviços, as
  notas), e conteúdo empacotado é somente-leitura.
* **A senha não vai junto e a transmissão sai desligada.** O `.env` é copiado
  sem `NFSE_SENHA` e com `NFSE_LIVE_MODE=false`.

Isso depende de `paths.py` medir tudo a partir de `sys.executable` quando
`sys.frozen` está ligado. Empacotado, `__file__` aponta para dentro do pacote —
somente-leitura, e temporário no modo arquivo único: as notas iriam para uma
pasta que some ao fechar o programa, sem erro nenhum na tela. Há testes que
travam esse comportamento.

## Reforma tributária (IBS/CBS)

Em 24/08/2026 a prefeitura republicou o portal e a emissão passou a exigir
quatro códigos novos. Faltando qualquer um, o portal **não recusa com
mensagem**: o servidor lança exceção e responde `HTTP 500 "The call failed on
the server"`, sem dizer por quê.

| Campo | De onde sai |
| --- | --- |
| **NBS** | filtrado pelo item da LC 116 do código de serviço |
| **Código Indicador da Operação** | da tabela de correlação, pelo NBS |
| **Classificação Tributária** | da tabela de correlação, pelo NBS |
| **CST – IBS/CBS** | padrão `000` (tributação integral), trocável |

Na tela, escolher o serviço carrega os NBS que lhe cabem — 675 códigos viram
algumas dezenas — e escolher o NBS preenche os outros dois. Quando o item tem
um único NBS (83 dos 200), tudo já vem pronto. Com vários NBS e nenhum
escolhido, os campos ficam **vazios**: um código plausível já selecionado passa
despercebido e sai como tributo errado.

As quatro tabelas vêm do próprio portal (`reforma.py`), não exigem login e são
guardadas por 30 dias. A correlação item → NBS → códigos vem de uma planilha,
convertida por `python importar_nbs.py <planilha.xlsx>`; a leitura respeita o
preenchimento herdado da planilha (célula vazia repete a de cima, linha sem NBS
acrescenta opção ao NBS anterior) e confere tudo contra o que o portal aceita.

No corpo da requisição, o NBS é um `java.lang.Integer`: viaja **cru e sem os
pontos** (`1.0401.23.00` → `104012300`) e ativar o objeto acrescenta uma posição
ao fluxo — o que empurra as retro-referências, que contam objetos. As posições
foram conferidas contra uma emissão real feita pelo navegador.

## A marca

O programa assina como **Dezorzi®** em dois lugares, e só:

* o **ícone da janela** (barra de título e barra de tarefas), com o monograma;
* uma linha `Dezorzi®` no rodapé da barra lateral e da tela de entrada, no
  tamanho e no tom do texto de apoio.

Nada além disso. A paleta das telas é a de `ui.py` e não foi trocada pelas cores
do logotipo: repintar o programa inteiro chamaria atenção justamente onde ela
não deve estar — a tela existe para a nota, não para a marca.

O monograma é **desenhado por fórmula** em `marca.py`, sem arquivo de imagem e
sem biblioteca externa, e é renderizado no tamanho exato de cada uso. Para
substituí-lo pelo arquivo oficial, ponha um `logo.png` em `assets/` ou use
*Configurações → Usar meu arquivo de logotipo…*. Detalhes em
[`assets/LEIA-ME.txt`](assets/LEIA-ME.txt).

O DANFSe impresso **não** leva a marca: o documento é o PDF que o portal gera, e
nada é redesenhado sobre ele — marca de quem fez o programa num documento fiscal
só serviria para confundir com o prestador.

## Estrutura

| Arquivo | Responsabilidade |
| --- | --- |
| `paths.py` | caminhos absolutos, independentes do diretório atual |
| `config.py` | leitura do `.env` e chaves de configuração |
| `validation.py` | validação e normalização dos dados fiscais |
| `storage.py` | gravação atômica e histórico de transmissões |
| `nfse_client.py` | montagem da requisição, escapes e envio |
| `session.py` | login HTTP e renovação de sessão |
| `service.py` | regra de emissão, compartilhada pelas interfaces |
| `server.py` | API HTTP e interface web |
| `desktop.py` | aplicativo desktop — as telas |
| `ui.py` | paleta, tipografia, estilos ttk e componentes visuais |
| `marca.py` | a marca Dezorzi®: monograma desenhado e nome |
| `reforma.py` | os quatro códigos da reforma e o NBS por serviço |
| `importar_nbs.py` | converte a planilha de correlação NBS |
| `empacotar.py` | gera o executável em `executavel/` (PyInstaller) |
| `services.py` | consulta os códigos de serviço habilitados no portal |
| `pdf.py` | baixa o DANFSe da nota emitida (dois passos, outro host) |
| `impressao.py` | descobre impressoras e manda o PDF para a fila |
| `municipios.py` | estados e municípios do IBGE, lidos do portal |
| `obras.py` | obras cadastradas da empresa (construção civil) |
| `recursos.py` | o que o portal libera à empresa (reter ISS, deduções) |
| `cep.py` | endereço a partir do CEP (ViaCEP) |
| `import_curl.py` | gerador de modelos a partir do cURL capturado |
| `testar_conexao.py` | testa login e sessão sem emitir nota |

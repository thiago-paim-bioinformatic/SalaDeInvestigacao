# Sala de Operações — Orquestrador de Agentes de IA (RAG)

Front-end em Flask que orquestra agentes de IA (RAG) para inteligência policial
e investigação patrimonial. O backend é formado pelos módulos:

- `agents.py` — classes OO (`CreateVectorDB`, `Agent`) com memória persistente;
- `llm.py` — leitura e divisão em chunks de PDFs (pipeline do RAG).

## Pré-requisitos

- Python 3.13+ (uso recomendado com ambiente virtual — venv).
- **LM Studio em execução** com o servidor local ativo em
  `http://127.0.0.1:1234/v1`, contendo carregados:
  - um modelo de **embedding** (ex.: `text-embedding-nomic-embed-text-v1.5`);
  - um modelo de **LLM** (ex.: `google/gemma-3-1b`).
- Dependências listadas em `requirements.txt`.

ou 

- **API OpenAI**


## Configuração

1. Crie e ative o ambiente virtual:

   **Windows (PowerShell):**
   ```
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   **Linux/macOS:**
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```

3. Crie o arquivo `.env` na raiz do projeto com base no modelo abaixo
   (a nomenclatura segue as variáveis lidas pelos scripts):

   ```
   # Servidor de modelos (API compatível com OpenAI — ex.: LM Studio)
   MODEL_EMBEDDING=<modelo_de_embedding>
   MODEL_LLM=<modelo_llm>
   BASE_URL_SERVER=http://127.0.0.1:1234/v1
   API_KEY_SERVER=lm-studio

   # Opcionais — inicialização do Flask
   HOST=127.0.0.1
   PORT=5000
   FLASK_DEBUG=1
   FLASK_RELOADER=0
   ```

   Legenda:

   | Variável | Descrição |
   | --- | --- |
   | `MODEL_EMBEDDING` | Modelo usado nos embeddings (busca semântica). |
   | `MODEL_LLM` | Modelo de linguagem usado nas respostas/rerank. |
   | `BASE_URL_SERVER` | Endereço da API compatível com OpenAI ou LM Studio. |
   | `API_KEY_SERVER` | Chave de API do servidor local (pode ser qualquer nome) ou API_KEY da OpenAI|
   | `HOST` | Interface de escuta do Flask (padrão `127.0.0.1`). |
   | `PORT` | Porta do Flask (padrão `5000`). |
   | `FLASK_DEBUG` | `1` para modo debug. |
   | `FLASK_RELOADER` | `0` (padrão) para manter o servidor com reinício manual. |

   > **Importante:** o arquivo `.env` contém configurações locais e **não deve
   > ser versionado**. Ele já está ignorado no `.gitignore`, então não o
   > renomeie nem o compartilhe.

## Como executar

Com a venv ativa e o LM Studio rodando (ou se já configurada a chave de API da OpenAI em `.env`):

```
python server.py
```

Na primeira subida, o servidor carrega as bases de conhecimento persistidas e
os agentes registrados, caso já existam, e exibe no console:

```
 * Serving Flask app 'server'
 * Debug mode: on
 * Running on http://127.0.0.1:5000
Press CTRL+C to quit
```

Abra no navegador o endereço informado (por padrão `http://127.0.0.1:5000`).
Para usar outra porta ou interface, defina `HOST`/`PORT` no `.env`.

## Como usar o App

### 1. Status do servidor
Confere a conexão com o LM Studio ou OpenAI (modelos carregados e disponíveis). Verifique
se o servidor está **online** antes de criar bases ou agentes.

### 2. Base de conhecimento
1. Clique em **Carregar base de conhecimento** e escolha **arquivos PDF** ou
   **uma pasta inteira** (todos os PDFs da pasta são indexados).
2. Dê um **nome** para a base (ou selecione uma existente para anexar novos
   arquivos).
3. Preencha **Categoria (gênero)** e **Categoria (espécie)** usadas como
   metadados dos documentos (ex.: gênero `Inquérito Policial`, espécie
   `IP 000x-2025-x0000x`).
4. Ajuste **chunk size** e **chunk overlap** (padrões: 500 e 100).
5. Clique em **Criar base de conhecimento** e acompanhe o progresso da
   indexação. No fim, a base aparece em **Bases carregadas**.

### 3. Cadastro de agentes
1. Use os botões **Configurar Nome**, **Persona**, **Habilidades** e **Tarefas**
   (abrem pop-ups) para montar o perfil do agente.
2. Selecione a **Base de conhecimento** e o **Tipo de retriever**
   (`mmr`, `similarity`, `similarity_score_threshold` ou `sem_base`).
3. Clique em **Criar agente**. O agente passa a constar em **Agentes
   registrados** (clique no ícone para ver o JSON). A memória persistente fica
   em `./agents_memory/<nome>`.
4. Para remover um agente, use **Deletar agente** — a memória persistente
   também é removida.

### 4. Interação com o agente
1. Selecione o **agente** e o **retriever**.
2. Marque **usar memória do agente** e/ou **salvar resposta na memória**.
3. Clique em **Pergunte ao Agente**, digite a pergunta e confirme. **REGEX**
   (opcional) restringe a busca por padrão nos trechos recuperados.
4. A resposta e os **trechos de contexto** utilizados são exibidos.

### 5. Orquestração (equipes de agentes)
1. Na sub-aba **Ambiente de Orquestração**, arraste ícones da paleta
   **Elementos de Orquestração** (Usuário, Saída, agentes) para o ambiente.
2. Conecte as portas: clique em uma saída (output) e depois na entrada (input)
   correspondente.
3. No elemento **Usuário**, clique em **Interação inicial** e digite o prompt
   que alimentará os agentes conectados.
4. Ajuste o zoom se necessário e clique em **Executar Orquestração**. Acompanhe
   o andamento no **Log do servidor** (tempo real via SSE) e veja o resultado
   na sub-aba **Entradas e Saídas**.
5. Use **Gravar orquestração** para salvar a estrutura (nós, arestas e prompt) e
   **Orquestrações salvas** para carregar ou excluir posteriormente.
   **Copiar texto gerado** copia o resultado final.

### 6. Memória do agente
Selecione o agente, escreva a pergunta e clique em **Acessar memória**. É feita
uma consulta por similaridade (RAG) na memória persistente do agente, exibindo
a resposta e os trechos da memória utilizados.

## Estrutura do projeto

```
server.py                  # API Flask e orquestração dos agentes
agents.py                  # Classes CreateVectorDB e Agent (memória persistente)
llm.py                     # Leitura/chunking de PDFs e helpers de RAG
requirements.txt           # Dependências do projeto
.env                       # Configuração local (não versionado)
templates/index.html       # Página principal
static/app.js, style.css   # Front-end
chroma_base_de_dados/      # Bases de conhecimento persistidas (ChromaDB)
agents_memory/<agente>/    # Memórias persistentes dos agentes
agentes_registrados.json   # Registro dos agentes criados
orquestracoes_salvas.json  # Orquestrações gravadas
```

## Solução de problemas

- **Status "LM Studio offline"**: confirme que o servidor do LM Studio está
  ativo em `http://127.0.0.1:1234/v1` e que os modelos de embedding e LLM estão
  carregados.
- **Porta ocupada**: ajuste `PORT` no `.env` (ex.: `PORT=5001`) e reinicie.
- **Console não mostra a linha "Running on"**: se o painel "Log do servidor" da
  página estiver funcionando, o servidor está de pé — o banner pode não ter
  aparecido por configuração de saída do terminal. O endereço padrão é
  `http://127.0.0.1:5000`.
- **Reinício automático**: o reloader vem desligado por padrão
  (`FLASK_RELOADER=0`). Para reativá-lo durante o desenvolvimento, mude essa
  variável no `.env` (atenção: reexecuta o `server.py` em um segundo processo).
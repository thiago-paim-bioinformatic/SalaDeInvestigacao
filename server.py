'''
script server.py
versão: 1.0
data: 10/09/2026
Descrição: front-end Flask que orquestra agentes de IA (RAG) para inteligência
policial e investigação patrimonial.

Utiliza os módulos do projeto:
    - llm.py    -> leitura e chunking de PDFs (pipeline procedimental do RAG.ipynb)
    - agents.py -> classes OO (CreateVectorDB, Agent) com memória persistente

Requisitos de execução:
    - Servidor LM Studio ativo em http://127.0.0.1:1234/v1 (api_key "lm-studio"),
      ou OpenAI API.
    - Dependência extra: flask (pip install flask)
'''

#bibliotecas
import collections
import datetime
import itertools
import json
import logging
import os
import queue
import shutil
import tempfile
import threading
import time
import re

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

import chromadb
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from dotenv import load_dotenv

import agents
import llm


#Carrega variáveis de ambiente
load_dotenv()

MODEL_EMBEDDING = os.getenv("MODEL_EMBEDDING")
MODEL_LLM = os.getenv("MODEL_LLM")
BASE_URL_SERVER = os.getenv("BASE_URL_SERVER")
API_KEY_SERVER = os.getenv("API_KEY_SERVER")

app = Flask(__name__)

# Registros em memória do processo
#   BANCO_CONHECIMENTO: nome da base -> vectorstore (Chroma)
#   AGENTES:            nome do agente -> {"instancia": Agent, "config": dict}
BANCO_CONHECIMENTO = {}
AGENTES = {}


def criar_embeddings(model=MODEL_EMBEDDING, base_url=BASE_URL_SERVER, api_key=API_KEY_SERVER):
    '''Cria a instância de embeddings via API compatível do LM Studio ou OpenAI.'''
    if re.match(pattern=r"[0-9]{3}\.[0-9]\.[0-9]\.[0-9]", string=str(BASE_URL_SERVER)):
        return OpenAIEmbeddings(
            model=model,
            base_url=base_url,
            api_key=api_key,
            chunk_size=1,
            check_embedding_ctx_length=False,
        )
    else:
        return OpenAIEmbeddings(
            api_key=api_key,
            chunk_size=1,
            check_embedding_ctx_length=False,
        )

def serializar_documento(doc):
    '''Converte um Document (langchain) em dict serializável para a API.'''
    return {
        "fonte": doc.metadata.get("source", "documento desconhecido"),
        "pagina": doc.metadata.get("page"),
        "conteudo": doc.page_content,
        "metadados": {str(k): str(v) for k, v in list(doc.metadata.items())},
    }


def verificar_servidor(base_url=BASE_URL_SERVER, api_key=API_KEY_SERVER):
    '''Consulta o endpoint /v1/models do LM Studio ou OpenAI para verificar disponibilidade.'''
    
    if re.match(pattern=r"[0-9]{3}\.[0-9]\.[0-9]\.[0-9]", string=str(BASE_URL_SERVER)):
        try:
            from openai import OpenAI
            cliente = OpenAI(base_url=base_url, api_key=api_key, timeout=5)
            modelos = [m.id for m in cliente.models.list()]
            return {"ativo": True, "modelos": modelos}
        except Exception as exc:  # servidor fora do ar ou modelo não carregado
            return {"ativo": False, "erro": str(exc)}
    else:
        try:
            from openai import OpenAI
            cliente = OpenAI(api_key=api_key, timeout=5)
            modelos = [m.id for m in cliente.models.list()]
            return {"ativo": True, "modelos": modelos}
        except Exception as exc:  # servidor fora do ar ou modelo não carregado
            return {"ativo": False, "erro": str(exc)}


# ---------------------------------------------------------------------------
# Persistência do projeto (bases no ChromaDB e agentes registrados)
# ---------------------------------------------------------------------------
ARQUIVO_AGENTES = "./agentes_registrados.json"
ARQUIVO_ORQUESTRACOES = "./orquestracoes_salvas.json"
DIRETORIO_PERSISTENCIA_BASES = "./chroma_base_de_dados"

# Buffer de logs em memória para o painel "Log do servidor" (SSE /api/logs).
LOG_BUFFER = collections.deque(maxlen=500)
LOG_IDS = itertools.count(start=1)


def adicionar_log(nivel, mensagem):
    '''Adiciona um registro ao buffer de logs e o devolve (para streaming SSE).'''
    entrada = {
        "id": next(LOG_IDS),
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "nivel": nivel,
        "mensagem": str(mensagem),
    }
    LOG_BUFFER.append(entrada)
    return entrada


class _BufferLogHandler(logging.StreamHandler):
    '''Envia os logs do Flask/Werkzeug para o console (stderr) e para o buffer do painel "Log do servidor".'''

    def emit(self, record):
        super().emit(record)
        try:
            mensagem = self.format(record)
        except Exception:
            mensagem = record.getMessage()
        adicionar_log("info", mensagem)


_handler_log = _BufferLogHandler()
_handler_log.setFormatter(
    logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s")
)
logging.getLogger().addHandler(_handler_log)


def carregar_bases_persistidas(directory=DIRETORIO_PERSISTENCIA_BASES):
    '''
    Lista automaticamente as bases de conhecimento persistidas no ChromaDB
    (coleções do diretório configurado) e as carrega em BANCO_CONHECIMENTO.
    '''
    if not os.path.isdir(directory):
        return
    try:
        cliente = chromadb.PersistentClient(path=directory)
        colecoes = cliente.list_collections()
    except Exception:
        return
    for colecao in colecoes:
        nome = colecao.name
        if nome in BANCO_CONHECIMENTO:
            continue
        try:
            BANCO_CONHECIMENTO[nome] = Chroma(
                collection_name=nome,
                persist_directory=directory,
                embedding_function=criar_embeddings(),
            )
        except Exception:
            continue


def criar_agente_instancia(nome: str, config: dict):
    '''
    Recria uma instância de Agent a partir da configuração persistida.
    Retorna None se a base de conhecimento referenciada não estiver carregada.
    '''
    conhecimento = str(config.get("conhecimento", ""))
    if conhecimento and conhecimento not in BANCO_CONHECIMENTO:
        return None
    try:
        agente = agents.Agent()
        agente.set_agent_name(nome)
        agente.set_agent_persona(config.get("persona", ""))
        agente.set_agent_skills(config.get("habilidades", ""))
        agente.set_agent_task(config.get("tarefa", ""))
        agente.set_agent_knowledge(
            BANCO_CONHECIMENTO.get(conhecimento) if conhecimento else None
        )
        embeddings = criar_embeddings()
        try:
            agente.create_memory(embeddings=embeddings)
        except Exception:
            # A coleção de memória já existente pode conflitar com os metadados
            # HNSW definidos em create_chromadb; abre o Chroma sem eles.
            memoria = agents.CreateVectorDB()
            memoria.set_collection_name(nome)
            memoria.set_persist_directory("./agents_memory/{}".format(nome))
            memoria.set_embedding_function(embeddings)
            memoria.vectorstore = Chroma(
                collection_name=nome,
                persist_directory="./agents_memory/{}".format(nome),
                embedding_function=embeddings,
            )
            agente.vectorstore_memory = memoria.vectorstore
            agente.memory = memoria
        agente.setup_llm_and_chain(
            model_llm=config.get("modelo_llm", MODEL_LLM),
            base_url=config.get("base_url", BASE_URL_SERVER),
            openai_api_key=config.get("api_key", API_KEY_SERVER),
        )
    except Exception:
        return None
    AGENTES[nome] = {"instancia": agente, "config": dict(config)}
    return agente


def salvar_agentes():
    '''Persiste as configurações dos agentes em ARQUIVO_AGENTES.'''
    try:
        with open(ARQUIVO_AGENTES, "w", encoding="utf-8") as arquivo:
            json.dump(
                {nome: item["config"] for nome, item in AGENTES.items()},
                arquivo,
                ensure_ascii=False,
                indent=2,
            )
    except Exception:
        pass


def carregar_agentes_persistidos():
    '''Recria os agentes salvos em ARQUIVO_AGENTES ao iniciar o servidor.'''
    if not os.path.isfile(ARQUIVO_AGENTES):
        return
    try:
        with open(ARQUIVO_AGENTES, "r", encoding="utf-8") as arquivo:
            registros = json.load(arquivo)
    except Exception:
        return
    for nome, config in registros.items():
        criar_agente_instancia(str(nome), config)


def ler_orquestracoes_salvas():
    '''Carrega ./orquestracoes_salvas.json (dict nome -> orquestração salva).'''
    if not os.path.isfile(ARQUIVO_ORQUESTRACOES):
        return {}
    try:
        with open(ARQUIVO_ORQUESTRACOES, "r", encoding="utf-8") as arquivo:
            registros = json.load(arquivo)
        return registros if isinstance(registros, dict) else {}
    except Exception:
        return {}


def gravar_orquestracao_salva(nome, dados):
    '''Persiste uma orquestração (nos/arestas/prompt_inicial) no JSON.'''
    registros = ler_orquestracoes_salvas()
    registros[str(nome)] = dados
    try:
        with open(ARQUIVO_ORQUESTRACOES, "w", encoding="utf-8") as arquivo:
            json.dump(registros, arquivo, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        adicionar_log("erro", "Falha ao gravar orquestração: {}".format(exc))
        return False


def excluir_orquestracao_salva(nome):
    '''Remove uma orquestração salva do JSON.'''
    registros = ler_orquestracoes_salvas()
    if nome not in registros:
        return False
    del registros[nome]
    try:
        with open(ARQUIVO_ORQUESTRACOES, "w", encoding="utf-8") as arquivo:
            json.dump(registros, arquivo, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        adicionar_log("erro", "Falha ao excluir orquestração: {}".format(exc))
        return False


@app.get("/api/logs")
def api_logs():
    '''
    Endpoint SSE com o debug do servidor em tempo real para o painel
    "Log do servidor". Emite o histórico do buffer e, depois, as novas entradas.
    '''

    def gerar_logs():
        ultimo_id = 0
        while True:
            for entrada in list(LOG_BUFFER):
                if entrada["id"] > ultimo_id:
                    yield "event: log\ndata: {}\n\n".format(json.dumps(entrada))
                    ultimo_id = entrada["id"]
            time.sleep(1)

    return Response(
        stream_with_context(gerar_logs()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/orquestracoes")
def listar_orquestracoes():
    '''Lista os nomes das orquestrações persistidas.'''
    return jsonify(list(ler_orquestracoes_salvas().keys()))


@app.post("/api/orquestracoes")
def salvar_orquestracao():
    '''Grava a estrutura de orquestração (nos/arestas/prompt_inicial).'''
    dados = request.get_json(force=True)
    nome = str(dados.get("nome", "")).strip()
    if not nome:
        return jsonify({"erro": "Informe um nome para a orquestração"}), 400
    if not dados.get("nos"):
        return jsonify({"erro": "Não há nós para salvar no ambiente"}), 400
    if gravar_orquestracao_salva(nome, {
        "nome": nome,
        "nos": dados.get("nos", []),
        "arestas": dados.get("arestas", []),
        "prompt_inicial": dados.get("prompt_inicial", ""),
    }):
        adicionar_log("info", "Orquestração '{}' gravada".format(nome))
        return jsonify({"ok": True, "nome": nome}), 201
    return jsonify({"erro": "Falha ao gravar a orquestração"}), 500


@app.post("/api/orquestracoes/<nome>/carregar")
def carregar_orquestracao(nome):
    '''Devolve uma orquestração salva para recriação no ambiente.'''
    registros = ler_orquestracoes_salvas()
    if nome not in registros:
        return jsonify({"erro": "Orquestração '{}' não encontrada".format(nome)}), 404
    return jsonify(registros[nome])


@app.post("/api/orquestracoes/<nome>/excluir")
def remover_orquestracao(nome):
    '''Remove uma orquestração salva.'''
    if excluir_orquestracao_salva(nome):
        adicionar_log("info", "Orquestração '{}' excluída".format(nome))
        return jsonify({"ok": True, "nome": nome})
    return jsonify({"erro": "Orquestração '{}' não encontrada".format(nome)}), 404


@app.get("/")
def index():
    '''Página principal (front-end).'''
    return render_template("index.html")


@app.get("/api/status")
def status():
    '''Estado do processo: configurações, servidor LM Studio, bases e agentes.'''
    return jsonify({
        "modelo_embedding": MODEL_EMBEDDING,
        "modelo_llm": MODEL_LLM,
        "base_url": BASE_URL_SERVER,
        "api_key": API_KEY_SERVER,
        "servidor": verificar_servidor(),
        "bases": list(BANCO_CONHECIMENTO.keys()),
        "agentes": list(AGENTES.keys()),
    })


@app.get("/api/conhecimentos")
def listar_conhecimentos():
    '''Lista as bases de conhecimento carregadas no processo.'''
    return jsonify(list(BANCO_CONHECIMENTO.keys()))


@app.post("/api/conhecimentos")
def criar_conhecimento():
    '''
    Cria uma base de conhecimento — ou anexa novos arquivos a uma base já
    existente — a partir de um ou mais PDFs enviados via multipart/form-data,
    transmitindo o progresso da indexação via SSE (text/event-stream). Os campos
    "files[]" podem conter arquivos individuais ou os arquivos de uma pasta
    inteira (seleção webkitdirectory do navegador). Cada batch de embeddings
    equivale a um passo do tqdm de
    CreateVectorDB.add_chunk_to_vectorstore (agents.py).
    Se já existir uma base carregada com o mesmo nome, os chunks dos novos PDFs
    são adicionados ao mesmo vectorstore (o Chroma é persistente).
    Eventos emitidos: "progresso" (feitos/total), "done" (base criada/anexada,
    com o campo "adicionada") e "erro".
    '''
    nome = str(request.form.get("nome", "")).strip()
    if not nome:
        return jsonify({"erro": "Informe o nome para a base de conhecimento"}), 400
    base_ja_existente = nome in BANCO_CONHECIMENTO

    arquivos_enviados = request.files.getlist("files[]")
    pdfs = []
    for up in arquivos_enviados:
        arquivo = os.path.basename(up.filename or "").strip()
        if arquivo and arquivo.lower().endswith(".pdf"):
            pdfs.append((arquivo, up.read()))
    if not pdfs:
        return jsonify({"erro": "Selecione ao menos um arquivo PDF válido"}), 400

    # Hoisting dos valores do request: a indexação roda em thread de fundo,
    # fora do request context, então não pode acessar `request` ali.
    genero = request.form.get("genero", "documento")
    especie = request.form.get("especie", "conhecimento")
    collection_name = request.form.get("collection_name", nome)
    persist_directory = request.form.get("persist_directory", DIRETORIO_PERSISTENCIA_BASES)
    try:
        chunk_size = int(request.form.get("chunk_size", 500))
        chunk_overlap = int(request.form.get("chunk_overlap", 100))
        batch_size = int(request.form.get("batch_size", 1))
    except ValueError:
        return jsonify({"erro": "Valores inválidos para chunk_size/chunk_overlap/batch_size"}), 400

    def gerar_progresso():
        fila_progresso = queue.Queue()
        diretorio_temporario = tempfile.mkdtemp(prefix="base_conhecimento_")

        def executar():
            acumulado = {"feitos": 0}
            try:
                base = agents.CreateVectorDB()
                if base_ja_existente:
                    # Reutiliza o vectorstore já carregado: os novos chunks são
                    # anexados à mesma coleção persistida (chamada só add_texts,
                    # sem reconfigurar a coleção/HNSW).
                    base.vectorstore = BANCO_CONHECIMENTO[nome]
                else:
                    base.set_collection_name(collection_name)
                    base.set_persist_directory(persist_directory)
                    base.set_embedding_function(criar_embeddings())
                    try:
                        base.create_chromadb()
                    except Exception:
                        # Coleção já existente em disco com outra configuração
                        # HNSW: abre sem os metadados (mesmo padrão da memória).
                        base.vectorstore = Chroma(
                            collection_name=collection_name,
                            persist_directory=persist_directory,
                            embedding_function=criar_embeddings(),
                        )

                plano_arquivos = []
                for indice, (arquivo, conteudo) in enumerate(pdfs):
                    caminho = os.path.join(
                        diretorio_temporario,
                        "{}_{}".format(indice, arquivo),
                    )
                    with open(caminho, "wb") as destino:
                        destino.write(conteudo)
                    documentos = llm.leitura_arquivo_pdf(
                        path_file=caminho,
                        metadados_categoria_genero=genero,
                        metadados_categoria_especie=especie,
                    )
                    chunks = llm.conversao_chunks(
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        documents=documentos,
                    )
                    if chunks:
                        plano_arquivos.append((arquivo, chunks))

                total_batches = sum(
                    len(range(0, len(chunks), batch_size))
                    for _, chunks in plano_arquivos
                )
                n_chunks = sum(len(chunks) for _, chunks in plano_arquivos)

                for arquivo, chunks in plano_arquivos:
                    def progresso_callback(feitos, total):
                        fila_progresso.put({
                            "tipo": "progresso",
                            "feitos": acumulado["feitos"] + feitos,
                            "total": total_batches,
                        })

                    base.add_chunk_to_vectorstore(
                        chunks=chunks,
                        batch_size=batch_size,
                        progresso_callback=progresso_callback,
                    )
                    acumulado["feitos"] += len(range(0, len(chunks), batch_size))

                fila_progresso.put({
                    "tipo": "done",
                    "nome": nome,
                    "n_chunks": n_chunks,
                    "n_arquivos": len(plano_arquivos),
                    "adicionada": base_ja_existente,
                    "vectorstore": base.return_vectorstore(),
                })
            except Exception as exc:
                fila_progresso.put({"tipo": "erro", "erro": "Falha ao criar a base: {}".format(exc)})
            finally:
                shutil.rmtree(diretorio_temporario, ignore_errors=True)

        threading.Thread(target=executar, daemon=True).start()

        while True:
            evento = fila_progresso.get()
            if evento["tipo"] == "progresso":
                yield "event: progresso\ndata: {}\n\n".format(json.dumps({
                    "feitos": evento["feitos"],
                    "total": evento["total"],
                }))
            elif evento["tipo"] == "done":
                BANCO_CONHECIMENTO[nome] = evento.pop("vectorstore")
                yield "event: done\ndata: {}\n\n".format(json.dumps({
                    "nome": evento["nome"],
                    "n_chunks": evento["n_chunks"],
                    "n_arquivos": evento["n_arquivos"],
                    "adicionada": evento["adicionada"],
                }))
                break
            else:
                yield "event: erro\ndata: {}\n\n".format(json.dumps({"erro": evento["erro"]}))
                break

    return Response(
        stream_with_context(gerar_progresso()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/agentes")
def criar_agente():
    '''
    Cria um agente usando a classe Agent (agents.py) com a estrutura de criação
    do RAG.ipynb: embeddings locais, base de conhecimento (vectorstore), memória
    persistente própria e cadeia LLM (com rerank embutido em run_agent).
    '''
    dados = request.get_json(force=True)
    nome = str(dados.get("nome", "")).strip()
    if not nome:
        return jsonify({"erro": "Informe o nome do agente"}), 400
    if nome in AGENTES:
        return jsonify({"erro": "O agente '{}' já existe".format(nome)}), 409

    retriever_type = str(dados.get("retriever_type", "mmr"))
    conhecimento = dados.get("conhecimento", "")
    if retriever_type != "sem_base" and conhecimento not in BANCO_CONHECIMENTO:
        return jsonify({"erro": "Base de conhecimento '{}' não encontrada".format(conhecimento)}), 400

    try:
        agente = agents.Agent()
        agente.set_agent_name(nome)
        agente.set_agent_persona(dados.get("persona", ""))
        agente.set_agent_skills(dados.get("habilidades", ""))
        agente.set_agent_task(dados.get("tarefa", ""))
        agente.set_agent_knowledge(
            BANCO_CONHECIMENTO.get(conhecimento) if conhecimento else None
        )
        agente.create_memory(embeddings=criar_embeddings())
        agente.setup_llm_and_chain(
            model_llm=dados.get("modelo_llm", MODEL_LLM),
            base_url=dados.get("base_url", BASE_URL_SERVER),
            openai_api_key=dados.get("api_key", API_KEY_SERVER),
        )
    except Exception as exc:
        return jsonify({"erro": "Falha ao criar o agente: {}".format(exc)}), 500

    config = {
        "nome": nome,
        "persona": dados.get("persona", ""),
        "habilidades": dados.get("habilidades", ""),
        "tarefa": dados.get("tarefa", ""),
        "conhecimento": conhecimento,
        "retriever_type": retriever_type,
        "modelo_llm": dados.get("modelo_llm", MODEL_LLM),
        "base_url": dados.get("base_url", BASE_URL_SERVER),
        "api_key": dados.get("api_key", API_KEY_SERVER),
    }
    AGENTES[nome] = {"instancia": agente, "config": config}
    salvar_agentes()
    return jsonify(config)


@app.get("/api/agentes")
def listar_agentes():
    '''Lista os agentes registrados com suas configurações.'''
    return jsonify({nome: item["config"] for nome, item in AGENTES.items()})


@app.post("/api/agentes/<nome>/excluir")
def excluir_agente(nome):
    '''
    Exclui um agente registrado e a sua memória persistente
    (./agents_memory/<nome>).
    '''
    if nome not in AGENTES:
        return jsonify({"erro": "Agente '{}' não encontrado".format(nome)}), 404
    pasta_memoria = "./agents_memory/{}".format(nome)
    if os.path.isdir(pasta_memoria):
        shutil.rmtree(pasta_memoria, ignore_errors=True)
    del AGENTES[nome]
    salvar_agentes()
    return jsonify({
        "ok": True,
        "agente": nome,
        "memoria_removida": not os.path.isdir(pasta_memoria),
    })


@app.post("/api/agentes/<nome>/perguntar")
def perguntar(nome):
    '''
    Executa uma pergunta em um agente individual.
    Fluxo: retriever (mmr/similarity/threshold) -> rerank (LLM) -> geração com memória.
    '''
    if nome not in AGENTES:
        return jsonify({"erro": "Agente '{}' não encontrado".format(nome)}), 404

    dados = request.get_json(force=True)
    pergunta = str(dados.get("pergunta", "")).strip()
    if not pergunta:
        return jsonify({"erro": "Informe uma pergunta"}), 400

    agente = AGENTES[nome]["instancia"]
    try:
        agente.run_agent(
            user_prompt=pergunta,
            retriever_type=dados.get("retriever_type", "mmr"),
            use_memory=bool(dados.get("usar_memoria", True)),
            regex_pattern=dados.get("regex_pattern"),
        )
        saida = agente.get_agent_answer()
        if dados.get("salvar_memoria", False):
            agente.add_info_to_memory()
    except Exception as exc:
        return jsonify({"erro": "Falha ao executar o agente: {}".format(exc)}), 500

    return jsonify({
        "agente": nome,
        "pergunta": pergunta,
        "resposta": str(saida["answer"]),
        "memoria_utilizada": str(saida["memory_docs"]),
        "trechos": [serializar_documento(d) for d in saida["top_text_rag"]],
    })


@app.post("/api/agentes/<nome>/memoria/acessar")
def acessar_memoria(nome):
    '''Consulta a memória persistente do agente (RAG sobre ./agents_memory/<nome>).'''
    if nome not in AGENTES:
        return jsonify({"erro": "Agente '{}' não encontrado".format(nome)}), 404

    dados = request.get_json(force=True)
    pergunta = str(dados.get("pergunta", "")).strip()
    if not pergunta:
        return jsonify({"erro": "Informe uma pergunta"}), 400

    agente = AGENTES[nome]["instancia"]
    try:
        agente.access_memory(user_prompt=pergunta, retriever_type=dados.get("retriever_type", "mmr"))
        memoria = agente.get_agent_memory()
    except Exception as exc:
        return jsonify({"erro": "Falha ao acessar a memória: {}".format(exc)}), 500

    return jsonify({
        "resposta_memoria": str(memoria["answer_memory"]),
        "trechos_memoria": [serializar_documento(d) for d in memoria["docs_memory"]],
    })


@app.post("/api/orquestrador")
def orquestrar():
    '''
    Orquestra um grafo de agentes (arrastados no "Ambiente de Orquestração").
    Nós: Usuário, agentes e Saída. Arestas: saída de um nó -> entrada de outro.
    Executa em ordem topológica. Quando o agente está em "sem_base" (não buscar
    na base de conhecimento), o {context} dele é composto pelas saídas dos
    agentes que o alimentam.
    '''
    dados = request.get_json(force=True)
    prompt_inicial = str(dados.get("prompt_inicial", "")).strip()
    nos = dados.get("nos", [])
    arestas = dados.get("arestas", [])

    if not nos:
        return jsonify({"erro": "Informe os nós do grafo de orquestração"}), 400

    adicionar_log("info", "Orquestração iniciada: {} nó(s) e {} aresta(s)".format(len(nos), len(arestas)))

    ids = [str(n.get("id")) for n in nos]
    if any(i == "None" or i == "" for i in ids):
        return jsonify({"erro": "Todo nó deve possuir um 'id'"}), 400
    if len(set(ids)) != len(ids):
        return jsonify({"erro": "Identificadores de nós duplicados no grafo"}), 400

    nos_por_id = {i: n for i, n in zip(ids, nos)}
    for n in nos:
        if n.get("tipo") == "agente":
            nome_agente = n.get("agente", "")
            if nome_agente not in AGENTES:
                return jsonify({"erro": "Agente '{}' não encontrado".format(nome_agente)}), 404

    arestas_por_destino = {i: [] for i in ids}
    arestas_por_origem = {i: [] for i in ids}
    for a in arestas:
        de = str(a.get("de", ""))
        para = str(a.get("para", ""))
        if de not in nos_por_id or para not in nos_por_id:
            return jsonify({"erro": "Aresta entre nós inexistentes: {} -> {}".format(de, para)}), 400
        arestas_por_destino[para].append(de)
        arestas_por_origem[de].append(para)

    # detecção de ciclo (DFS)
    def detectar_ciclo():
        visitados, em_pilha = set(), set()

        def dfs(noh):
            if noh in em_pilha:
                return True
            if noh in visitados:
                return False
            em_pilha.add(noh)
            for vizinho in arestas_por_origem[noh]:
                if dfs(vizinho):
                    return True
            em_pilha.remove(noh)
            visitados.add(noh)
            return False

        return any(dfs(noh) for noh in ids)

    if detectar_ciclo():
        return jsonify({"erro": "O grafo de orquestração contém um ciclo"}), 400

    saidas = {}
    sistema = []

    def processar_noh(noh):
        entradas = [saidas[origem] for origem in arestas_por_destino[noh] if origem in saidas]
        entrada = "\n\n".join(entradas)
        no = nos_por_id[noh]
        tipo = no.get("tipo", "agente")
        item = {"id": noh, "tipo": tipo}

        if tipo == "usuario":
            item["entrada"] = ""
            item["saida"] = prompt_inicial
            saidas[noh] = prompt_inicial
        elif tipo == "saida":
            item["entrada"] = entrada
            item["saida"] = entrada
            saidas[noh] = entrada
        elif tipo == "agente":
            nome_agente = no.get("agente", "")
            agente = AGENTES[nome_agente]["instancia"]
            config = AGENTES[nome_agente]["config"]
            retriever_type = config.get("retriever_type", "mmr")
            item["entrada"] = entrada or "(sem entrada)"
            inicio_agente = time.time()
            adicionar_log("info", "Executando agente '{}' (retriever={})...".format(nome_agente, retriever_type))
            try:
                agente.run_agent(
                    user_prompt=entrada or prompt_inicial,
                    retriever_type=retriever_type,
                    use_memory=bool(no.get("usar_memoria", True)),
                    regex_pattern=no.get("regex_pattern"),
                    contexto_externo=entradas if retriever_type == "sem_base" else None,
                )
                saida = agente.get_agent_answer()
                item["saida"] = str(saida["answer"])
                item["trechos"] = [serializar_documento(d) for d in saida["top_text_rag"]]
                adicionar_log(
                    "info",
                    "Agente '{}' concluído em {:.1f}s".format(nome_agente, time.time() - inicio_agente),
                )
            except Exception as exc:
                item["saida"] = ""
                item["erro"] = str(exc)
                adicionar_log("erro", "Falha no agente '{}': {}".format(nome_agente, exc))
            saidas[noh] = item.get("saida", "")
        else:
            return False

        sistema.append(item)
        return True

    # ordem topológica (Kahn), dando prioridade ao nó Usuário para propagar o prompt inicial
    graus_entrada = {i: len(arestas_por_destino[i]) for i in ids}
    fila = collections.deque(i for i in ids if graus_entrada[i] == 0)
    processados = set()

    def chave_prioridade(noh):
        return 0 if nos_por_id[noh].get("tipo") == "usuario" else 1

    while fila:
        noh = min(fila, key=chave_prioridade)
        fila.remove(noh)
        if noh in processados:
            continue
        if not processar_noh(noh):
            continue
        processados.add(noh)
        for vizinho in arestas_por_origem[noh]:
            graus_entrada[vizinho] -= 1
            if graus_entrada[vizinho] == 0:
                fila.append(vizinho)

    if len(processados) < len(ids):
        return jsonify({
            "erro": "Parte do grafo não pôde ser processada por dependência de entrada inexistente"
        }), 400

    nos_saida = [noh for noh in ids if nos_por_id[noh].get("tipo") == "saida"]
    saida_final = "\n\n".join(saidas.get(noh, "") for noh in nos_saida) if nos_saida else ""

    adicionar_log("info", "Orquestração concluída: {} nó(s) processado(s)".format(len(processados)))

    return jsonify({
        "prompt_inicial": prompt_inicial,
        "sistema": sistema,
        "saida": saida_final,
    })


def _env_bool(nome, padrao):
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes")


if __name__ == "__main__":
    carregar_bases_persistidas()
    carregar_agentes_persistidos()
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=_env_bool("FLASK_DEBUG", True),
        use_reloader=_env_bool("FLASK_RELOADER", False),
        threaded=True,
    )
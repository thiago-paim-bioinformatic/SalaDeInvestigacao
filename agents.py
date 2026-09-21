#import llm

#bibliotecas

#O PyMuPDFLoader funciona perfeitamente (e de forma extremamente rápida) tanto com PDFs originais/nativos quanto com PDFs escaneados.
#pip install pymupdf pymupdf4llm
#from langchain_community.document_loaders import PyMuPDFLoader

# Loader de PDF
from langchain_community.document_loaders import PyPDFLoader

#Loader de TXT
from langchain_community.document_loaders import TextLoader


# Strings 
from langchain_core.documents import Document

# Divisão de texto em blocos
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Embedding - aqui, via API do Google
#from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Embedding - aqui, via OpenAI...o LMStudio tem API compatível.
from langchain_openai import OpenAIEmbeddings

#LLM - do Gemini
#from langchain_google_genai import ChatGoogleGenerativeAI

# LLM - da OpenAI, compatível com LMStudio
from langchain_openai import ChatOpenAI

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate

from langchain_classic.chains.combine_documents import create_stuff_documents_chain

from langchain_classic.chains import create_retrieval_chain

#vector.database
from langchain_chroma import Chroma

#monitoramento de progresso de embedding
from tqdm import tqdm


class CreateChunks():
    def __init__(self):
        None
        
    def load_file_pdf(self,
                      path_file:str,
                      metadados_categoria_genero:str,
                      metadados_categoria_especie:str):
        """
        metadados_categoria_genero:str -> classe superior que pertence o documento. P.ex.: Inquérito Policial
        metadados_categoria_especie:str -> classe inferior que pertence o documento. P. ex.: IP 0001-2025-700000
        """
        loader = PyPDFLoader(path_file)
        documents = loader.load()
        for doc in documents:
            doc.metadata[str(metadados_categoria_genero)] = str(metadados_categoria_especie)
        self.documents = documents

    def load_strings(self,
                    strings:str,
                    metadados_categoria_genero:str,
                    metadados_categoria_especie:str):
        
        doc = Document(page_content=strings)
        doc.metadata[str(metadados_categoria_genero)] = str(metadados_categoria_especie)
        self.doc = [doc]
        print(type(self.doc))
        print(self.doc)
        
    def chunks(self, chunk_size:int, chunk_overlap:int, database:str):
        """
        O Recursive Text Splitter é uma abordagem utilizada para dividir textos extensos em pedaços
        menores (chunks) de forma  inteligente.
        A ideia é quebrar recursivamente o texto, respeitando limites de tamanho definidos e, 
        ao mesmo tempo, tentando preservar a integridade semântica dos trechos. Em vez 
        de realizar uma simples divisão linear, esse método procura pontos naturais de 
        separação, como quebras de parágrafo ou sentenças, para evitar a perda de contexto importante.
        """
        # divisão em chunks
        #parâmetro 'documents' : é a saída do método leitura_arquivo_pdf
        text_splitter = RecursiveCharacterTextSplitter (
            chunk_size = chunk_size,
            chunk_overlap = chunk_overlap
        )
        
        if database=="info_docs":
            chunks = text_splitter.split_documents(self.documents)
            return chunks
        elif database=="info_memory":
            chunks = text_splitter.split_documents(self.doc)
            return chunks
        else:
            print("Não foram carregados arquivos PDF ou strings. Execute o método 'load_file_pdf' ou 'load_strings'\n")
            return None


class CreateVectorDB ():
    def __init__(self):
        None
    
    def set_collection_name(self, collection_name:str):
        self.collection_name = collection_name
    
    def set_persist_directory(self, persist_directory:str):
        self.persist_directory = persist_directory
    
    def set_embedding_function(self, embedding_function):
        self.embedding_function = embedding_function
    
    def create_chromadb(self):
        vectorstore = Chroma(
            collection_name=self.collection_name,
            persist_directory=self.persist_directory,
            embedding_function=self.embedding_function,
            collection_metadata={
                "hnsw:space": "cosine",        # Métrica de distância Similaridade por Cosseno
                "hnsw:construction_ef": 200,   # Mais precisão na criação (indexação mais lenta)
                "hnsw:search_ef": 50,          # Mais precisão na busca (retriever um pouco mais lento)
                "hnsw:M": 32                   # Mais conexões entre os vetores (gasta mais RAM)
            },
        )
        self.vectorstore = vectorstore
    
    def add_chunk_to_vectorstore (self, chunks, batch_size:int, progresso_callback=None):
        batch_size = batch_size
        total = len(range(0, len(chunks), batch_size))
        for i, indice in enumerate(
            tqdm(range(0, len(chunks), batch_size)),
            start=1
        ):
            batch = chunks[indice:indice + batch_size]
        
            #extrai texto dos chuncks
            texts = [
                doc.page_content
                for doc in batch
            ]
        
            #extrai os metadados do chunk
            metadatas = [
                doc.metadata
                for doc in batch
            ]
            self.vectorstore.add_texts(texts=texts, metadatas=metadatas)
            if progresso_callback:
                progresso_callback(i, total)

    def return_vectorstore(self):
        return self.vectorstore

## criar método de carregar banco de dados existente

class Agent():
    def __init__(self):
        self.memory=CreateVectorDB()
    def set_agent_name(self, name:str):
        self.name = name
    def set_agent_persona(self, persona:str):
        self.persona = persona
    def set_agent_skills(self, skills:str):
        self.skills = skills
    def set_agent_task(self, task:str):
        self.task = task
    def set_agent_knowledge(self, knowledge):
        """
        A base de conhecimento é dada pelo banco de dados
        criado, para realização de RAG.
        Informa uma instância 'vectostore', que é a saída
        do método CreateVectorDB.return_vectorstore().
        """
        if knowledge:
            self.knowledge = knowledge
        else:
            None
    
    def create_memory(self, embeddings):
        memory = CreateVectorDB()
        self.memory.set_collection_name(str(self.name))
        self.memory.set_persist_directory(f"./agents_memory/{str(self.name)}")
        self.memory.set_embedding_function(embeddings)
        self.memory.create_chromadb()
        vectorstore_memory=self.memory.return_vectorstore()
        self.vectorstore_memory=vectorstore_memory

    def setup_llm_and_chain(self, model_llm:str, base_url:str, openai_api_key:str):
        """
        Cria a instância do LLM e a cadeia de processamento de documentos separadamente,
        permitindo interceptar os documentos para o rerank.
        """
        llm = ChatOpenAI (
            model=model_llm,
            base_url=base_url,
            openai_api_key=openai_api_key,
            temperature=0 # Recomendado manter 0 para respostas baseadas em contexto
        )

        
        system_prompt=f"""
        Seu nome é {self.name} e {self.persona}.

        Você tem as seguintes habilidades: 
        {self.skills}

        A sua tarefa é a seguinte:
        {self.task}
        
        Utilize estritamente o contexto abaixo e os dados de memória, se disponíveis, para responder à pergunta:
        Contexto: {{context}}
        
        Memória: {{memory}}
        
        """
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}")
        ])
        document_chain = create_stuff_documents_chain(llm, prompt)
        
        self.llm=llm
        self.document_chain=document_chain
    
    def run_agent(self, user_prompt:str, 
                  retriever_type="mmr", 
                  use_memory=True, 
                  regex_pattern:str = None,
                  contexto_externo=None):
        
        search_kwargs = {} # configuração de argumento de busca...permite também busca por regex

        if regex_pattern:
            search_kwargs["where_document"] = {"$regex":regex_pattern}

        if retriever_type == "sem_base":
            # Não busca na base de conhecimento: o contexto é composto pelas
            # saídas recebidas de outros agentes durante a orquestração.
            top_docs = [
                Document(page_content=str(texto))
                for texto in (contexto_externo or [])
            ]
            docs_iniciais = []
            self.retriever = None
        
        else:
            
            if retriever_type == "mmr":
                search_kwargs.update({ #atualiza o dicionário 'search_kwargs'
                        "k":5,
                        "fetch_k": 20
                    })
                retriever = self.knowledge.as_retriever(
                    search_type="mmr",
                    search_kwargs=search_kwargs
                )
                self.retriever=retriever
            
            elif retriever_type == "similarity_score_threshold":
                search_kwargs.update({
                        "score_threshold": 0.7
                })
                retriever = self.knowledge.as_retriever(
                    search_type="similarity_score_threshold",
                    search_kwargs = search_kwargs
                )
                self.retriever=retriever
            
            elif retriever_type == "similarity":
                search_kwargs.update({"k":3})
                retriever = self.knowledge.as_retriever(
                    search_type="similarity",
                    search_kwargs=search_kwargs
                )
                self.retriever=retriever
                
            else:
                None

            # 1. Recuperação Inicial (Retriever)
            docs_iniciais = self.retriever.invoke(user_prompt)
             
            #2. Rerank Semântico
            '''
            Reordena os documentos recuperados com base na relevância
            usando o próprio LLm (rerankig semântico)
            '''
            prompt_rerank = PromptTemplate(
                input_variables=["pergunta", "texto"],
                template="""
                Você é um especialista em inteligência policial.
                
                Pergunta do usuário:
                {pergunta}
                
                Trecho do documento:
                {texto}
                
                Avalie a relevância desse trecho para responder a pergunta.
                Responda APENAS com um número de 0 a 10.
                """
            )
        
            documentos_com_score = []
            #itera sobre os trechos retornados em documentos, a partir da primeira chamada por busca de similaridade
            #da pergunta com o vectorstore
            for doc in docs_iniciais:
                score = self.llm.invoke(
                    prompt_rerank.format(
                        pergunta=user_prompt,
                        texto=doc.page_content
                    )
                ).content
                try:
                    score = float(score)
                except:
                    score = 0
                documentos_com_score.append((score, doc))
            
            #ordena do mais relevante para o menos relevante
            documentos_ordenados = sorted(
                documentos_com_score,
                key=lambda x: x[0], reverse=True
            )
        
            #retorna apenas os documentos
            docs_reranked=[doc for _,doc in documentos_ordenados]
            
            # Seleciona apenas os 3 mais relevantes após o rerank
            top_docs = docs_reranked[:3] 

        ####### IMPORTANTE #######
        # Criar chamada de acesso a memória do agente com o mesmo `user_prompt`
        # Concatenar com `top_docs` e explicitar que `foi buscado na memória do agente`
        # Será a entrada para `context`...
        ####### IMPORTANTE #######

        if use_memory == True:
            try:
                self.access_memory(user_prompt=user_prompt,  retriever_type="mmr")
                get_memory = self.get_agent_memory()
                memory = get_memory["answer_memory"]
            except:
                memory = []
        else:
            memory = []
            
        # 3. Geração da Resposta Final
        answer = self.document_chain.invoke({
            "context": top_docs,
            "memory":memory,
            "input": user_prompt
        })

        self.answer=answer
        self.user_prompt=user_prompt
        self.top_docs=top_docs
        self.memory_docs=memory

    def get_agent_answer(self) -> dict:
        output = {
            "answer":self.answer,
            "user_prompt":self.user_prompt,
            "top_text_rag":self.top_docs,
            "memory_docs":self.memory_docs
        }
        return output
        
    def add_info_to_memory(self):
        data = []
        data.append(str(self.user_prompt))
        data.append(str(self.answer))
        data_memory = "\n".join(data)
        
        chunks_memory = CreateChunks()
        chunks_memory.load_strings(
            strings=data_memory,
            metadados_categoria_genero="Memória de Agente",
            metadados_categoria_especie=str(self.user_prompt)
        )
        chunks = chunks_memory.chunks(
            chunk_size=850,
            chunk_overlap=150,
            database="info_memory"
        )
        
        self.memory.add_chunk_to_vectorstore(chunks=chunks, batch_size=1)

    def access_memory(self, user_prompt:str, retriever_type="mmr"):
        if retriever_type == "mmr":
            retriever_memory = self.vectorstore_memory.as_retriever(
                search_type="mmr",
                search_kwargs={
                    "k":5,
                    "fetch_k": 20
                }
            )
            self.retriever_memory=retriever_memory
        
        elif retriever_type == "similarity_score_threshold":
            retriever_memory = self.vectorstore_memory.as_retriever(
                search_type="similarity_score_threshold",
                search_kwargs={
                    "score_threshold": 0.7
                }
            )
            self.retriever_memory=retriever_memory
        
        elif retriever_type == "similarity":
            retriever_memory = self.vectorstore_memory.as_retriever(
                search_type="similarity",
                search_kwargs={"k":3}
            )
            self.retriever_memory=retriever_memory
            
        else:
            None


         # 1. Recuperação Inicial (Retriever)
        docs_recuperados = self.retriever_memory.invoke(user_prompt)
         
        # 2. Geração da Resposta Final
        answer = self.document_chain.invoke({
            "context": docs_recuperados,
            "input": user_prompt,
            "memory": [] # aqui não é carregada a memória, pois já se está buscando na própria...
        })

        self.answer_memory=answer
        self.user_prompt_memory=user_prompt
        self.docs_recuperados=docs_recuperados

    def get_agent_memory(self) -> dict:
        output = {
            "answer_memory":self.answer_memory,
            "user_prompt_memory":self.user_prompt_memory,
            "docs_memory":self.docs_recuperados
        }
        return output

"""
OBS.: elaborar o método para criar memória de longo prazo para cada Agente. e
Essa memória deve ser consultada por similaridade (RAG) e compor também a busca semântica
sobre a Base de Conhecimento.
"""
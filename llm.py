'''
script llm.py
versão: 1.0
data: 22/05/2026
autor: Thiago Paim
Descrição: bibliotecas e funções para a criação de um agente de IA
'''

#bibliotecas

# Loader de PDF
from langchain_community.document_loaders import PyPDFLoader

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




# CRIAÇÃO DA BASE DE CONHECIMENTO
# Carregamento de arquivo PDF
def leitura_arquivo_pdf (path_file:str, metadados_categoria_genero:str, metadados_categoria_especie:str):
    """
    metadados_categoria_genero:str -> classe superior que pertence o documento. P.ex.: Inquérito Policial
    metadados_categoria_especie:str -> classe inferior que pertence o documento. P. ex.: IP 0001-2025-700000
    """
    loader = PyPDFLoader(path_file)
    documents = loader.load()
    for doc in documents:
        doc.metadata[str(metadados_categoria_genero)] = str(metadados_categoria_especie)
    return documents

#Conversão do documento em chunks
def conversao_chunks (chunk_size:int, chunk_overlap:int, documents):
    """
    O Recursive Text Splitter é uma abordagem utilizada para dividir textos extensos em pedaços menores (chunks) de forma inteligente. A ideia é quebrar recursivamente o texto, respeitando limites de tamanho definidos e, ao mesmo tempo, tentando preservar a integridade semântica dos trechos. Em vez de realizar uma simples divisão linear, esse método procura pontos naturais de separação, como quebras de parágrafo ou sentenças, para evitar a perda de contexto importante.
    """
    # divisão em chunks
    #parâmetro 'documents' : é a saída do método leitura_arquivo_pdf
    text_splitter = RecursiveCharacterTextSplitter (
        chunk_size = chunk_size,
        chunk_overlap = chunk_overlap
    )
    chunks = text_splitter.split_documents(documents)
    return chunks


#Embedding e criação da database
def embedding_and_database (model:str, 
                            base_url:str, 
                            api_key:str, 
                            batch_size:int, 
                            chunks
                           ):

    embeddings = OpenAIEmbeddings(
        model=model,
        base_url=base_url,
        api_key=api_key,
        chunk_size=1,
        check_embedding_ctx_length=False
    )


    vectorstore = Chroma(
        persist_directory="./chroma_base_de_dados",
        embedding_function=embeddings
    )

    batch_size = batch_size

    for i in tqdm(range(0, len(chunks), batch_size)):
        batch = chunks[i:i + batch_size]
    
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
    
        #adiciona a base de dados vetorial
        vectorstore.add_texts(
            texts=texts,
            metadatas=metadatas
        )
    return vectorstore

# cria o retriever, três informações semelhantes na recuperação...COM MMR...recuperação de contexto
def metodo_retriever (retriever_type, vectorstore):

    if retriever_type == "mmr":
        retriever = vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k":5,
                "fetch_k": 20
            }
        )
        return retriever
        
    elif retriever_type == "similarity_score_threshold":
        retriever = vectorstore.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={
                "score_threshold": 0.7
            }
        )
        return retriever
        
    elif retriever_type == "similarity":
        retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k":3}
        )
        return retriever
        
    else:
        None
#################################
#implementação da RAG sem RERANK
#################################

    
def retrieval_augmented_generation (
    model_llm:str, 
    base_url:str, 
    openai_api_key:str, 
    system_prompt:str, 
    retriever):
    
    
    llm = ChatOpenAI (
        model=model_llm,
        base_url=base_url,
        openai_api_key=openai_api_key,
    )

    # Prompt do sistema
    prompt = ChatPromptTemplate.from_template(system_prompt)
    
    # Equivalente ao chain_type="stuff"
    document_chain = create_stuff_documents_chain(
        llm,
        prompt
    )
    
    # Retrieval chain
    qa_chain = create_retrieval_chain(
        retriever,
        document_chain
    )

    return qa_chain


def chat_with_rag (user_prompt:str, qa_chain):    
    response = qa_chain.invoke({
        "input": user_prompt})
    
    print("Chat:")
    print(user_prompt)
    
    print("/nResposta do agente:")
    print(response["answer"])
    
    print("Trechos utilizados como contexto:/n")
    for i, doc in enumerate(response["context"]):
        print(f"---- Trecho {i+1} ---")
        print(f"Fonte: {doc.metadata.get('source', 'Documento desconhecido')}")
        print(f"Página: {doc.metadata.get('page', 'N/A')}")
        print("Conteúdo:")
        print(doc.page_content)
        print("/n/n")

#################################
#implementação da RAG COM RERANK
#################################
    
def rerank (pergunta, documentos, llm):
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
    for doc in documentos:
        score = llm.invoke(
            prompt_rerank.format(
                pergunta=pergunta,
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
    return [doc for _,doc in documentos_ordenados]



def setup_llm_e_chain(model_llm:str, base_url:str, openai_api_key:str, system_prompt:str):
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

    prompt = ChatPromptTemplate.from_template(system_prompt)
    document_chain = create_stuff_documents_chain(llm, prompt)
    
    return llm, document_chain


def chat_with_rag_and_rerank(user_prompt:str, retriever, llm_instance, document_chain):    
    """
    Executa o fluxo completo: Retriever -> Rerank -> Geração
    """
    # 1. Recuperação Inicial (Retriever)
    docs_iniciais = retriever.invoke(user_prompt)
    
    # 2. Rerank Semântico
    # Opcional: você pode fatiar a lista (ex: docs_reranked[:3]) para enviar apenas os 3 melhores
    print("Processando Rerank dos documentos...")
    docs_reranked = rerank(pergunta=user_prompt, documentos=docs_iniciais, llm=llm_instance)
    top_docs = docs_reranked[:3] # Seleciona apenas os 3 mais relevantes após o rerank

    # 3. Geração da Resposta Final
    answer = document_chain.invoke({
        "context": top_docs,
        "input": user_prompt
    })
    
    # --- Prints e formatação de saída ---
    print("\n" + "="*40)
    print("Chat:")
    print(user_prompt)
    
    print("\nResposta do agente:")
    print(answer)
    
    print("\nTrechos utilizados como contexto após Rerank:\n")
    for i, doc in enumerate(top_docs):
        print(f"---- Trecho {i+1} ---")
        print(f"Fonte: {doc.metadata.get('source', 'Documento desconhecido')}")
        print(f"Página: {doc.metadata.get('page', 'N/A')}")
        print("Conteúdo:")
        print(doc.page_content)
        print("\n")



    
'''
MODEL_LLM = "text-embedding-nomic-embed-text-v1.5",
BASE_URL_SERVER = "http://127.0.0.1:1234/v1",
API_KEY_SERVER = "lm-studio",
'''

'''
VERIFICAR QUAL O MELHOR MODELO DE EMBEDDING SE ADAPTA PARA A BUSCA SEMÂNTICA LOCAL
'''
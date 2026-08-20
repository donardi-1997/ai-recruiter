import boto3

from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate


# ============================================================
# CONFIGURACIÓN
# ============================================================

AWS_REGION = "us-east-2"

KNOWLEDGE_BASE_ID = "CP7BI7MQVB"


# ============================================================
# CLIENTE BEDROCK KNOWLEDGE BASE
# ============================================================

bedrock_agent = boto3.client(
    "bedrock-agent-runtime",
    region_name=AWS_REGION
)


# ============================================================
# LLM
# ============================================================

llm = ChatBedrock(
    model_id="amazon.nova-lite-v1:0",
    region_name=AWS_REGION,
    model_kwargs={
        "temperature": 0
    }
)


# ============================================================
# RETRIEVAL MULTI-CANDIDATO
# ============================================================

def retrieve_candidates(question: str, number_of_results: int = 10):

    response = bedrock_agent.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,

        retrievalQuery={
            "text": question
        },

        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": number_of_results
            }
        }
    )

    results = response.get(
        "retrievalResults",
        []
    )

    candidates = []

    for result in results:

        text = result.get(
            "content",
            {}
        ).get(
            "text",
            ""
        )

        score = result.get(
            "score",
            0
        )

        metadata = result.get(
            "metadata",
            {}
        )

        candidates.append({
            "text": text,
            "score": score,
            "metadata": metadata,
            "location": result.get(
                "location",
                {}
            )
        })

    return candidates


# ============================================================
# GENERAR RESPUESTA
# ============================================================

def ask_candidates(question: str):

    results = retrieve_candidates(question)

    if not results:

        return {
            "answer": "No encontré información relevante.",
            "sources": []
        }

    context_parts = []

    for index, result in enumerate(results, start=1):

        context_parts.append(
            f"""
FUENTE {index}

METADATA:
{result["metadata"]}

CONTENIDO:
{result["text"]}
"""
        )

    context = "\n\n".join(
        context_parts
    )

    prompt = ChatPromptTemplate.from_messages([

        (
            "system",
            """
Eres un asistente especializado en selección de candidatos.

Tu tarea es analizar múltiples CVs.

Utiliza EXCLUSIVAMENTE la información proporcionada
en el contexto.

No inventes información.

Identifica correctamente los candidatos mencionados
en los documentos.

Cuando sea posible, menciona:

- Nombre del candidato
- Experiencia relevante
- Tecnologías relacionadas
- Nivel de coincidencia con la consulta

Si no existe información suficiente,
indícalo claramente.

Sé preciso y profesional.

CONTEXTO DE LOS CVs:

{context}
"""
        ),

        (
            "human",
            "{question}"
        )
    ])

    chain = prompt | llm

    response = chain.invoke({
        "context": context,
        "question": question
    })

    return {
        "answer": response.content,
        "sources": results
    }


# ============================================================
# PRUEBA MVP3
# ============================================================

if __name__ == "__main__":

    question = """
    ¿Qué candidatos tienen experiencia trabajando con AWS?
    Compara sus principales tecnologías y experiencia.
    """

    result = ask_candidates(question)

    print()
    print("=" * 80)
    print("RESPUESTA MULTI-CANDIDATO")
    print("=" * 80)

    print(
        result["answer"]
    )

    print()
    print("=" * 80)
    print("FUENTES RECUPERADAS")
    print("=" * 80)

    for index, source in enumerate(
        result["sources"],
        start=1
    ):

        print()
        print(
            f"--- FUENTE {index} ---"
        )

        print(
            f"Score: {source['score']}"
        )

        print(
            f"Metadata: {source['metadata']}"
        )

        print(
            f"Location: {source['location']}"
        )

        print(
            f"Text: {source['text'][:500]}"
        )
import boto3

from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate


# ============================================================
# CONFIGURACIÓN
# ============================================================

AWS_REGION = "us-east-2"

KNOWLEDGE_BASE_ID = "CP7BI7MQVB"

CANDIDATE_ID = "78e90670-1134-4836-b7b0-241e9b1e9bca"


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
# RETRIEVAL
# ============================================================

def retrieve_cv(question: str, number_of_results: int = 5):

    response = bedrock_agent.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,

        retrievalQuery={
            "text": question
        },

        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": number_of_results,

                "filter": {
                    "equals": {
                        "key": "candidate_id",
                        "value": CANDIDATE_ID
                    }
                }
            }
        }
    )

    results = response.get("retrievalResults", [])

    context = []

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

        context.append({
            "text": text,
            "score": score,
            "location": result.get(
                "location",
                {}
            )
        })

    return context


# ============================================================
# GENERAR RESPUESTA
# ============================================================

def ask_cv(question: str):

    results = retrieve_cv(question)

    if not results:
        return {
            "answer": "No encontré información relevante en el CV.",
            "sources": []
        }

    context = "\n\n".join(
        result["text"]
        for result in results
    )

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """
Eres un asistente especializado en selección de candidatos.

Responde preguntas sobre el candidato utilizando
EXCLUSIVAMENTE la información proporcionada en el contexto.

No inventes información.

Si la información no está disponible en el contexto,
indica claramente que no está disponible.

Sé preciso y profesional.

CONTEXTO DEL CV:
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
# PRUEBA
# ============================================================

if __name__ == "__main__":

    question = """
    ¿Qué experiencia tiene Adrian Felipe Restrepo Guerra
    trabajando con AWS?
    """

    result = ask_cv(question)

    print("\n")
    print("=" * 80)
    print("RESPUESTA")
    print("=" * 80)

    print(result["answer"])

    print("\n")
    print("=" * 80)
    print("FUENTES")
    print("=" * 80)

    for source in result["sources"]:

        print(
            f"\nScore: {source['score']}"
        )

        print(
            source["location"]
        )
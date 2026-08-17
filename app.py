import requests
import streamlit as st


# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://ub8njxuol0.execute-api.us-east-2.amazonaws.com/chat"


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="AI CV Recruiter",
    page_icon="🤖",
    layout="centered"
)


# ============================================================
# HEADER
# ============================================================

st.title("🤖 AI CV Recruiter")

st.markdown(
    """
    Analiza el CV de un candidato utilizando:

    - 🧠 Amazon Bedrock
    - 🔎 RAG / búsqueda semántica
    - 📚 Amazon Bedrock Knowledge Bases
    - 🗄️ Amazon S3
    - ⚡ AWS Lambda
    - 🌐 API Gateway
    """
)

st.divider()


# ============================================================
# SESSION STATE
# ============================================================

if "messages" not in st.session_state:
    st.session_state.messages = []


# ============================================================
# CHAT HISTORY
# ============================================================

for message in st.session_state.messages:

    with st.chat_message(message["role"]):

        st.markdown(
            message["content"]
        )


# ============================================================
# CHAT INPUT
# ============================================================

question = st.chat_input(
    "Pregunta algo sobre el candidato..."
)


# ============================================================
# PROCESS QUESTION
# ============================================================

if question:

    # --------------------------------------------------------
    # User message
    # --------------------------------------------------------

    st.session_state.messages.append(
        {
            "role": "user",
            "content": question
        }
    )

    with st.chat_message("user"):
        st.markdown(question)


    # --------------------------------------------------------
    # Assistant message
    # --------------------------------------------------------

    with st.chat_message("assistant"):

        with st.spinner("Analizando el CV..."):

            try:

                response = requests.post(
                    API_URL,
                    json={
                        "question": question
                    },
                    timeout=60
                )


                # ------------------------------------------------
                # HTTP error
                # ------------------------------------------------

                if response.status_code != 200:

                    st.error(
                        f"API Error: {response.status_code}"
                    )

                    st.code(
                        response.text
                    )

                    st.stop()


                # ------------------------------------------------
                # Parse response
                # ------------------------------------------------

                data = response.json()


                answer = data.get(
                    "answer",
                    "No se recibió una respuesta."
                )


                # ------------------------------------------------
                # Display answer
                # ------------------------------------------------

                st.markdown(answer)


                # ------------------------------------------------
                # Sources
                # ------------------------------------------------

                sources = data.get(
                    "sources",
                    []
                )

                if sources:

                    with st.expander(
                        "📚 Fuentes utilizadas"
                    ):

                        for index, source in enumerate(
                            sources,
                            start=1
                        ):

                            score = source.get(
                                "score",
                                0
                            )

                            location = source.get(
                                "location",
                                {}
                            )

                            s3_location = location.get(
                                "s3Location",
                                {}
                            )

                            uri = s3_location.get(
                                "uri",
                                "Unknown"
                            )


                            st.markdown(
                                f"""
                                **Fuente {index}**

                                - Documento: `{uri}`
                                - Relevancia: `{score:.2%}`
                                """
                            )


                # ------------------------------------------------
                # Save assistant message
                # ------------------------------------------------

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer
                    }
                )


            except requests.exceptions.Timeout:

                st.error(
                    "La API tardó demasiado en responder."
                )


            except requests.exceptions.RequestException as e:

                st.error(
                    "No fue posible conectarse con la API."
                )

                st.code(
                    str(e)
                )


            except Exception as e:

                st.error(
                    "Ocurrió un error inesperado."
                )

                st.code(
                    str(e)
                )


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header("📄 Candidate CV")

    st.info(
        "El chatbot responde utilizando "
        "información recuperada del CV."
    )

    st.divider()

    st.subheader("Architecture")

    st.markdown(
        """
        **Frontend**

        Streamlit

        ↓

        **API**

        Amazon API Gateway

        ↓

        **Compute**

        AWS Lambda

        ↓

        **RAG**

        Amazon Bedrock Knowledge Base

        ↓

        **Vector DB**

        Amazon S3 Vectors

        ↓

        **LLM**

        Amazon Nova 2 Lite
        """
    )

    st.divider()

    if st.button("🗑️ Limpiar conversación"):

        st.session_state.messages = []

        st.rerun()
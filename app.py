import os

import boto3
import requests
import streamlit as st
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

AWS_REGION = os.getenv(
    "AWS_REGION",
    "us-east-2"
)

COGNITO_USER_POOL_ID = os.getenv(
    "COGNITO_USER_POOL_ID"
)

COGNITO_CLIENT_ID = os.getenv(
    "COGNITO_CLIENT_ID"
)

API_URL = os.getenv(
    "API_URL",
    "http://ai-recruiter-api-alb-184707625.us-east-2.elb.amazonaws.com"
).rstrip("/")

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="AI CV Recruiter",
    page_icon="🤖",
    layout="wide"
)

# ============================================================
# COGNITO CLIENT
# ============================================================

cognito = boto3.client(
    "cognito-idp",
    region_name=AWS_REGION
)

# ============================================================
# SESSION STATE
# ============================================================

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "access_token" not in st.session_state:
    st.session_state.access_token = None

if "user" not in st.session_state:
    st.session_state.user = None

if (
    st.session_state.authenticated
    and st.session_state.access_token
    and st.session_state.user is None
):

    if not validate_session():

        st.session_state.authenticated = False
        st.session_state.access_token = None
        st.session_state.user = None

        st.rerun()

if "selected_candidate_id" not in st.session_state:
    st.session_state.selected_candidate_id = None

if "candidate_page" not in st.session_state:
    st.session_state.candidate_page = 1

# ============================================================
# LOGIN
# ============================================================

def login(
    username: str,
    password: str
):

    try:

        response = cognito.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": password
            }
        )

        authentication_result = response.get(
            "AuthenticationResult"
        )

        if not authentication_result:

            return (
                False,
                "No se recibió el resultado de autenticación."
            )

        access_token = authentication_result.get(
            "AccessToken"
        )

        if not access_token:

            return (
                False,
                "Cognito no devolvió un Access Token."
            )

        # ====================================================
        # VALIDATE TOKEN WITH API
        # ====================================================

        me_response = requests.get(
            f"{API_URL}/auth/me",
            headers={
                "Authorization": (
                    f"Bearer {access_token}"
                )
            },
            timeout=10
        )

        if me_response.status_code != 200:

            return (
                False,
                "El token fue obtenido de Cognito, "
                "pero la API no pudo validarlo."
            )

        me_data = me_response.json()

        # ====================================================
        # SAVE SESSION
        # ====================================================

        st.session_state.authenticated = True

        st.session_state.access_token = access_token

        st.session_state.user = {
            "username": username
        }

        return True, None

    except cognito.exceptions.NotAuthorizedException:

        return (
            False,
            "Usuario o contraseña incorrectos."
        )

    except cognito.exceptions.UserNotFoundException:

        return (
            False,
            "El usuario no existe."
        )

    except requests.exceptions.RequestException as e:

        return (
            False,
            f"No fue posible validar la sesión con la API: {e}"
        )

    except Exception as e:

        return False, str(e)

# ============================================================
# API GET
# ============================================================

def api_get(
    endpoint,
    params=None
):

    response = requests.get(
        f"{API_URL}{endpoint}",
        headers={
            "Authorization": (
                f"Bearer {st.session_state.access_token}"
            )
        },
        params=params,
        timeout=30
    )

    if response.status_code == 401:

        st.session_state.authenticated = False

        st.session_state.access_token = None

        st.session_state.user = None

        st.rerun()

    response.raise_for_status()

    return response.json()

def validate_session():

    if not st.session_state.access_token:
        return False

    try:

        response = requests.get(
            f"{API_URL}/auth/me",
            headers={
                "Authorization": (
                    f"Bearer {st.session_state.access_token}"
                )
            },
            timeout=10
        )

        if response.status_code != 200:
            return False

        data = response.json()

        st.session_state.user = data.get(
            "user"
        )

        return True

    except requests.exceptions.RequestException:

        return False

def get_jobs():

    return api_get(
        "/jobs"
    )

# ============================================================
# API POST
# ============================================================

def api_post(
    endpoint,
    json_data=None
):

    response = requests.post(
        f"{API_URL}{endpoint}",
        headers={
            "Authorization": (
                f"Bearer {st.session_state.access_token}"
            ),
            "Content-Type": "application/json"
        },
        json=json_data,
        timeout=60
    )

    response.raise_for_status()

    return response.json()

# ============================================================
# CURRENT USER
# ============================================================

def get_current_user():

    try:

        return api_get(
            "/auth/me"
        ).get(
            "user"
        )

    except Exception:

        return None

# ============================================================
# LOGOUT
# ============================================================

def logout():

    st.session_state.authenticated = False

    st.session_state.access_token = None

    st.session_state.user = None

    st.session_state.selected_candidate_id = None

    st.rerun()



# ============================================================
# LOGIN SCREEN
# ============================================================

if not st.session_state.authenticated:

    st.title(
        "🤖 AI CV Recruiter"
    )

    st.markdown(
        """
        ### Intelligent Candidate Screening

        Evalúa candidatos utilizando:

        - Amazon Bedrock
        - RAG
        - Bedrock Knowledge Bases
        - Amazon S3
        - FastAPI
        - Amazon Cognito
        """
    )

    st.divider()

    col1, col2, col3 = st.columns(
        [1, 2, 1]
    )

    with col2:

        with st.form(
            "login_form"
        ):

            st.subheader(
                "🔐 Iniciar sesión"
            )

            username = st.text_input(
                "Email"
            )

            password = st.text_input(
                "Password",
                type="password"
            )

            submitted = st.form_submit_button(
                "Iniciar sesión",
                use_container_width=True
            )

            if submitted:

                if not username or not password:

                    st.error(
                        "Ingresa email y contraseña."
                    )

                else:

                    with st.spinner(
                        "Autenticando..."
                    ):

                        success, error = login(
                            username,
                            password
                        )

                    if success:

                        st.rerun()

                    else:

                        st.error(
                            error
                        )

    st.stop()

# ============================================================
# LOAD USER
# ============================================================

if st.session_state.user is None:

    with st.spinner(
        "Validando sesión..."
    ):

        st.session_state.user = (
            get_current_user()
        )

    if st.session_state.user is None:

        st.session_state.authenticated = False

        st.session_state.access_token = None

        st.error(
            "No fue posible validar la sesión."
        )

        st.rerun()

# ============================================================
# CREATE JOB
# ============================================================

with st.expander("➕ Crear nueva vacante"):

    new_job_title = st.text_input(
        "Título de la vacante",
        placeholder="Ej: Backend Developer"
    )

    new_job_description = st.text_area(
        "Descripción de la vacante",
        placeholder=(
            "Describe el cargo, responsabilidades "
            "y requisitos..."
        ),
        height=180
    )

    if st.button(
        "Crear vacante",
        type="primary",
        use_container_width=True
    ):

        if not new_job_title.strip():

            st.error(
                "El título es obligatorio."
            )

        elif len(new_job_title.strip()) < 3:

            st.error(
                "El título debe tener al menos 3 caracteres."
            )

        elif not new_job_description.strip():

            st.error(
                "La descripción es obligatoria."
            )

        elif len(new_job_description.strip()) < 10:

            st.error(
                "La descripción debe tener al menos 10 caracteres."
            )

        else:

            try:

                response = api_post(
                    "/jobs",
                    json_data={
                        "title": new_job_title.strip(),
                        "description": new_job_description.strip()
                    }
                )

                st.success(
                    "✅ Vacante creada correctamente."
                )

                st.json(
                    response
                )

                st.rerun()

            except requests.exceptions.RequestException as e:

                st.error(
                    "No fue posible crear la vacante."
                )

                st.code(
                    str(e)
                )

# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.title(
        "🤖 AI Recruiter"
    )

    st.divider()

    st.subheader(
        "👤 Usuario"
    )

    st.write(
        st.session_state.user.get(
            "username",
            "Usuario"
        )
    )

    st.divider()

    st.subheader(
        "📋 Vacante seleccionada"
    )

    st.divider()

    if st.button(
        "🚪 Cerrar sesión",
        use_container_width=True
    ):
        logout()

# ============================================================
# LOAD JOBS
# ============================================================

try:

    jobs_response = api_get(
        "/jobs"
    )

except requests.exceptions.RequestException as e:

    st.error(
        "No fue posible obtener las vacantes."
    )

    st.code(
        str(e)
    )

    st.stop()


# ============================================================
# NORMALIZE JOBS
# ============================================================

jobs = jobs_response.get(
    "jobs",
    []
)


# ============================================================
# JOB SELECTOR
# ============================================================

selected_job_id = None


if jobs:

    job_options = {}

    for job in jobs:

        job_id = job.get(
            "job_id"
        )

        job_title = job.get(
            "title",
            "Vacante"
        )

        job_options[
            job_title
        ] = job_id


    selected_job_label = st.selectbox(
        "📋 Seleccionar vacante",
        list(
            job_options.keys()
        )
    )


    selected_job_id = job_options[
        selected_job_label
    ]

else:

    st.warning(
        "No hay vacantes disponibles. "
        "Crea una nueva vacante para comenzar."
    )

    st.info(
        "Puedes crear tu primera vacante desde "
        "la sección de creación de vacantes."
    )

    st.stop()

# ============================================================
# CREATE CANDIDATE
# ============================================================

with st.expander("👤 Agregar candidato"):

    candidate_name = st.text_input(
        "Nombre del candidato",
        placeholder="Ej: Adrian Felipe"
    )

    candidate_file = st.file_uploader(
        "CV del candidato",
        type=["pdf"],
        help="Sube el CV en formato PDF."
    )

    if st.button(
        "📤 Subir candidato",
        type="primary",
        use_container_width=True
    ):

        if not candidate_name.strip():

            st.warning(
                "Ingresa el nombre del candidato."
            )

        elif candidate_file is None:

            st.warning(
                "Selecciona un archivo PDF."
            )

        else:

            try:

                response = requests.post(
                    f"{API_URL}/candidates",
                    headers={
                        "Authorization": (
                            f"Bearer "
                            f"{st.session_state.access_token}"
                        )
                    },
                    data={
                        "name": candidate_name
                    },
                    files={
                        "file": (
                            candidate_file.name,
                            candidate_file.getvalue(),
                            "application/pdf"
                        )
                    },
                    timeout=120
                )

                if response.status_code != 200:

                    st.error(
                        f"Error al subir CV: "
                        f"{response.status_code}"
                    )

                    st.code(
                        response.text
                    )

                else:

                    data = response.json()

                    st.success(
                        "✅ CV subido correctamente."
                    )

                    candidate = data.get(
                        "candidate",
                        {}
                    )

                    st.write(
                        f"**Candidato:** "
                        f"{candidate.get('name', candidate_name)}"
                    )

                    st.write(
                        f"**ID:** "
                        f"`{candidate.get('id', 'N/A')}`"
                    )

                    st.info(
                        "El CV fue enviado a S3 y la "
                        "ingestión en Bedrock Knowledge "
                        "Base fue iniciada."
                    )

                    st.json(data)

            except requests.exceptions.Timeout:

                st.error(
                    "La subida tardó demasiado."
                )

            except requests.exceptions.RequestException as e:

                st.error(
                    "No fue posible conectarse con la API."
                )

                st.code(
                    str(e)
                )



# ============================================================
# LOAD JOB SUMMARY
# ============================================================

try:

    summary = api_get(
        f"/jobs/{selected_job_id}/summary"
    )


except requests.exceptions.RequestException as e:

    st.error(
        "No fue posible obtener el resumen de la vacante."
    )

    st.code(
        str(e)
    )

    st.stop()


job_title = summary.get(
    "job_title",
    "Vacante"
)

# ============================================================
# LOAD JOBS
# ============================================================

try:

    jobs_response = get_jobs()

except requests.exceptions.RequestException as e:

    st.error(
        "No fue posible obtener las vacantes."
    )

    st.code(
        str(e)
    )

    st.stop()


# ============================================================
# NORMALIZE JOBS RESPONSE
# ============================================================

if isinstance(jobs_response, dict):

    jobs = jobs_response.get(
        "jobs",
        []
    )

else:

    jobs = jobs_response


if not jobs:

    st.warning(
        "No hay vacantes disponibles."
    )

    st.stop()

# ============================================================
# HEADER
# ============================================================

st.title(
    f"📊 {job_title}"
)

st.caption(
    "AI-powered candidate screening"
)

st.divider()


# ============================================================
# SUMMARY METRICS
# ============================================================

col1, col2, col3, col4, col5 = st.columns(5)

with col1:

    st.metric(
        "Candidates",
        summary.get(
            "total_candidates",
            0
        )
    )

with col2:

    st.metric(
        "Evaluated",
        summary.get(
            "evaluated_candidates",
            0
        )
    )

with col3:

    st.metric(
        "Strong Matches",
        summary.get(
            "strong_matches",
            0
        )
    )

with col4:

    st.metric(
        "Average Score",
        summary.get(
            "average_score",
            0
        )
    )

with col5:

    st.metric(
        "Pending",
        summary.get(
            "pending_candidates",
            0
        )
    )


st.divider()


# ============================================================
# TOP CANDIDATE
# ============================================================

top_candidate = summary.get(
    "top_candidate"
)


if top_candidate:

    st.subheader(
        "🏆 Top Candidate"
    )

    col1, col2, col3 = st.columns(3)

    with col1:

        st.write(
            "**Candidate**"
        )

        st.write(
            top_candidate.get(
                "candidate_name",
                "Unknown"
            )
        )

    with col2:

        st.metric(
            "Match Score",
            top_candidate.get(
                "match_score",
                0
            )
        )

    with col3:

        recommendation = top_candidate.get(
            "recommendation",
            "LOW_MATCH"
        )

        if recommendation == "STRONG_MATCH":

            st.success(
                recommendation
            )

        elif recommendation == "PARTIAL_MATCH":

            st.warning(
                recommendation
            )

        else:

            st.error(
                recommendation
            )


st.divider()

# ============================================================
# FILTERS
# ============================================================

st.subheader(
    "🔎 Candidate Ranking"
)

col1, col2, col3 = st.columns(3)

with col1:

    min_score = st.number_input(
        "Minimum score",
        min_value=0,
        max_value=100,
        value=0,
        step=10
    )

with col2:

    recommendation_filter = st.selectbox(
        "Recommendation",
        [
            "ALL",
            "STRONG_MATCH",
            "PARTIAL_MATCH",
            "LOW_MATCH"
        ]
    )

with col3:

    page_size = st.selectbox(
        "Candidates per page",
        [5, 10, 20, 50],
        index=1
    )


# ============================================================
# PAGINATION STATE
# ============================================================

if "candidate_page" not in st.session_state:

    st.session_state.candidate_page = 1

# ============================================================
# RESET PAGINATION WHEN FILTERS CHANGE
# ============================================================

current_filter_state = (
    min_score,
    recommendation_filter,
    page_size
)

if (
    "candidate_filter_state"
    not in st.session_state
):

    st.session_state.candidate_filter_state = (
        current_filter_state
    )

elif (
    st.session_state.candidate_filter_state
    != current_filter_state
):

    st.session_state.candidate_filter_state = (
        current_filter_state
    )

    st.session_state.candidate_page = 1


# ============================================================
# LOAD CANDIDATES
# ============================================================

params = {
    "page": st.session_state.candidate_page,
    "page_size": page_size
}


if min_score > 0:

    params["min_score"] = min_score


if recommendation_filter != "ALL":

    params["recommendation"] = (
        recommendation_filter
    )


try:

    candidates_response = api_get(
        f"/jobs/{selected_job_id}/candidates",
        params=params
    )

    # ============================================================
    # PAGINATION INFO
    # ============================================================

    current_page = candidates_response.get(
        "page",
        1
    )

    total_pages = candidates_response.get(
        "total_pages",
        1
    )

    total_candidates = candidates_response.get(
        "total",
        0
    )

except requests.exceptions.RequestException as e:

    st.error(
        "No fue posible obtener los candidatos."
    )

    st.code(
        str(e)
    )

    st.stop()


candidates = candidates_response.get(
    "candidates",
    []
)

# ============================================================
# PAGINATION CONTROLS
# ============================================================

if total_pages > 1:

    st.divider()

    col1, col2, col3 = st.columns(
        [1, 2, 1]
    )

    with col1:

        if st.button(
            "⬅ Previous",
            disabled=current_page <= 1
        ):

            st.session_state.candidate_page = (
                current_page - 1
            )

            st.rerun()

    with col2:

        st.markdown(
            f"""
            <div style="text-align:center">
                <b>Page {current_page} of {total_pages}</b>
                <br>
                {total_candidates} candidates
            </div>
            """,
            unsafe_allow_html=True
        )

    with col3:

        if st.button(
            "Next ➡",
            disabled=current_page >= total_pages
        ):

            st.session_state.candidate_page = (
                current_page + 1
            )

            st.rerun()

# ============================================================
# PAGINATION INFO
# ============================================================

current_page = candidates_response.get(
    "page",
    1
)

total = candidates_response.get(
    "total",
    0
)

total_pages = candidates_response.get(
    "total_pages",
    1
)

if total > 0:

    start_item = (
        (current_page - 1)
        * page_size
        + 1
    )

    end_item = min(
        current_page * page_size,
        total
    )

    st.caption(
        f"Showing {start_item}–{end_item} "
        f"of {total} candidates"
    )

    col1, col2, col3 = st.columns(
        [1, 2, 1]
    )

    with col1:

        if st.button(
            "← Previous",
            disabled=current_page <= 1,
            key="previous_candidates"
        ):

            st.session_state.candidate_page = (
                current_page - 1
            )

            st.rerun()

    with col2:

        st.markdown(
            f"<div style='text-align:center;'>"
            f"Page {current_page} of {total_pages}"
            f"</div>",
            unsafe_allow_html=True
        )

    with col3:

        if st.button(
            "Next →",
            disabled=current_page >= total_pages,
            key="next_candidates"
        ):

            st.session_state.candidate_page = (
                current_page + 1
            )

            st.rerun()


# ============================================================
# EVALUATE ALL CANDIDATES
# ============================================================

st.divider()

st.subheader(
    "🤖 Evaluación de candidatos"
)

st.caption(
    "Evalúa todos los candidatos registrados "
    "contra la vacante seleccionada."
)

if st.button(
    "🚀 Evaluar todos los candidatos",
    type="primary",
    use_container_width=True,
    key="evaluate_all_candidates"
):

    # ========================================================
    # VALIDAR VACANTE
    # ========================================================

    if not selected_job_id:

        st.error(
            "Debes seleccionar una vacante antes de evaluar."
        )

    else:

        try:

            # =================================================
            # OBTENER CANDIDATOS
            # =================================================

            st.info(
                "Obteniendo candidatos..."
            )

            all_candidates_response = api_get(
                "/candidates"
            )

            all_candidates = (
                all_candidates_response.get(
                    "candidates",
                    []
                )
            )

            if not all_candidates:

                st.warning(
                    "No hay candidatos registrados."
                )

            else:

                st.info(
                    f"Se encontraron "
                    f"{len(all_candidates)} candidatos."
                )

                progress = st.progress(
                    0
                )

                status_text = st.empty()

                successful = 0
                failed = 0

                errors = []

                total_candidates = len(
                    all_candidates
                )

                # =============================================
                # EVALUAR CANDIDATOS
                # =============================================

                for index, candidate in enumerate(
                    all_candidates,
                    start=1
                ):

                    # IMPORTANTE:
                    # /candidates devuelve id/name
                    # en tu API actual.

                    candidate_id = candidate.get(
                        "candidate_id"
                    )

                    candidate_name = candidate.get(
                        "name",
                        "Unknown"
                    )

                    status_text.write(
                        f"**Evaluando {candidate_name}** "
                        f"({index}/{total_candidates})"
                    )

                    # =========================================
                    # VALIDAR ID
                    # =========================================

                    if not candidate_id:

                        failed += 1

                        errors.append(
                            f"{candidate_name}: "
                            "el candidato no tiene ID."
                        )

                        progress.progress(
                            index / total_candidates
                        )

                        continue

                    # =========================================
                    # LLAMAR EVALUATE-JOB
                    # =========================================

                    try:

                        response = requests.post(
                            f"{API_URL}/candidates/"
                            f"{candidate_id}/evaluate-job",

                            headers={
                                "Authorization": (
                                    f"Bearer "
                                    f"{st.session_state.access_token}"
                                ),
                                "Content-Type": (
                                    "application/json"
                                )
                            },

                            json={
                                "job_id": selected_job_id
                            },

                            timeout=180
                        )

                        # =====================================
                        # RESPUESTA
                        # =====================================

                        if response.status_code in (
                            200,
                            201
                        ):

                            successful += 1

                            st.success(
                                f"✅ {candidate_name} evaluado."
                            )

                        else:

                            failed += 1

                            error_message = (
                                f"{candidate_name}: "
                                f"HTTP {response.status_code} - "
                                f"{response.text}"
                            )

                            errors.append(
                                error_message
                            )

                            st.error(
                                error_message
                            )

                    except requests.exceptions.Timeout:

                        failed += 1

                        error_message = (
                            f"{candidate_name}: "
                            "timeout al evaluar."
                        )

                        errors.append(
                            error_message
                        )

                        st.error(
                            error_message
                        )

                    except requests.exceptions.RequestException as e:

                        failed += 1

                        error_message = (
                            f"{candidate_name}: "
                            f"{str(e)}"
                        )

                        errors.append(
                            error_message
                        )

                        st.error(
                            error_message
                        )

                    except Exception as e:

                        failed += 1

                        error_message = (
                            f"{candidate_name}: "
                            f"{str(e)}"
                        )

                        errors.append(
                            error_message
                        )

                        st.error(
                            error_message
                        )

                    progress.progress(
                        index / total_candidates
                    )

                # =============================================
                # FINALIZAR
                # =============================================

                status_text.empty()

                st.divider()

                st.subheader(
                    "📊 Resultado de evaluación"
                )

                st.write(
                    f"Total candidatos: "
                    f"**{total_candidates}**"
                )

                st.write(
                    f"Evaluados correctamente: "
                    f"**{successful}**"
                )

                st.write(
                    f"Con errores: "
                    f"**{failed}**"
                )

                if successful:

                    st.success(
                        f"✅ Se evaluaron "
                        f"{successful} candidatos "
                        f"correctamente."
                    )

                if failed:

                    st.warning(
                        f"⚠️ {failed} candidatos "
                        f"no pudieron ser evaluados."
                    )

                if errors:

                    with st.expander(
                        "🔎 Ver errores"
                    ):

                        for error in errors:

                            st.error(
                                error
                            )

                # =============================================
                # ACTUALIZAR
                # =============================================

                if successful:

                    st.info(
                        "Actualizando ranking..."
                    )

                    st.session_state.candidate_page = 1

                    st.rerun()

        except requests.exceptions.RequestException as e:

            st.error(
                "No fue posible obtener los candidatos."
            )

            st.code(
                str(e)
            )

        except Exception as e:

            st.error(
                "Ocurrió un error al evaluar los candidatos."
            )

            st.code(
                str(e)
            )

# ============================================================
# CANDIDATE TABLE
# ============================================================

if not candidates:

    st.info(
        "No hay candidatos que coincidan con los filtros."
    )

else:

    for candidate in candidates:

        candidate_id = candidate.get(
            "candidate_id"
        )

        candidate_name = candidate.get(
            "name",
            "Unknown"
        )

        match_score = candidate.get(
            "match_score",
            0
        )

        recommendation = candidate.get(
            "recommendation",
            "LOW_MATCH"
        )

        strengths = candidate.get(
            "strengths",
            []
        )

        gaps = candidate.get(
            "gaps",
            []
        )

        with st.container(
            border=True
        ):

            col1, col2, col3, col4 = st.columns(
                [3, 1, 2, 1]
            )

            with col1:

                st.write(
                    f"### #{candidate.get('rank', '-')}"
                    f" {candidate_name}"
                )

            with col2:

                st.metric(
                    "Score",
                    match_score
                )

            with col3:

                if recommendation == "STRONG_MATCH":

                    st.success(
                        recommendation
                    )

                elif recommendation == "PARTIAL_MATCH":

                    st.warning(
                        recommendation
                    )

                else:

                    st.error(
                        recommendation
                    )

            with col4:

                if st.button(
                    "View",
                    key=f"view_{candidate_id}"
                ):

                    st.session_state.selected_candidate_id = (
                        candidate_id
                    )

            col1, col2 = st.columns(2)

            with col1:

                st.write(
                    "**Strengths**"
                )

                if strengths:

                    for strength in strengths:

                        st.write(
                            f"✅ {strength}"
                        )

                else:

                    st.write(
                        "No strengths available."
                    )

            with col2:

                st.write(
                    "**Gaps**"
                )

                if gaps:

                    for gap in gaps:

                        st.write(
                            f"⚠️ {gap}"
                        )

                else:

                    st.write(
                        "No major gaps."
                    )


# ============================================================
# SELECTED CANDIDATE
# ============================================================

selected_candidate_id = (
    st.session_state.selected_candidate_id
)


if selected_candidate_id:

    st.divider()

    st.header(
        "👤 Candidate Details"
    )

    try:

        candidate_detail = api_get(
            f"/jobs/{selected_job_id}/candidates/"
            f"{selected_candidate_id}"
        )

        explanation = api_get(
            f"/jobs/{selected_job_id}/candidates/"
            f"{selected_candidate_id}/explanation"
        )

        requirements = api_get(
            f"/jobs/{selected_job_id}/candidates/"
            f"{selected_candidate_id}/requirements"
        )

    except requests.exceptions.RequestException as e:

        st.error(
            "No fue posible cargar el detalle del candidato."
        )

        st.code(
            str(e)
        )

        st.stop()


    # ========================================================
    # CANDIDATE HEADER
    # ========================================================

    col1, col2, col3 = st.columns(3)

    with col1:

        st.subheader(
            candidate_detail.get(
                "candidate_name",
                "Unknown"
            )
        )

    with col2:

        st.metric(
            "Match Score",
            candidate_detail.get(
                "match_score",
                0
            )
        )

    with col3:

        recommendation = candidate_detail.get(
            "recommendation",
            "LOW_MATCH"
        )

        if recommendation == "STRONG_MATCH":

            st.success(
                recommendation
            )

        elif recommendation == "PARTIAL_MATCH":

            st.warning(
                recommendation
            )

        else:

            st.error(
                recommendation
            )


    # ========================================================
    # TABS
    # ========================================================

    tab1, tab2, tab3 = st.tabs(
        [
            "📋 Requirements",
            "🧠 Explanation",
            "📊 Raw Data"
        ]
    )


    # ========================================================
    # REQUIREMENTS
    # ========================================================

    with tab1:

        requirement_list = requirements.get(
            "requirements",
            []
        )

        for requirement in requirement_list:

            status = requirement.get(
                "status",
                "UNKNOWN"
            )

            name = requirement.get(
                "requirement",
                "Unknown"
            )

            evidence = requirement.get(
                "evidence"
            ) or "No se encontró evidencia suficiente en el CV."

            if status == "MATCH":

                st.success(
                    f"✅ {name}"
                )

            elif status == "PARTIAL":

                st.warning(
                    f"⚠️ {name}"
                )

            else:

                st.error(
                    f"❌ {name}"
                )

            st.caption(
                evidence
            )


    # ========================================================
    # EXPLANATION
    # ========================================================

    with tab2:

        st.subheader(
            "Why this candidate?"
        )

        st.write(
            explanation.get(
                "explanation",
                "No explanation available."
            )
        )

        st.divider()

        st.write(
            "**Key Strengths**"
        )

        for strength in explanation.get(
            "key_strengths",
            []
        ):

            st.write(
                f"✅ {strength}"
            )

        st.write(
            "**Main Gaps**"
        )

        for gap in explanation.get(
            "main_gaps",
            []
        ):

            st.write(
                f"⚠️ {gap}"
            )

        st.divider()

        st.info(
            explanation.get(
                "summary",
                ""
            )
        )


    # ========================================================
    # RAW DATA
    # ========================================================

    with tab3:

        st.json(
            candidate_detail
        )


    # ========================================================
    # CLOSE
    # ========================================================

    if st.button(
        "✖ Close candidate"
    ):

        st.session_state.selected_candidate_id = None

        st.rerun()
import requests
import streamlit as st
import streamlit.components.v1 as components
import base64
import datetime

# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://vb9uu61dt6.execute-api.us-east-2.amazonaws.com/prod/chat"

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="AI CV Recruiter",
    page_icon="🤖",
    layout="wide"
)

# Custom CSS for nicer UI
st.markdown(
    """
    <style>
    :root {
      --accent:#6C63FF;
      --muted:#6b7280;
      --card:#ffffff;
      --bg:#f6f7fb;
    }
    .stApp { background: var(--bg); }
    .header {
      display:flex; align-items:center; gap:12px;
    }
    .title { font-size:28px; font-weight:700; }
    .subtitle { color:var(--muted); margin-top:-6px; }
    .chat-box { background:var(--card); padding:16px; border-radius:12px; box-shadow: 0 4px 14px rgba(30,41,59,0.06); }
    .user-msg { background:#eef2ff; padding:10px 12px; border-radius:10px; }
    .assistant-msg { background:#f8fafc; padding:12px; border-radius:10px; }
    .small { color:var(--muted); font-size:12px }
    .source { background:#fff; padding:8px; border-radius:8px; border:1px solid #eef2ff; }
    .logo { height:48px; width:48px; border-radius:8px; background:linear-gradient(135deg,var(--accent),#9b8cff); display:flex; align-items:center; justify-content:center; color:white; font-weight:700 }
    </style>
    """,
    unsafe_allow_html=True
)

# ============================================================
# HEADER
# ============================================================

col1, col2 = st.columns([0.12, 0.88])
with col1:
    st.markdown('<div class="logo">AI</div>', unsafe_allow_html=True)
with col2:
    st.markdown('<div class="header"><div class="title">AI CV Recruiter</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Analiza y resume CVs con Bedrock + RAG — bonito y funcional</div>', unsafe_allow_html=True)

st.divider()

# ============================================================
# SESSION STATE
# ============================================================

if "messages" not in st.session_state:
    st.session_state.messages = []

if "uploaded_file" not in st.session_state:
    st.session_state.uploaded_file = None

# ============================================================
# LAYOUT: Main + Right panel
# ============================================================

main, right = st.columns([2, 1])

with main:
    st.markdown('<div class="chat-box">', unsafe_allow_html=True)

    # Chat history display with nicer bubbles
    for i, message in enumerate(st.session_state.messages):
        role = message.get('role')
        content = message.get('content')
        timestamp = message.get('time', '')
        if role == 'user':
            st.markdown(f"<div class='user-msg'><strong>Tú:</strong> {content}</div>", unsafe_allow_html=True)
            st.write('')
        else:
            st.markdown(f"<div class='assistant-msg'><strong>AI:</strong> {content}</div>", unsafe_allow_html=True)
            # copy + download buttons
            cols = st.columns([0.1,0.1,0.8])
            with cols[0]:
                # Copy button using component
                comp_html = f"""
                <button onclick="navigator.clipboard.writeText(`{content.replace('`','\\`')}`)">📋 Copiar</button>
                """
                components.html(comp_html, height=35)
            with cols[1]:
                st.download_button('⬇️', content, file_name=f'answer_{i}.txt')
            with cols[2]:
                st.write('')
            st.write('')

    st.markdown('</div>', unsafe_allow_html=True)

    # Input area
    with st.form('ask_form', clear_on_submit=True):
        question = st.text_input('Pregunta algo sobre el candidato...', '')
        submitted = st.form_submit_button('Enviar')

    if submitted and question:
        # Save user message
        st.session_state.messages.append({'role':'user','content':question,'time':str(datetime.datetime.utcnow())})
        # show immediate user message
        st.experimental_rerun()

    # If last message is user and not answered, call API
    if st.session_state.messages and st.session_state.messages[-1]['role'] == 'user':
        last = st.session_state.messages[-1]
        # Check if it already has an assistant reply after it
        if len(st.session_state.messages) < 2 or st.session_state.messages[-2]['role'] != 'assistant' or st.session_state.messages[-2].get('in_reply_to') != last.get('time'):
            with st.spinner('Analizando el CV...'):
                try:
                    response = requests.post(API_URL, json={'question': last['content']}, timeout=60)
                    if response.status_code != 200:
                        st.error(f'API Error: {response.status_code}')
                        st.code(response.text)
                    else:
                        data = response.json()
                        answer = data.get('answer', 'No se recibió respuesta')
                        sources = data.get('sources', [])
                        st.session_state.messages.append({'role':'assistant','content':answer,'time':str(datetime.datetime.utcnow()),'sources':sources,'in_reply_to': last.get('time')})
                        st.experimental_rerun()
                except Exception as e:
                    st.error('Error conectando con la API.')
                    st.code(str(e))

with right:
    st.header('📄 Candidate CV')
    st.info('Sube el CV para usarlo en las búsquedas. (S3 backend opcional)')

    uploaded = st.file_uploader('Subir CV (pdf, txt, docx)', type=['pdf','txt','docx'])
    if uploaded is not None:
        st.session_state.uploaded_file = uploaded
        st.success(f'Archivo cargado: {uploaded.name} ({uploaded.size} bytes)')
        # Preview first bytes
        try:
            raw = uploaded.getvalue()
            preview = raw[:4000]
            try:
                txt = preview.decode('utf-8', errors='ignore')
                st.text_area('Preview', txt[:2000], height=200)
            except Exception:
                st.write('Preview no disponible para este tipo de archivo.')
        except Exception:
            st.write('No fue posible leer el archivo.')

    st.divider()
    st.subheader('Settings')
    st.caption('Opciones rápidas')
    api_region = st.text_input('AWS Region', value='us-east-2')
    st.button('Guardar ajustes')

    st.divider()
    st.subheader('Architecture')
    st.markdown('''
    - Streamlit (Frontend)
    - API Gateway → Lambda (Backend)
    - Bedrock KB + S3 (RAG)
    ''')

    st.divider()

    if st.button('🗑️ Limpiar conversación'):
        st.session_state.messages = []
        st.experimental_rerun()

# Footnote / help
st.markdown('''
---
Consejos:
- Usa el uploader para adjuntar CVs.
- Copia o descarga respuestas con los botones.
- Para integrar upload a S3 o a la KB, añade un endpoint backend /upload.
''')

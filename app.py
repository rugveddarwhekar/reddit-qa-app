import streamlit as st
from langchain.document_loaders import JSONLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.vectorstores import Chroma
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from reddit_data_download import get_reddit_data
import os
from dotenv import load_dotenv
import asyncio
import logging
import time
import json
import hashlib

load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Reddit Android Beta Analyzer",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for Premium UI ---
st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
    }
    h1 {
        font-family: 'Inter', sans-serif;
        background: -webkit-linear-gradient(45deg, #4285F4, #9B72CB);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
    }
    h2, h3 {
        font-family: 'Inter', sans-serif;
        color: #E0E0E0;
    }
    .stButton>button {
        background: linear-gradient(90deg, #4285F4 0%, #9B72CB 100%);
        color: white;
        border: none;
        padding: 0.5rem 1rem;
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(66, 133, 244, 0.3);
    }
    .metric-card {
        background-color: #262730;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #464855;
    }
    </style>
    """, unsafe_allow_html=True)

# --- Configure Logging ---
LOG_FILE = "streamlit_app.log"
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# --- Constants ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DATA_DIR = "data"
CHROMA_DB_DIR = "chroma_db"
DEFAULT_FLAIRS = ["Android 15 QPR1 Beta 1", "Android 15 QPR1 Beta 2", "Android 15 QPR1 Beta 3", "Android 16 DP1", "Android 16 DP2", "Android 16 Beta 1", "Android 16 Beta 2"]
TIME_FILTERS = ["hour", "day", "week", "month", "year", "all"]

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CHROMA_DB_DIR, exist_ok=True)


def process_reddit_data(reddit_data, identifier):
    """Processes the fetched Reddit data and creates the vector store."""
    try:
        temp_file_path = os.path.join(DATA_DIR, f"temp_{hashlib.sha256(identifier.encode('utf-8')).hexdigest()}.json")
        with open(temp_file_path, "w") as f:
            json.dump(reddit_data, f)

        loader = JSONLoader(file_path=temp_file_path, jq_schema='.', text_content=False)
        data = loader.load()
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        documents = text_splitter.split_documents(data)
        embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=GOOGLE_API_KEY)

        # --- Use Hashing for Collection Name ---
        hash_object = hashlib.sha256(identifier.encode('utf-8'))
        hex_dig = hash_object.hexdigest()
        collection_name = f"reddit_{hex_dig[:56]}"

        vectordb = Chroma.from_documents(
            documents,
            embeddings,
            persist_directory=CHROMA_DB_DIR,
            collection_name=collection_name,
        )
        vectordb.persist()
        return vectordb

    except Exception as e:
        logger.exception(f"Error in process_reddit_data: {e}")
        st.error(f"An error occurred during data processing: {e}")
        return None


def create_qa_chain(vectordb):
    """Creates a RetrievalQA chain."""
    if vectordb is None:
        return None

    try:
        model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=GOOGLE_API_KEY,
            temperature=0.2,
            max_retries=6,
        )
        template = """You are a helpful Android Feedback Assistant. Use the following user comments to answer the question. 
If the answer is not in the context, state that clearly.
Context provided:
{context}

Question: {question}
Answer:"""
        QA_CHAIN_PROMPT = PromptTemplate.from_template(template)

        qa_chain = RetrievalQA.from_chain_type(
            model,
            retriever=vectordb.as_retriever(search_kwargs={"k": 5}),
            return_source_documents=True,
            chain_type_kwargs={"prompt": QA_CHAIN_PROMPT},
        )
        return qa_chain
    except Exception as e:
        logger.exception(f"Error in create_qa_chain: {e}")
        st.error(f"Failed to create QA chain: {e}")
        return None

# --- Session State Initialization ---
if "qa_chain" not in st.session_state:
    st.session_state.qa_chain = None
if "vectordb" not in st.session_state:
    st.session_state.vectordb = None
if "gemini_request_count" not in st.session_state:
    st.session_state.gemini_request_count = 0
if "last_response" not in st.session_state:
    st.session_state.last_response = None
if "last_question" not in st.session_state:
    st.session_state.last_question = ""

# --- Sidebar Configuration ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/3/3e/Android_robot_head.svg/260px-Android_robot_head.svg.png", width=50)
    st.title("Configuration")
    
    st.subheader("Data Source")
    data_source = st.selectbox("Select Source Type:", ["Flair", "Post URL", "Keywords + Time"])

    identifier = None
    data_type = None
    time_filter = None

    if data_source == "Flair":
        selected_flair = st.selectbox("Choose Flair:", options=DEFAULT_FLAIRS + ["Other"])
        if selected_flair == "Other":
            identifier = st.text_input("Enter Custom Flair:")
        else:
            identifier = selected_flair
        data_type = "flair"

    elif data_source == "Post URL":
        identifier = st.text_input("Paste Post URL:")
        data_type = "url"

    elif data_source == "Keywords + Time":
        identifier = st.text_input("Enter Keywords (comma-sep):")
        time_filter = st.selectbox("Time Filter:", options=TIME_FILTERS)
        data_type = "keywords"

    st.markdown("---")
    
    # Load Data Button
    if st.button("🔄 Load & Process Data", use_container_width=True):
        if identifier:
             with st.spinner("Fetching discussions from Reddit..."):
                reddit_data = asyncio.run(get_reddit_data(data_type, identifier, time_filter, DATA_DIR))
                if reddit_data:
                    st.success(f"Fetched {len(reddit_data)} threads.")
                    with st.spinner("Embedding data into Vector Store..."):
                        vectordb = process_reddit_data(reddit_data, identifier)
                        st.session_state.vectordb = vectordb
                        st.session_state.qa_chain = create_qa_chain(vectordb)
                        st.session_state.last_response = None # Reset chat on new data
                        st.success("✅ System Ready!")
                else:
                    st.error("No data found.")
        else:
            st.warning("Please enter valid input.")

    st.markdown("---")
    st.markdown("### 📊 API Usage")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Requests", st.session_state.gemini_request_count)
    with col2:
        st.metric("Status", "Active" if st.session_state.qa_chain else "Idle")

# --- Main Interaction Area ---
st.title("Reddit Android Feedback Analyzer")
st.markdown("Ask natural language questions about the gathered community feedback.")

if st.session_state.qa_chain is None:
    st.info("👈 Please configure the data source in the sidebar and click **Load & Process Data** to begin.")
    st.stop()

# Q&A Interface
question = st.text_area("What would you like to know?", height=100, placeholder="e.g., Is the battery life better in this beta?")

col_ask, col_clear = st.columns([1, 5])
with col_ask:
    ask_button = st.button("✨ Ask Gemini", type="primary")

# Logic to prevent accidental calls:
# Only run if button is clicked OR if we have a stored response and the question hasn't changed meaningfully (to persist view on reruns)
if ask_button and question:
    if question.strip() == "":
        st.warning("Please type a question.")
    else:
        with st.spinner("Analyzing community sentiment..."):
            try:
                st.session_state.gemini_request_count += 1
                logger.info(f"Gemini API request: {question}")
                
                # Invoke Chain
                result = st.session_state.qa_chain.invoke({"query": question})
                
                # Store in session state
                st.session_state.last_response = result
                st.session_state.last_question = question
                
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                logger.exception(e)

# Display Result (Persisted)
if st.session_state.last_response:
    st.markdown("### 🤖 Insight")
    st.markdown(f"<div style='background-color: #1E1E1E; padding: 20px; border-radius: 10px; border-left: 5px solid #4285F4;'>{st.session_state.last_response['result']}</div>", unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("📚 View Source Comments"):
        for i, doc in enumerate(st.session_state.last_response['source_documents']):
            st.markdown(f"**Source {i+1}:**")
            st.info(doc.page_content)
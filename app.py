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

# --- Configure Logging ---
LOG_FILE = "streamlit_app.log"
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)

# --- Constants and Configuration ---
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
        # --- End Hashing ---

        vectordb = Chroma.from_documents(
            documents,
            embeddings,
            persist_directory=CHROMA_DB_DIR,
            collection_name=collection_name,
        )
        vectordb.persist()
        # os.remove(temp_file_path)  # Clean up the temporary file.
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
        template = """Use the following pieces of context to answer the question at the end. If you don't know the answer, just mention that you we do not have sufficient data for answering the question and do no try to make up an answer and mention that we may support it in the future. This is a collection of public user comments about the latest Android beta version. Users like to share the feedback in online forums and this is the data.
{context}
Question: {question}
Answer:"""
        QA_CHAIN_PROMPT = PromptTemplate.from_template(template)

        qa_chain = RetrievalQA.from_chain_type(
            model,
            retriever=vectordb.as_retriever(search_kwargs={"k": 2}),
            return_source_documents=True,
            chain_type_kwargs={"prompt": QA_CHAIN_PROMPT},
        )
        return qa_chain
    except Exception as e:
        logger.exception(f"Error in create_qa_chain: {e}")
        st.error(f"Failed to create QA chain: {e}")
        return None

# --- Streamlit App ---
st.title("Reddit Android Beta Feedback Analyzer")

data_source = st.selectbox("Select Data Source:", ["Flair", "Post URL", "Keywords + Time"])

if data_source == "Flair":
    selected_flair = st.selectbox("Select a Flair:", options=DEFAULT_FLAIRS + ["Other"])
    identifier = custom_flair if (selected_flair == "Other" and (custom_flair := st.text_input("Enter Custom Flair:"))) else selected_flair
    data_type = "flair"
    time_filter = None

elif data_source == "Post URL":
    identifier = st.text_input("Enter Post URL:")
    data_type = "url"
    time_filter = None

elif data_source == "Keywords + Time":
    identifier = st.text_input("Enter Keywords (comma-separated):")
    time_filter = st.selectbox("Select Time Filter:", options=TIME_FILTERS)
    data_type = "keywords"

else: #Default option
    identifier = None
    data_type = None
    time_filter = None

# Initialize session state
if "qa_chain" not in st.session_state:
    st.session_state.qa_chain = None
if "vectordb" not in st.session_state:
    st.session_state.vectordb = None
if "gemini_request_count" not in st.session_state:
    st.session_state.gemini_request_count = 0
if "gemini_success_count" not in st.session_state:
    st.session_state.gemini_success_count = 0
if "gemini_failure_count" not in st.session_state:
    st.session_state.gemini_failure_count = 0
if "current_identifier" not in st.session_state:
    st.session_state.current_identifier = None

# Load data and create QA chain
if st.button("Load Data and Initialize"):
    if identifier:
        if st.session_state.current_identifier != (data_type, identifier, time_filter):
            with st.spinner("Loading and processing data..."):
                reddit_data = asyncio.run(get_reddit_data(data_type, identifier, time_filter, DATA_DIR))
                if reddit_data:
                    st.session_state.vectordb = process_reddit_data(reddit_data, identifier)
                    st.session_state.qa_chain = create_qa_chain(st.session_state.vectordb)
                    st.session_state.current_identifier = (data_type, identifier, time_filter)
                    st.success("Data loaded and initialized successfully!")
                else:
                    st.error("Failed to fetch Reddit data.")
        else:
             st.info("Data already loaded for this input.")
    else:
        st.warning("Please provide input for the selected data source.")

# User input and Q&A
question = st.text_input("Ask a question about Android Beta feedback:")
show_sources = st.checkbox("Show source documents")

if question and st.session_state.qa_chain:
    with st.spinner("Generating answer..."):
        try:
            st.session_state.gemini_request_count += 1
            logger.info(f"Gemini API request: {question}")
            result = st.session_state.qa_chain.invoke({"query": question})
            st.session_state.gemini_success_count += 1
            st.write(result["result"])
            logger.info(f"Gemini API response: {result['result']}")
            if show_sources:
                with st.expander("Source Documents"):
                    for doc in result["source_documents"]:
                        st.write(doc.page_content)
        except Exception as e:
            st.session_state.gemini_failure_count += 1
            logger.exception(f"Error during Gemini API call: {e}")
            st.error(f"An error occurred: {e}")

elif question:
    st.warning("Please load data and initialize the QA chain first.")

# Display metrics
st.write(f"Gemini API Requests: {st.session_state.gemini_request_count}")
st.write(f"Successful Responses: {st.session_state.gemini_success_count}")
st.write(f"Failed Responses: {st.session_state.gemini_failure_count}")
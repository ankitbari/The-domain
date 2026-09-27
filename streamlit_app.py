"""AI Product Hunter Automation - Streamlit frontend.

Phase 2: minimal UI that submits a niche to the FastAPI backend's /hunt
endpoint and renders the JSON response.
"""

import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("BACKEND_API_URL") or "http://127.0.0.1:8000"
READ_TIMEOUT = int(os.getenv("BACKEND_READ_TIMEOUT", "600"))
REQUEST_TIMEOUT = (10, READ_TIMEOUT)

st.set_page_config(
    page_title="AI Product Hunter Automation",
    layout="wide",
)

st.title("AI Product Hunter Automation")

niche = st.text_input("Enter a product niche:", value="pet gadgets")

if st.button("Hunt Products", type="primary"):
    try:
        response = requests.post(
            f"{API_URL}/hunt",
            json={"niche": niche},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        st.json(response.json())
    except requests.exceptions.RequestException as error:
        st.error(f"Failed to connect to the backend: {error}")
        st.info(f"Make sure the FastAPI backend is running at {API_URL}.")

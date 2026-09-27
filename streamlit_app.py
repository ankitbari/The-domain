"""AI Product Hunter Automation - Streamlit frontend.

Submits a niche to the FastAPI backend's /hunt endpoint. Phase 4: shows a
live status while Decodo discovery scraping runs, then renders the result
with the raw discovery JSON behind an expander.
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
        with st.status("Scraping discovery sources with Decodo...", expanded=True) as status:
            response = requests.post(
                f"{API_URL}/hunt",
                json={"niche": niche},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            status.update(label="Discovery scraping complete", state="complete")
        st.json(data)

        with st.expander("Raw Discovery JSON"):
            st.json(data.get("discovery_data", []))
    except requests.exceptions.RequestException as error:
        st.error(f"Failed to connect to the backend: {error}")
        st.info(f"Make sure the FastAPI backend is running at {API_URL}.")

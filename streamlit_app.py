"""AI Product Hunter Automation - Streamlit frontend.

Submits a niche to the FastAPI backend's /hunt endpoint. Phase 5: shows a
compact initial ranking table built from the backend's locally scored,
deduplicated product candidates. Screening and supplier stages arrive in
later phases.
"""

import os

import pandas as pd
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
        with st.status("Scraping and normalizing discovery sources...", expanded=True) as status:
            response = requests.post(
                f"{API_URL}/hunt",
                json={"niche": niche},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            status.update(label="Discovery complete", state="complete")

        products = data.get("initial_products", [])
        if not products:
            st.info("No product candidates were extracted from the discovery sources.")
        else:
            st.subheader(f"Initial Ranking ({len(products)} candidates)")
            table = pd.DataFrame(
                [
                    {
                        "Score": product.get("viral_score"),
                        "Product": product.get("product"),
                        "Price": product.get("price"),
                        "Currency": product.get("currency"),
                        "Rating": product.get("rating"),
                        "Reviews": product.get("reviews"),
                        "Sales": product.get("sales"),
                        "Sources": ", ".join(product.get("source", [])),
                    }
                    for product in products
                ]
            )
            st.dataframe(table, use_container_width=True, hide_index=True)
    except requests.exceptions.RequestException as error:
        st.error(f"Failed to connect to the backend: {error}")
        st.info(f"Make sure the FastAPI backend is running at {API_URL}.")

# AI Product Hunter Automation

A FastAPI + Streamlit automation system for dropshipping product discovery,
real-time safety/quality screening, and supplier-aware ranking.

Given a niche, the system discovers candidate products from Google, Amazon,
Reddit, TikTok Shop, and YouTube signals (via the Decodo scraping API),
screens every candidate locally with Laya (a fast typed-decision model) to
reject unsafe, prohibited, or non-product noise before any expensive
generative call, ranks the survivors for viral and commercial potential with
an LLM, validates suppliers with live Alibaba/AliExpress offers, and produces
a final, supplier-aware shortlist you can act on immediately.

## Setup

Create the virtual environment (requires [uv](https://docs.astral.sh/uv/)):

```bash
uv venv ai-product-hunter-automation
```

Activate it:

- macOS/Linux:

  ```bash
  source ai-product-hunter-automation/bin/activate
  ```

- Windows:

  ```bat
  ai-product-hunter-automation\Scripts\activate
  ```

Install dependencies:

```bash
uv pip install -r requirements.txt
```

Configure the environment (fill in your API keys — never commit real
credentials):

```bash
cp .env.example .env
```

## Running

Start the FastAPI backend:

```bash
uv run api.py
# or
python api.py
```

- API URL: `http://127.0.0.1:8000`
- Interactive docs: `http://127.0.0.1:8000/docs`

Start the Streamlit frontend (in a second terminal, with the backend running):

```bash
uv run streamlit run streamlit_app.py
```

- Streamlit URL: `http://localhost:8501`

## Notes

- The first run downloads the Laya model weights from Hugging Face Hub
  (a few hundred MB) and needs internet access once; after that it runs
  fully offline and in-process.
- No database, queues, authentication, or persistent sessions: each request
  runs the pipeline fresh and returns a complete, self-contained result.

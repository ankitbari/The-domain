# CLAUDE.md — AI Product Hunter Automation

This file is read automatically by Claude Code at the start of every
session and is the authoritative index for this repository's build spec.
Build the system described here from scratch. If the repo is already
partially built, inspect it first and resume from the first incomplete
phase — do not redo finished work.

**How to use this file:** the full instructions for each build phase live
in separate files under `.claude/phases/`, not in this file. Before starting
a phase, read that phase's file (see the index below). Read one phase file
at a time — don't preload the others into context. This keeps each session
focused and keeps this index file itself small and fast to load.

## Purpose

**AI Product Hunter Automation** is a product-research automation system for
dropshipping operators. Given a niche, it autonomously:

1. **Discovers** candidate products from Google, Amazon, Reddit, TikTok
   Shop, and YouTube signals via the Decodo scraping API.
2. **Screens** every candidate in milliseconds with Laya, a local typed-decision
   model, rejecting unsafe, prohibited, or non-product noise before any
   expensive generative call is made.
3. **Ranks** the surviving candidates for viral and commercial potential
   using an LLM (Sarvam AI, with OpenAI and a generic provider as fallbacks),
   grounded in local, evidence-based scoring.
4. **Validates suppliers** for the top candidates by sourcing live Alibaba
   and AliExpress offers, screening each listing for credibility and
   counterfeit risk with Laya.
5. **Produces a final, supplier-aware shortlist** — ranked, priced, sourced,
   and safety-gated — that a dropshipper can act on immediately.

## Engineering principles

These principles govern every phase and should resolve any ambiguity a
phase file doesn't cover:

- **Resilience over completeness.** A single failed scrape, provider outage,
  or malformed marketplace page must never crash the pipeline. Isolate
  failures per source/offer/provider and surface them as structured warnings
  instead.
- **Deterministic fallback, always.** Every stage that depends on an external
  LLM must have a local, evidence-based fallback that produces a usable
  result with no network access at all.
- **Cheap gates before expensive calls.** Laya's local, millisecond-scale
  screening always runs before a candidate or listing is sent to a paid,
  slower generative model — never after, and never as a replacement for it.
- **Safety cannot be silently bypassed.** The Laya policy gate in Phase 9
  applies uniformly regardless of which ranking method (AI or deterministic)
  produced a score, and a missing signal is treated as "unknown," never as
  an automatic pass or an automatic block.
- **No hidden state.** No database, no queues, no persistent sessions — each
  request runs the pipeline fresh and returns a complete, self-contained
  result.
- **Minimal footprint.** No authentication, Docker, deployment tooling,
  frontend framework, or abstraction layer beyond what a phase explicitly
  calls for.

## Architecture

- Python, FastAPI backend + Streamlit frontend. Keep application logic in
  `api.py` and `streamlit_app.py` — Laya's helper functions live in `api.py`
  alongside the rest of the pipeline, not in a separate module, unless the
  file becomes genuinely unwieldy.
- FastAPI runs at `http://127.0.0.1:8000`; Streamlit talks to that same URL.
- No database, no authentication, no queues, no Docker, no deployment files,
  no frontend framework, no unnecessary abstractions.
- Laya runs fully in-process on local weights (downloaded once from Hugging
  Face Hub on first use). It makes no outbound API calls and needs no API
  key. It must never replace the generative ranking step — only pre-filter
  candidates before it, add calibrated signals alongside it, and apply a
  final independent safety gate after it.

### Key project structure

- `api.py` — FastAPI backend: discovery, the Laya gate, AI ranking, supplier
  sourcing, final ranking, and the full workflow.
- `streamlit_app.py` — Streamlit UI that stages requests for discovery,
  screening, and sourcing.
- `test_api.py` — unit tests covering discovery, the Laya gate, ranking,
  supplier flow, and edge cases.
- `README.md` — startup, environment, and usage documentation.
- `.claude/phases/` — the detailed, phase-by-phase build instructions this
  file indexes.

## Build phases

Work through these in order. Each row links to the file with full
instructions for that phase — open it when you start that phase.

| Phase | File | What it builds |
|---|---|---|
| 1 | `.claude/phases/phase-1-project-setup.md` | venv, `requirements.txt`, `.env.example`, `README.md` skeleton |
| 2 | `.claude/phases/phase-2-fastapi-streamlit-app.md` | first working FastAPI + Streamlit app, `/health`, placeholder `/hunt` |
| 3 | `.claude/phases/phase-3-discovery-sources.md` | `build_source_urls`: the ten Decodo source payloads |
| 4 | `.claude/phases/phase-4-decodo-scraping.md` | real concurrent Decodo scraping with per-source failure isolation |
| 5 | `.claude/phases/phase-5-normalize-extraction.md` | response compaction, product extraction, dedup, local viral score |
| 6 | `.claude/phases/phase-6-laya-guardrail.md` | the Laya fast-decision gate that screens candidates before any LLM call |
| 7 | `.claude/phases/phase-7-sarvam-ranking.md` | AI ranking via Sarvam AI, with OpenAI and a generic fallback |
| 8 | `.claude/phases/phase-8-supplier-sourcing.md` | Alibaba/AliExpress sourcing + Laya supplier-credibility screening |
| 9 | `.claude/phases/phase-9-final-ranking-ui-docs.md` | final supplier-aware ranking, Laya safety gate, staged API, UI, tests, README |

Each phase file assumes you've already read this index (Purpose,
Engineering principles, Architecture) — it doesn't repeat that context.

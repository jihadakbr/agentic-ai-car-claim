# Agentic AI Car Insurance Claim Assessment

An end-to-end car insurance claim system where a field surveyor uploads damage photos and the vehicle registration document, and the system returns a costed, auditable recommendation. Computer vision finds which parts are damaged and how badly, a rules-based cost engine prices the repair, and the total is compared against the Indonesian regulatory threshold for a total loss. An adjuster always makes the final approve, reject, or send-back call.

## Overview

The pipeline runs 14 stages end to end, of which 2 are genuinely agentic. The assessment agent decides for itself whether the evidence is sufficient, and can hold the claim to request a specific photo from the surveyor before it commits to a recommendation. The pricing agent reaches out to the open web when a vehicle is missing from the price catalogue. Three further stages call an LLM once with a fixed output shape, and the remaining nine are computer vision, fixed rules, and arithmetic that return the same result every time they see the same input.

A claim moves through the system like this. The surveyor submits damage photos, one registration document photo, and a policy number. Photos are normalised, fingerprinted, and screened per photo for blur and for whether a vehicle is present at all. OCR reads the registration document, and the vehicle and policy rows are looked up from that document rather than from anything the surveyor typed. Two segmentation models mark car parts and damage areas, and the masks are overlapped to compute damaged area ratio per part. Seven validity checks run, each recording its own pass or fail reason. The used market value is resolved, with the pricing agent searching the web only when the catalogue has no answer. The cost engine decides replace or repair per part, prices parts and labour, and computes the total loss ratio. The assessment agent then either holds the claim with a specific photo request or issues a recommendation. Finally the adjuster reviews the reasoning, corrects any wrong detection, confirms the market value, and approves, rejects, or sends the claim back. An approved repair issues a work order to the partner workshop, a total loss issues a vehicle purchase offer, both as generated PDFs, and every stage is written to an append-only audit log.

## Demo

[![Live App](https://img.shields.io/badge/Live-App-000000?logo=vercel)](https://agentic-ai-car-claim.vercel.app)

<!-- [![YouTube Demo](https://img.shields.io/badge/YouTube-Demo-red?logo=youtube)](https://youtu.be/) -->

[![Kaggle Training](https://img.shields.io/badge/Kaggle-Training-20BEFF?logo=kaggle)](https://www.kaggle.com/code/jihadakbr/car-claim-detection)

## Key Features

- **Every component named for what it actually is**: 2 agents that choose their own next step, 3 single-call LLM steps, and 9 deterministic steps.
- **Regulatory grounding**: the 75% total loss threshold is the Constructive Total Loss definition from PSAKBI, the Indonesian standard motor policy, measured against used market value rather than purchase price.
- **Rules trigger, the agent phrases**: whether a claim is held for more photos is decided by fixed rules so the same claim never passes today and fails tomorrow, while the agent writes what specifically must be visible in the next upload.
- **Seven deterministic validity checks with no generative AI**: reused photo detection by perceptual hash, plate on the body versus the registration document, chassis number format, cross-angle consistency, and previously claimed damage that was never repaired.
- **Rerunnable rejections**: a dispute six months later can be replayed and produces an identical result, with the failing check named in plain language.
- **Traceable pricing**: replace-or-repair comes from a database matrix keyed on damaged area ratio, so two identical claims always produce identical numbers, and every threshold lives in a table rather than in code.
- **Pricing agent that refuses to guess**: catalogue first, then the policy's own vehicle, then a web search that saves only the sources it actually cited and rejects out-of-range numbers, and if none of that works it reports the price as unknown and disables approval until the adjuster supplies it.
- **Conditional second pass**: the agent pulls underwriting guidance and prior claims on the same policy only when it flags the case as borderline, so ordinary claims cost a single LLM call.
- **Measured with the right metric**: damage detection is scored by pixel IoU against human annotation, not mAP, because the cost engine consumes damaged area ratio and never counts objects.
- **Zero running cost**, with an on-premise equivalent named for every hosted component, since the production target refuses cloud.

## Architecture

![Architecture diagram](img/Car%20Claim%20Workflow.png)

## Models

Two Ultralytics YOLO11s-seg instance segmentation models trained on the Humans in the Loop Car Parts and Car Damages dataset, 21 part classes and 8 damage classes collapsed to the 4 the cost engine can act on. One of the part classes is the licence plate, which removed the need to train a separate plate detector.

`gpt-oss-20b` on Groq with a free OpenRouter tier as fallback serves both agents and the LLM steps, Qwen 2.5 through Ollama is the on-premise path, and RapidOCR reads the registration document.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI via `gradio.Server`, SQLAlchemy |
| Frontend | Next.js, React, TypeScript |
| Database | PostgreSQL (Supabase), SQLite for local development |
| Object storage | Supabase Storage |
| Instance segmentation | Ultralytics YOLO11 |
| OCR | RapidOCR |
| Image processing | Pillow |
| PDF generation | ReportLab |
| LLM providers | Groq, OpenRouter, Ollama (on-premise) |
| Model training | Kaggle |
| Hosting | Hugging Face Spaces (backend), Vercel (frontend) |
| Python package manager | uv |

## Project Structure

```
.
├── backend/    # API, vision pipeline, cost engine, agents, database
├── frontend/   # Next.js app: surveyor upload flow, adjuster review, access management
└── img/        # Architecture diagram
```

Inside `backend/src/app`, code is organized by the kind of component it is:

- `agents/` - true agentic components (claim assessment, used market price search) plus the web search tool
- `llm_steps/` - single-shot LLM calls (STNK resolver, parts resolver, report generator)
- `pipeline/` - deterministic steps (pre-processing, detection, mask overlap, photo eligibility gate, STNK OCR, cost engine, orchestration)
- `api/` - HTTP routes, validity checks, persistence, access control
- `db/` - database models, seed data, session
- `laporan/` - PDF generation for estimates, work orders, and purchase offers
- `core/` - business rules, authentication, permissions, LLM client, token budget guard

## Prerequisites

- Python 3.11+
- uv (Python package manager)
- Node.js 20+
- Trained model weights in `backend/models/` as `part.pt` and `damage.pt`. Without them the system runs with a stub detector and the detections are fabricated.
- (Optional) A Groq and/or OpenRouter API key. Without one, the cost engine and all validity checks still run, and only the agent recommendation and the narrative summary are missing.

## Getting Started

### 1. Start the backend

```bash
cd backend
uv sync --extra ml --extra serve
cp .env.example .env
# fill in .env: at minimum GROQ_API_KEY, or leave it empty to run without agent features
uv run python scripts/isi_data_awal.py
uv run python app.py
```

The API is now available at `http://localhost:7860`. Data goes to a local SQLite file at `backend/dev.db`, so no database server is needed.

### 2. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The web app is now available at `http://localhost:3000`.

## Usage

- Log in as a surveyor to submit a claim: a policy number, one to six damage photos, and one photo of the vehicle registration document.
- The claim is answered immediately and processed in the background, so a surveyor in the field can move on to the next car.
- Log in as an adjuster to see the ranked claim list, the detection overlay on each photo, the seven validity checks with their reasons, the itemised cost table, and the total loss ratio. Correct any wrong detection, confirm the used market value, then approve, reject, or send the claim back.
- An approved repair issues a work order to the partner workshop; a total loss issues a vehicle purchase offer. Both are generated as PDFs.

## Testing

```bash
cd backend
uv run pytest
```

# R'Solv

R'Solv is an AI-powered exception review tool for beneficiary claim processing.

## What it does

R'Solv:

- Reads beneficiary claim PDFs with Claude through Amazon Bedrock
- Extracts structured case information
- Checks explicit requirements with deterministic rules
- Runs an XGBoost model as a secondary signal
- Shows when the rules and ML model disagree
- Keeps a human reviewer in control

## How it works

```text
PDF
↓
Claude / Amazon Bedrock
↓
Structured case facts
↓
Deterministic rules + XGBoost
↓
Case result and explanation
↓
Human review
```

The LLM understands the document.

The deterministic rules check explicit requirements.

The ML model runs alongside the rules as an additional signal.

## C.A.R.D.

R'Solv is powered by **C.A.R.D.**

**Case. Automatic. Review. Dashboard.**

## Technology

- Python
- Flask
- JavaScript
- Amazon Bedrock
- Claude
- XGBoost
- HTML / CSS

## Run the project

Backend:

```bash
cd /workshop
python3 backend/app.py
```

Frontend:

```bash
cd /workshop
python3 -m http.server 5506 --directory frontend
```

## Note

R'Solv is a hackathon prototype. It does not make legal or financial approval decisions. Humans remain in control of review decisions.

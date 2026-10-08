# R'Solv _(lplhackathon)_

A human-in-the-loop exception review prototype combining document AI, explicit rules, and a secondary ML signal.

## Background

R'Solv was built for the LPL Financial University Hackathon. It separates fuzzy document understanding from deterministic requirement checks instead of asking one model to make the entire decision.

## Install

```bash
git clone https://github.com/ameliaeckard/lplhackathon.git
cd lplhackathon
pip install -r requirements.txt
```

Amazon Bedrock credentials and model access are required for document extraction.

## Usage

Start the backend:

```bash
python backend/app.py
```

Serve the frontend:

```bash
python -m http.server 5506 --directory frontend
```

## Architecture

```text
PDF
 ↓
Claude / Amazon Bedrock
 ↓
Structured case facts
 ↓
Deterministic rules + XGBoost
 ↓
Explanation and disagreement signals
 ↓
Human review
```

The system does not make legal or financial approval decisions. Final review remains with a person.

## Maintainer

[Amelia Eckard](https://github.com/ameliaeckard)

## Contributing

Issues are welcome for bugs or documentation problems. Please open an issue before a substantial pull request.

## License

UNLICENSED © Amelia Eckard.

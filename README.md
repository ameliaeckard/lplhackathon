R'SOLV FULL LIVE-SYSTEM UPDATE — NO DATA
========================================

This is the source overlay to merge into /workshop.

PRESERVED ON PURPOSE
--------------------
This package does NOT include or delete /workshop/data/.

It also does NOT replace your trained ML work. Keep your existing:
  /workshop/ml/model_features.py
  /workshop/ml/models/resolve_model.joblib
  /workshop/ml/models/metrics.json
  plus any training/build scripts already in /workshop/ml/.

KEEP YOUR WORKING CONFIG.JS
---------------------------
This package contains frontend/config.example.js, but NOT frontend/config.js.
That is intentional. Keep the config.js that already points at your working
AWS forwarded backend URL.

WHAT IS INCLUDED
----------------
- R'Solv startup branding
- C.A.R.D. = Case. Automatic. Review. Dashboard.
- browser-side PDF compression BEFORE Flask
- ~0.35 MB best-effort transport target
- real upload progress
- local browser PDF libraries after setup
- Claude text/form extraction + visual fallback
- deterministic beneficiary rules
- saved XGBoost secondary signal
- rules/ML disagreement callout
- Evidence -> Fact -> Rule -> Result trace
- "What would clear this implemented exception?" preview
- human review workflow:
    Awaiting Review
    Follow-up Required
    Ready to Continue
    Return to Review Queue
- optional reviewer note
- timestamped review history
- backend request IDs + stage logs
- vertical Info pipeline
- Flexbox-based layout

INSTALL
-------
1. Merge this folder into /workshop.
2. Do NOT delete /workshop/data.
3. Do NOT delete your existing ml/model_features.py or ml/models/.
4. Do NOT overwrite your working frontend/config.js.
5. Run:

   cd /workshop
   bash setup.sh

6. Restart backend:

   python3 backend/app.py

7. If your frontend server on port 5500 is already running, leave it alone
   and refresh the browser. Otherwise:

   python3 -m http.server 5500 --directory frontend

IMPORTANT LANGUAGE
------------------
C.A.R.D. does not label claims "approved" or "compliant."

Deterministic case status:
  Needs Attention
  No Detected Exception
  Unable to Determine

Human review is an operational outcome:
  Awaiting Review
  Follow-up Required
  Ready to Continue

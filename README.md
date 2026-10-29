# Smart Inventory Manager

A beginner-friendly inventory app built with Python, Streamlit, Pandas and SQLite, with an optional Groq AI assistant.

## Features
- Dashboard with metrics, charts and recent transactions
- Add, search, edit and delete products
- Sales (stock out) and restock (stock in) with validation
- Low-stock alerts based on each product's minimum level
- Full transaction history with filters
- AI assistant that answers from your real database records

## Run locally
```
pip install -r requirements.txt
streamlit run app.py
```

## AI assistant (optional)
Add `GROQ_API_KEY` in Streamlit Cloud > App settings > Secrets:
```
GROQ_API_KEY = "your-key-here"
```
For local use, create `.streamlit/secrets.toml` with the same line (never upload it to GitHub).

## Note on storage
Data is saved in a local `inventory.db` file. On Streamlit Community Cloud this file can be reset when the app is rebuilt or rebooted. For permanent storage, move to a hosted database such as Supabase or Neon (PostgreSQL).

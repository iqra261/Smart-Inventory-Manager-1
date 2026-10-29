"""Smart Inventory Manager - Streamlit + SQLite + optional Groq AI assistant."""
import os
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

DB_PATH = "inventory.db"
CURRENCY = "$"                      # change to your currency symbol
GROQ_MODEL = "llama-3.3-70b-versatile"

st.set_page_config(page_title="Smart Inventory Manager", page_icon="📦", layout="wide")


# ----------------------------------------------------------------------------
# Database helpers
# ----------------------------------------------------------------------------
def run(sql, params=(), fetch=False):
    """Run one SQL statement safely (parameters prevent SQL injection)."""
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.execute(sql, params)
        rows = cur.fetchall() if fetch else None
        con.commit()
        return rows
    finally:
        con.close()


def read_df(sql, params=()):
    con = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


def init_db():
    """Create tables if they do not exist (existing data is never touched)."""
    run("""CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
            unit_price REAL NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
            min_stock INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0))""")
    run("""CREATE TABLE IF NOT EXISTS transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            balance_after INTEGER NOT NULL)""")


def load_products():
    df = read_df("SELECT * FROM products ORDER BY product_id")
    df["inventory_value"] = df["quantity"] * df["unit_price"]
    return df


def load_transactions():
    return read_df("SELECT * FROM transactions ORDER BY transaction_id DESC")


def next_product_id():
    rows = run("""SELECT product_id FROM products
                  UNION SELECT product_id FROM transactions""", fetch=True)
    nums = [int(r[0][1:]) for r in rows if r[0][1:].isdigit()]
    return f"P{(max(nums) if nums else 0) + 1:04d}"


def record_transaction(pid, kind, qty):
    """Change stock and log the transaction together. Returns (ok, message)."""
    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute("SELECT name, quantity FROM products WHERE product_id=?",
                          (pid,)).fetchone()
        if row is None:
            return False, "Product not found."
        name, current = row
        new_qty = current - qty if kind == "Sale" else current + qty
        if new_qty < 0:
            return False, f"Not enough stock. Only {current} unit(s) available."
        con.execute("UPDATE products SET quantity=? WHERE product_id=?", (new_qty, pid))
        con.execute("""INSERT INTO transactions
                       (timestamp, product_id, product_name, type, quantity, balance_after)
                       VALUES (?,?,?,?,?,?)""",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pid, name, kind, qty, new_qty))
        con.commit()
        return True, f"{kind} recorded for {name}. New stock: {new_qty}."
    except sqlite3.Error as e:
        con.rollback()
        return False, f"Database error: {e}"
    finally:
        con.close()


def validate_product(name, category, quantity, price, min_stock, exclude_id=None):
    errors = []
    if not name.strip():
        errors.append("Product name is required.")
    if not category.strip():
        errors.append("Category is required.")
    if quantity < 0 or price < 0 or min_stock < 0:
        errors.append("Quantity, price and minimum stock cannot be negative.")
    if name.strip():
        dup = run("SELECT product_id FROM products WHERE LOWER(name)=LOWER(?)",
                  (name.strip(),), fetch=True)
        if any(r[0] != exclude_id for r in dup):
            errors.append("A product with this name already exists.")
    return errors


def flash(msg, kind="success"):
    st.session_state["flash"] = (kind, msg)


def show_flash():
    if "flash" in st.session_state:
        kind, msg = st.session_state.pop("flash")
        getattr(st, kind)(msg)


def money(x):
    return f"{CURRENCY}{x:,.2f}"


def product_picker(df, key):
    labels = {r.product_id: f"{r.product_id} - {r.name} (stock: {r.quantity})"
              for r in df.itertuples()}
    return st.selectbox("Product", list(labels), format_func=labels.get, key=key)


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------
def page_dashboard():
    st.title("📦 Dashboard")
    show_flash()
    p, t = load_products(), load_transactions()
    low = p[p["quantity"] <= p["min_stock"]]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total products", len(p))
    c2.metric("Units in stock", int(p["quantity"].sum()))
    c3.metric("Inventory value", money(p["inventory_value"].sum()))
    c4.metric("Low-stock products", len(low))

    if not low.empty:
        st.warning(f"⚠️ {len(low)} product(s) are at or below their minimum stock: "
                   + ", ".join(low["name"]))
    if p.empty:
        st.info("No products yet. Go to **Products** to add your first one.")
        return

    left, right = st.columns(2)
    with left:
        st.subheader("Stock levels by product")
        st.bar_chart(p.set_index("name")["quantity"])
    with right:
        st.subheader("Inventory value by product")
        st.bar_chart(p.set_index("name")["inventory_value"])

    st.subheader("Units sold per day")
    sales = t[t["type"] == "Sale"].copy()
    if sales.empty:
        st.caption("No sales recorded yet.")
    else:
        sales["date"] = sales["timestamp"].str[:10]
        st.line_chart(sales.groupby("date")["quantity"].sum())

    st.subheader("Recent transactions")
    if t.empty:
        st.caption("No transactions yet.")
    else:
        st.dataframe(t.head(10), hide_index=True)


def page_products():
    st.title("🛒 Products")
    show_flash()
    tab_view, tab_add, tab_edit, tab_del = st.tabs(["View / Search", "Add", "Edit", "Delete"])
    p = load_products()

    with tab_view:
        q = st.text_input("Search by product name or ID")
        view = p
        if q.strip():
            m = p["name"].str.contains(q.strip(), case=False, regex=False) | \
                p["product_id"].str.contains(q.strip(), case=False, regex=False)
            view = p[m]
        if view.empty:
            st.info("No products to show.")
        else:
            st.dataframe(view, hide_index=True)

    with tab_add:
        with st.form("add_form", clear_on_submit=True):
            name = st.text_input("Product name")
            category = st.text_input("Category")
            c1, c2, c3 = st.columns(3)
            qty = c1.number_input("Starting quantity", min_value=0, step=1, value=0)
            price = c2.number_input("Unit price", min_value=0.0, step=0.5, value=0.0)
            min_stock = c3.number_input("Minimum stock level", min_value=0, step=1, value=5)
            if st.form_submit_button("Add product"):
                errs = validate_product(name, category, qty, price, min_stock)
                if errs:
                    for e in errs:
                        st.error(e)
                else:
                    pid = next_product_id()
                    run("INSERT INTO products VALUES (?,?,?,?,?,?)",
                        (pid, name.strip(), category.strip(), 0, float(price), int(min_stock)))
                    if qty > 0:
                        record_transaction(pid, "Restock", int(qty))
                    flash(f"Product {name.strip()} added with ID {pid}.")
                    st.rerun()

    with tab_edit:
        if p.empty:
            st.info("Nothing to edit yet.")
        else:
            pid = product_picker(p, "edit_pick")
            r = p[p["product_id"] == pid].iloc[0]
            with st.form(f"edit_form_{pid}"):
                name = st.text_input("Product name", value=r["name"])
                category = st.text_input("Category", value=r["category"])
                c1, c2 = st.columns(2)
                price = c1.number_input("Unit price", min_value=0.0, step=0.5,
                                        value=float(r["unit_price"]))
                min_stock = c2.number_input("Minimum stock level", min_value=0, step=1,
                                            value=int(r["min_stock"]))
                st.caption(f"Current quantity: {r['quantity']}. Change quantity using "
                           "the Restock or Sales pages so it is recorded in history.")
                if st.form_submit_button("Save changes"):
                    errs = validate_product(name, category, int(r["quantity"]), price,
                                            min_stock, exclude_id=pid)
                    if errs:
                        for e in errs:
                            st.error(e)
                    else:
                        run("""UPDATE products SET name=?, category=?, unit_price=?,
                               min_stock=? WHERE product_id=?""",
                            (name.strip(), category.strip(), float(price), int(min_stock), pid))
                        flash(f"Product {pid} updated.")
                        st.rerun()

    with tab_del:
        if p.empty:
            st.info("Nothing to delete yet.")
        else:
            pid = product_picker(p, "del_pick")
            st.warning("Deleting a product cannot be undone. Its past transactions stay in history.")
            sure = st.checkbox("Yes, I want to delete this product", key=f"del_ok_{pid}")
            if st.button("Delete product", disabled=not sure):
                run("DELETE FROM products WHERE product_id=?", (pid,))
                flash(f"Product {pid} deleted.")
                st.rerun()


def page_stock(kind):
    title = "📥 Stock In / Restock" if kind == "Restock" else "📤 Sales / Stock Out"
    st.title(title)
    show_flash()
    p = load_products()
    if p.empty:
        st.info("Add a product first on the **Products** page.")
        return
    pid = product_picker(p, f"pick_{kind}")
    label = "Quantity received" if kind == "Restock" else "Quantity sold or removed"
    with st.form(f"form_{kind}", clear_on_submit=True):
        qty = st.number_input(label, min_value=1, step=1, value=1)
        if st.form_submit_button("Record " + ("restock" if kind == "Restock" else "sale")):
            ok, msg = record_transaction(pid, kind, int(qty))
            if ok:
                flash(msg)
                st.rerun()
            else:
                st.error(msg)


def page_alerts():
    st.title("🚨 Low-Stock Alerts")
    p = load_products()
    low = p[p["quantity"] <= p["min_stock"]].copy()
    if low.empty:
        st.success("All products are above their minimum stock level. 🎉")
        return
    low["units_needed_to_reach_minimum"] = low["min_stock"] - low["quantity"]
    low["status"] = low["quantity"].apply(lambda q: "OUT OF STOCK" if q == 0 else "LOW")
    st.error(f"{len(low)} product(s) need restocking.")
    st.dataframe(low[["product_id", "name", "category", "quantity", "min_stock",
                      "units_needed_to_reach_minimum", "status"]], hide_index=True)


def page_history():
    st.title("🧾 Transaction History")
    t = load_transactions()
    if t.empty:
        st.info("No transactions recorded yet.")
        return
    c1, c2, c3 = st.columns(3)
    prod = c1.selectbox("Product", ["All"] + sorted(t["product_name"].unique()))
    kind = c2.selectbox("Type", ["All", "Sale", "Restock"])
    dates = pd.to_datetime(t["timestamp"]).dt.date
    rng = c3.date_input("Date range", value=(dates.min(), dates.max()))
    if prod != "All":
        t = t[t["product_name"] == prod]
        dates = dates[t.index]
    if kind != "All":
        t = t[t["type"] == kind]
    dates = pd.to_datetime(t["timestamp"]).dt.date
    if isinstance(rng, (tuple, list)) and len(rng) == 2:
        t = t[(dates >= rng[0]) & (dates <= rng[1])]
    st.caption(f"{len(t)} record(s)")
    st.dataframe(t, hide_index=True)


def get_groq_key():
    try:
        key = st.secrets["GROQ_API_KEY"]
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY")


def build_context():
    p, t = load_products(), load_transactions().head(30)
    low = p[p["quantity"] <= p["min_stock"]]
    return (f"Total products: {len(p)}\nTotal units: {int(p['quantity'].sum())}\n"
            f"Total inventory value: {p['inventory_value'].sum():.2f}\n"
            f"Low-stock products: {', '.join(low['name']) or 'none'}\n\n"
            f"PRODUCTS (CSV):\n{p.to_csv(index=False)}\n"
            f"RECENT TRANSACTIONS (CSV, newest first):\n{t.to_csv(index=False)}")


def page_ai():
    st.title("🤖 AI Inventory Assistant")
    key = get_groq_key()
    if not key:
        st.info("The AI assistant is switched off because no `GROQ_API_KEY` secret was found. "
                "All other features work normally. See the README to enable it.")
        return
    st.caption("Try: Which products need restocking? What is the total inventory value? "
               "Summarize recent sales and restocking.")
    history = st.session_state.setdefault("chat", [])
    for m in history:
        with st.chat_message(m["role"]):
            st.write(m["content"])
    question = st.chat_input("Ask about your inventory...")
    if not question:
        return
    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)
    system = ("You are an inventory assistant. Answer ONLY using the data below. "
              "If the data does not contain the answer, say so. Never invent products "
              "or numbers. Be concise.\n\n" + build_context())
    with st.chat_message("assistant"):
        try:
            from groq import Groq
            client = Groq(api_key=key)
            resp = client.chat.completions.create(
                model=GROQ_MODEL, temperature=0.2,
                messages=[{"role": "system", "content": system}] + history[-10:])
            answer = resp.choices[0].message.content
        except Exception as e:
            answer = f"Sorry, the AI assistant could not answer right now ({type(e).__name__}). Please try again later."
        st.write(answer)
    history.append({"role": "assistant", "content": answer})


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
init_db()
PAGES = {
    "📦 Dashboard": page_dashboard,
    "🛒 Products": page_products,
    "📥 Stock In / Restock": lambda: page_stock("Restock"),
    "📤 Sales / Stock Out": lambda: page_stock("Sale"),
    "🚨 Low-Stock Alerts": page_alerts,
    "🧾 Transaction History": page_history,
    "🤖 AI Assistant": page_ai,
}
st.sidebar.title("Smart Inventory Manager")
PAGES[st.sidebar.radio("Go to", list(PAGES))]()
st.sidebar.caption("Data is stored in a local SQLite file (inventory.db).")

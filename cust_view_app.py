import os
import tempfile
from typing import Tuple, Optional

import requests
import pandas as pd
import gradio as gr
from supabase import create_client, Client

# ============================================================
# 1. Imports & Assets: Supabase Credentials & GitHub Assets
# ============================================================

# --- Supabase Credentials (from your stored context) ---
SUPABASE_URL = "https://qsdhkywvongjkvkwsafv.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_-tp3tRkhFfn-p6lrun1Uqg_VlfdegRu"


def get_supabase_client() -> Client:
    """Initialize and return a Supabase client."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# --- GitHub Raw Asset URLs ---
LOGO_URL = (
    "https://github.com/pradeep-isb/Mistee/blob/main/"
    "ChatGPT%20Image%20Dec%2030,%202025,%2008_31_30%20PM.png?raw=true"
)
CSS_URL = "https://raw.githubusercontent.com/pradeep-isb/Mistee/refs/heads/main/style.py"


def download_logo() -> str:
    """Download the logo from GitHub and return the local file path."""
    resp = requests.get(LOGO_URL)
    resp.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(resp.content)
    tmp.flush()
    tmp.close()
    return tmp.name


def load_brand_css() -> str:
    """
    Download CSS (style.py equivalent) from GitHub and return as a string.
    If you want to extend with additional CSS, append to this string.
    """
    resp = requests.get(CSS_URL)
    resp.raise_for_status()
    external_css = resp.text

    # You can add extra high-end minimalist tweaks here if needed
    extra_css = """
    body, .gradio-container {
        background-color: #FAF9F6;
        color: #333333;
    }
    """
    return external_css + "\n" + extra_css


# Download assets once at app start
LOGO_PATH = download_logo()
mishtee_css = load_brand_css()


# ============================================================
# 2. Core Data Functions (Supabase + Schema)
# ============================================================

def fetch_customer_orders(phone: str) -> Tuple[str, pd.DataFrame]:
    """
    Given a customer phone number:
      - Fetch customer name from `customers` table
      - Fetch all orders from `orders` table for that phone
      - Enrich with product details from `products`
      - Return:
          greeting (str),
          orders_df (pd.DataFrame) -> bind to 'My Order History'
    """
    supabase = get_supabase_client()
    phone = phone.strip()

    # ---------- 1. Fetch Customer Name ----------
    customer_name: Optional[str] = "MishTee Guest"
    cust_res = (
        supabase.table("customers")
        .select("full_name")
        .eq("phone", phone)
        .limit(1)
        .execute()
    )

    if cust_res.data:
        customer_name = cust_res.data[0].get("full_name") or customer_name

    # Personalized greeting
    greeting = f"Namaste, {customer_name} ji! Great to see you again."

    # ---------- 2. Fetch Orders ----------
    orders_res = (
        supabase.table("orders")
        .select(
            "order_id, order_date, product_id, store_id, agent_id, "
            "qty_kg, order_value_inr, order_margin_inr, status"
        )
        .eq("cust_phone", phone)
        .order("order_date", desc=True)
        .execute()
    )

    orders_data = orders_res.data or []

    if not orders_data:
        empty_df = pd.DataFrame(
            columns=[
                "order_id",
                "order_date",
                "sweet_name",
                "variant_type",
                "qty_kg",
                "order_value_inr",
                "order_margin_inr",
                "status",
                "store_id",
                "agent_id",
                "product_id",
            ]
        )
        return greeting, empty_df

    orders_df = pd.DataFrame(orders_data)

    # ---------- 3. Enrich with Product Info ----------
    if "product_id" in orders_df.columns:
        product_ids = orders_df["product_id"].dropna().unique().tolist()
    else:
        product_ids = []

    if product_ids:
        prod_res = (
            supabase.table("products")
            .select("item_id, sweet_name, variant_type")
            .in_("item_id", product_ids)
            .execute()
        )
        prod_data = prod_res.data or []
        products_df = pd.DataFrame(prod_data)

        if not products_df.empty:
            orders_df = orders_df.merge(
                products_df,
                how="left",
                left_on="product_id",
                right_on="item_id",
            )
            orders_df.drop(columns=["item_id"], inplace=True, errors="ignore")

    desired_cols = [
        "order_id",
        "order_date",
        "sweet_name",
        "variant_type",
        "qty_kg",
        "order_value_inr",
        "order_margin_inr",
        "status",
        "store_id",
        "agent_id",
        "product_id",
    ]
    orders_df = orders_df[[c for c in desired_cols if c in orders_df.columns]]

    return greeting, orders_df


def fetch_top_trending_products() -> pd.DataFrame:
    """
    Computes the top 4 best-selling products based on total order quantity.

    Steps:
      - Fetch all orders from `orders`
      - Group by product_id and sum `qty_kg`
      - Sort descending and keep top 4
      - Join with `products` table to fetch sweet_name, variant_type, price_per_kg
      - Return a tidy DataFrame to show in 'Trending Today'
    """
    supabase = get_supabase_client()

    orders_res = (
        supabase.table("orders")
        .select("product_id, qty_kg")
        .execute()
    )
    orders_data = orders_res.data or []

    if not orders_data:
        return pd.DataFrame(
            columns=[
                "sweet_name",
                "variant_type",
                "total_qty_kg",
                "price_per_kg",
                "product_id",
            ]
        )

    orders_df = pd.DataFrame(orders_data)
    orders_df["qty_kg"] = pd.to_numeric(
        orders_df.get("qty_kg", 0), errors="coerce"
    ).fillna(0)

    agg_df = (
        orders_df.groupby("product_id", as_index=False)["qty_kg"]
        .sum()
        .rename(columns={"qty_kg": "total_qty_kg"})
    )
    agg_df = agg_df.sort_values("total_qty_kg", ascending=False).head(4)

    if agg_df.empty:
        return pd.DataFrame(
            columns=[
                "sweet_name",
                "variant_type",
                "total_qty_kg",
                "price_per_kg",
                "product_id",
            ]
        )

    top_product_ids = agg_df["product_id"].dropna().unique().tolist()

    prod_res = (
        supabase.table("products")
        .select("item_id, sweet_name, variant_type, price_per_kg")
        .in_("item_id", top_product_ids)
        .execute()
    )
    prod_data = prod_res.data or []
    products_df = pd.DataFrame(prod_data)

    if not products_df.empty:
        trending_df = agg_df.merge(
            products_df,
            how="left",
            left_on="product_id",
            right_on="item_id",
        )
        trending_df.drop(columns=["item_id"], inplace=True, errors="ignore")
    else:
        trending_df = agg_df.copy()
        trending_df["sweet_name"] = None
        trending_df["variant_type"] = None
        trending_df["price_per_kg"] = None

    desired_cols = [
        "sweet_name",
        "variant_type",
        "total_qty_kg",
        "price_per_kg",
        "product_id",
    ]
    trending_df = trending_df[[c for c in desired_cols if c in trending_df.columns]]

    return trending_df


# ============================================================
# 3. Gradio App Logic
# ============================================================

def on_login(phone: str):
    """
    Welcome Logic:
      - Takes phone input
      - Returns greeting, order history DataFrame, trending DataFrame
    """
    if not phone or not phone.strip():
        # Basic guardrail; still show trending with guest greeting
        greeting = "Namaste, MishTee Guest ji! Please enter a valid phone number."
        trending_df = fetch_top_trending_products()
        empty_df = pd.DataFrame(
            columns=[
                "order_id",
                "order_date",
                "sweet_name",
                "variant_type",
                "qty_kg",
                "order_value_inr",
                "order_margin_inr",
                "status",
                "store_id",
                "agent_id",
                "product_id",
            ]
        )
        return greeting, empty_df, trending_df

    greeting, orders_df = fetch_customer_orders(phone)
    trending_df = fetch_top_trending_products()
    return greeting, orders_df, trending_df


# ============================================================
# 4. Gradio UI Layout – Vertical Stack + Tabs
# ============================================================

with gr.Blocks(css=mishtee_css, title="MishTee-Magic Customer App") as demo:
    # ---------- Header: Centered Logo + Slogan ----------
    with gr.Row():
        gr.HTML(
            f"""
            <div style="width:100%; text-align:center; padding-top: 20px; padding-bottom: 10px;">
                <img src="file/{LOGO_PATH}" alt="MishTee-Magic Logo" style="max-height:120px;"/>
                <h2 style="margin-top: 10px; letter-spacing: 0.15em; text-transform: uppercase;">
                    [Purity and Health]
                </h2>
            </div>
            """
        )

    # ---------- Welcome / Login Section ----------
    with gr.Row():
        phone_input = gr.Textbox(
            label="Customer Login (Phone Number)",
            placeholder="Enter registered phone (starts with 9...)",
        )
        login_button = gr.Button("Login")

    greeting_md = gr.Markdown(
        "Welcome to MishTee-Magic! Please log in with your phone number.",
        elem_id="greeting-area",
    )

    # ---------- Tabbed View for Data Tables ----------
    with gr.Tabs():
        with gr.Tab("My Order History"):
            order_history_df = gr.Dataframe(
                value=pd.DataFrame(
                    columns=[
                        "order_id",
                        "order_date",
                        "sweet_name",
                        "variant_type",
                        "qty_kg",
                        "order_value_inr",
                        "order_margin_inr",
                        "status",
                        "store_id",
                        "agent_id",
                        "product_id",
                    ]
                ),
                label="My Order History",
                interactive=False,
            )

        with gr.Tab("Trending Today"):
            trending_df = gr.Dataframe(
                value=pd.DataFrame(
                    columns=[
                        "sweet_name",
                        "variant_type",
                        "total_qty_kg",
                        "price_per_kg",
                        "product_id",
                    ]
                ),
                label="Trending Today",
                interactive=False,
            )

    # ---------- Wire up Login Logic ----------
    login_button.click(
        fn=on_login,
        inputs=phone_input,
        outputs=[greeting_md, order_history_df, trending_df],
    )


# ============================================================
# 5. Main Entry Point
# ============================================================

if __name__ == "__main__":
    demo.launch()

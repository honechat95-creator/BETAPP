import streamlit as st
import requests

st.set_page_config(page_title="Test Telegram", page_icon="📲")
st.title("📲 Test Telegram")

TELEGRAM_BOT_TOKEN = "PEGA_AQUI_TU_TOKEN_NUEVO"
TELEGRAM_CHAT_ID = "PEGA_AQUI_TU_CHAT_ID"

def telegram_send(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    params = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        r = requests.get(url, params=params, timeout=20)
        return {
            "ok_http": True,
            "status_code": r.status_code,
            "text": r.text
        }
    except Exception as e:
        return {
            "ok_http": False,
            "status_code": None,
            "text": str(e)
        }

if st.button("Enviar prueba a Telegram", use_container_width=True):
    result = telegram_send("🚀 MENSAJE DE PRUEBA DESDE STREAMLIT")
    st.write(result)

import os
import time

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

# --- Инициализация состояния ---
if "search_id" not in st.session_state:
    st.session_state.search_id = None
if "status" not in st.session_state:
    st.session_state.status = "idle"
if "results" not in st.session_state:
    st.session_state.results = []
if "scores" not in st.session_state:
    st.session_state.scores = []
if "error" not in st.session_state:
    st.session_state.error = ""


# --- Функции API ---
def start_search(query: str, region: str, limit: int):
    try:
        resp = requests.post(
            f"{API_BASE}/search",
            json={"query": query, "region": region, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()["search_id"]
    except Exception as e:
        st.session_state.error = f"Ошибка запуска поиска: {str(e)}"
        st.session_state.status = "failed"
        return None


def poll_results(search_id: str):
    try:
        resp = requests.get(f"{API_BASE}/search/{search_id}/results")
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "completed":
            st.session_state.results = data.get("results", [])
            st.session_state.scores = data.get("scores", [])
            st.session_state.status = "completed"
        elif data["status"] == "failed":
            st.session_state.error = data.get("error", "Неизвестная ошибка")
            st.session_state.status = "failed"
        else:
            st.session_state.status = "processing"
    except Exception as e:
        st.session_state.error = f"Ошибка при опросе: {str(e)}"
        st.session_state.status = "failed"


def add_comment(search_id: str, result_id: str, comment: str):
    try:
        requests.patch(
            f"{API_BASE}/results/{search_id}/{result_id}/comment",
            params={"comment": comment},
        )
        poll_results(search_id)  # обновим данные
    except Exception as e:
        st.error(f"Не удалось добавить комментарий: {e}")


def get_csv_link(search_id: str) -> str:
    return f"{API_BASE}/search/{search_id}/export"


# --- UI ---
st.set_page_config(page_title="Поиск поставщиков", layout="wide")
st.title("🔍 Поиск поставщиков")

# Форма поиска
with st.form("search_form"):
    col1, col2 = st.columns(2)
    with col1:
        query = st.text_input("Что ищем (мука, упаковка...)", key="query")
        region = st.text_input("Регион (Москва, СПб...)", key="region")
    with col2:
        limit = st.number_input(
            "Количество веб-страниц для поиска",
            min_value=1,
            max_value=5,
            value=3,
            step=1,
        )
    submitted = st.form_submit_button("Найти")

if submitted:
    if not query or not region:
        st.error("Заполните оба поля: товар и регион")
    else:
        st.session_state.search_id = None
        st.session_state.status = "idle"
        st.session_state.results = []
        st.session_state.scores = []
        st.session_state.error = ""
        with st.spinner("Запускаем поиск..."):
            search_id = start_search(query, region, limit)
            if search_id:
                st.session_state.search_id = search_id
                st.session_state.status = "processing"

if st.session_state.status == "processing" and st.session_state.search_id:
    with st.spinner("⏳ Ожидание завершения поиска..."):
        while st.session_state.status == "processing":
            poll_results(st.session_state.search_id)
            if st.session_state.status == "processing":
                time.sleep(2)

if st.session_state.status == "failed":
    st.error(f"❌ {st.session_state.error}")

if st.session_state.status == "completed":
    results = st.session_state.results
    scores = st.session_state.scores

    if not results:
        st.info("Ничего не найдено.")
    else:
        csv_url = get_csv_link(st.session_state.search_id)
        st.download_button(
            label="📥 Скачать CSV",
            data=requests.get(csv_url).content,
            file_name=f"search_{st.session_state.search_id}.csv",
            mime="text/csv",
        )

        # Таблица с результатами
        st.subheader(f"Найдено {len(results)} поставщиков")

        # Генерируем заголовки
        cols = st.columns([3, 3, 2, 2, 2, 1, 1])
        cols[0].write("**Название**")
        cols[1].write("**Контакты**")
        cols[2].write("**Цена**")
        cols[3].write("**Сертификаты**")
        cols[4].write("**Комментарий**")
        cols[5].write("**Рейтинг**")
        cols[6].write("**Действие**")

        for i, card in enumerate(results):
            row = st.columns([3, 3, 2, 2, 2, 1, 1])
            row[0].write(card.get("name", ""))
            row[1].write(card.get("contacts", ""))
            row[2].write(card.get("price") or "—")
            certs = ", ".join(card.get("certificates", [])) or "—"
            row[3].write(certs[:50] + "…" if len(certs) > 50 else certs)
            row[4].write(card.get("comment") or "")
            row[5].write(f"{scores[i]:.2f}" if i < len(scores) else "—")

            # Кнопка для редактирования комментария
            if row[6].button("✏️", key=f"edit_btn_{card['id']}"):
                st.session_state["edit_target"] = {
                    "search_id": st.session_state.search_id,
                    "result_id": card["id"],
                    "current_comment": card.get("comment", ""),
                }
                st.rerun()

        # --- Форма редактирования (появляется, если есть edit_target) ---
        if "edit_target" in st.session_state:
            target = st.session_state["edit_target"]
            with st.container(border=True):
                st.markdown("### ✏️ Редактирование комментария")
                new_comment = st.text_area(
                    "Комментарий", value=target["current_comment"]
                )
                col1, col2 = st.columns(2)
                if col1.button("💾 Сохранить", key="save_comment"):
                    add_comment(target["search_id"], target["result_id"], new_comment)
                    del st.session_state["edit_target"]
                    st.rerun()
                if col2.button("❌ Отмена", key="cancel_comment"):
                    del st.session_state["edit_target"]
                    st.rerun()

"""
Отладчик вызова structured_llm из твоего пайплайна.
Воспроизводит точный вызов, при ошибке парсинга показывает сырой JSON.
Требуются переменные окружения (или вставь напрямую):
- OPENROUTER_API_KEY
- OPENROUTER_MODEL (по умолчанию 'openai/gpt-4o')
"""

import asyncio
import os
from typing import List, Optional, Union

import dotenv

dotenv.load_dotenv()

from langchain_core.exceptions import OutputParserException
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError


# ──────────────────────────────────
# Схемы – точная копия твоих SupplierCard / SupplierCardList
# ──────────────────────────────────
class SupplierCard(BaseModel):
    name: str
    contacts: str
    website: Optional[str] = None
    source: Optional[str] = None
    price: Optional[str] = None
    min_order: Optional[str] = None
    certificates: Union[List[str], str, None] = None
    delivery_conditions: Optional[str] = None
    region_covered: Optional[str] = None
    comment: Optional[str] = None


class SupplierCardList(BaseModel):
    suppliers: List[SupplierCard]


# ──────────────────────────────────
# Настройки – как у тебя в settings
# ──────────────────────────────────
API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o")
BASE_URL = "https://openrouter.ai/api/v1"

# Твой промпт (можно скопировать сюда тестовый текст)
TEST_TEXT = """
ООО "Мука-Хлеб", телефон +7 999 123-45-67, сайт mukahleb.ru,
поставляют муку по всей России, минимальный заказ 1 тонна,
сертификат ISO 9001, доставка ТК.
"""

PROMPT = (
    "Ты — анализатор поставщиков. Извлеки из текстов информацию о поставщиках продуктов питания, ингредиентов, упаковки. "
    "Для каждого найденного поставщика создай объект с полями: name, contacts, website, source (URL источника), price, min_order, certificates, delivery_conditions, region_covered. "
    "Если информации нет, оставляй поле null. Не придумывай данные.\n\n"
    "Ответ верни строго как JSON-объект с единственным ключом 'suppliers', который содержит массив таких объектов.\n\n"
    f"Тексты:\n{TEST_TEXT}"
)

# ──────────────────────────────────
# LLM – точная копия инициализации
# ──────────────────────────────────
llm = ChatOpenAI(
    api_key=API_KEY,
    model=MODEL,
    base_url=BASE_URL,
    temperature=0,
)

structured_llm = llm.with_structured_output(SupplierCardList)


# ──────────────────────────────────
# Главная асинхронная проверка
# ──────────────────────────────────
async def main():
    print("Запуск structured_llm.ainvoke...")
    try:
        result: SupplierCardList = await structured_llm.ainvoke(PROMPT[:150_000])
        print(f"✅ Успешно. Найдено поставщиков: {len(result.suppliers)}")
        for c in result.suppliers:
            print(f"  - {c.name}")
    except (ValidationError, OutputParserException) as e:
        print(f"❌ Ошибка парсинга/валидации:\n{e}\n")
        # Получаем сырой ответ обычным вызовом (без структуры)
        print("Получаю сырой ответ модели...")
        raw_response = await llm.ainvoke(PROMPT[:150_000])
        raw_text = (
            raw_response.content
            if hasattr(raw_response, "content")
            else str(raw_response)
        )
        print("=" * 60)
        print("СЫРОЙ ОТВЕТ МОДЕЛИ:")
        print(raw_text)
        print("=" * 60)
    except Exception as e:
        print(f"❌ Неизвестная ошибка: {e}")


if __name__ == "__main__":
    asyncio.run(main())

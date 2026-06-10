import asyncio
import json
import logging
import re
import uuid
from typing import List, Tuple

import redis.asyncio as redis
from cache import cache_search_id, get_cached_search_id, invalidate_cache
from firecrawl import FirecrawlApp
from langchain.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from schemas import SearchRequest, SupplierCard, SupplierCardList
from settings import settings

logger = logging.getLogger("supplier_search")

firecrawl = FirecrawlApp(api_key=settings.firecrawl_api_key)

llm = ChatOpenAI(
    api_key=settings.openrouter_api_key,
    model=settings.openrouter_model,
    base_url="https://openrouter.ai/api/v1",
    temperature=0,
)

structured_llm = llm.with_structured_output(SupplierCardList)


def _compute_score(card: SupplierCard) -> float:
    """Simple heuristic: more useful fields => higher score."""
    score = 1.0
    if card.price:
        score += 0.5
    if card.certificates:
        score += 0.3 * len(card.certificates)
    if card.min_order:
        score += 0.2
    if card.delivery_conditions:
        score += 0.2
    if card.website:
        score += 0.1
    return score


async def _do_search(search_id: str, req: SearchRequest, redis_client: redis.Redis):
    logger.info(
        "Starting search %s for query '%s' region '%s'",
        search_id,
        req.query,
        req.region,
    )
    try:
        search_result = firecrawl.search(
            query=f"поставщики {req.query} {req.region}",
            limit=req.limit,
            scrape_options={"formats": ["markdown"], "onlyMainContent": True},
        )
        search_data = search_result.web
        if not search_data:
            raise ValueError("Firecrawl returned no results")
        texts = [item.markdown for item in search_data if item.markdown]
        if not texts:
            raise ValueError("No page content to analyze")

        logger.debug("Search %s: got %d pages with content", search_id, len(texts))
        combined_text = "\n\n---\n\n".join(texts)
        url_pattern = r"https?://\S+|www\.\S+"
        combined_text = re.sub(url_pattern, "", combined_text)

        prompt = (
            "Ты — анализатор поставщиков. Извлеки из текстов информацию о поставщиках продуктов питания, ингредиентов, упаковки. "
            "Для каждого найденного поставщика создай объект с полями: name (строка), contacts (строка — все контакты через запятую), "
            "website (строка или null), source (строка URL или null), price (строка или null), min_order (строка или null), "
            "certificates (массив строк, каждый сертификат отдельным элементом), "
            "delivery_conditions (строка или null), region_covered (строка или null). "
            "Если информации нет, оставляй поле null. Не придумывай данные.\n\n"
            "Ответь СТРОГО JSON-объектом с ключом 'suppliers' — массивом таких объектов. "
            "JSON оберни в ```json ... ```\n\n"
            f"Тексты:\n{combined_text}"
        )

        safe_prompt = prompt[:120_000]
        messages = [
            SystemMessage(
                content="Ты — помощник, который всегда возвращает только JSON без лишнего текста."
            ),
            HumanMessage(content=safe_prompt),
        ]
        response = await llm.ainvoke(messages)
        response_text = response.content.strip()

        # Достаём JSON из маркдаун-блока или сырого текста
        json_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL
        )
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_str = response_text
        start = json_str.find("{")
        end = json_str.rfind("}")
        if start != -1 and end != -1:
            json_str = json_str[start : end + 1]
        data = json.loads(json_str)

        # === Нормализация сырых данных под схему ===
        raw_suppliers = data.get("suppliers", [])
        if not isinstance(raw_suppliers, list):
            raise ValueError("JSON не содержит массив suppliers")

        normalized = []
        for item in raw_suppliers:
            # contacts: если список -> объединяем через "; ", если None -> пустая строка
            contacts = item.get("contacts")
            if isinstance(contacts, list):
                contacts = "; ".join(str(c) for c in contacts if c)
            elif contacts is None:
                contacts = ""
            item["contacts"] = str(contacts)

            # certificates: если строка -> список из одного элемента, если None -> пустой список
            certs = item.get("certificates")
            if isinstance(certs, str):
                item["certificates"] = [certs]
            elif certs is None or not isinstance(certs, list):
                item["certificates"] = []
            else:
                # Оставляем список как есть
                item["certificates"] = certs

            # website, source и т.п. оставляем как есть (будут проверены моделью)
            normalized.append(item)

        # Теперь валидируем
        result = SupplierCardList.model_validate({"suppliers": normalized})

        logger.info(
            "Search %s: LLM extracted %d supplier(s)", search_id, len(result.suppliers)
        )
        logger.debug("Model output: %s", response_text)

        if not result.suppliers:
            raise ValueError("LLM found no suppliers")

        # Дедупликация и подсчёт очков (код без изменений)
        def _normalize_certificates(card: SupplierCard) -> SupplierCard:
            if isinstance(card.certificates, str):
                card.certificates = [card.certificates]
            elif card.certificates is None:
                card.certificates = []
            return card

        unique_cards: dict[tuple, SupplierCard] = {}
        for card in result.suppliers:
            card = _normalize_certificates(card)
            key = (card.name.strip().lower(), card.contacts.strip().lower())
            if key not in unique_cards:
                unique_cards[key] = card

        scored_cards: List[Tuple[float, str]] = []
        for _, card in enumerate(unique_cards.values()):
            if not card.source and search_data:
                first = search_data[0]
                source = getattr(first, "url", None)
                if not source:
                    metadata = getattr(first, "metadata", None)
                    if metadata:
                        source = getattr(metadata, "url", None)
                card.source = source if source else None

            score = _compute_score(card)
            card_json = card.model_dump_json(exclude={"comment"})
            scored_cards.append((score, card_json))

        logger.debug(
            "Search %s: scored %d unique suppliers", search_id, len(scored_cards)
        )

        pipe = redis_client.pipeline()
        await pipe.delete(f"search:{search_id}:results")
        for score, card_json in scored_cards:
            pipe.zadd(f"search:{search_id}:results", {card_json: score})
        pipe.set(f"search:{search_id}:status", "completed")
        pipe.expire(f"search:{search_id}:results", 3600)
        pipe.expire(f"search:{search_id}:status", 3600)
        await pipe.execute()

        logger.info("Search %s completed successfully", search_id)

    except Exception as e:
        logger.error("Search %s failed: %s", search_id, e)
        await redis_client.set(f"search:{search_id}:status", "failed")
        await redis_client.set(f"search:{search_id}:error", str(e))
        await redis_client.expire(f"search:{search_id}:status", 3600)
        await redis_client.expire(f"search:{search_id}:error", 3600)
        await invalidate_cache(redis_client, req.query, req.region, req.limit)


async def search_suppliers(req: SearchRequest, redis_client: redis.Redis) -> str:
    """Check cache for a matching search result, otherwise start a new supplier search."""
    cached_id = await get_cached_search_id(
        redis_client, req.query, req.region, req.limit
    )
    if cached_id:
        status = await redis_client.get(f"search:{cached_id}:status")
        if status == "completed":
            if await redis_client.exists(f"search:{cached_id}:results"):
                logger.info("Cache hit: returning completed search %s", cached_id)
                return cached_id
            else:
                logger.warning(
                    "Cache hit but no results for %s, invalidating", cached_id
                )
                await invalidate_cache(redis_client, req.query, req.region, req.limit)
        await invalidate_cache(redis_client, req.query, req.region, req.limit)

    search_id = str(uuid.uuid4())
    logger.info("No valid cache entry. Creating new search %s", search_id)
    pipe = redis_client.pipeline()
    pipe.set(f"search:{search_id}:status", "processing")
    pipe.expire(f"search:{search_id}:status", 3600)
    await pipe.execute()
    await cache_search_id(redis_client, req.query, req.region, req.limit, search_id)

    asyncio.create_task(_do_search(search_id, req, redis_client))
    return search_id

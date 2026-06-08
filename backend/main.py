import csv
import io
import logging

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from schemas import SearchRequest, SearchResponse, SupplierCard
from services import search_suppliers
from settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("supplier_search")

app = FastAPI(title="Supplier Search")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    app.state.redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)


@app.on_event("shutdown")
async def shutdown():
    await app.state.redis.close()


@app.post("/search", response_model=SearchResponse)
async def create_search(req: SearchRequest):
    search_id = await search_suppliers(req, app.state.redis)
    return SearchResponse(search_id=search_id, status="processing")


@app.get("/search/{search_id}/results", response_model=SearchResponse)
async def get_results(search_id: str):
    r: redis.Redis = app.state.redis
    status = await r.get(f"search:{search_id}:status")
    if not status:
        raise HTTPException(status_code=404, detail="Search not found")

    if status == "processing":
        return SearchResponse(search_id=search_id, status="processing")
    elif status == "failed":
        error = await r.get(f"search:{search_id}:error")
        return SearchResponse(
            search_id=search_id,
            status="failed",
            error=error or "Unknown error",
        )

    raw = await r.zrevrange(f"search:{search_id}:results", 0, -1, withscores=True)
    results = []
    scores = []
    comments = await r.hgetall(f"search:{search_id}:comments")

    for member_json, score in raw:
        card = SupplierCard.model_validate_json(member_json)
        comment = comments.get(card.id)
        if comment:
            card.comment = comment
        results.append(card)
        scores.append(score)

    return SearchResponse(
        search_id=search_id, status="completed", results=results, scores=scores
    )


@app.patch("/results/{search_id}/{result_id}/comment")
async def add_comment(
    search_id: str,
    result_id: str,
    comment: str = Query(..., min_length=1, max_length=500),
):
    r = app.state.redis
    if not await r.exists(f"search:{search_id}:results"):
        raise HTTPException(status_code=404, detail="Search results not found")
    await r.hset(f"search:{search_id}:comments", result_id, comment)
    return {"ok": True}


@app.get("/search/{search_id}/export")
async def export_csv(search_id: str):
    r = app.state.redis
    status = await r.get(f"search:{search_id}:status")
    if not status or status != "completed":
        raise HTTPException(status_code=404, detail="Completed results not found")

    raw = await r.zrevrange(f"search:{search_id}:results", 0, -1, withscores=True)
    comments = await r.hgetall(f"search:{search_id}:comments")

    output = io.StringIO()
    output.write("\ufeff")  # BOM for Excel

    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Score",
            "ID",
            "Name",
            "Contacts",
            "Website",
            "Price",
            "Min Order",
            "Certificates",
            "Delivery",
            "Region",
            "Comment",
            "Source",
        ]
    )

    for member_json, score in raw:
        card = SupplierCard.model_validate_json(member_json)
        comment = comments.get(card.id, "")
        writer.writerow(
            [
                score,
                card.id,
                card.name,
                card.contacts,
                card.website or "",
                card.price or "",
                card.min_order or "",
                "; ".join(card.certificates) if card.certificates else "",
                card.delivery_conditions or "",
                card.region_covered or "",
                comment,
                card.source or "",
            ]
        )

    csv_content = output.getvalue()
    output.close()

    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=suppliers_{search_id}.csv"
        },
    )

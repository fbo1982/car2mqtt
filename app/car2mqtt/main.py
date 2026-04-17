from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from . import __version__
from .manager import VehicleManager
from .mapping.canonical import BMW_EXAMPLE_MAPPING, example_bmw_mapping
from .models import VehicleConfig
from .providers import provider_schemas
from .store import StateStore


BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Car2MQTT", version=__version__)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

store = StateStore()
manager = VehicleManager(store)


class VehiclePayload(BaseModel):
    id: str
    label: str
    manufacturer: str
    license_plate: str
    enabled: bool = True
    provider_config: dict = {}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/version")
async def version() -> dict:
    return {"version": __version__}


@app.get("/api/providers")
async def providers() -> list[dict]:
    return [schema.model_dump(mode="json") for schema in provider_schemas()]


@app.get("/api/vehicles")
async def list_vehicles() -> list[dict]:
    return [record.model_dump(mode="json") for record in manager.list_vehicles()]


@app.get("/api/vehicles/{vehicle_id}")
async def get_vehicle(vehicle_id: str) -> dict:
    try:
        return manager.get_vehicle(vehicle_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vehicle not found") from exc


@app.post("/api/vehicles")
async def save_vehicle(payload: VehiclePayload) -> dict:
    try:
        vehicle = VehicleConfig.model_validate(payload.model_dump())
        return manager.save_vehicle(vehicle).model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/vehicles/{vehicle_id}")
async def update_vehicle(vehicle_id: str, payload: VehiclePayload) -> dict:
    if vehicle_id != payload.id:
        raise HTTPException(status_code=400, detail="vehicle id mismatch")
    return await save_vehicle(payload)


@app.delete("/api/vehicles/{vehicle_id}")
async def delete_vehicle(vehicle_id: str) -> dict:
    await manager.delete_vehicle(vehicle_id)
    return {"ok": True}


@app.post("/api/vehicles/{vehicle_id}/start")
async def start_vehicle(vehicle_id: str) -> dict:
    try:
        return (await manager.start_vehicle(vehicle_id)).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vehicle not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/vehicles/{vehicle_id}/stop")
async def stop_vehicle(vehicle_id: str) -> dict:
    try:
        return (await manager.stop_vehicle(vehicle_id)).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vehicle not found") from exc


@app.get("/api/health")
async def health() -> list[dict]:
    return [snapshot.model_dump(mode="json") for snapshot in manager.health()]


@app.get("/api/mapping/examples/bmw")
async def mapping_example() -> dict:
    return {
        "raw_hint": BMW_EXAMPLE_MAPPING,
        "mapped": example_bmw_mapping().model_dump(mode="json"),
    }


def run() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8099)


if __name__ == "__main__":
    run()

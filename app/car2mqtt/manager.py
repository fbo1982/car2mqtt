from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict

from .models import AppState, HealthSnapshot, VehicleConfig, VehicleRecord, VehicleStatus, utcnow
from .providers import get_provider
from .store import StateStore


@dataclass
class RuntimeWorker:
    vehicle: VehicleConfig
    task: asyncio.Task[None]


class VehicleManager:
    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.state = self.store.load()
        self.records: Dict[str, VehicleRecord] = {
            vehicle.id: VehicleRecord(config=vehicle) for vehicle in self.state.vehicles
        }
        self.workers: Dict[str, RuntimeWorker] = {}

    def reload(self) -> AppState:
        self.state = self.store.load()
        for vehicle in self.state.vehicles:
            self.records.setdefault(vehicle.id, VehicleRecord(config=vehicle))
            self.records[vehicle.id].config = vehicle
        for stale_id in list(self.records):
            if stale_id not in {vehicle.id for vehicle in self.state.vehicles}:
                self.records.pop(stale_id, None)
        return self.state

    def list_vehicles(self) -> list[VehicleRecord]:
        self.reload()
        return [self.records[vehicle.id] for vehicle in self.state.vehicles]

    def get_vehicle(self, vehicle_id: str) -> VehicleRecord:
        self.reload()
        if vehicle_id not in self.records:
            raise KeyError(vehicle_id)
        return self.records[vehicle_id]

    def save_vehicle(self, vehicle: VehicleConfig) -> VehicleRecord:
        self.reload()
        vehicles = [v for v in self.state.vehicles if v.id != vehicle.id]
        vehicles.append(vehicle)
        vehicles.sort(key=lambda item: item.label.lower())
        self.state.vehicles = vehicles
        self.store.save(self.state)
        record = self.records.get(vehicle.id, VehicleRecord(config=vehicle))
        record.config = vehicle
        record.message = "Saved"
        self.records[vehicle.id] = record
        return record

    async def delete_vehicle(self, vehicle_id: str) -> None:
        if vehicle_id in self.workers:
            await self.stop_vehicle(vehicle_id)
        self.reload()
        self.state.vehicles = [v for v in self.state.vehicles if v.id != vehicle_id]
        self.store.save(self.state)
        self.records.pop(vehicle_id, None)

    async def start_vehicle(self, vehicle_id: str) -> VehicleRecord:
        record = self.get_vehicle(vehicle_id)
        if vehicle_id in self.workers:
            return record

        record.status = VehicleStatus.STARTING
        record.message = "Starting worker"

        async def runner() -> None:
            provider = get_provider(record.config)
            await provider.validate_config()
            await provider.start()
            record.status = VehicleStatus.RUNNING
            record.message = "Worker running"
            record.last_seen = utcnow()
            try:
                while True:
                    await asyncio.sleep(5)
                    health = await provider.health()
                    record.last_seen = utcnow()
                    record.message = str(health.get("message", "OK"))
            except asyncio.CancelledError:
                await provider.stop()
                record.status = VehicleStatus.STOPPED
                record.message = "Stopped"
                raise

        task = asyncio.create_task(runner(), name=f"car2mqtt-{vehicle_id}")
        self.workers[vehicle_id] = RuntimeWorker(vehicle=record.config, task=task)

        def _done_callback(done_task: asyncio.Task[None]) -> None:
            self.workers.pop(vehicle_id, None)
            if done_task.cancelled():
                return
            exception = done_task.exception()
            if exception:
                record.status = VehicleStatus.ERROR
                record.message = str(exception)

        task.add_done_callback(_done_callback)
        await asyncio.sleep(0)
        return record

    async def stop_vehicle(self, vehicle_id: str) -> VehicleRecord:
        record = self.get_vehicle(vehicle_id)
        worker = self.workers.get(vehicle_id)
        if not worker:
            record.status = VehicleStatus.STOPPED
            record.message = "Already stopped"
            return record
        worker.task.cancel()
        try:
            await worker.task
        except asyncio.CancelledError:
            pass
        record.status = VehicleStatus.STOPPED
        record.message = "Stopped"
        return record

    def health(self) -> list[HealthSnapshot]:
        return [
            HealthSnapshot(
                vehicle_id=record.config.id,
                status=record.status,
                last_seen=record.last_seen,
                message=record.message,
            )
            for record in self.list_vehicles()
        ]

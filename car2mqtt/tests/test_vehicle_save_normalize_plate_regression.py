from app.api import server


def test_server_exposes_normalize_plate_for_vehicle_save_path():
    # Regression for v1.2.62: _save_vehicle referenced normalize_plate without importing it.
    assert callable(server.normalize_plate)
    assert server.normalize_plate("GG-CA 911E") == "GGCA911E"

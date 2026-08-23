from __future__ import annotations


def main() -> None:
    import uvicorn

    uvicorn.run(
        "simulation_server.main:create_app",
        host="0.0.0.0",
        port=8000,
        factory=True,
    )


if __name__ == "__main__":
    main()

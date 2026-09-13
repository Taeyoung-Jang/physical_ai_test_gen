"""Fixed simple regression fixtures followed by seeded rooms and maze worlds."""

from .core import Box, Config, SceneSpec, generate


def stage_world(name: str):
    if name in {"rooms", "maze"}:
        return generate(
            Config(
                mode=name,
                seed=7,
                width=15 if name == "rooms" else 9,
                height=15 if name == "rooms" else 9,
                cell_size_m=1.8,
                robot_radius_m=0.4,
                safety_margin_m=0.1,
                obstacle_count=4 if name == "rooms" else 0,
            )
        )
    if name not in {"straight", "corner", "obstacle"}:
        raise ValueError("unknown navigation stage")
    cfg = Config(
        mode="rooms",
        seed={"straight": 101, "corner": 102, "obstacle": 103}[name],
        width=9,
        height=9,
        cell_size_m=1.8,
        robot_radius_m=0.4,
        safety_margin_m=0.1,
        obstacle_count=int(name == "obstacle"),
    )
    if name == "corner":
        free = {(x, 1) for x in range(1, 8)} | {(7, y) for y in range(1, 8)}
        spawn, goal = (1, 1), (7, 7)
    elif name == "obstacle":
        free = {(x, y) for x in range(1, 8) for y in range(3, 6)}
        spawn, goal = (1, 4), (7, 4)
    else:
        free = {(x, 4) for x in range(1, 8)}
        spawn, goal = (1, 4), (7, 4)
    s = cfg.cell_size_m
    boxes = [
        Box(f"wall_{x}_{y}", "wall", ((x + 0.5) * s, (y + 0.5) * s, 1.2), (s, s, 2.4))
        for y in range(9)
        for x in range(9)
        if (x, y) not in free
    ]
    if name == "obstacle":
        boxes.append(Box("obstacle_0", "obstacle", (4.5 * s, 4.5 * s, 0.5), (1.0, 1.0, 1.0), True))
    return SceneSpec(
        cfg,
        tuple(boxes),
        (),
        (),
        ((spawn[0] + 0.5) * s, (spawn[1] + 0.5) * s),
        ((goal[0] + 0.5) * s, (goal[1] + 0.5) * s),
        f"navigation-fixture-v1:{name}",
    )

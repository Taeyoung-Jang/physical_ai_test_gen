"""Height/friction/navigation preview generated from the authoritative 2.5D map."""


def plot_terrain(spec, nav, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, axes = plt.subplots(3, 1, figsize=(12, 8))
    extent = [
        0,
        spec.config.width * spec.config.cell_size_m,
        0,
        spec.config.height * spec.config.cell_size_m,
    ]
    for ax, key, title in zip(
        axes[:2], ("height_m", "friction"), ("Support height (m)", "Sliding friction coefficient")
    ):
        data = np.array(nav[key])
        img = ax.imshow(data, origin="lower", extent=extent, aspect="equal", cmap="viridis")
        fig.colorbar(img, ax=ax, fraction=0.02)
        points = np.array(nav["path_xy_m"])
        if len(points):
            ax.plot(points[:, 0], points[:, 1], "r--", linewidth=1)
        ax.set(title=title, ylabel="Y (m)")
        ax.set_ylim(spec.spawn_xy[1] - 4.5, spec.spawn_xy[1] + 4.5)
    for s in spec.surfaces:
        axes[2].plot(
            [s.x0, s.x1], [s.height(s.x0, spec.spawn_xy[1]), s.height(s.x1, spec.spawn_xy[1])], "b-"
        )
    axes[2].set(
        xlabel="X (m)", ylabel="Height (m)", title="Centerline elevation profile (not a rollout)"
    )
    axes[2].grid(alpha=0.3)
    fig.suptitle(spec.scene_id + " | configured planning limits, not certified G1 traversability")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)

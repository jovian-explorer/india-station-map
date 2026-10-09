"""Plot Indian state boundaries and observation stations from a CSV file."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
import shutil
import tempfile
import urllib.error
import urllib.request
import warnings

ROOT = Path(__file__).resolve().parent
INDIA_URL = (
    "https://raw.githubusercontent.com/Amazing-coder1203/BharatMaps/"
    "92a5898c67beea05fc76b008e042a1dcce081c2d/india-states-v2.geojson"
)
WORLD_URL = "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip"
DEFAULT_EXTENT = (65.0, 98.0, 5.0, 38.0)


def load_stations(path: Path) -> list[dict]:
    """Read name, longitude, latitude and optional label_dx/label_dy (points)."""
    stations = []
    names = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"name", "longitude", "latitude"}.issubset(reader.fieldnames or []):
            raise ValueError("Station CSV needs name,longitude,latitude columns.")
        for line, row in enumerate(reader, start=2):
            name = row["name"].strip()
            if not name or name in names:
                raise ValueError(f"Station CSV row {line}: names must be nonempty and unique.")
            try:
                lon, lat = float(row["longitude"]), float(row["latitude"])
                dx = float(row.get("label_dx") or 9)
                dy = float(row.get("label_dy") or 4)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Station CSV row {line}: invalid numeric value.") from error
            if not all(math.isfinite(v) for v in (lon, lat, dx, dy)):
                raise ValueError(f"Station CSV row {line}: values must be finite.")
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError(f"Station CSV row {line}: coordinates are out of range.")
            names.add(name)
            stations.append(dict(name=name, longitude=lon, latitude=lat, dx=dx, dy=dy))
    if not stations:
        raise ValueError("Station CSV has no stations.")
    return stations


def cached_file(url: str, destination: Path, offline: bool = False) -> Path:
    """Download once, atomically, so interrupted downloads cannot poison the cache."""
    destination = Path(destination)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    if offline:
        raise FileNotFoundError(f"Offline mode: missing map data {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "india-station-map/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
                temporary = Path(stream.name)
                shutil.copyfileobj(response, stream)
        if temporary.stat().st_size == 0:
            raise ValueError(f"Empty map download: {url}")
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def load_boundaries(path: Path):
    """Normalize to WGS84 and repair invalid polygons before drawing."""
    import geopandas as gpd

    frame = gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f"Boundary file has no coordinate reference system: {path}")
    frame = frame.to_crs("EPSG:4326")
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    frame.geometry = frame.geometry.make_valid()
    frame = frame.explode(ignore_index=True)
    frame = frame[frame.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    if frame.empty:
        raise ValueError(f"No polygon geometries found in {path}")
    return frame


def draw_reference_curves(ax):
    """Optional curves preserved from the source notebook, not an IGRF calculation."""
    import numpy as np

    curves = np.genfromtxt(ROOT / "examples" / "reference_curves.csv", delimiter=",", names=True)
    x = curves["longitude"]
    ax.fill_between(x, curves["crest_low"], curves["crest_high"], color="#6A1B9A",
                    alpha=0.13, label="Reference crest band", zorder=3)
    ax.plot(x, curves["dip_equator"], "--", color="#B44715", linewidth=1.6,
            label="Reference dip-equator curve", zorder=4)
    ax.plot(x, curves["crest_mean"], color="#6A1B9A", linewidth=1.6,
            label="Reference mean-crest curve", zorder=4)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)


def plot_map(stations, india_file: Path, world_file: Path | None = None, *,
             extent=DEFAULT_EXTENT, title="Observation stations in India", marker="antenna",
             reference_curves=False, figsize=(10, 10), color="#C53F3F"):
    """Return (figure, axes); coordinates and extent are WGS84 degrees."""
    import geopandas as gpd
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as MarkerPath

    west, east, south, north = extent
    if not (-180 <= west < east <= 180 and -90 < south < north < 90):
        raise ValueError("Extent must be WEST EAST SOUTH NORTH, with increasing WGS84 bounds.")
    if marker not in {"antenna", "circle"}:
        raise ValueError("Marker must be antenna or circle.")
    india = load_boundaries(india_file)
    world = load_boundaries(world_file) if world_file is not None else None
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_facecolor("#E7EFF4")
    if world is not None:
        column = next((name for name in ("ADMIN", "NAME") if name in world.columns), None)
        if column is None:
            plt.close(fig)
            raise ValueError("World boundaries need an ADMIN or NAME country column.")
        neighbors = world.cx[west:east, south:north]
        neighbors = neighbors[neighbors[column] != "India"]
        if not neighbors.empty:
            neighbors.plot(ax=ax, facecolor="#E7E3DC", edgecolor="#A5A49F", linewidth=0.55, zorder=1)
    india.plot(ax=ax, facecolor="#FCFCFA", edgecolor="#A8B5BE", linewidth=0.4, zorder=2)
    gpd.GeoSeries([india.geometry.union_all()], crs=india.crs).boundary.plot(
        ax=ax, color="#334B5B", linewidth=0.9, zorder=3)
    if reference_curves:
        draw_reference_curves(ax)
    # A marker drawn in points keeps the antenna size stable when the map is zoomed.
    antenna = MarkerPath(
        [(0, -1), (0, 1), (-.65, 1), (.65, 1), (-.45, .45), (.45, .45), (-.25, -.1), (.25, -.1)],
        [MarkerPath.MOVETO, MarkerPath.LINETO] * 4,
    )
    visible = 0
    for station in stations:
        lon, lat = station["longitude"], station["latitude"]
        if not west <= lon <= east or not south <= lat <= north:
            warnings.warn(f"Station {station['name']} is outside the map extent.", stacklevel=2)
            continue
        visible += 1
        ax.plot(lon, lat, marker=antenna if marker == "antenna" else "o",
                color=color, markersize=14 if marker == "antenna" else 6,
                markeredgewidth=1.4, linestyle="none", zorder=6)
        ax.annotate(station["name"], (lon, lat), xytext=(station.get("dx", 9), station.get("dy", 4)),
                    textcoords="offset points", fontsize=11, fontweight="bold", color="#243B4B",
                    bbox=dict(boxstyle="round,pad=.2", fc="white", ec="none", alpha=.88), zorder=7)
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect(1 / math.cos(math.radians((south + north) / 2)))
    ax.set_axisbelow(True)
    ax.grid(linestyle=":", linewidth=.6, color="#8197A6", alpha=.55)
    ax.tick_params(top=True, right=True, labelsize=10)
    ax.set_xlabel("Longitude (°E)", labelpad=10)
    ax.set_ylabel("Latitude (°N)", labelpad=10)
    ax.set_title(title, loc="left", fontsize=17, fontweight="bold", pad=18, color="#243B4B")
    ax.text(0, 1.01, f"{visible} stations · Geographic coordinates (WGS84)", transform=ax.transAxes,
            fontsize=9, color="#526979")
    note = "Boundaries: BharatMaps" + (" / Natural Earth" if world is not None else "")
    if reference_curves:
        note += " · Curves: notebook references; no model epoch specified"
    fig.text(.5, .015, note, ha="center", fontsize=7, color="#526979")
    fig.tight_layout(rect=(0, .04, 1, 1))
    return fig, ax


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stations", type=Path, default=ROOT / "examples" / "stations.csv")
    parser.add_argument("--output", type=Path, default=Path("outputs/india_station_map.png"))
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Downloaded map cache")
    parser.add_argument("--india-boundaries", type=Path, help="Use your own state GeoJSON/shapefile")
    parser.add_argument("--world-boundaries", type=Path, help="Use your own country boundaries")
    parser.add_argument("--offline", action="store_true", help="Use local data only")
    parser.add_argument("--no-neighbors", action="store_true", help="Skip neighboring countries")
    parser.add_argument("--reference-curves", action="store_true", help="Add original notebook reference curves")
    parser.add_argument("--marker", choices=("antenna", "circle"), default="antenna")
    parser.add_argument("--extent", type=float, nargs=4, default=DEFAULT_EXTENT,
                        metavar=("WEST", "EAST", "SOUTH", "NORTH"))
    parser.add_argument("--title", default="Observation stations in India")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--show", action="store_true", help="Also open an interactive plot window")
    args = parser.parse_args(argv)
    if args.output.suffix.lower() not in {".png", ".pdf", ".svg"}:
        parser.error("Output must end in .png, .pdf or .svg")
    if args.dpi <= 0:
        parser.error("DPI must be positive")
    west, east, south, north = args.extent
    if not (-180 <= west < east <= 180 and -90 < south < north < 90):
        parser.error("Extent must be WEST EAST SOUTH NORTH, with increasing WGS84 bounds")
    try:
        stations = load_stations(args.stations)
        india = args.india_boundaries or cached_file(INDIA_URL, args.data_dir / "india_states_v2.geojson", args.offline)
        world = None
        if not args.no_neighbors:
            world = args.world_boundaries or cached_file(WORLD_URL, args.data_dir / "world_map_50m.zip", args.offline)
        import matplotlib
        if not args.show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, _ = plot_map(stations, india, world, extent=args.extent, title=args.title,
                          marker=args.marker, reference_curves=args.reference_curves)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.output, dpi=args.dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
        print(f"Saved {args.output.resolve()}")
        if args.show:
            plt.show()
        plt.close(fig)
    except (OSError, ValueError, urllib.error.URLError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

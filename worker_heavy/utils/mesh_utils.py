import tempfile
from pathlib import Path
from typing import Literal

import structlog
import trimesh

logger = structlog.get_logger(__name__)


class MeshProcessingError(Exception):
    """Raised when mesh processing (repair or tetrahedralization) fails."""

    pass


def repair_mesh(
    mesh: trimesh.Trimesh, max_attempts: int = 3, session_id: str | None = None
) -> trimesh.Trimesh:
    """Repairs a mesh to ensure it is watertight and manifold.

    Args:
        mesh: Input trimesh object.
        max_attempts: Number of times to try repairing the mesh.
        session_id: Optional session ID for logging attribution.

    Returns:
        Repaired trimesh object.

    Raises:
        MeshProcessingError: If the mesh cannot be repaired after max_attempts.
    """
    for attempt in range(max_attempts):
        if mesh.is_watertight and mesh.is_winding_consistent:
            return mesh

        logger.info(
            f"Attempt {attempt + 1}/{max_attempts}: Mesh is not watertight or has inconsistent winding, attempting repair",
            session_id=session_id,
        )

        # process() merges vertices, removes duplicate/degenerate faces and unreferenced vertices
        mesh.process()

        # Repair normals and fill holes
        mesh.fix_normals()
        mesh.fill_holes()

    if not mesh.is_watertight:
        raise MeshProcessingError(
            "Mesh failed to become watertight after multiple repair attempts."
        )

    return mesh


def repair_mesh_file(
    input_path: Path, output_path: Path, session_id: str | None = None
) -> Path:
    """Reads a mesh file, repairs it, and writes it back.

    Args:
        input_path: Path to input mesh (STL, OBJ, etc.)
        output_path: Path to write repaired mesh (typically STL for Gmsh)
        session_id: Optional session ID for logging attribution.

    Returns:
        Path to the repaired mesh file.
    """
    mesh = trimesh.load(str(input_path))
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)

    repaired = repair_mesh(mesh, session_id=session_id)
    repaired.export(str(output_path))
    return output_path


def tetrahedralize(
    input_path: Path,
    output_msh_path: Path,
    method: Literal["gmsh", "tetgen"] = "gmsh",
    refine_level: float = 1.0,
    part_label: str = "unknown",
    session_id: str | None = None,
) -> Path:
    """Tetrahedralizes a surface mesh into a 3D volumetric mesh.

    Retries with mesh repair for non-manifold input.

    Args:
        input_path: Path to the input surface mesh (STL).
        output_msh_path: Path where the .msh file should be saved.
        method: The tetrahedralization tool to use.
        refine_level: Factor to adjust mesh density (smaller = finer).
        part_label: Label of the part being tetrahedralized for observability.

    Returns:
        Path to the generated .msh file.

    Raises:
        MeshProcessingError: If tetrahedralization fails after retry.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input mesh not found: {input_path}")

    max_retries = 1

    for attempt in range(max_retries + 1):
        try:
            if method == "gmsh":
                return _tetrahedralize_gmsh(input_path, output_msh_path, refine_level)
            if method == "tetgen":
                return _tetrahedralize_tetgen(input_path, output_msh_path)
            raise ValueError(f"Unknown tetrahedralization method: {method}")
        except Exception as e:
            logger.warning(
                f"Tetrahedralization attempt {attempt} failed for {part_label} using {method}: {e}",
                session_id=session_id,
            )

            if attempt < max_retries:
                logger.info(
                    f"Attempting mesh repair and retry for {part_label}",
                    session_id=session_id,
                )
                try:
                    # Create a temporary repaired file to avoid overwriting original input if needed,
                    # but here we'll just overwrite it for simplicity in the pipeline
                    repair_mesh_file(input_path, input_path, session_id=session_id)
                    continue
                except Exception as repair_error:
                    logger.error(
                        "mesh_repair_failed",
                        part_label=part_label,
                        error=str(repair_error),
                        session_id=session_id,
                    )
                    raise MeshProcessingError(
                        f"Tetrahedralization failed and repair also failed: {e}"
                    ) from e
            else:
                raise MeshProcessingError(
                    f"Tetrahedralization failed after {max_retries} retries: {e}"
                ) from e
    return None


def _tetrahedralize_gmsh(
    input_path: Path, output_msh_path: Path, refine_level: float
) -> Path:
    """Internal implementation using Gmsh Python API."""
    import gmsh

    try:
        if not gmsh.isInitialized():
            gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.model.add("VolumetricModel")

        # Load the STL
        gmsh.merge(str(input_path))

        # In Gmsh, STL is just a collection of triangles (discrete surfaces)
        # We need to create a volume from them.
        entities = gmsh.model.getEntities(2)
        if not entities:
            raise RuntimeError("No surfaces found in STL")

        # Create a surface loop from all surfaces
        surface_tags = [e[1] for e in entities]
        loop_tag = gmsh.model.geo.addSurfaceLoop(surface_tags)

        # Add a volume
        gmsh.model.geo.addVolume([loop_tag])
        gmsh.model.geo.synchronize()

        # Optional: refine mesh size
        gmsh.option.setNumber("Mesh.MeshSizeFactor", refine_level)
        gmsh.option.setNumber("Mesh.Algorithm", 6)  # HXT for 3D
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 32)  # Refine near curves

        # Force MSH v2.2 ASCII (more widely supported)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.Binary", 0)

        # Generate 3D mesh
        gmsh.model.mesh.generate(3)

        # Verify that 3D elements were actually created
        # getElements(3) returns (elementTypes, elementTags, nodeTags)
        elem_types, _, _ = gmsh.model.mesh.getElements(3)
        if len(elem_types) == 0:
            raise RuntimeError(
                "Gmsh failed to generate 3D tetrahedral elements. Check if the surface is closed and manifold."
            )

        # Optimize 3D mesh for better quality
        gmsh.model.mesh.optimize("Netgen")

        # Save as .msh
        output_msh_path.parent.mkdir(parents=True, exist_ok=True)
        gmsh.write(str(output_msh_path))

        return output_msh_path
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()


def _tetrahedralize_tetgen(input_path: Path, output_msh_path: Path) -> Path:
    """Fallback implementation using TetGen CLI."""
    import shutil
    import subprocess

    import gmsh

    # Check for tetgen binary
    tetgen_bin = shutil.which("tetgen")
    if not tetgen_bin:
        raise FileNotFoundError(
            "TetGen binary not found. Please install tetgen or use gmsh method."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_stl = Path(tmpdir) / input_path.name
        tmp_stl.write_bytes(input_path.read_bytes())

        # -p: Tetrahedralize a piecewise linear complex
        # -q: Quality mesh generation. A minimum radius-edge ratio may be specified.
        cmd = [tetgen_bin, "-pq1.2", str(tmp_stl)]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"TetGen failed: {e.stderr}")

        # TetGen produces .node and .ele files (and .face, .edge)
        # We need to convert this to .msh using Gmsh
        base_name = tmp_stl.stem
        node_file = Path(tmpdir) / f"{base_name}.1.node"
        ele_file = Path(tmpdir) / f"{base_name}.1.ele"

        if not node_file.exists() or not ele_file.exists():
            raise RuntimeError("TetGen did not produce .node or .ele files.")

        try:
            if not gmsh.isInitialized():
                gmsh.initialize()
            gmsh.model.add("TetGenImport")

            # Parse .node file
            nodes = []
            with open(node_file) as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                header = lines[0].split()
                num_nodes = int(header[0])
                for line in lines[1 : num_nodes + 1]:
                    parts = line.split()
                    # index, x, y, z
                    nodes.append((float(parts[1]), float(parts[2]), float(parts[3])))

            # Parse .ele file
            elements = []
            with open(ele_file) as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                header = lines[0].split()
                num_eles = int(header[0])
                for line in lines[1 : num_eles + 1]:
                    parts = line.split()
                    # index, n1, n2, n3, n4
                    elements.append([int(p) for p in parts[1:5]])

            # Add to Gmsh
            node_tags = []
            flat_coords = []
            for i, (x, y, z) in enumerate(nodes):
                node_tags.append(i + 1)
                flat_coords.extend([x, y, z])

            # Add discrete entity to hold mesh
            tag = 1
            gmsh.model.addDiscreteEntity(3, tag)

            gmsh.model.mesh.addNodes(3, tag, node_tags, flat_coords)

            # Add elements (tetrahedrons = type 4)
            # Flatten element list
            ele_tags = list(range(1, len(elements) + 1))
            flat_eles = []
            for el in elements:
                flat_eles.extend(el)

            gmsh.model.mesh.addElements(3, tag, [4], [ele_tags], [flat_eles])

            # Force MSH v2.2 ASCII (more widely supported)
            gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
            gmsh.option.setNumber("Mesh.Binary", 0)

            # Save as .msh
            output_msh_path.parent.mkdir(parents=True, exist_ok=True)
            gmsh.write(str(output_msh_path))

            return output_msh_path

        finally:
            if gmsh.isInitialized():
                gmsh.finalize()

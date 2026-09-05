"""Measuring and interpreting completed scans.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import json
import logging
import os

import numpy as np

from pystxmcontrol.controller.agent_ports import (
    frame_geometry, frames_available, serves,
)
from pystxmcontrol.controller.tool_registry import tool

from .common import _decimate

log = logging.getLogger(__name__)


class AnalysisTools:
    """Measuring and interpreting completed scans."""

    @tool(requires=('frames',))
    def get_last_scan_stats(self, daq: str = "default") -> str:
        """Return statistics and spatial analysis of the most recently completed scan image.

        Computes mean, std, contrast, and the physical coordinates (µm) of the
        darkest region — useful for locating absorbing features such as particles.

        Args:
            daq: DAQ channel to analyse (e.g. 'default', 'xrf', 'tey'). Falls back to
                'default' if the requested channel is absent.
        """
        if not frames_available(self._image_model):
            return "Image model not available."

        all_images = self._image_model.get('all_detector_images')
        if not isinstance(all_images, dict):
            return "No scan image available yet — run a scan first."

        # Fall back to 'default' if the requested DAQ is absent
        image = all_images.get(daq)
        if image is None and daq != 'default':
            image = all_images.get('default')
            daq = 'default'
        if image is None or not isinstance(image, np.ndarray) or image.ndim < 2:
            return f"No valid image data for DAQ '{daq}'."

        ny, nx = image.shape[:2]
        flat = image.astype(float)

        mean_val  = float(np.mean(flat))
        std_val   = float(np.std(flat))
        min_val   = float(np.min(flat))
        max_val   = float(np.max(flat))
        contrast  = round(std_val / mean_val, 4) if mean_val > 0 else 0.0

        # Physical geometry from the model
        x_center, y_center, x_range, y_range = frame_geometry(self._image_model)

        def px_to_um(col, row):
            x = x_center + (col / max(nx - 1, 1) - 0.5) * x_range
            y = y_center + (row / max(ny - 1, 1) - 0.5) * y_range
            return round(x, 3), round(y, 3)

        # Single darkest pixel
        min_row, min_col = np.unravel_index(np.argmin(flat), flat.shape)
        darkest_x, darkest_y = px_to_um(min_col, min_row)

        # Centroid of pixels in the darkest 20 % of the dynamic range.
        # Using a range-based threshold (not a rank percentile) so that a mostly
        # uniform image with a few dark spots still isolates those spots correctly.
        dyn_range = max_val - min_val
        if dyn_range > 0:
            threshold = min_val + 0.20 * dyn_range
            dark_rows, dark_cols = np.where(flat <= threshold)
            if len(dark_rows) == 0:
                dark_rows, dark_cols = np.array([min_row]), np.array([min_col])
        else:
            # Uniform image — centroid is the image centre
            dark_rows, dark_cols = np.array([ny // 2]), np.array([nx // 2])
        centroid_x, centroid_y = px_to_um(
            float(np.mean(dark_cols)), float(np.mean(dark_rows))
        )

        available_daqs = list(all_images.keys())

        result = {
            "daq": daq,
            "available_daqs": available_daqs,
            "image_shape_px": [ny, nx],
            "scan_area_um": {"x_range": x_range, "y_range": y_range,
                             "x_center": x_center, "y_center": y_center},
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "min": round(min_val, 4),
            "max": round(max_val, 4),
            "contrast": contrast,
            "darkest_pixel_um": {"x": darkest_x, "y": darkest_y},
            "dark_region_centroid_um": {"x": centroid_x, "y": centroid_y},
            "interpretation": (
                "High contrast (>0.3) suggests absorbing features present. "
                "dark_region_centroid_um gives the physical centre of the "
                "darkest 10% of pixels — a good re-centre target for a zoom scan."
            ),
        }
        return json.dumps(result, indent=2)

    def _log_particle_map(self, qimg, meta: dict, text: str) -> str:
        """Write the just-rendered particle map to the open logbook. Returns a short status
        suffix for the finder's result. The map is always cached as the computed image
        (see caller) so add_to_logbook(attach='computed') can re-attach it even when no
        logbook is open here."""
        if qimg is None:
            return " (a particle map could not be rendered)."
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return (" A particle map was prepared but not saved — no logbook is open. Open one "
                    "and call add_to_logbook(attach='computed') to save it.")
        try:
            idx = model.add(snap_qimage=qimg, meta=meta, text=text, author="agent")
        except Exception as e:
            return f" (particle map prepared but the logbook write failed: {e})."
        return f" A particle map was saved to the logbook (entry #{idx})."

    @tool(requires=('frames',))
    def find_particles(self, max_particles: int | None = None, daq: str = "default",
                       save_map: bool = True) -> str:
        """Locate absorbing particles in a single transmission image and return scan regions.

        Uses Otsu thresholding on the inverted image plus connected-component analysis — this
        finds *generic* absorbers in ONE image; it is NOT element-specific.  For an element
        request (e.g. iron) after a two-energy scan, use count_element_particles() instead,
        which builds the elemental (OD-difference) map and finds the element-bearing particles.
        Results are stored internally and can be submitted immediately with start_multiregion_scan().

        Args:
            max_particles: cap on regions returned, ordered by size (default: all found).
            daq: detector channel to analyse.
            save_map: when True (default), render an overview image with a numbered box
                around each found region and save it to the open logbook (and cache it as the
                computed image for add_to_logbook(attach='computed')). Set False to skip.
        """
        if not frames_available(self._image_model):
            return "Image model not available."

        all_images = self._image_model.get('all_detector_images')
        if not isinstance(all_images, dict):
            return "No scan image available — run an overview scan first."

        image = all_images.get(daq)
        if image is None and daq != 'default':
            image = all_images.get('default')
            daq = 'default'
        if image is None or not isinstance(image, np.ndarray) or image.ndim < 2:
            return f"No valid image for DAQ '{daq}'."

        ny, nx = image.shape[:2]
        x_center, y_center, x_range, y_range = frame_geometry(self._image_model)
        px_x = x_range / nx   # µm per pixel in x
        px_y = y_range / ny   # µm per pixel in y

        boxes = _decimate(image, max_particles=max_particles)
        if not boxes:
            return "No particles found. Try a lower threshold or check that there is contrast in the image."

        # Convert pixel bboxes → µm scan regions with 30% padding (min 2 pixels each side)
        pad_px = 2
        regions = []
        for b in boxes:
            minr = max(0, b['minr'] - pad_px)
            minc = max(0, b['minc'] - pad_px)
            maxr = min(ny - 1, b['maxr'] + pad_px)
            maxc = min(nx - 1, b['maxc'] + pad_px)

            # Centre and size in µm
            cx = x_center + (((minc + maxc) / 2) / (nx - 1) - 0.5) * x_range
            cy = y_center + (((minr + maxr) / 2) / (ny - 1) - 0.5) * y_range
            rx = (maxc - minc) * px_x
            ry = (maxr - minr) * px_y

            regions.append({
                'xCenter': round(cx, 3), 'yCenter': round(cy, 3),
                'xRange':  round(rx, 3), 'yRange':  round(ry, 3),
            })

        self._particle_regions = regions
        # Store the overview pixel size (µm/px) so start_multiregion_scan() has a
        # sensible default if no pixel_size_nm is requested.
        self._overview_pixel_size_um = (px_x, px_y)

        # Render a map of the found regions on the overview and save it to the logbook so the
        # user gets a visual of where every ROI sits within the overview. The rendered figure
        # is also cached as the computed image (add_to_logbook(attach='computed')).
        logbook_note = ""
        if save_map:
            # col 0 → x_center - x_range/2, row 0 → y_center - y_range/2 (find_particles'
            # pixel-centre convention), drawn origin='lower' so boxes land on their features.
            extent = (x_center - x_range / 2.0, x_center + x_range / 2.0,
                      y_center - y_range / 2.0, y_center + y_range / 2.0)
            map_qimg = self._render_particle_map(
                image, regions, extent, title=f"Found {len(regions)} particle(s)")
            map_meta = {'result': 'particle map', 'particles': len(regions),
                        'overview_um': f"{x_range:.1f}×{y_range:.1f}"}
            if map_qimg is not None:
                self._remember_computed_figure(map_qimg, "particle map", map_meta)
            text = (f"Particle finder located {len(regions)} region(s) in a "
                    f"{x_range:.1f}×{y_range:.1f} µm overview. Numbered boxes mark each "
                    "region's footprint.")
            logbook_note = self._log_particle_map(map_qimg, map_meta, text)

        overview_pixel_nm = round(px_x * 1000, 1)
        result = {
            "particles_found": len(regions),
            "overview_pixel_size_nm": overview_pixel_nm,
            "overview_scan_um": {"x_range": x_range, "y_range": y_range,
                                  "x_center": x_center, "y_center": y_center},
            "regions": regions,
            "particle_map": logbook_note.strip() or "not requested (save_map=False)",
            "next_step": "Call start_multiregion_scan() to image all regions. "
                         "Pass pixel_size_nm to scan at higher resolution than the overview "
                         f"(overview was {overview_pixel_nm} nm/px).",
        }
        return json.dumps(result, indent=2)

    @tool(requires=('recommendations',))
    def get_intelligence_recommendations(self) -> str:
        """Return any pending recommendations from the intelligence module and clear the queue.

        The intelligence module analyses each completed scan and posts structured
        recommendations here, e.g. recentre suggestions (off-centre feature) and focus
        calibrations. (Two-energy element mapping is NOT posted here — the task agent owns
        that: call count_element_particles() to build the elemental map and find element
        particles on demand.)

        This tool drains the queue — call it after every wait_for_scan().
        """
        if not serves(self._image_model, "recommendations"):
            return ("Intelligence recommendations are not available in this session "
                    "— nothing is subscribed to the server's intelligence stream.")

        pending = list(self._image_model.get("pending_recommendations") or [])
        self._image_model.set("pending_recommendations", [])

        for rec in pending:
            # Cache the most recent focus recommendation for apply_focus_calibration().
            if rec.get("subtype") == "focus" and rec.get("delta_z") is not None:
                self._last_focus_report = rec

        if not pending:
            return "No recommendations pending."

        return json.dumps({"recommendations": pending}, indent=2)

    def _get_scan_buffer(self) -> list:
        """Return the buffered-scan records (newest last), or [] if unavailable."""
        buf = self._image_model.get('scan_buffer')
        if buf is None:
            return []
        try:
            return list(buf)
        except TypeError:
            return []

    def _get_buffered_scan(self, scan_id: str | None = None,
                           index: int | None = None,
                           min_energies: int = 1) -> dict | None:
        """Resolve a single buffered-scan record.

        Selection order: explicit *index* (0 = oldest, -1 = newest), then *scan_id*
        substring match, otherwise the most recent record with >= min_energies frames.
        Returns None when nothing matches.
        """
        records = self._get_scan_buffer()
        if not records:
            return None
        if index is not None:
            try:
                return records[index]
            except IndexError:
                return None
        if scan_id:
            for rec in reversed(records):
                if scan_id in (rec.get('scan_id') or ''):
                    return rec
            return None
        for rec in reversed(records):
            if len(rec.get('energies') or []) >= min_energies:
                return rec
        return None

    @tool(requires=('frames',))
    def list_buffered_scans(self) -> str:
        """List the completed scans held in memory, newest last.

        The GUI retains the last several completed scans (full multi-energy stacks) so
        the agent can analyse a prior scan without re-running it — e.g. count_element_particles()
        on a two-energy scan that is no longer the most recent.  Each entry's 'index' can be
        passed to count_element_particles(scan_index=...).
        """
        records = self._get_scan_buffer()
        if not records:
            return ("No scans buffered yet. Buffering happens when an Image scan completes "
                    "in the GUI (requires the GUI controller; not available in headless runs).")
        out = []
        for i, rec in enumerate(records):
            energies = rec.get('energies') or []
            out.append({
                "index": i,
                "scan_id": os.path.basename(rec.get('scan_id') or '') or None,
                "scan_type": rec.get('scan_type') or None,
                "n_energies": len(energies),
                "energy_range_eV": ([round(float(min(energies)), 2),
                                     round(float(max(energies)), 2)] if energies else None),
            })
        return json.dumps({"buffered_scans": out, "count": len(out)}, indent=2)

    @tool(requires=('frames',))
    def count_element_particles(self, pre_energy: float | None = None,
                                edge_energy: float | None = None,
                                daq: str = "default", region: int = 0,
                                scan_id: str | None = None,
                                scan_index: int | None = None,
                                max_particles: int | None = None,
                                save_map: bool = True) -> str:
        """Count particles and how many contain an element, from a buffered two-energy scan.

        Builds the two-energy elemental map (the same OD-difference the Analysis tab's Map
        button computes) from a buffered multi-energy scan, then counts (a) all particles
        via pre-edge absorption and (b) the element-containing subset via the elemental map.
        Frames within one scan are already co-registered, so no alignment is needed.

        Use this for element questions (e.g. "how many particles contain iron?") after a
        two-energy scan (pre-edge + edge).  Unlike find_particles() (generic absorbers in one
        image) this needs two energies.  This is the single owner of two-energy elemental
        mapping — it works directly on the in-memory buffered scan and also caches the map so
        add_to_logbook(attach="computed") can save it.

        The element-containing regions are stored for start_multiregion_scan(), so you can
        immediately zoom into the element-bearing particles.

        Args:
            pre_energy:  pre-edge energy in eV; snaps to the nearest frame. Omit to use the
                         lowest-energy frame.
            edge_energy: on-edge energy in eV; snaps to the nearest frame. Omit to use the
                         highest-energy frame.
            daq:         detector channel to analyse (default 'default').
            region:      scan-region index for multi-region scans (default 0).
            scan_id:     analyse a specific buffered scan by id substring; default = most
                         recent scan with >= 2 energies.
            scan_index:  analyse a specific buffered scan by index (see list_buffered_scans);
                         takes precedence over scan_id.
            max_particles: cap on element regions returned, ordered by size (default: all).
            save_map: when True (default), render the elemental map with a numbered box around
                each element-containing region and save it to the open logbook (and cache it as
                the computed image for add_to_logbook(attach='computed')). Set False to skip.
        """
        from pystxmcontrol.utils.image import (two_energy_map, otsu_absorption_mask,
                                               find_feature_boxes)

        rec = self._get_buffered_scan(scan_id=scan_id, index=scan_index, min_energies=2)
        if rec is None:
            return ("No buffered two-energy scan found. Run a two-energy scan (pre-edge + edge), "
                    "or call list_buffered_scans() to see what is available.")

        stx = rec.get('stxm')
        energies = np.asarray(rec.get('energies') or [], dtype=float)
        if stx is None or energies.size < 2:
            return "Buffered scan has fewer than two energies — element mapping needs two."

        interp = getattr(stx, 'interp_counts', None)
        if not isinstance(interp, dict):
            return "Buffered scan has no image data."
        if daq not in interp and 'default' in interp:
            daq = 'default'
        if daq not in interp:
            return f"No detector channel '{daq}' in buffered scan."
        try:
            stack3 = np.asarray(interp[daq][region], dtype=float)
        except (IndexError, TypeError):
            return f"Region {region} not available in buffered scan."
        if stack3.ndim != 3 or stack3.shape[0] < 2:
            return "Buffered scan region does not contain a two-energy stack."

        # Resolve the two frame indices: nearest-energy snap, or first/last fallback.
        pre_idx = (int(np.argmin(np.abs(energies - pre_energy)))
                   if pre_energy is not None else 0)
        edge_idx = (int(np.argmin(np.abs(energies - edge_energy)))
                    if edge_energy is not None else energies.size - 1)
        if pre_idx == edge_idx:
            return ("Pre-edge and edge energies resolved to the same frame "
                    f"({float(energies[pre_idx])} eV). Choose two distinct energies.")
        pre = stack3[pre_idx]
        edge = stack3[edge_idx]

        # Element map (bright where the element absorbs more on the edge) and total particles.
        element_map, valid = two_energy_map(pre, edge)

        # Retain the computed map so the agent can save it to the logbook
        # (add_to_logbook(attach="computed")); it is not a live scan frame.
        self._remember_computed_image(
            element_map,
            label="two-energy elemental map",
            meta={
                "computation": "two-energy elemental (OD-difference) map",
                "pre_energy": f"{float(energies[pre_idx]):.2f} eV",
                "edge_energy": f"{float(energies[edge_idx]):.2f} eV",
                "daq": daq,
                "scan_id": os.path.basename(rec.get('scan_id') or '') or None,
            },
        )
        element_mask = otsu_absorption_mask(element_map, dark=False, valid=valid)
        total_mask = otsu_absorption_mask(pre, dark=True)

        element_boxes = find_feature_boxes(element_mask, max_features=max_particles)
        total_boxes = find_feature_boxes(total_mask)

        # Pixel boxes -> µm scan regions, using the buffered scan's requested grid.
        ny, nx = pre.shape[:2]
        try:
            xpos = np.asarray(stx.xPos[region], dtype=float)
            ypos = np.asarray(stx.yPos[region], dtype=float)
        except (AttributeError, IndexError, TypeError):
            xpos = ypos = None

        regions = []
        logbook_note = ""
        if xpos is not None and ypos is not None and xpos.size >= 2 and ypos.size >= 2:
            pad_px = 2
            cols = np.arange(xpos.size)
            rows = np.arange(ypos.size)
            for b in element_boxes:
                minr = max(0, b['minr'] - pad_px)
                minc = max(0, b['minc'] - pad_px)
                maxr = min(ny - 1, b['maxr'] + pad_px)
                maxc = min(nx - 1, b['maxc'] + pad_px)
                cx = float(np.interp((minc + maxc) / 2.0, cols, xpos))
                cy = float(np.interp((minr + maxr) / 2.0, rows, ypos))
                rx = abs(float(xpos[min(maxc, nx - 1)] - xpos[minc]))
                ry = abs(float(ypos[min(maxr, ny - 1)] - ypos[minr]))
                regions.append({
                    'xCenter': round(cx, 3), 'yCenter': round(cy, 3),
                    'xRange': round(rx, 3), 'yRange': round(ry, 3),
                })
            self._particle_regions = regions
            px_x = abs(float(xpos[-1] - xpos[0])) / max(nx - 1, 1)
            px_y = abs(float(ypos[-1] - ypos[0])) / max(ny - 1, 1)
            self._overview_pixel_size_um = (px_x, px_y)

            # Map the element-containing regions on the elemental map itself (bright = element)
            # so the user sees where every ROI sits. Extent uses the raw xPos/yPos endpoints
            # (col 0 → xpos[0], row 0 → ypos[0]) so the picture stays faithful to the scan
            # direction while the boxes, in absolute µm, stay aligned. Rendered even when no
            # element region is found — the map alone documents the negative result.
            if save_map:
                extent = (float(xpos[0]), float(xpos[-1]), float(ypos[0]), float(ypos[-1]))
                map_qimg = self._render_particle_map(
                    element_map, regions, extent,
                    title=f"{len(regions)} element particle(s)")
                map_meta = {
                    'result': 'element particle map',
                    'element_particles': len(regions),
                    'pre_energy': f"{float(energies[pre_idx]):.2f} eV",
                    'edge_energy': f"{float(energies[edge_idx]):.2f} eV",
                    'daq': daq,
                }
                if map_qimg is not None:
                    # Overwrite the cached elemental map with the boxed version so
                    # add_to_logbook(attach='computed') attaches the annotated map.
                    self._remember_computed_figure(map_qimg, "element particle map", map_meta)
                text = (f"Two-energy element map ({float(energies[pre_idx]):.1f} → "
                        f"{float(energies[edge_idx]):.1f} eV): {len(regions)} element-containing "
                        "region(s); numbered boxes mark each footprint.")
                logbook_note = self._log_particle_map(map_qimg, map_meta, text)
        elif save_map:
            logbook_note = (" A map could not be built — the buffered scan has no per-pixel "
                            "position data; the elemental map is still cached for "
                            "add_to_logbook(attach='computed').")

        total = len(total_boxes)
        n_elem = len(element_boxes)
        result = {
            "total_particles": total,
            "element_particles": n_elem,
            "fraction_with_element": round(n_elem / total, 3) if total else None,
            "pre_energy_eV": round(float(energies[pre_idx]), 2),
            "edge_energy_eV": round(float(energies[edge_idx]), 2),
            "daq": daq,
            "scan_id": os.path.basename(rec.get('scan_id') or '') or None,
            "element_regions": regions,
            "element_map": logbook_note.strip() or "not requested (save_map=False)",
            "next_step": ("Element regions stored. Call start_multiregion_scan(pixel_size_nm=...) "
                          "to image the element-containing particles at higher resolution."
                          if regions else
                          "No element-containing particles detected at these two energies."),
        }
        return json.dumps(result, indent=2)

    @tool(requires=('frames',))
    def analyze_energy_stack(self,
                             file: str | None = None,
                             daq: str = "default", region: int = 0,
                             scan_id: str | None = None,
                             scan_index: int | None = None,
                             n_components: int = 4, n_clusters: int = 4,
                             max_iter: int = 500, init: str = "nndsvda",
                             log: bool = True, note: str | None = None) -> str:
        """Analyse a multi-energy stack with autoProcess + non-negative matrix factorisation.

        Runs the same pipeline as the Analysis tab's Auto Process + Calculate NNMF buttons,
        headless: subtract dark field -> despike -> align frames -> optical density (calcOD),
        then NMF (sklearn) with k-means clustering of the NMF weight maps. Produces a
        colour-coded cluster map and the per-cluster mean OD spectra.

        Use this for a many-energy spectral stack (a NEXAFS / energy-stack scan), NOT a
        two-energy scan (use count_element_particles for two energies). By default it analyses
        the most recent buffered multi-energy scan; pass file=... to analyse a saved
        .stxm/.hdr/.cxi stack instead.

        When log is True (default) and a logbook is open, it posts one entry containing a
        combined figure — the cluster map beside the cluster spectra — authored as 'agent'.
        The figure is also cached so add_to_logbook(attach='computed') can re-post it.

        Args:
            file:         analyse a saved stack file (.stxm/.hdr/.cxi) by path; omit to use a
                          buffered in-memory scan.
            daq:          detector channel (buffered scans only; default 'default').
            region:       scan-region index for multi-region scans/files (default 0).
            scan_id:      analyse a specific buffered scan by id substring (buffered only).
            scan_index:   analyse a specific buffered scan by index (see list_buffered_scans);
                          takes precedence over scan_id.
            n_components: NMF components (default 4). Clamped to the number of energies.
            n_clusters:   k-means clusters of the NMF weight maps (default 4).
            max_iter:     NMF max iterations (default 500).
            init:         NMF initialisation ('nndsvda' default, or 'random').
            log:          post the result to the logbook (default True).
            note:         logbook entry text; a summary is generated when omitted.
        """
        from pystxmcontrol.utils.stack import stack

        # ---- resolve the stack: saved file, or in-memory buffered scan --------------
        if file:
            path = os.path.expanduser(file)
            if not os.path.isfile(path):
                return f"Stack file not found: {file}"
            if not path.lower().endswith(('.stxm', '.hdr', '.cxi')):
                return "Unsupported stack file — expected a .stxm, .hdr, or .cxi file."
            try:
                stk = stack(fileName=path, iRegion=region)
            except Exception as e:
                return f"Failed to open stack file {os.path.basename(path)}: {e}"
            source = os.path.basename(path)
            if getattr(stk, 'processedFrames', None) is None or len(stk.energies) < 3:
                return (f"Stack '{source}' has fewer than 3 energies — NMF needs a multi-energy "
                        "stack. Use count_element_particles for a two-energy scan.")
        else:
            rec = self._get_buffered_scan(scan_id=scan_id, index=scan_index, min_energies=3)
            if rec is None:
                return ("No buffered multi-energy stack found. Run an energy stack (>= 3 "
                        "energies), pass file=..., or call list_buffered_scans().")
            stk, err = self._stack_from_buffered_scan(rec, daq=daq, region=region)
            if stk is None:
                return err
            source = os.path.basename(rec.get('scan_id') or '') or "buffered scan"

        n_energies = int(len(stk.energies))
        # NMF requires n_components <= n_features (energies); clamp with a note.
        clamp_note = ""
        if n_components > n_energies:
            clamp_note = (f"n_components reduced from {n_components} to {n_energies} "
                          "to match the number of energies")
            n_components = n_energies

        # ---- autoProcess (dark field -> despike -> align -> OD), then NMF -----------
        try:
            stk.subtractDarkField()
            stk.despike()
            stk.alignFrames(mode='manualtranslation')
            stk.calcOD()
        except Exception as e:
            return f"autoProcess failed on '{source}': {e}"
        try:
            stk.calcNMF(n_components=n_components, n_clusters=n_clusters,
                        max_iter=max_iter, init=init)
        except Exception as e:
            return f"NMF failed on '{source}': {e}"

        energies = np.asarray(stk.energies, dtype=float)
        cluster_sizes = [int((stk.clusters == i).sum()) for i in range(n_clusters)]

        meta = {
            "computation": "autoProcess + NNMF (cluster map + cluster spectra)",
            "source": source,
            "n_components": n_components,
            "n_clusters": n_clusters,
            "n_energies": n_energies,
            "energy_range_eV": f"{energies.min():.2f}-{energies.max():.2f}",
            "daq": None if file else daq,
        }

        # Render the combined cluster-map + cluster-spectra figure and cache it so the
        # logbook post below (or a later add_to_logbook(attach='computed')) can embed it.
        title = f"NNMF of {source}: {n_components} components, {n_clusters} clusters"
        qimg = self._render_nmf_figure(stk, title=title)
        self._remember_computed_figure(qimg, label="NNMF cluster map + spectra", meta=meta)

        result = {
            "source": source,
            "n_components": n_components,
            "n_clusters": n_clusters,
            "n_energies": n_energies,
            "energy_range_eV": [round(float(energies.min()), 2),
                                round(float(energies.max()), 2)],
            "cluster_pixel_counts": cluster_sizes,
            "stack_shape": list(stk.odFrames.shape),
        }
        if clamp_note:
            result["clamp_note"] = clamp_note

        # ---- one-shot logbook post -------------------------------------------------
        if log:
            model = self._logbook_model
            if model is None or not getattr(model, "folder", None):
                result["logbook"] = ("not posted — no logbook is open; open one in the Logbook "
                                     "tab, then call add_to_logbook(attach='computed').")
            elif qimg is None:
                result["logbook"] = "not posted — the figure could not be rendered."
            else:
                text = note or (
                    f"NNMF analysis of {source}: {n_components} NMF components, "
                    f"{n_clusters} clusters over {n_energies} energies "
                    f"({energies.min():.2f}-{energies.max():.2f} eV). "
                    "Cluster map and per-cluster OD spectra attached.")
                try:
                    index = model.add(snap_qimage=qimg, meta=meta, text=text, author="agent")
                    result["logbook"] = (f"posted entry #{index} to "
                                         f"'{os.path.basename(model.folder)}'.")
                except Exception as e:
                    result["logbook"] = f"failed to post: {e}"
        else:
            result["logbook"] = ("not requested — the figure is cached; call "
                                 "add_to_logbook(attach='computed') to post it.")

        return json.dumps(result, indent=2)

    @tool(requires=('frames',))
    def get_image_center_of_mass(self, daq: str = "default") -> str:
        """Return the center of mass of the Otsu-thresholded absorption mask.

        Inverts the transmission image so absorbing particles are bright, applies
        an Otsu threshold to produce a binary mask, then computes the unweighted
        centroid of that mask.  This is the same thresholding used by find_particles()
        so the result is consistent with particle detection.

        Returns physical µm coordinates that can be passed directly to
        update_scan(x_center=..., y_center=...) to re-centre the next scan on the feature.

        Args:
            daq: detector channel to use (default 'default').
        """
        from pystxmcontrol.utils.image import image_com, otsu_absorption_mask

        if not frames_available(self._image_model):
            return "Image model not available."

        all_images = self._image_model.get('all_detector_images')
        if not isinstance(all_images, dict):
            return "No scan image available — run a scan first."

        image = all_images.get(daq)
        if image is None and daq != 'default':
            image = all_images.get('default')
            daq = 'default'
        if image is None or not isinstance(image, np.ndarray) or image.ndim < 2:
            return f"No valid image data for DAQ '{daq}'."

        x_center, y_center, x_range, y_range = frame_geometry(self._image_model)

        result = image_com(image, x_center, y_center, x_range, y_range)
        if result is None:
            return "Otsu threshold produced an empty mask — no absorbing features detected."
        com_x, com_y = result

        masked_pixels = int(otsu_absorption_mask(image).sum())
        return json.dumps({
            "daq": daq,
            "masked_pixels": masked_pixels,
            "center_of_mass_um": {"x": round(com_x, 3), "y": round(com_y, 3)},
            "scan_center_um":    {"x": x_center, "y": y_center},
            "offset_from_scan_center_um": {
                "x": round(com_x - x_center, 3),
                "y": round(com_y - y_center, 3),
            },
            "note": "Pass center_of_mass_um values to update_scan(x_center=..., y_center=...) "
                    "to re-centre the next scan on this feature.",
        }, indent=2)

    def _latest_two_energy_map(self):
        """Build the OD-difference (two-energy elemental) map from the newest buffered
        two-energy scan. Returns (array, meta) on success, or (None, reason).

        This lets add_to_logbook(attach="computed") save the map even when the agent
        obtained its particle count from the intelligence module (which computes the map
        server-side and cannot ship the array over the monitor stream) rather than from
        count_element_particles. Requires the GUI scan buffer — unavailable headless.
        """
        try:
            from pystxmcontrol.utils.image import two_energy_map
        except Exception as e:
            return None, f"image utilities unavailable ({e})"
        rec = self._get_buffered_scan(min_energies=2)
        if rec is None:
            return None, ("no buffered two-energy scan (buffering needs a completed two-energy "
                          "Image scan in the GUI; unavailable in headless runs)")
        stx = rec.get('stxm')
        energies = np.asarray(rec.get('energies') or [], dtype=float)
        interp = getattr(stx, 'interp_counts', None)
        if stx is None or energies.size < 2 or not isinstance(interp, dict):
            return None, "buffered scan has no two-energy image data"
        daq = 'default' if 'default' in interp else next(iter(interp), None)
        if daq is None:
            return None, "no detector channel in buffered scan"
        try:
            stack3 = np.asarray(interp[daq][0], dtype=float)
        except (IndexError, TypeError):
            return None, "buffered scan region unavailable"
        if stack3.ndim != 3 or stack3.shape[0] < 2:
            return None, "buffered scan is not a two-energy stack"
        diff, _valid = two_energy_map(stack3[0], stack3[-1])
        meta = {
            "computation": "two-energy elemental (OD-difference) map",
            "pre_energy": f"{float(energies[0]):.2f} eV",
            "edge_energy": f"{float(energies[-1]):.2f} eV",
            "daq": daq,
            "scan_id": os.path.basename(rec.get('scan_id') or '') or None,
        }
        return diff, meta

    def _stack_from_buffered_scan(self, rec: dict, daq: str = "default", region: int = 0):
        """Build a bare stack object from a buffered scan's in-memory transmission cube.

        Returns (stack, "") on success or (None, error_message).  The returned stack has
        processedFrames / energies populated so the autoProcess + NMF stack methods run
        headless exactly as they would on a file-loaded stack (they operate on ndarrays,
        not on the rawFrames image objects that file loading builds)."""
        from pystxmcontrol.utils.stack import stack
        stx = rec.get('stxm')
        energies = np.asarray(rec.get('energies') or [], dtype=float)
        if stx is None or energies.size < 3:
            return None, "Buffered scan has fewer than three energies — NMF needs a stack."
        interp = getattr(stx, 'interp_counts', None)
        if not isinstance(interp, dict):
            return None, "Buffered scan has no image data."
        if daq not in interp and 'default' in interp:
            daq = 'default'
        if daq not in interp:
            return None, f"No detector channel '{daq}' in buffered scan."
        try:
            cube = np.asarray(interp[daq][region], dtype=float)
        except (IndexError, TypeError):
            return None, f"Region {region} not available in buffered scan."
        if cube.ndim != 3 or cube.shape[0] < 3:
            return None, "Buffered scan region is not a multi-energy stack."
        stk = stack()
        stk.processedFrames = cube.copy()
        stk.energies = energies
        stk.shape = stk.processedFrames.shape
        return stk, ""

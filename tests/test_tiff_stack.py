"""Loading a multi-page TIFF plus its sidecar energy list.

The format carries frames and energies and nothing else, so what these tests pin down
is mostly what happens at the edges: a sidecar that is missing, that disagrees with the
TIFF, or that is a table rather than a list; and a pixel size that the file does not
record, which must stay unknown rather than become a plausible-looking number.
"""

import numpy as np
import pytest
import tifffile

from pystxmcontrol.gui.stack_files import describe_stack
from pystxmcontrol.utils import tiff_stack


def write_stack(tmp_path, name="scan", n=4, shape=(6, 8), energies=None,
               sidecar=".txt", **tiff_kwargs):
    """A multi-page TIFF and its energy list; returns (tiff path, energies)."""
    energies = [700.0 + i for i in range(n)] if energies is None else energies
    frames = np.arange(n * shape[0] * shape[1], dtype="float32").reshape((n, *shape))
    path = tmp_path / f"{name}.tif"
    # photometric: without it tifffile stores a short first axis as RGB planes rather
    # than as the separate pages a real export writes.
    tiff_kwargs.setdefault("photometric", "minisblack")
    tifffile.imwrite(str(path), frames, **tiff_kwargs)
    if sidecar is not None:
        (tmp_path / f"{name}{sidecar}").write_text(
            "\n".join(str(e) for e in energies) + "\n")
    return path, energies


class TestReadingThePair:

    def test_frames_and_energies_come_back_together(self, tmp_path):
        path, energies = write_stack(tmp_path, n=4, shape=(6, 8))
        st = tiff_stack.read_tiff_stack(str(path))
        assert st.frames.shape == (4, 6, 8)
        assert list(st.energies) == energies
        assert st.energy_file.endswith("scan.txt")

    def test_a_single_page_tiff_is_a_one_frame_stack(self, tmp_path):
        path, _ = write_stack(tmp_path, n=1, shape=(6, 8))
        assert tiff_stack.read_tiff_stack(str(path)).frames.shape == (1, 6, 8)

    def test_the_sidecar_may_be_dat_or_csv(self, tmp_path):
        path, energies = write_stack(tmp_path, sidecar=".dat")
        assert list(tiff_stack.read_tiff_stack(str(path)).energies) == energies

    def test_a_missing_sidecar_says_which_file_is_wanted(self, tmp_path):
        path, _ = write_stack(tmp_path, sidecar=None)
        with pytest.raises(ValueError, match=r"scan\.txt"):
            tiff_stack.read_tiff_stack(str(path))

    def test_a_colour_tiff_is_refused(self, tmp_path):
        """Not a spectral stack — and silently reading its channels as energies would
        produce three nonsense 'frames'."""
        path = tmp_path / "rgb.tif"
        tifffile.imwrite(str(path), np.zeros((6, 8, 3), dtype="uint8"), photometric="rgb")
        (tmp_path / "rgb.txt").write_text("700.0\n")
        with pytest.raises(ValueError, match="colour image"):
            tiff_stack.read_tiff_stack(str(path))

    def test_a_disagreeing_sidecar_names_both_counts(self, tmp_path):
        """Silently zipping 4 frames to 3 energies would mislabel every frame."""
        path, _ = write_stack(tmp_path, n=4, energies=[700.0, 701.0, 702.0])
        with pytest.raises(ValueError, match="3 energies.*4 pages"):
            tiff_stack.read_tiff_stack(str(path))


class TestReadingTheEnergies:

    def _energies(self, tmp_path, text):
        path = tmp_path / "e.txt"
        path.write_text(text)
        return tiff_stack.read_energies(str(path))

    def test_one_per_line(self, tmp_path):
        assert list(self._energies(tmp_path, "700.5\n701.5\n702.5\n")) == [700.5, 701.5, 702.5]

    def test_comments_blank_lines_and_a_header_are_skipped(self, tmp_path):
        text = "# energies (eV)\nEnergy\n\n700.0\n701.0  ; trailing note\n"
        assert list(self._energies(tmp_path, text)) == [700.0, 701.0]

    def test_a_wrapped_list_reads_as_one_sequence(self, tmp_path):
        assert list(self._energies(tmp_path, "700 701 702\n703 704\n")) == \
            [700.0, 701.0, 702.0, 703.0, 704.0]

    def test_a_table_keeps_the_column_that_reads_as_energies(self, tmp_path):
        """An index column alongside the energies must not become the energy axis."""
        text = "0, 700.0\n1, 701.0\n2, 702.0\n"
        assert list(self._energies(tmp_path, text)) == [700.0, 701.0, 702.0]

    def test_an_ambiguous_table_is_refused(self, tmp_path):
        """Two columns that both read as energies: guessing would mislabel the frames."""
        with pytest.raises(ValueError, match="columns"):
            self._energies(tmp_path, "700.0 800.0\n701.0 801.0\n702.0 802.0\n")

    def test_a_file_with_no_numbers_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="no numbers"):
            self._energies(tmp_path, "energies\nnone recorded\n")


class TestPixelSize:
    """The pair records no scale unless the TIFF's resolution tags are really set."""

    def test_unset_resolution_tags_mean_unknown(self, tmp_path):
        # What the MANTiS export writes: resolution 1 with ResolutionUnit NONE.
        path, _ = write_stack(tmp_path)
        assert tiff_stack.read_tiff_stack(str(path)).pixel_size_um is None

    def test_centimetre_resolution_is_converted(self, tmp_path):
        # 250 px/cm → 40 µm per pixel.
        path, _ = write_stack(tmp_path, resolution=(250, 250), resolutionunit="CENTIMETER")
        assert tiff_stack.read_tiff_stack(str(path)).pixel_size_um == pytest.approx(40.0)

    def test_an_imagej_micron_scale_is_used(self, tmp_path):
        path, _ = write_stack(tmp_path, imagej=True, resolution=(20.0, 20.0),
                              metadata={"unit": "micron"})
        assert tiff_stack.read_tiff_stack(str(path)).pixel_size_um == pytest.approx(0.05)

    def test_an_absurd_scale_is_treated_as_unknown(self, tmp_path):
        """A kilometre per pixel is a mis-tagged file, not a STXM scan."""
        path, _ = write_stack(tmp_path, imagej=True, resolution=(1e-6, 1e-6),
                              metadata={"unit": "micron"})
        assert tiff_stack.read_tiff_stack(str(path)).pixel_size_um is None


class TestTheAnalysisStack:
    """What the analysis app actually gets when it opens one of these."""

    def _stack(self, path):
        from pystxmcontrol.utils.stack import stack
        return stack(fileName=str(path))

    def test_the_stack_loads_frames_energies_and_one_region(self, tmp_path):
        path, energies = write_stack(tmp_path, n=4, shape=(6, 8))
        st = self._stack(path)
        assert st.processedFrames.shape == (4, 6, 8)
        assert list(st.energies) == energies
        assert st.hdr == {"nRegions": 1}          # the viewer reads its region count here
        assert st.daq_list == ["default"]

    def test_an_unrecorded_pixel_size_is_flagged_not_invented(self, tmp_path):
        """reset() and the crop/registration paths divide by the pixel size, so the
        stack carries a placeholder — but it must not pass as a measurement."""
        path, _ = write_stack(tmp_path)
        st = self._stack(path)
        assert st.pixelSizeKnown is False
        assert st.xpixelsize == 1.0
        assert "not recorded" in "\n".join(describe_stack(st))

    def test_a_recorded_pixel_size_is_adopted(self, tmp_path):
        path, _ = write_stack(tmp_path, shape=(6, 8), resolution=(250, 250),
                              resolutionunit="CENTIMETER")
        st = self._stack(path)
        assert st.pixelSizeKnown is True
        assert st.xpixelsize == pytest.approx(40.0)
        assert "X range:       320.000 µm" in "\n".join(describe_stack(st))

    def test_optical_density_survives_non_positive_pixels(self, tmp_path):
        """Zero and slightly negative pixels make -log() non-finite; those are scrubbed,
        because a single NaN fails PCA/NMF outright."""
        path, _ = write_stack(tmp_path, n=4, shape=(6, 8))
        st = self._stack(path)
        st.processedFrames[0, 0, 0] = 0.0
        st.processedFrames[0, 0, 1] = -1e-6
        st.calcOD()
        assert np.isfinite(st.odFrames).all()

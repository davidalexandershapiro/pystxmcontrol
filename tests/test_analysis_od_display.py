"""The analysis viewer must show what the OD checkbox says it is showing.

Both the Auto Process slot and the OD checkbox slot set the spectrum plot's y-axis
before switching the image view.  When that axis call raised — it used an AxisItem API
the installed pyqtgraph does not have — Qt swallowed the exception inside the slot and
the half-finished result was a checkbox and a spectrum plot reading OD above an image
view still showing transmission, with nothing on screen to say so.
"""

import numpy as np
import pytest
import tifffile

pytest.importorskip("PySide6", reason="GUI tests need PySide6")
pytest.importorskip("pyqtgraph", reason="the analysis viewer needs pyqtgraph")


@pytest.fixture(scope="module")
def stack_file(tmp_path_factory):
    """A small TIFF stack + energy list: enough frames for OD and an I0 region."""
    tmp_path = tmp_path_factory.mktemp("odstack")
    n, ny, nx = 4, 12, 16
    frames = np.full((n, ny, nx), 100.0, dtype="float32")
    frames[:, 4:8, 6:11] = 40.0                 # an absorbing blob to give OD contrast
    path = tmp_path / "od_demo.tif"
    tifffile.imwrite(str(path), frames, photometric="minisblack")
    (tmp_path / "od_demo.txt").write_text("\n".join(str(700.0 + i) for i in range(n)))
    return str(path)


@pytest.fixture(scope="module")
def analysis(qapp, stack_file):
    from pystxmcontrol.gui.dashboard.analysis_app import AnalysisApp
    widget = AnalysisApp()
    yield widget
    widget.close()
    widget.deleteLater()


def shown(widget):
    """The frames currently in the image view, back in (n_e, ny, nx) order."""
    return widget.ui.a2_imageView.image.transpose(0, 2, 1)


class TestOpticalDensityDisplay:

    def test_auto_process_switches_the_view_to_optical_density(self, analysis, stack_file):
        analysis.load_file(stack_file)
        sv = analysis.ui.a2_stack_viewer
        assert np.allclose(shown(analysis), sv.stack.processedFrames)

        sv.autoProcess()

        assert analysis.ui.a2_odCheckbox.isChecked()
        assert np.allclose(shown(analysis), sv.stack.odFrames)

    def test_the_checkbox_switches_the_view_both_ways(self, analysis, stack_file):
        analysis.load_file(stack_file)
        sv = analysis.ui.a2_stack_viewer
        sv.autoProcess()
        od, transmission = sv.stack.odFrames, sv.stack.processedFrames

        analysis.ui.a2_odCheckbox.setChecked(False)
        assert np.allclose(shown(analysis), transmission)

        analysis.ui.a2_odCheckbox.setChecked(True)
        assert np.allclose(shown(analysis), od)

    def test_the_axis_label_follows_the_data(self, analysis, stack_file):
        analysis.load_file(stack_file)
        sv = analysis.ui.a2_stack_viewer
        axis = analysis.ui.a2_spectrumPlot.getPlotItem().getAxis('left')

        sv.autoProcess()
        assert axis.labelText == "Optical Density"
        analysis.ui.a2_odCheckbox.setChecked(False)
        assert axis.labelText == "Counts"


class TestOpticalDensityAxisScale:
    """OD ticks are the OD values — pyqtgraph must not quietly rescale them.

    The axis carries no unit string, so a hidden x1000 rescale would leave no prefix in
    the label to reveal it: the plot would read 500 for an OD of 0.5.
    """

    def _od_axis(self, analysis):
        pi = analysis.ui.a2_spectrumPlot.getPlotItem()
        analysis._a2_set_y_axis_od_mode(pi, True)
        return pi.getAxis('left')

    @pytest.mark.parametrize("lo, hi", [(0.0, 0.5), (0.0001, 0.0005), (0.0, 5.0)])
    def test_the_scale_stays_one_to_one_over_any_range(self, analysis, lo, hi):
        axis = self._od_axis(analysis)
        axis.setRange(lo, hi)
        assert axis.autoSIPrefixScale == 1.0
        assert "x1e" not in axis.labelString()

    def test_counts_mode_keeps_its_automatic_prefix(self, analysis):
        """Only OD is pinned: a counts axis should still scale, and say that it has."""
        pi = analysis.ui.a2_spectrumPlot.getPlotItem()
        analysis._a2_set_y_axis_od_mode(pi, False)
        axis = pi.getAxis('left')
        axis.setRange(0.0, 5e6)
        assert axis.autoSIPrefix is True
        assert "x1e+06" in axis.labelString()

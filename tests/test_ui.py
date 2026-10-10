import os
from pathlib import Path
import pytest


def test_ui_is_a_project_monitor_and_uses_one_worker(tmp_path):
    pytest.importorskip('PyQt6')
    from PyQt6.QtWidgets import QApplication
    from app.ui.window import Window
    from app.core.project import Project
    app=QApplication.instance() or QApplication([])
    project=Project.create(tmp_path,'Workspace B');window=Window(tmp_path)
    window.list.setCurrentRow(0);app.processEvents()
    assert window.project.root==project.root
    assert window.tabs.count()==4 and 'DRAFT' in window.status.text()
    assert window.renderer.currentText()=='software-egl'
    window.close()


def test_ui_pins_the_project_while_worker_runs(tmp_path):
    pytest.importorskip('PyQt6')
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QProcess
    from app.ui.window import Window
    app=QApplication.instance() or QApplication([]);window=Window(tmp_path)
    window.worker_state(QProcess.ProcessState.Starting)
    assert not window.list.isEnabled() and not window.new_button.isEnabled()
    window.worker_state(QProcess.ProcessState.NotRunning)
    assert window.list.isEnabled() and window.new_button.isEnabled()
    window.close()


def test_gui_startup_does_not_import_simulation_engines(tmp_path):
    pytest.importorskip('PyQt6')
    import subprocess,sys
    code='''from PyQt6.QtWidgets import QApplication
from app.ui.window import Window
import sys
app=QApplication([])
window=Window(sys.argv[1])
assert not any(name.split('.')[0] in ('mujoco','pxr','isaaclab','omni','torch') for name in sys.modules)
window.close()
'''
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_compare_tabs_do_not_grow_window_and_refit_after_resize(tmp_path):
    pytest.importorskip('PyQt6')
    from PyQt6.QtGui import QImage
    from PyQt6.QtWidgets import QApplication
    from app.core.project import Project
    from app.ui.window import Window

    app = QApplication.instance() or QApplication([])
    project = Project.create(tmp_path, 'Preview sizing')
    previews = project.root / 'working/validation/previews/000_side'
    previews.mkdir(parents=True)
    for name, size in [('side_by_side', (2560, 960)), ('overlay', (1280, 960)), ('difference', (960, 1280))]:
        image = QImage(*size, QImage.Format.Format_RGB32)
        image.fill(0x708090)
        assert image.save(str(previews / (name + '.png')))

    window = Window(tmp_path)
    window.timer.stop()
    try:
        window.show()
        window.tabs.setCurrentIndex(2)
        window.list.setCurrentRow(0)
        app.processEvents()
        initial = window.size()
        assert initial.width() <= 1300 and initial.height() <= 860
        for index in range(30):
            window.compare_tabs.setCurrentIndex(index % 3)
            app.processEvents()
            window.poll()
            app.processEvents()
            assert window.size() == initial
            label = list(window.pictures.values())[index % 3]
            assert label.pixmap().width() <= label.contentsRect().width()
            assert label.pixmap().height() <= label.contentsRect().height()

        window.resize(1000, 700)
        app.processEvents()
        window.poll()
        app.processEvents()
        assert window.width() == 1000 and window.height() == 700
        for label in window.pictures.values():
            assert label.pixmap().width() <= label.contentsRect().width()
            assert label.pixmap().height() <= label.contentsRect().height()
    finally:
        window.close()


def test_input_worker_uses_own_packages_instead_of_gui_pythonpath(tmp_path, monkeypatch):
    pytest.importorskip('PyQt6')
    from PIL import Image
    from PyQt6.QtWidgets import QApplication, QFileDialog
    from app.core.project import Project
    from app.ui.window import Window
    import sys

    app = QApplication.instance() or QApplication([])
    project = Project.create(tmp_path / 'projects', 'Isolated worker')
    image = tmp_path / 'input.png'
    Image.new('RGB', (64, 48)).save(image)
    gui_packages = tmp_path / 'gui-site'
    gui_packages.mkdir()
    (gui_packages / 'numpy.py').write_text('raise RuntimeError("GUI NumPy leaked into worker")')
    monkeypatch.setenv('PYTHONPATH', str(gui_packages))
    monkeypatch.setenv('PYTHONHOME', str(tmp_path / 'wrong-python-home'))
    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', lambda *args: ([str(image)], ''))
    window = Window(project.root.parent)
    window.timer.stop()
    try:
        window.list.setCurrentRow(0)
        window.python.setText(sys.executable)
        window.add('image')
        assert window.process.waitForFinished(5000), window.log.toPlainText()
        assert window.process.exitCode() == 0, window.log.toPlainText()
        assert len(project.evidence['images']) == 1
        assert os.environ['PYTHONHOME'].endswith('wrong-python-home')
    finally:
        window.close()

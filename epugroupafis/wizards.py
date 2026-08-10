import os

from pwem.wizards.wizard import EmWizard
from pyworkflow.gui.browser import FileBrowserWindow

import relion.convert as relionConvert

from .protocols import ProtGenerateAfisGroups


class EpugroupafisMtfSelector(EmWizard):
    """Select an MTF STAR file from Relion's predefined collection."""

    _targets = [(ProtGenerateAfisGroups, ['mtfFile'])]

    def show(self, form, *args):
        def setPath(fileInfo):
            form.setVar('mtfFile', fileInfo.getPath())

        mtfDir = os.path.join(os.path.dirname(relionConvert.__file__), 'mtfs')
        browser = FileBrowserWindow(
            'Select one of the predefined MTF files',
            form, mtfDir, onSelect=setPath)
        browser.show()
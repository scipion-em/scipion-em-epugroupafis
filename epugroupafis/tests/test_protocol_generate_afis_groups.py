import os
import tempfile
import unittest
from unittest.mock import patch

from emtable import Table

from epugroupafis.protocols import ProtGenerateAfisGroups
from epugroupafis.wizards import EpugroupafisMtfSelector


class _Movie:
    def __init__(self, fileName, micName):
        self._fileName = fileName
        self._micName = micName

    def getFileName(self):
        return self._fileName

    def getMicName(self):
        return self._micName


class TestGenerateAfisGroups(unittest.TestCase):
    def testMtfWizardTargetsProtocolAndSetsSelectedPath(self):
        class Form:
            def setVar(self, name, value):
                self.name = name
                self.value = value

        class FileInfo:
            @staticmethod
            def getPath():
                return '/tmp/mtf.star'

        form = Form()
        self.assertEqual([(ProtGenerateAfisGroups, ['mtfFile'])],
                         EpugroupafisMtfSelector._targets)

        with patch('epugroupafis.wizards.FileBrowserWindow') as browserClass:
            EpugroupafisMtfSelector().show(form)
            onSelect = browserClass.call_args.kwargs['onSelect']
            onSelect(FileInfo())
            browserClass.return_value.show.assert_called_once_with()

        self.assertEqual('mtfFile', form.name)
        self.assertEqual('/tmp/mtf.star', form.value)

    def testCreateRelionStarUsesScipionMicrographNames(self):
        with tempfile.TemporaryDirectory() as tmpDir:
            inputStar = os.path.join(tmpDir, 'movies.star')
            outputStar = os.path.join(tmpDir, 'movies_relion.star')
            with open(inputStar, 'w') as inputFile:
                inputFile.write("""
data_optics

loop_
_rlnOpticsGroupName #1
_rlnOpticsGroup #2
opticsGroup1 1
opticsGroup2 2

data_movies

loop_
_rlnMicrographMovieName #1
_rlnOpticsGroup #2
/tmp/FoilHole_1_Fractions.mrc 2
/tmp/FoilHole_2_Fractions.mrc 1
""")

            movies = [
                _Movie('/data/FoilHole_1_Fractions.mrc', 'movie_001'),
                _Movie('/data/FoilHole_2_Fractions.mrc', 'movie_002')
            ]
            ProtGenerateAfisGroups._createRelionStar(
                inputStar, outputStar, movies)

            outputTable = Table(fileName=outputStar,
                                tableName='micrographs')
            rows = list(outputTable)
            self.assertEqual(['movie_001', 'movie_002'],
                             [row.rlnMicrographName for row in rows])
            self.assertEqual([2, 1],
                             [row.rlnOpticsGroup for row in rows])


if __name__ == '__main__':
    unittest.main()
import os
import tempfile
import unittest
from unittest.mock import patch

from emtable import Table
from pyworkflow.object import Integer

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
    def testDirectInputAvoidsStaging(self):
        with tempfile.TemporaryDirectory() as tmpDir:
            xmlDir = os.path.join(tmpDir, 'xml')
            movieDir = os.path.join(tmpDir, 'movies')
            os.makedirs(xmlDir)
            os.makedirs(movieDir)
            movies = []
            for index in range(2):
                root = 'FoilHole_%d_Data_10_11_20200101_120000' % index
                movieFile = os.path.join(movieDir, root + '_Fractions.eer')
                open(movieFile, 'w').close()
                open(os.path.join(xmlDir, root + '.xml'), 'w').close()
                movies.append(_Movie(movieFile, 'movie_%03d' % index))

            infoMessages = []
            result = ProtGenerateAfisGroups._useDirectInput(
                xmlDir, movies, info=infoMessages.append)

            self.assertEqual((xmlDir, movieDir, 'eer', 2, 0, 0), result)
            self.assertTrue(any('without staging' in message
                                for message in infoMessages))
            self.assertEqual([], [name for name in os.listdir(tmpDir)
                                  if name == 'afis_input'])

    def testSummaryReportsIgnoredFiles(self):
        protocol = ProtGenerateAfisGroups.__new__(ProtGenerateAfisGroups)
        protocol.outputStar = object()
        protocol.numberOfGroups = Integer(5)
        protocol._matchedPairs = Integer(12)
        protocol._ignoredMovies = Integer(2)
        protocol._ignoredXml = Integer(3)

        self.assertEqual([
            'Generated 5 AFIS optics groups from 12 matched movie/XML pairs.',
            'Ignored 2 movie(s) without XML metadata and 3 XML file(s) '
            'without a matching input movie.'
        ], protocol._summary())

    def testStageInputFlattensNestedMoviesAndXml(self):
        with tempfile.TemporaryDirectory() as tmpDir:
            movieDir = os.path.join(tmpDir, 'movies', 'GridSquare1')
            xmlDir = os.path.join(tmpDir, 'Images-Disc1', 'GridSquare1',
                                  'Data')
            inputDir = os.path.join(tmpDir, 'protocol', 'tmp', 'afis_input')
            os.makedirs(movieDir)
            os.makedirs(xmlDir)

            roots = ['FoilHole_1_Data_10_11_20200101_120000',
                     'FoilHole_2_Data_20_21_20200101_120100']
            movies = []
            for index, root in enumerate(roots):
                movieFile = os.path.join(movieDir, root + '_Fractions.mrc')
                xmlFile = os.path.join(xmlDir, root + '.xml')
                open(movieFile, 'w').close()
                open(xmlFile, 'w').close()
                movies.append(_Movie(movieFile, 'movie_%03d' % index))
            unmatchedMovie = os.path.join(
                movieDir, 'FoilHole_3_Data_30_31_20200101_120200_Fractions.mrc')
            open(unmatchedMovie, 'w').close()
            movies.append(_Movie(unmatchedMovie, 'movie_003'))

            infoMessages = []
            warningMessages = []
            extension, matchedCount, ignoredMovies, ignoredXml = (
                ProtGenerateAfisGroups._stageInputFiles(
                    tmpDir, movies, inputDir, info=infoMessages.append,
                    warning=warningMessages.append))

            self.assertEqual('mrc', extension)
            self.assertEqual(2, matchedCount)
            self.assertEqual(1, ignoredMovies)
            self.assertEqual(0, ignoredXml)
            self.assertEqual(
                sorted([root + suffix for root in roots
                        for suffix in ('.xml', '_Fractions.mrc')]),
                sorted(os.listdir(inputDir)))
            self.assertTrue(all(os.path.islink(os.path.join(inputDir, name))
                                for name in os.listdir(inputDir)))
            self.assertTrue(any('Found 2 matched movie/XML pair(s)'
                                in message for message in infoMessages))
            self.assertEqual(4, sum('Created symbolic link:' in message
                                    for message in infoMessages))
            self.assertIn('AFIS staging completed with 2 pair(s).',
                          infoMessages)
            self.assertEqual(1, len(warningMessages))
            self.assertIn('Ignoring movie without matching XML metadata:',
                          warningMessages[0])

    def testMatchingSkipsMovieWithoutXml(self):
        with tempfile.TemporaryDirectory() as tmpDir:
            movie = _Movie(
                os.path.join(tmpDir,
                             'FoilHole_1_Data_10_11_20200101_120000_Fractions.mrc'),
                'movie_001')
            unrelatedXml = os.path.join(
                tmpDir, 'FoilHole_2_Data_20_21_20200101_120100.xml')
            open(unrelatedXml, 'w').close()
            pairs, unmatchedMovies, unmatchedXml, extension = (
                ProtGenerateAfisGroups._matchMoviesAndXml(tmpDir, [movie]))

            self.assertEqual([], pairs)
            self.assertEqual([movie], unmatchedMovies)
            self.assertEqual([unrelatedXml], unmatchedXml)
            self.assertEqual('mrc', extension)

    def testFindsXmlWithoutMovie(self):
        with tempfile.TemporaryDirectory() as tmpDir:
            matchedRoot = 'FoilHole_1_Data_10_11_20200101_120000'
            unmatchedRoot = 'FoilHole_2_Data_20_21_20200101_120100'
            matchedXml = os.path.join(tmpDir, matchedRoot + '.xml')
            unmatchedXml = os.path.join(tmpDir, unmatchedRoot + '.xml')
            open(matchedXml, 'w').close()
            open(unmatchedXml, 'w').close()
            movie = _Movie(os.path.join(
                tmpDir, matchedRoot + '_Fractions.eer'), 'movie_001')

            pairs, unmatchedMovies, unmatchedXmlFiles, _ = (
                ProtGenerateAfisGroups._matchMoviesAndXml(tmpDir, [movie]))

            self.assertEqual([], unmatchedMovies)
            self.assertEqual([unmatchedXml], unmatchedXmlFiles)

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
import os
import shlex
from enum import Enum
from fnmatch import fnmatch

from emtable import Table
from pwem.objects import EMFile
from pwem.protocols import EMProtocol
from pyworkflow.protocol import params
from pyworkflow.utils import cleanPath, createAbsLink, makePath

from epugroupafis import Plugin


class AfisOutputs(Enum):
    outputStar = EMFile
    outputRelionStar = EMFile


class ProtGenerateAfisGroups(EMProtocol):
    """Generate RELION optics groups from EPU AFIS movie metadata."""

    _label = 'Generate AFIS groups from movies'
    _possibleOutputs = AfisOutputs

    def _defineParams(self, form):
        form.addSection(label='Input')
        form.addParam('inputMovies', params.PointerParam,
                      pointerClass='SetOfMovies', important=True,
                      label='Input movies')
        form.addParam('xmlDir', params.PathParam, important=True,
                      label='EPU XML metadata directory',
                      help='Root directory of the EPU session. Subdirectories '
                          'are searched recursively for the XML metadata '
                          'matching each input movie.')
        form.addParam('numberOfGroups', params.IntParam, default=5,
                      validators=[params.GE(5)],
                      label='Number of optics groups',
                      help='EPU_group_AFIS requires at least five groups to '
                          'determine the acquisition grid axes.')
        form.addParam('algorithm', params.EnumParam, default=0,
                      choices=['K-means', 'Hierarchical clustering'],
                      label='Clustering algorithm')
        form.addParam('mtfFile', params.FileParam, allowsNull=True,
                      label='MTF STAR file',
                      help='Optional detector MTF file stored in data_optics.')
        form.addParallelSection(threads=1, mpi=0)

    def _insertAllSteps(self):
        inputId = self.inputMovies.get().getObjId()
        self._insertFunctionStep(self.runAfisStep, inputId, needsGPU=False)
        self._insertFunctionStep(self.createOutputStep, inputId,
                                 needsGPU=False)

    def runAfisStep(self, inputId):
        movies = self.inputMovies.get()
        inputDir = self._getTmpPath('afis_input')
        extension = self._stageInputFiles(self.xmlDir.get(), movies, inputDir)

        acquisition = movies.getAcquisition()
        args = [
            '--xml_dir', inputDir,
            '--n_clusters', str(self.numberOfGroups.get()),
            '--algorithm', 'kmeans' if self.algorithm.get() == 0 else 'hac',
            '--apix', str(movies.getSamplingRate()),
            '--voltage', str(acquisition.getVoltage()),
            '--cs', str(acquisition.getSphericalAberration()),
            '--q0', str(acquisition.getAmplitudeContrast()),
            '--ftype', extension,
            '--movie_dir', inputDir,
            '--output_fn', self._getExtraPath('movies.star'),
            '--quiet'
        ]
        if self.mtfFile.hasValue():
            args.extend(['--mtf_fn', self.mtfFile.get()])

        Plugin.runEpugroupafis(self, ' '.join(shlex.quote(value)
                                              for value in args))

    @classmethod
    def _stageInputFiles(cls, xmlDir, movies, inputDir):
        pairs, extension = cls._matchMoviesAndXml(xmlDir, movies)
        cleanPath(inputDir)
        makePath(inputDir)

        for movie, xmlFile in pairs:
            for source in (movie.getFileName(), xmlFile):
                createAbsLink(os.path.abspath(source),
                              os.path.join(inputDir,
                                           os.path.basename(source)))
        return extension

    @staticmethod
    def _matchMoviesAndXml(xmlDir, movies):
        xmlFiles = sorted(
            os.path.join(root, name)
            for root, _, names in os.walk(xmlDir)
            for name in names
            if (fnmatch(name, 'FoilHole_*_Data_*.xml') and
                not fnmatch(name, '*ractions.xml')))
        if not xmlFiles:
            raise ValueError('No EPU FoilHole XML metadata files were found.')

        moviesByName = {}
        extensions = set()
        for movie in movies:
            basename = os.path.basename(movie.getFileName())
            if basename in moviesByName:
                raise ValueError('Input movies contain a duplicated filename: '
                                 '%s' % basename)
            moviesByName[basename] = movie
            extensions.add(os.path.splitext(basename)[1].lstrip('.'))

        if len(extensions) != 1:
            raise ValueError('All input movies must have the same file '
                             'extension for EPU_group_AFIS.')
        extension = extensions.pop()

        pairs = []
        usedXmlFiles = set()
        for basename, movie in moviesByName.items():
            matchingXml = []
            for xmlFile in xmlFiles:
                xmlRoot = os.path.splitext(os.path.basename(xmlFile))[0]
                if fnmatch(basename, '*%s*ractions.%s' %
                           (xmlRoot, extension)):
                    matchingXml.append(xmlFile)

            if not matchingXml:
                raise ValueError('No EPU XML metadata file matches input '
                                 'movie: %s' % basename)
            if len(matchingXml) > 1:
                raise ValueError('More than one EPU XML metadata file matches '
                                 'input movie: %s' % basename)

            xmlFile = matchingXml[0]
            if xmlFile in usedXmlFiles:
                raise ValueError('The same EPU XML metadata file matches more '
                                 'than one input movie: %s' % xmlFile)
            usedXmlFiles.add(xmlFile)
            pairs.append((movie, xmlFile))

        return pairs, extension

    def createOutputStep(self, inputId):
        inputStar = self._getExtraPath('movies.star')
        relionStar = self._getExtraPath('movies_relion.star')
        self._createRelionStar(inputStar, relionStar, self.inputMovies.get())

        outputStar = EMFile(inputStar)
        outputRelionStar = EMFile(relionStar)
        self._defineOutputs(outputStar=outputStar,
                            outputRelionStar=outputRelionStar)
        self._defineSourceRelation(self.inputMovies, outputStar)
        self._defineSourceRelation(self.inputMovies, outputRelionStar)

    @staticmethod
    def _createRelionStar(inputStar, outputStar, movies):
        opticsTable = Table(fileName=inputStar, tableName='optics')
        moviesTable = Table(fileName=inputStar, tableName='movies')

        moviesByName = {}
        for movie in movies:
            basename = os.path.basename(movie.getFileName())
            if basename in moviesByName:
                raise ValueError('Input movies contain a duplicated filename: %s'
                                 % basename)
            moviesByName[basename] = movie

        micrographsTable = Table(columns=[
            Table.Column('rlnMicrographName', str),
            Table.Column('rlnOpticsGroup', int)
        ])
        for row in moviesTable:
            basename = os.path.basename(row.rlnMicrographMovieName)
            movie = moviesByName.get(basename)
            if movie is None:
                raise ValueError('Movie from EPU_group_AFIS was not found in '
                                 'the Scipion input set: %s' % basename)
            micrographsTable.addRow(rlnMicrographName=movie.getMicName(),
                                    rlnOpticsGroup=row.rlnOpticsGroup)

        with open(outputStar, 'w') as outputFile:
            outputFile.write('# Star file generated with Scipion\n')
            outputFile.write('# version 30001\n')
            opticsTable.writeStar(outputFile, tableName='optics')
            outputFile.write('# version 30001\n')
            micrographsTable.writeStar(outputFile, tableName='micrographs')

    def _validate(self):
        errors = []
        if not os.path.isdir(self.xmlDir.get()):
            errors.append('The EPU XML metadata directory does not exist.')
        elif self.inputMovies.get().getSize() > 0:
            try:
                pairs, _ = self._matchMoviesAndXml(
                    self.xmlDir.get(), self.inputMovies.get())
                if self.numberOfGroups.get() > len(pairs):
                    errors.append('The number of optics groups cannot exceed '
                                  'the number of matched movies.')
            except ValueError as error:
                errors.append(str(error))
        if self.inputMovies.get().getSize() == 0:
            errors.append('The input movie set is empty.')
        if self.mtfFile.hasValue() and not os.path.isfile(self.mtfFile.get()):
            errors.append('The MTF STAR file does not exist.')
        return errors

    def _summary(self):
        if not hasattr(self, 'outputStar'):
            return ['Outputs have not been generated yet.']
        return ['Generated %d AFIS optics groups.' % self.numberOfGroups.get()]

    def _methods(self):
        return []
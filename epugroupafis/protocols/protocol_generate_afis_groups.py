import os
import shlex
from enum import Enum
from fnmatch import fnmatch

from emtable import Table
from pwem.objects import EMFile
from pwem.protocols import EMProtocol
from pyworkflow.object import Integer
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
        form.addParam('xmlFilesInSameFolder', params.BooleanParam,
                      default=False,
                      label='Are all XML in the same folder?',
                      help='Enable this when all EPU XML metadata files are '
                           'directly inside the selected directory. The '
                           'protocol will run on the original files without '
                           'creating a flat staging directory.')
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
        form.addParallelSection(threads=8, mpi=0)

    def _insertAllSteps(self):
        inputId = self.inputMovies.get().getObjId()
        self._insertFunctionStep(self.runAfisStep, inputId, needsGPU=False)
        self._insertFunctionStep(self.createOutputStep, inputId,
                                 needsGPU=False)

    def runAfisStep(self, inputId):
        movies = self.inputMovies.get()
        if self.xmlFilesInSameFolder.get():
            xmlDir, moviesDir, extension, matchedCount, ignoredMovies, ignoredXml = (
                self._useDirectInput(self.xmlDir.get(), movies,
                                     info=self.info))
        else:
            inputDir = self._getTmpPath('afis_input')
            extension, matchedCount, ignoredMovies, ignoredXml = (
                self._stageInputFiles(self.xmlDir.get(), movies, inputDir,
                                      info=self.info, warning=self.warning))
            xmlDir = moviesDir = inputDir
        self._matchedPairs = Integer(matchedCount)
        self._ignoredMovies = Integer(ignoredMovies)
        self._ignoredXml = Integer(ignoredXml)
        self._store()

        acquisition = movies.getAcquisition()
        args = [
            '--xml_dir', xmlDir,
            '--n_clusters', str(self.numberOfGroups.get()),
            '--algorithm', 'kmeans' if self.algorithm.get() == 0 else 'hac',
            '--apix', str(movies.getSamplingRate()),
            '--voltage', str(acquisition.getVoltage()),
            '--cs', str(acquisition.getSphericalAberration()),
            '--q0', str(acquisition.getAmplitudeContrast()),
            '--ftype', extension,
            '--movie_dir', moviesDir,
            '--output_fn', self._getExtraPath('movies.star'),
            '--workers', str(self.numberOfThreads.get()),
            '--quiet'
        ]
        if self.mtfFile.hasValue():
            args.extend(['--mtf_fn', self.mtfFile.get()])

        Plugin.runEpugroupafis(self, ' '.join(shlex.quote(value)
                                              for value in args))

    @classmethod
    def _useDirectInput(cls, xmlDir, movies, info=None):
        info = info or (lambda message: None)
        movieFiles = [os.path.abspath(movie.getFileName())
                      for movie in movies]
        extensions = {os.path.splitext(path)[1].lstrip('.')
                      for path in movieFiles}
        if len(extensions) != 1:
            raise ValueError('All input movies must have the same file '
                             'extension for EPU_group_AFIS.')

        moviesDir = os.path.commonpath(
            [os.path.dirname(path) for path in movieFiles])
        xmlFiles = [name for name in os.listdir(xmlDir)
                    if (fnmatch(name, 'FoilHole_*_Data_*.xml') and
                        not fnmatch(name, '*ractions.xml'))]
        movieCount = len(movieFiles)
        xmlCount = len(xmlFiles)
        matchedCount = min(movieCount, xmlCount)

        info('Using XML files directly without staging: %s' % xmlDir)
        info('Using movies directly from common directory: %s' % moviesDir)
        info('Direct input contains %d movie(s) and %d XML file(s).'
             % (movieCount, xmlCount))
        return (xmlDir, moviesDir, extensions.pop(), matchedCount,
                max(0, movieCount - xmlCount), max(0, xmlCount - movieCount))

    @classmethod
    def _stageInputFiles(cls, xmlDir, movies, inputDir, info=None,
                         warning=None):
        info = info or (lambda message: None)
        warning = warning or (lambda message: None)
        info('Searching EPU XML metadata recursively in: %s' % xmlDir)
        pairs, unmatchedMovies, unmatchedXml, extension = (
            cls._matchMoviesAndXml(xmlDir, movies))
        info('Found %d matched movie/XML pair(s), %d unmatched movie(s), '
             'and %d unmatched XML file(s).'
             % (len(pairs), len(unmatchedMovies), len(unmatchedXml)))

        for movie in unmatchedMovies:
            warning('Ignoring movie without matching XML metadata: %s'
                    % movie.getFileName())
        for xmlFile in unmatchedXml:
            warning('Ignoring XML metadata without matching input movie: %s'
                    % xmlFile)

        info('Creating flat AFIS staging directory: %s' % inputDir)
        cleanPath(inputDir)
        makePath(inputDir)

        for movie, xmlFile in pairs:
            info('Staging pair: %s <-> %s'
                 % (movie.getFileName(), xmlFile))
            for source in (movie.getFileName(), xmlFile):
                destination = os.path.join(inputDir,
                                           os.path.basename(source))
                createAbsLink(os.path.abspath(source), destination)
                info('Created symbolic link: %s -> %s'
                     % (destination, os.path.abspath(source)))
        info('AFIS staging completed with %d pair(s).' % len(pairs))
        return (extension, len(pairs), len(unmatchedMovies),
                len(unmatchedXml))

    @staticmethod
    def _findXmlFiles(xmlDir):
        return sorted(
            os.path.join(root, name)
            for root, _, names in os.walk(xmlDir)
            for name in names
            if (fnmatch(name, 'FoilHole_*_Data_*.xml') and
                not fnmatch(name, '*ractions.xml')))

    @classmethod
    def _matchMoviesAndXml(cls, xmlDir, movies):
        xmlFiles = cls._findXmlFiles(xmlDir)

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
        unmatchedMovies = []
        usedXmlFiles = set()
        for basename, movie in moviesByName.items():
            matchingXml = []
            for xmlFile in xmlFiles:
                xmlRoot = os.path.splitext(os.path.basename(xmlFile))[0]
                if fnmatch(basename, '*%s*ractions.%s' %
                           (xmlRoot, extension)):
                    matchingXml.append(xmlFile)

            if not matchingXml:
                unmatchedMovies.append(movie)
                continue
            if len(matchingXml) > 1:
                raise ValueError('More than one EPU XML metadata file matches '
                                 'input movie: %s' % basename)

            xmlFile = matchingXml[0]
            if xmlFile in usedXmlFiles:
                raise ValueError('The same EPU XML metadata file matches more '
                                 'than one input movie: %s' % xmlFile)
            usedXmlFiles.add(xmlFile)
            pairs.append((movie, xmlFile))

        unmatchedXmlFiles = [xmlFile for xmlFile in xmlFiles
                             if xmlFile not in usedXmlFiles]
        return pairs, unmatchedMovies, unmatchedXmlFiles, extension

    def createOutputStep(self, inputId):
        inputStar = self._getExtraPath('movies.star')
        relionStar = self._getExtraPath('movies_relion.star')
        self._createRelionStar(inputStar, relionStar, self.inputMovies.get(),
                               warning=self.warning)

        outputStar = EMFile(inputStar)
        outputRelionStar = EMFile(relionStar)
        self._defineOutputs(outputStar=outputStar,
                            outputRelionStar=outputRelionStar)
        self._defineSourceRelation(self.inputMovies, outputStar)
        self._defineSourceRelation(self.inputMovies, outputRelionStar)

    @staticmethod
    def _createRelionStar(inputStar, outputStar, movies, warning=None):
        warning = warning or (lambda message: None)
        opticsTable = Table(fileName=inputStar, tableName='optics')
        moviesTable = Table(fileName=inputStar, tableName='movies')

        moviesByName = {}
        for movie in movies:
            fileName = movie.getFileName()
            aliases = {os.path.basename(fileName),
                       os.path.basename(os.path.realpath(fileName)),
                       os.path.basename(movie.getMicName())}
            getAttributeValue = getattr(movie, 'getAttributeValue', None)
            if getAttributeValue is not None:
                originalFileName = getAttributeValue('_originalFileName', None)
                if originalFileName:
                    aliases.add(os.path.basename(originalFileName))
            for alias in aliases:
                if (alias in moviesByName and
                        moviesByName[alias] is not movie):
                    raise ValueError('Input movies contain a duplicated name: '
                                     '%s' % alias)
                moviesByName[alias] = movie

        micrographsTable = Table(columns=[
            Table.Column('rlnMicrographName', str),
            Table.Column('rlnOpticsGroup', int)
        ])
        for row in moviesTable:
            basename = os.path.basename(row.rlnMicrographMovieName)
            movie = moviesByName.get(basename)
            if movie is None:
                micrographName = row.rlnMicrographMovieName
                warning('Using the EPU_group_AFIS movie path because it '
                        'could not be matched to the Scipion input set: %s'
                        % basename)
            else:
                micrographName = movie.getMicName()
            micrographsTable.addRow(rlnMicrographName=micrographName,
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
        if self.inputMovies.get().getSize() == 0:
            errors.append('The input movie set is empty.')
        if self.mtfFile.hasValue() and not os.path.isfile(self.mtfFile.get()):
            errors.append('The MTF STAR file does not exist.')
        return errors

    def _summary(self):
        if not hasattr(self, 'outputStar'):
            return ['Outputs have not been generated yet.']
        return [
            'Generated %d AFIS optics groups from %d matched movie/XML pairs.'
            % (self.numberOfGroups.get(), self._matchedPairs.get()),
            'Ignored %d movie(s) without XML metadata and %d XML file(s) '
            'without a matching input movie.'
            % (self._ignoredMovies.get(), self._ignoredXml.get())
        ]

    def _methods(self):
        return []
import os
import shlex
from enum import Enum

from emtable import Table
from pwem.objects import EMFile
from pwem.protocols import EMProtocol
from pyworkflow.protocol import params
from pyworkflow.utils import createAbsLink, makePath

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
                      help='Directory containing FoilHole_*_Data_*.xml files.')
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
        moviesDir = self._getTmpPath('movies')
        makePath(moviesDir)
        for movie in movies:
            createAbsLink(movie.getFileName(),
                          os.path.join(moviesDir,
                                       os.path.basename(movie.getFileName())))

        firstMovie = movies.getFirstItem()
        extension = os.path.splitext(firstMovie.getFileName())[1].lstrip('.')
        acquisition = movies.getAcquisition()
        args = [
            '--xml_dir', self.xmlDir.get(),
            '--n_clusters', str(self.numberOfGroups.get()),
            '--algorithm', 'kmeans' if self.algorithm.get() == 0 else 'hac',
            '--apix', str(movies.getSamplingRate()),
            '--voltage', str(acquisition.getVoltage()),
            '--cs', str(acquisition.getSphericalAberration()),
            '--q0', str(acquisition.getAmplitudeContrast()),
            '--ftype', extension,
            '--movie_dir', moviesDir,
            '--output_fn', self._getExtraPath('movies.star'),
            '--quiet'
        ]
        if self.mtfFile.hasValue():
            args.extend(['--mtf_fn', self.mtfFile.get()])

        Plugin.runEpugroupafis(self, ' '.join(shlex.quote(value)
                                              for value in args))

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
        elif not any(name.startswith('FoilHole_') and
                     name.endswith('.xml') and
                     not name.endswith('Fractions.xml')
                     for _, _, names in os.walk(self.xmlDir.get())
                     for name in names):
            errors.append('No EPU FoilHole XML metadata files were found.')
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
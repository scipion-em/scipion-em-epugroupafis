import os

import pwem
from pyworkflow.utils import Environ

from .constants import (EPUGROUPAFIS, EPUGROUPAFIS_DEFAULT_ACTIVATION_CMD,
                        EPUGROUPAFIS_ENV_ACTIVATION, EPUGROUPAFIS_ENV_NAME,
                        EPUGROUPAFIS_HOME, EPUGROUPAFIS_PROGRAM,
                        EPUGROUPAFIS_REPOSITORY, EPUGROUPAFIS_VERSION)

__version__ = '3.0.0'
_references = ['Morado2020']


class Plugin(pwem.Plugin):
    _supportedVersions = [EPUGROUPAFIS_VERSION]
    _url = 'https://github.com/scipion-em/scipion-em-epugroupafis'

    @classmethod
    def _defineVariables(cls):
        cls._defineVar(EPUGROUPAFIS_ENV_ACTIVATION,
                       EPUGROUPAFIS_DEFAULT_ACTIVATION_CMD)
        cls._defineEmVar(EPUGROUPAFIS_HOME,
                         '%s-%s' % (EPUGROUPAFIS, EPUGROUPAFIS_VERSION))

    @classmethod
    def getEnviron(cls):
        environ = Environ(os.environ)
        environ.pop('PYTHONPATH', None)
        return environ

    @classmethod
    def defineBinaries(cls, env):
        installedFlag = '%s_installed' % EPUGROUPAFIS_ENV_NAME
        command = cls.getCondaActivationCmd()
        command += (' conda create -y -n %s -c conda-forge python=3.10 '
                    'numpy scikit-learn matplotlib && ' % EPUGROUPAFIS_ENV_NAME)
        command += 'conda activate %s && ' % EPUGROUPAFIS_ENV_NAME
        command += 'git clone --depth 1 %s . && ' % EPUGROUPAFIS_REPOSITORY
        command += ('install -m 755 EPU_Group_AFIS.py '
                    '"$CONDA_PREFIX/bin/%s" && ' % EPUGROUPAFIS_PROGRAM)
        command += 'touch %s' % installedFlag

        envPath = os.environ.get('PATH', '')
        env.addPackage(
            EPUGROUPAFIS,
            version=EPUGROUPAFIS_VERSION,
            tar='void.tgz',
            commands=[(command, installedFlag)],
            neededProgs=cls.getDependencies(),
            vars={'PATH': envPath} if envPath else None,
            default=True)

    @classmethod
    def getDependencies(cls):
        dependencies = ['git']
        if not cls.getCondaActivationCmd():
            dependencies.append('conda')
        return dependencies

    @classmethod
    def runEpugroupafis(cls, protocol, args, cwd=None):
        command = cls.getCondaActivationCmd()
        command += ' %s && %s' % (cls.getVar(EPUGROUPAFIS_ENV_ACTIVATION),
                                  EPUGROUPAFIS_PROGRAM)
        protocol.runJob(command, args, env=cls.getEnviron(), cwd=cwd,
                        numberOfMpi=1)
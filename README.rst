===================================
Scipion plugin for EPU_group_AFIS
===================================

This plugin runs `EPU_group_AFIS <https://github.com/DustinMorado/EPU_group_AFIS>`_
inside Scipion 3. The program groups movies acquired with EPU AFIS into RELION
optics groups from their XML metadata.

Installation
------------

Install the plugin in development mode from a Scipion installation::

    scipion3 installp -p /path/to/scipion-em-epugroupafis --devel

Then install ``epugroupafis-git`` from Scipion's plugin manager. This creates a
dedicated Conda environment and installs the current upstream Git version.

Protocols
---------

* **Generate AFIS groups from movies** creates the original EPU_group_AFIS STAR
  file and a second STAR file accepted by RELION's **Assign optics groups**
  protocol.
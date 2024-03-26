import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Annotated, List, Tuple, Optional, Dict

import qt
from slicer.parameterNodeWrapper import parameterPack, Choice, WithinRange


@parameterPack
@dataclass
class Parameter:
    """
    Parameters storing the NNUNet config in Python formats.
    Sets the default values as used by the Segmentation Logic.
    Parameters are compatible with 3D Slicer parameterNodeWrapper.

    Provides method to convert to nnUNet process arg list.
    """
    folds: str = ""
    device: Annotated[str, Choice(["cuda", "cpu", "mps"])] = "cuda"
    stepSize: Annotated[float, WithinRange(0., 1.0)] = 0.5
    disableTta: bool = True
    nProcessPreprocessing: Annotated[int, WithinRange(1, 999)] = 1
    nProcessSegmentationExport: Annotated[int, WithinRange(1, 999)] = 1
    checkPointName: str = ""
    modelPath: Path = Path()

    def asDict(self) -> Dict:
        return asdict(self)

    def asArgList(self, inDir: Path, outDir: Path) -> List:
        import torch

        isValid, reason = self.isValid()
        if not isValid:
            raise RuntimeError(f"Invalid nnUNet configuration. {reason}")

        device = self.device if torch.cuda.is_available() else "cpu"
        args = [
            "-i", inDir.as_posix(),
            "-o", outDir.as_posix(),
            "-d", self._datasetName,
            "-tr", self._configurationNameParts[0],
            "-p", self._configurationNameParts[1],
            "-c", self._configurationNameParts[-1],
            "-f", *[str(f) for f in self._foldsAsList()],
            "-npp", self.nProcessPreprocessing,
            "-nps", self.nProcessSegmentationExport,
            "-step_size", self.stepSize,
            "-device", device,
            "-chk", self._getCheckpointName()
        ]

        if self.disableTta:
            args.append("--disable_tta")

        return args

    def toSettings(self, settings: Optional[qt.QSettings] = None, key: str = "") -> None:
        """
        Saves the current Parameters to QSettings.
        If settings is not provided, saves to the default .ini file.
        """
        key = key or self._defaultSettingsKey()
        settings = settings or qt.QSettings()
        settings.setValue(key, json.dumps(self.asDict(), cls=_PathEncoder))
        settings.sync()

    @classmethod
    def fromSettings(cls, settings: Optional[qt.QSettings] = None, key: str = ""):
        """
        Creates Parameters from the saved settings.
        If settings is not provided, loads from the default .ini file.
        If Parameter is not found or contains partial data, loads available and defaults the rest.
        """
        key = key or cls._defaultSettingsKey()
        settings = settings or qt.QSettings()
        val = settings.value(key, "")
        val_dict = json.loads(val, object_hook=_PathEncoder.decodePath) if val else {}

        instance = cls()
        for k, v in val_dict.items():
            try:
                instance.setValue(k, v)
            except TypeError:
                continue
        return instance

    @classmethod
    def _defaultSettingsKey(cls):
        return "SlicerNNUNet/Parameter"

    def _getCheckpointName(self):
        return self.checkPointName or "checkpoint_final.pth"

    def isValid(self) -> Tuple[bool, str]:
        """
        Checks if the current configuration is valid.
        Returns True and empty string if that's the case.
        False and reason for failure otherwise.
        """
        if not self._isDatasetPathValid():
            return False, f"Dataset.json file is missing. Provided model dir :\n{self.modelPath}"

        # Check input configuration folds matches the input model folder
        missing_folds = self._getMissingFolds()
        if missing_folds:
            return False, f"Model folder is missing the following folds : {missing_folds}."

        # Check folds with invalid weights
        folds_with_invalid_weights = self._getFoldsWithInvalidWeights()
        if folds_with_invalid_weights:
            return False, f"Following model folds don't contain {self.checkPointName} weights : {folds_with_invalid_weights}."

        if not len(self._configurationNameParts) == 3:
            return (
                False,
                "Invalid nnUNet configuration folder."
                "  Expected folder name such as <trainer_name>__<plan_name>__<conf_name>"
            )

        return True, ""

    def readSegmentIdsAndLabelsFromDatasetFile(self) -> Optional[List[Tuple[str, str]]]:
        """
        Load SegmentIds / labels pairs from the dataset file.
        """
        if not self._isDatasetPathValid():
            return None

        with open(self._datasetPath, "r") as f:
            dataset_dict = json.loads(f.read())
            labels = dataset_dict.get("labels")
            return [(f"Segment_{v}", k) for k, v in labels.items()]

    @property
    def _datasetPath(self):
        try:
            return next(self.modelPath.rglob("dataset.json")) if self.modelPath else None
        except StopIteration:
            return None

    def _foldsAsList(self):
        return [int(f) for f in self.folds.strip().split(",")] if self.folds else [0]

    def _getFoldPaths(self) -> List[Tuple[int, Path]]:
        return [(fold, self._configurationFolder.joinpath(f"fold_{fold}")) for fold in self._foldsAsList()]

    def _getMissingFolds(self):
        return [fold for fold, path in self._getFoldPaths() if not path.exists()]

    def _getFoldsWithInvalidWeights(self):
        return [fold for fold, path in self._getFoldPaths() if not path.joinpath(self._getCheckpointName()).exists()]

    @property
    def _configurationFolder(self) -> Path:
        return self._datasetPath.parent

    @property
    def _datasetFolder(self) -> Path:
        return self._configurationFolder.parent

    @property
    def _datasetName(self) -> str:
        return self._datasetFolder.name

    @property
    def modelFolder(self) -> Path:
        return self._datasetFolder.parent

    @property
    def _configurationNameParts(self) -> List[str]:
        return self._configurationFolder.name.split("__")

    def _isDatasetPathValid(self) -> bool:
        return self._datasetPath is not None


class _PathEncoder(json.JSONEncoder):
    """
    Helper encoder to save / restore modelPath from QSettings.
    """

    def default(self, obj):
        if isinstance(obj, Path):
            return {'_path': str(obj)}
        return super().default(obj)

    @staticmethod
    def decodePath(obj):
        if '_path' in obj:
            return Path(obj['_path'])
        return obj

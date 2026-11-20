"""Import BoTorch/GPyTorch with the Torch JIT FutureWarning filtered."""

from __future__ import annotations

import warnings

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=FutureWarning, message=r".*torch\.jit\.script.*")
    import gpytorch  # type: ignore[import-untyped]
    import torch
    from botorch.acquisition.acquisition import AcquisitionFunction
    from botorch.acquisition.logei import qLogNoisyExpectedImprovement
    from botorch.acquisition.objective import LinearMCObjective
    from botorch.fit import fit_gpytorch_mll
    from botorch.models.gp_regression import SingleTaskGP
    from botorch.models.model import Model
    from botorch.models.transforms.outcome import Standardize
    from botorch.optim.optimize import optimize_acqf
    from gpytorch.constraints import GreaterThan  # type: ignore[import-untyped]
    from gpytorch.kernels import MaternKernel, ScaleKernel  # type: ignore[import-untyped]
    from gpytorch.likelihoods import GaussianLikelihood  # type: ignore[import-untyped]
    from gpytorch.mlls import ExactMarginalLogLikelihood  # type: ignore[import-untyped]
    from linear_operator.utils.warnings import NumericalWarning  # type: ignore[import-untyped]
    from sklearn.cluster import HDBSCAN  # type: ignore[import-untyped]
    from torch import Tensor

__all__ = [
    "HDBSCAN",
    "AcquisitionFunction",
    "ExactMarginalLogLikelihood",
    "GaussianLikelihood",
    "GreaterThan",
    "LinearMCObjective",
    "MaternKernel",
    "Model",
    "NumericalWarning",
    "ScaleKernel",
    "SingleTaskGP",
    "Standardize",
    "Tensor",
    "fit_gpytorch_mll",
    "gpytorch",
    "optimize_acqf",
    "qLogNoisyExpectedImprovement",
    "torch",
]

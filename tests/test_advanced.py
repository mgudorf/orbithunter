import pytest
import numpy as np
import orbithunter as orb
import h5py
import pathlib

here = pathlib.Path(__file__).parent.resolve()
data_path = here / "test_data.h5"


@pytest.fixture()
def fixed_OrbitKS_data():
    # Generated from
    # np.random.seed(0)
    # np.random.randn(6, 6).round(8); values chosen because of size, truncation error
    state = np.array(
        [
            [1.76405235, 0.40015721, 0.97873798, 2.2408932, 1.86755799, -0.97727788],
            [0.95008842, -0.15135721, -0.10321885, 0.4105985, 0.14404357, 1.45427351],
            [0.76103773, 0.12167502, 0.44386323, 0.33367433, 1.49407907, -0.20515826],
            [0.3130677, -0.85409574, -2.55298982, 0.6536186, 0.8644362, -0.74216502],
            [2.26975462, -1.45436567, 0.04575852, -0.18718385, 1.53277921, 1.46935877],
            [0.15494743, 0.37816252, -0.88778575, -1.98079647, -0.34791215, 0.15634897],
        ]
    )
    return state


def test_orbit_data():
    with h5py.File(data_path, "r") as file:

        def h5_helper(name, cls):
            nonlocal file
            attrs = dict(file["/".join([name, "0"])].attrs.items())
            state = file["/".join([name, "0"])][...]
            return cls(
                state=state,
                **{
                    **attrs,
                    "parameters": tuple(attrs["parameters"]),
                    "discretization": tuple(attrs["discretization"]),
                }
            )

        rpo = h5_helper("rpo", orb.RelativeOrbitKS)
        defect = h5_helper("defect", orb.RelativeOrbitKS)
        large_defect = h5_helper("large_defect", orb.RelativeOrbitKS)
        drifter = h5_helper("drifter", orb.RelativeEquilibriumOrbitKS)
        wiggle = h5_helper("wiggle", orb.AntisymmetricOrbitKS)
        streak = h5_helper("streak", orb.EquilibriumOrbitKS)
        double_streak = h5_helper("double_streak", orb.EquilibriumOrbitKS)
        manual = [rpo, defect, large_defect, drifter, wiggle, streak, double_streak]

    # Read in the same orbits as above using the native orbithunter io
    # keys included so that the import order matches `static_orbits`
    keys = (
        "rpo",
        "defect",
        "large_defect",
        "drifter",
        "wiggle",
        "streak",
        "double_streak",
    )
    automatic = orb.read_h5(data_path, keys)
    for static, read in zip(manual, automatic):
        assert static.cost() < 1e-7
        assert static.cost() == read.cost()
        assert np.isclose(static.state, read.state).all()
        assert static.parameters == read.parameters


def test_glue():
    with h5py.File(data_path, "r") as file:

        def h5_helper(name, cls):
            nonlocal file
            attrs = dict(file["/".join([name, "0"])].attrs.items())
            state = file["/".join([name, "0"])][...]
            return cls(
                state=state,
                **{
                    **attrs,
                    "parameters": tuple(attrs["parameters"]),
                    "discretization": tuple(attrs["discretization"]),
                }
            )


def test_hunt_Orbit():
    methods = ['newton_descent', 'lstsq', 'solve', 'adj', 'gd', 'lsqr', 'lsmr', 'bicg', 'bicgstab', 'gmres', 'lgmres',
               'cg', 'cgs', 'qmr', 'minres', 'gcrotmk','nelder-mead', 'powell', 'cg_min', 'bfgs', 'newton-cg', 'l-bfgs-b',
               'tnc', 'cobyla', 'slsqp', 'trust-constr', 'dogleg', 'trust-ncg', 'trust-exact', 'trust-krylov', 'hybr',
               'lm','broyden1', 'broyden2', 'linearmixing','diagbroyden', 'excitingmixing',
               'df-sane', 'krylov', 'anderson']
    return None


def test_hunt_Orbit_subclass():
    methods = ['newton_descent', 'lstsq', 'solve', 'adj', 'gd', 'lsqr', 'lsmr', 'bicg', 'bicgstab', 'gmres', 'lgmres',
               'cg', 'cgs', 'qmr', 'minres', 'gcrotmk','nelder-mead', 'powell', 'cg_min', 'bfgs', 'newton-cg', 'l-bfgs-b',
               'tnc', 'cobyla', 'slsqp', 'trust-constr', 'dogleg', 'trust-ncg', 'trust-exact', 'trust-krylov', 'hybr',
               'lm','broyden1', 'broyden2', 'linearmixing','diagbroyden', 'excitingmixing',
               'df-sane', 'krylov', 'anderson']
    return None


class TestOrbit(orb.Orbit):

    def eqn(self):
        # Solve x^2 - n = 0 for n in [0, dim-1]e
        return self.state**2 - np.arange(self.state.size)

    def matvec(self, other, **kwargs):
        return 2 * other

    def rmatvec(self, other, **kwargs):
        return 2 * other

    def jacobian(self, **kwargs):
        return 2*np.diag(self.state.ravel())

    def hess(self, **kwargs):
        return 2 * np.tile(np.eye(self.size), (self.eqn().size, 1, 1))

    def hessp(self, left_other, right_other, **kwargs):
        return left_other.state
